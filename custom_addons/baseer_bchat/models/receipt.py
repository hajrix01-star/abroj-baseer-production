"""Reserved immutable receipt schema. No writer exists in this increment."""
from odoo import api, fields, models
from odoo.exceptions import AccessError


class BChatReceipt(models.Model):
    _name = 'baseer.bchat.receipt'
    _description = 'BChat persisted-message receipt (reserved)'
    _order = 'id desc'
    _check_company_auto = True

    user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    client_uuid = fields.Char(required=True, readonly=True, size=36)
    payload_digest = fields.Char(required=True, readonly=True, size=64)
    channel_id = fields.Many2one('discuss.channel', required=True, readonly=True, ondelete='restrict')
    message_id = fields.Many2one('mail.message', required=True, readonly=True, ondelete='restrict')

    _user_uuid_unique = models.Constraint(
        'UNIQUE(user_id, client_uuid)',
        'A client UUID can identify only one message operation for a user.',
    )
    _message_unique = models.Constraint(
        'UNIQUE(message_id)', 'A native message can have only one BChat receipt.',
    )
    _digest_format = models.Constraint(
        "CHECK(payload_digest ~ '^[0-9a-f]{64}$')", 'A SHA-256 payload digest is required.',
    )
    _uuid_format = models.Constraint(
        "CHECK(client_uuid ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')",
        'A canonical UUIDv4 is required.',
    )

    # ACLs also deny mutation. These guards defend alternate ORM entrypoints,
    # even for an administrator. A future writer must be separately reviewed.
    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('BChat receipt creation is not enabled.'))

    def write(self, values):
        raise AccessError(self.env._('BChat receipts are immutable.'))

    def unlink(self):
        raise AccessError(self.env._('BChat receipt deletion is not enabled.'))
