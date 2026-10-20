"""Audit fields for BWork's internal request channel; no new ERP rights."""
from odoo.addons.baseer_bwork.compatibility import LEGACY_SOURCE_CHANNEL

from odoo import api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.baseer_procurement_requests.models.procurement import REQUEST_CREATE_INTERNAL


BWORK_RECEIPT_INTERNAL = 'bwork_receipt_internal'
_STATE_ACTION_FEED_TOKEN = object()


class ProcurementRequest(models.Model):
    _inherit = 'baseer.procurement.request'
    # The base ERP addon must not import/initialize this optional addon.
    _bwork_source_channel = LEGACY_SOURCE_CHANNEL

    def _bwork_publish_state_result(self, before):
        self.invalidate_recordset(['state'])
        service = self.env['baseer.bwork.service']
        for order in self.sudo():
            if (order.id in before and order.source_channel == LEGACY_SOURCE_CHANNEL
                    and order.state != before[order.id]):
                service._order_publish_change(order)

    def _bwork_prior_states(self):
        return {order.id: order.state for order in self.sudo()
                if order.source_channel == LEGACY_SOURCE_CHANNEL}

    def action_mark_sent(self):
        before = self._bwork_prior_states()
        scoped = self.with_context(bwork_state_action_feed=_STATE_ACTION_FEED_TOKEN)
        result = super(ProcurementRequest, scoped).action_mark_sent()
        self._bwork_publish_state_result(before)
        return result

    def action_confirm_manager_receipt(self):
        before = self._bwork_prior_states()
        scoped = self.with_context(bwork_state_action_feed=_STATE_ACTION_FEED_TOKEN)
        result = super(ProcurementRequest, scoped).action_confirm_manager_receipt()
        self._bwork_publish_state_result(before)
        return result

    def action_confirm_actual_purchase(self):
        before = self._bwork_prior_states()
        scoped = self.with_context(bwork_state_action_feed=_STATE_ACTION_FEED_TOKEN)
        result = super(ProcurementRequest, scoped).action_confirm_actual_purchase()
        self._bwork_publish_state_result(before)
        return result

    def action_cancel(self):
        before = self._bwork_prior_states()
        scoped = self.with_context(bwork_state_action_feed=_STATE_ACTION_FEED_TOKEN)
        result = super(ProcurementRequest, scoped).action_cancel()
        self._bwork_publish_state_result(before)
        return result

    source_channel = fields.Selection([
        ('odoo', 'Odoo'), (LEGACY_SOURCE_CHANNEL, 'BWork'),
    ], default='odoo', readonly=True, copy=False, index=True)
    internal_submitted_at = fields.Datetime(readonly=True, copy=False, index=True)
    bwork_room_id = fields.Many2one('baseer.bwork.room', readonly=True, copy=False,
                                    check_company=True, ondelete='restrict', index=True)
    bwork_message_id = fields.Many2one('baseer.bwork.message', readonly=True, copy=False,
                                       check_company=True, ondelete='restrict', index=True)
    receipt_client_token = fields.Char(readonly=True, copy=False, index=True)
    receipt_payload_hash = fields.Char(readonly=True, copy=False)
    receipt_share_uuid = fields.Char(readonly=True, copy=False, size=36, index=True)
    receipt_result_message_id = fields.Many2one(
        'baseer.bwork.message', readonly=True, copy=False, check_company=True,
        ondelete='restrict', index=True,
    )

    _bwork_message_unique = models.Constraint(
        'unique(bwork_message_id)', 'A BWork order message may link to only one request.',
    )
    _bwork_receipt_token_unique = models.Constraint(
        'unique(receipt_client_token)', 'A BWork receipt token may be used only once.',
    )
    _bwork_receipt_share_uuid_unique = models.Constraint(
        'unique(receipt_share_uuid)', 'A BWork receipt result UUID may be used only once.',
    )
    _bwork_receipt_result_message_unique = models.Constraint(
        'unique(receipt_result_message_id)', 'A BWork receipt result message may link to only one request.',
    )

    _bwork_internal_fields = {'source_channel', 'internal_submitted_at',
                              'bwork_room_id', 'bwork_message_id'}
    _bwork_receipt_fields = {
        'receipt_client_token', 'receipt_payload_hash',
        'receipt_share_uuid', 'receipt_result_message_id',
    }

    @api.model_create_multi
    def create(self, vals_list):
        allowed = bool(self.env.su and self.env.context.get(REQUEST_CREATE_INTERNAL))
        if not allowed and any(self._bwork_internal_fields & set(vals) for vals in vals_list):
            raise AccessError(self.env._('The internal request channel is maintained by the server.'))
        receipt_allowed = bool(self.env.su and self.env.context.get(BWORK_RECEIPT_INTERNAL))
        if not receipt_allowed and any(self._bwork_receipt_fields & set(vals) for vals in vals_list):
            raise AccessError(self.env._('The receipt replay token is maintained by the server.'))
        return super().create(vals_list)

    def write(self, vals):
        prior_states = self._bwork_prior_states() if 'state' in vals else {}
        if self._bwork_internal_fields & set(vals):
            if not (self.env.su and self.env.context.get(REQUEST_CREATE_INTERNAL)):
                raise AccessError(self.env._('The internal request channel is maintained by the server.'))
        if self._bwork_receipt_fields & set(vals):
            if not (self.env.su and self.env.context.get(BWORK_RECEIPT_INTERNAL)):
                raise AccessError(self.env._('The receipt replay token is maintained by the server.'))
        result = super().write(vals)
        if prior_states and self.env.context.get('bwork_state_action_feed') is not _STATE_ACTION_FEED_TOKEN:
            self._bwork_publish_state_result(prior_states)
        return result
