"""Explicit per-membership delivery/read acknowledgements for BWork messages."""

from odoo import api, fields, models
from odoo.exceptions import AccessError


_RECEIPT_TOKEN = object()


class BWorkMessageReceipt(models.Model):
    _name = 'baseer.bwork.message.receipt'
    _description = 'BWork private message recipient acknowledgement'
    _order = 'id'
    _check_company_auto = True

    message_id = fields.Many2one('baseer.bwork.message', required=True, readonly=True,
                                 ondelete='restrict', index=True)
    membership_id = fields.Many2one('baseer.bwork.membership', required=True, readonly=True,
                                    ondelete='restrict', index=True)
    recipient_user_id = fields.Many2one('res.users', required=True, readonly=True,
                                       ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True,
                                 ondelete='restrict', index=True)
    delivered_at = fields.Datetime(readonly=True)
    read_at = fields.Datetime(readonly=True)

    _message_member_unique = models.Constraint(
        'UNIQUE(message_id, membership_id)', 'One BWork receipt per message and membership epoch.',
    )
    _read_after_delivery = models.Constraint(
        'CHECK(read_at IS NULL OR delivered_at IS NOT NULL)',
        'A read receipt also requires delivery.',
    )

    def init(self):
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bwork_receipt_unread_member_idx
            ON baseer_bwork_message_receipt (membership_id, message_id)
            WHERE read_at IS NULL
        ''')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BWork receipt creation is unavailable.'))

    @api.model
    def _create_verified(self, vals_list, token):
        if token is not _RECEIPT_TOKEN:
            raise AccessError(self.env._('A verified BWork message is required.'))
        return super(BWorkMessageReceipt, self.sudo()).create(vals_list)

    def write(self, vals):
        raise AccessError(self.env._('Direct BWork receipt changes are unavailable.'))

    def _write_verified(self, vals, token):
        if token is not _RECEIPT_TOKEN or set(vals) - {'delivered_at', 'read_at'}:
            raise AccessError(self.env._('A verified BWork acknowledgement is required.'))
        return super(BWorkMessageReceipt, self.sudo()).write(vals)

    def unlink(self):
        raise AccessError(self.env._('BWork message receipts cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('BWork message receipts cannot be copied.'))
