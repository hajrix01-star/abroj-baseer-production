"""Content-free retry receipts; never generic ORM access to private metadata."""
import hashlib
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..contracts import ProtocolError, canonical_uuid


_SOCIAL_TOKEN = object()


class BChatSocialOperation(models.Model):
    _name = 'baseer.bchat.social.operation'
    _description = 'BChat private social operation receipt'
    _order = 'id desc'

    actor_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict', index=True)
    action = fields.Char(required=True, readonly=True, size=32)
    client_uuid = fields.Char(required=True, readonly=True, size=36)
    payload_digest = fields.Char(required=True, readonly=True, size=64)
    result_json = fields.Text(required=True, readonly=True)

    _actor_action_uuid_unique = models.Constraint(
        'UNIQUE(actor_id, action, client_uuid)', 'One social operation receipt belongs to one user intent.',
    )
    _digest_format = models.Constraint("CHECK(payload_digest ~ '^[0-9a-f]{64}$')", 'A SHA-256 digest is required.')
    _uuid_format = models.Constraint(
        "CHECK(client_uuid ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')",
        'A canonical operation UUIDv4 is required.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Private BChat operation receipts are service-owned.'))

    def write(self, vals):
        raise AccessError(self.env._('Private BChat operation receipts are immutable.'))

    def unlink(self):
        raise AccessError(self.env._('Private BChat operation receipts are immutable.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('Private BChat operation receipts cannot be copied.'))

    @api.model
    def _create_verified(self, values, token):
        if token is not _SOCIAL_TOKEN or set(values) != {
                'actor_id', 'action', 'client_uuid', 'payload_digest', 'result_json'}:
            raise AccessError(self.env._('A verified BChat operation receipt is required.'))
        if len(values['result_json'].encode('utf-8')) > 4096:
            raise ProtocolError('result_too_large', 'Operation receipt exceeds its supported size.', 413)
        return super(BChatSocialOperation, self.sudo()).create(values)


class BChatSocialOperationService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _social_lock_operation(self, action, token, intent):
        user = self._require_user()
        token = canonical_uuid(token)
        if type(action) is not str or not action or len(action) > 32:
            raise ValueError('Invalid internal social operation action')
        digest = hashlib.sha256(json.dumps(intent, ensure_ascii=False, sort_keys=True,
                                          separators=(',', ':')).encode('utf-8')).hexdigest()
        self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                            ['bchat-social:%s:%s:%s' % (user.id, action, token)])
        existing = self.env['baseer.bchat.social.operation'].sudo().search([
            ('actor_id', '=', user.id), ('action', '=', action), ('client_uuid', '=', token),
        ], limit=1)
        if not existing:
            # Advisory locks do not refresh an Odoo REPEATABLE READ snapshot.
            # A committed receipt which won while we waited must be read from
            # a fresh snapshot, with fresh scope authorization, not recreated.
            with self.env.registry.cursor() as fresh_cr:
                fresh_cr.execute('''
                    SELECT payload_digest, result_json FROM baseer_bchat_social_operation
                    WHERE actor_id = %s AND action = %s AND client_uuid = %s
                ''', [user.id, action, token])
                row = fresh_cr.fetchone()
                if row:
                    fresh = api.Environment(fresh_cr, user.id, {
                        'allowed_company_ids': self.env.context.get('allowed_company_ids', []),
                    })
                    fresh['baseer.bchat.service']._social_replay_guard(action, intent)
                    if row[0] != digest:
                        raise ProtocolError('idempotency_conflict', 'This operation UUID belongs to another intent.', 409)
                    return digest, json.loads(row[1])
        if existing and existing.payload_digest != digest:
            raise ProtocolError('idempotency_conflict', 'This operation UUID belongs to another intent.', 409)
        return digest, json.loads(existing.result_json) if existing else None

    @api.model
    def _social_replay_guard(self, action, intent):
        """Each supported action owns its fresh, non-locking scope check."""
        raise AccessError(self.env._('This private operation scope is unavailable.'))

    @api.model
    def _social_complete_operation(self, action, token, digest, result):
        user = self._require_user()
        self.env['baseer.bchat.social.operation']._create_verified({
            'actor_id': user.id, 'action': action, 'client_uuid': token,
            'payload_digest': digest,
            'result_json': json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
        }, _SOCIAL_TOKEN)
