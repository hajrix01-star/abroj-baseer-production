"""Explicit per-membership delivery/read acknowledgements for BChat messages."""

from odoo import api, fields, models
from odoo.exceptions import AccessError


_RECEIPT_TOKEN = object()


class BChatMessageReceipt(models.Model):
    _name = 'baseer.bchat.message.receipt'
    _description = 'BChat private message recipient acknowledgement'
    _order = 'id'
    _check_company_auto = True

    message_id = fields.Many2one('baseer.bchat.message', required=True, readonly=True,
                                 ondelete='restrict', index=True)
    membership_id = fields.Many2one('baseer.bchat.membership', required=True, readonly=True,
                                    ondelete='restrict', index=True)
    recipient_user_id = fields.Many2one('res.users', required=True, readonly=True,
                                       ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True,
                                 ondelete='restrict', index=True)
    delivered_at = fields.Datetime(readonly=True)
    read_at = fields.Datetime(readonly=True)

    _message_member_unique = models.Constraint(
        'UNIQUE(message_id, membership_id)', 'One BChat receipt per message and membership epoch.',
    )
    _read_after_delivery = models.Constraint(
        'CHECK(read_at IS NULL OR delivered_at IS NOT NULL)',
        'A read receipt also requires delivery.',
    )

    def init(self):
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bchat_receipt_unread_member_idx
            ON baseer_bchat_message_receipt (membership_id, message_id)
            WHERE read_at IS NULL
        ''')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BChat receipt creation is unavailable.'))

    @api.model
    def _create_verified(self, vals_list, token):
        if token is not _RECEIPT_TOKEN:
            raise AccessError(self.env._('A verified BChat message is required.'))
        return super(BChatMessageReceipt, self.sudo()).create(vals_list)

    def write(self, vals):
        raise AccessError(self.env._('Direct BChat receipt changes are unavailable.'))

    def _write_verified(self, vals, token):
        if token is not _RECEIPT_TOKEN or set(vals) - {'delivered_at', 'read_at'}:
            raise AccessError(self.env._('A verified BChat acknowledgement is required.'))
        return super(BChatMessageReceipt, self.sudo()).write(vals)

    def _eligibility_exclusion_reason(self):
        """Current eligibility is not evidence that somebody read a message.

        This internal, content-free reason is computed without changing either
        original acknowledgement timestamp. Restoring a right restores the
        original outstanding receipt, never a fabricated acknowledgement.
        """
        self.ensure_one()
        member = self.membership_id
        user = self.recipient_user_id
        message = self.message_id
        if (not member.active or member.user_id != user
                or member.room_id != message.room_id
                or member.company_id != message.company_id
                or message.id <= member.joined_after_message_id):
            return 'membership_ended'
        if not user.active or not user._is_internal():
            return 'account_inactive'
        if message.company_id not in user.company_ids:
            return 'company_revoked'
        if not user._bchat_effective_permissions()['chat_view']:
            return 'chat_revoked'
        return False

    def unlink(self):
        raise AccessError(self.env._('BChat message receipts cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('BChat message receipts cannot be copied.'))
