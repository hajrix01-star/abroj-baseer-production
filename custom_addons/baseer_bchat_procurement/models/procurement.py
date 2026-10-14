"""Audit fields for BChat's internal request channel; no new ERP rights."""
from odoo import api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.baseer_procurement_requests.models.procurement import REQUEST_CREATE_INTERNAL


BCHAT_RECEIPT_INTERNAL = 'bchat_receipt_internal'
_STATE_ACTION_FEED_TOKEN = object()


class ProcurementRequest(models.Model):
    _inherit = 'baseer.procurement.request'

    def _bchat_publish_state_result(self, before):
        self.invalidate_recordset(['state'])
        service = self.env['baseer.bchat.service']
        for order in self.sudo():
            if (order.id in before and order.source_channel == 'bchat'
                    and order.state != before[order.id]):
                service._order_publish_change(order)

    def _bchat_prior_states(self):
        return {order.id: order.state for order in self.sudo()
                if order.source_channel == 'bchat'}

    def action_mark_sent(self):
        before = self._bchat_prior_states()
        scoped = self.with_context(bchat_state_action_feed=_STATE_ACTION_FEED_TOKEN)
        result = super(ProcurementRequest, scoped).action_mark_sent()
        self._bchat_publish_state_result(before)
        return result

    def action_confirm_manager_receipt(self):
        before = self._bchat_prior_states()
        scoped = self.with_context(bchat_state_action_feed=_STATE_ACTION_FEED_TOKEN)
        result = super(ProcurementRequest, scoped).action_confirm_manager_receipt()
        self._bchat_publish_state_result(before)
        return result

    def action_confirm_actual_purchase(self):
        before = self._bchat_prior_states()
        scoped = self.with_context(bchat_state_action_feed=_STATE_ACTION_FEED_TOKEN)
        result = super(ProcurementRequest, scoped).action_confirm_actual_purchase()
        self._bchat_publish_state_result(before)
        return result

    def action_cancel(self):
        before = self._bchat_prior_states()
        scoped = self.with_context(bchat_state_action_feed=_STATE_ACTION_FEED_TOKEN)
        result = super(ProcurementRequest, scoped).action_cancel()
        self._bchat_publish_state_result(before)
        return result

    source_channel = fields.Selection([
        ('odoo', 'Odoo'), ('bchat', 'BChat'),
    ], default='odoo', readonly=True, copy=False, index=True)
    internal_submitted_at = fields.Datetime(readonly=True, copy=False, index=True)
    bchat_room_id = fields.Many2one('baseer.bchat.room', readonly=True, copy=False,
                                    check_company=True, ondelete='restrict', index=True)
    bchat_message_id = fields.Many2one('baseer.bchat.message', readonly=True, copy=False,
                                       check_company=True, ondelete='restrict', index=True)
    receipt_client_token = fields.Char(readonly=True, copy=False, index=True)
    receipt_payload_hash = fields.Char(readonly=True, copy=False)

    _bchat_message_unique = models.Constraint(
        'unique(bchat_message_id)', 'A BChat order message may link to only one request.',
    )
    _bchat_receipt_token_unique = models.Constraint(
        'unique(receipt_client_token)', 'A BChat receipt token may be used only once.',
    )

    _bchat_internal_fields = {'source_channel', 'internal_submitted_at',
                              'bchat_room_id', 'bchat_message_id'}
    _bchat_receipt_fields = {'receipt_client_token', 'receipt_payload_hash'}

    @api.model_create_multi
    def create(self, vals_list):
        allowed = bool(self.env.su and self.env.context.get(REQUEST_CREATE_INTERNAL))
        if not allowed and any(self._bchat_internal_fields & set(vals) for vals in vals_list):
            raise AccessError(self.env._('The internal request channel is maintained by the server.'))
        receipt_allowed = bool(self.env.su and self.env.context.get(BCHAT_RECEIPT_INTERNAL))
        if not receipt_allowed and any(self._bchat_receipt_fields & set(vals) for vals in vals_list):
            raise AccessError(self.env._('The receipt replay token is maintained by the server.'))
        return super().create(vals_list)

    def write(self, vals):
        prior_states = self._bchat_prior_states() if 'state' in vals else {}
        if self._bchat_internal_fields & set(vals):
            if not (self.env.su and self.env.context.get(REQUEST_CREATE_INTERNAL)):
                raise AccessError(self.env._('The internal request channel is maintained by the server.'))
        if self._bchat_receipt_fields & set(vals):
            if not (self.env.su and self.env.context.get(BCHAT_RECEIPT_INTERNAL)):
                raise AccessError(self.env._('The receipt replay token is maintained by the server.'))
        result = super().write(vals)
        if prior_states and self.env.context.get('bchat_state_action_feed') is not _STATE_ACTION_FEED_TOKEN:
            self._bchat_publish_state_result(prior_states)
        return result
