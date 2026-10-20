"""Private staged BWork media; direct ORM access is intentionally denied."""
from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError


_MEDIA_TOKEN = object()


class BWorkMedia(models.Model):
    _name = 'baseer.bwork.media'
    _description = 'BWork private media'
    _check_company_auto = True
    _order = 'id desc'

    room_id = fields.Many2one('baseer.bwork.room', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    membership_id = fields.Many2one('baseer.bwork.membership', required=True, readonly=True, ondelete='restrict')
    author_user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict', index=True)
    upload_uuid = fields.Char(required=True, readonly=True, size=36)
    kind = fields.Selection([('image', 'Image'), ('file', 'File'), ('audio', 'Audio')], required=True, readonly=True)
    # OOXML MIME values are longer than 40 bytes; truncation breaks the
    # canonical DMS extension lookup after a successful staged upload.
    mime = fields.Char(required=True, readonly=True, size=127)
    size_bytes = fields.Integer(required=True, readonly=True)
    sha256 = fields.Char(required=True, readonly=True, size=64)
    name = fields.Char(required=True, readonly=True, size=160)
    state = fields.Selection([('staged', 'Staged'), ('attached', 'Attached'),
                              ('cancelled', 'Cancelled'), ('expired', 'Expired')],
                             required=True, readonly=True, default='staged')
    message_id = fields.Many2one('baseer.bwork.message', readonly=True, ondelete='restrict', index=True)
    attachment_id = fields.Many2one('ir.attachment', readonly=True, ondelete='restrict')
    thumbnail_attachment_id = fields.Many2one('ir.attachment', readonly=True, ondelete='restrict')
    document_type = fields.Selection([
        ('invoice', 'Invoice'), ('payment_receipt', 'Payment receipt'), ('other', 'Other'),
    ], required=True, readonly=True, default='other')
    document_policy_version = fields.Integer(readonly=True, default=0)
    document_file_id = fields.Integer(readonly=True, default=0)

    _user_upload_uuid_unique = models.Constraint(
        'UNIQUE(author_user_id, upload_uuid)', 'An upload UUID identifies one BWork media file.',
    )
    _media_sha_format = models.Constraint(
        "CHECK(sha256 ~ '^[0-9a-f]{64}$')", 'A SHA-256 digest is required.',
    )

    def init(self):
        # Keep historical attached/cancelled/expired rows out of both lookup
        # paths; only staged uploads count toward quota or TTL cleanup.
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bwork_media_staged_expiry_idx
            ON baseer_bwork_media (id, create_date) WHERE state = 'staged'
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bwork_media_staged_quota_idx
            ON baseer_bwork_media (author_user_id) INCLUDE (size_bytes)
            WHERE state = 'staged'
        ''')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BWork media creation is unavailable.'))

    @api.model
    def _create_verified(self, vals, token):
        if token is not _MEDIA_TOKEN:
            raise AccessError(self.env._('A verified BWork service operation is required.'))
        return super(BWorkMedia, self.sudo()).create(vals)

    def _write_verified(self, vals, token):
        if token is not _MEDIA_TOKEN or set(vals) - {
                'state', 'message_id', 'attachment_id', 'thumbnail_attachment_id',
                'document_type', 'document_policy_version', 'document_file_id'}:
            raise AccessError(self.env._('A verified BWork service operation is required.'))
        return super(BWorkMedia, self.sudo()).write(vals)

    def write(self, vals):
        raise AccessError(self.env._('BWork media is immutable outside its verified service.'))

    def unlink(self):
        raise AccessError(self.env._('BWork media cannot be deleted directly.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('BWork media cannot be copied.'))

    @api.model
    def _cron_expire_staged_uploads(self):
        """Service-owned bounded cleanup of unsent uploads."""
        return self.env['baseer.bwork.service'].with_user(SUPERUSER_ID)._v2_expire_staged_uploads()
