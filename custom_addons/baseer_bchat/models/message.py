"""Immutable text kept exclusively in BChat tables, never mail.message."""
from odoo import api, fields, models
from odoo.exceptions import AccessError


_SERVICE_TOKEN = object()


class BChatMessage(models.Model):
    _name = 'baseer.bchat.message'
    _description = 'BChat private text message'
    _order = 'id desc'
    _check_company_auto = True

    room_id = fields.Many2one('baseer.bchat.room', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    membership_id = fields.Many2one('baseer.bchat.membership', required=True, readonly=True, ondelete='restrict')
    author_user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict', index=True)
    client_uuid = fields.Char(required=True, readonly=True, size=36)
    payload_digest = fields.Char(required=True, readonly=True, size=64)
    text = fields.Text(readonly=True)
    media_id = fields.Many2one('baseer.bchat.media', readonly=True, ondelete='restrict', index=True)
    reply_to_message_id = fields.Many2one(
        'baseer.bchat.message', readonly=True, ondelete='restrict', index=True,
    )

    _user_uuid_unique = models.Constraint('UNIQUE(author_user_id, client_uuid)', 'A client UUID identifies one BChat message.')
    _digest_format = models.Constraint("CHECK(payload_digest ~ '^[0-9a-f]{64}$')", 'A SHA-256 digest is required.')
    _uuid_format = models.Constraint(
        "CHECK(client_uuid ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')",
        'A canonical UUIDv4 is required.',
    )

    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS baseer_bchat_message_room_id_desc_idx
            ON baseer_bchat_message (room_id, id DESC)
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS baseer_bchat_message_media_uniq
            ON baseer_bchat_message (media_id) WHERE media_id IS NOT NULL
        """)

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BChat message creation is unavailable.'))

    @api.model
    def _create_verified(self, vals, token):
        if token is not _SERVICE_TOKEN:
            raise AccessError(self.env._('A verified BChat service operation is required.'))
        return super(BChatMessage, self.sudo()).create(vals)

    def write(self, vals):
        raise AccessError(self.env._('BChat messages are immutable.'))

    def unlink(self):
        raise AccessError(self.env._('BChat messages cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('BChat messages cannot be copied.'))
