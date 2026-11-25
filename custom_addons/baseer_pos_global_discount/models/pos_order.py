"""Preserve historical discount data and prevent unsafe legacy refunds."""
from copy import deepcopy

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_ORDER_METADATA = {'baseer_global_discount_kind', 'baseer_global_discount_value',
                   'baseer_global_discount_gross', 'baseer_global_discount_locked',
                   'baseer_global_discount_reason', 'baseer_global_discount_snapshot',
                   'baseer_offline_draft_kind', 'baseer_offline_draft_value',
                   'baseer_offline_draft_revision', 'baseer_offline_draft_command_uuid',
                   'baseer_offline_draft_digest'}
_LINE_METADATA = {'baseer_global_discount_line', 'baseer_global_discount_source_id'}


class DiscountEvent(models.Model):
    _name = 'baseer.pos.global.discount.event'
    _description = 'Immutable invoice discount command'
    _order = 'id desc'

    order_id = fields.Many2one('pos.order', ondelete='set null', index=True)
    order_uuid = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    action_uuid = fields.Char(required=True, index=True)
    fingerprint = fields.Char(required=True)
    payload = fields.Json(required=True)
    _unique_action = models.Constraint('unique(action_uuid)', 'This discount command already exists.')

    @api.model_create_multi
    def create(self, values):
        raise AccessError(_('Discount audit records cannot be created.'))

    def write(self, values):
        raise AccessError(_('Discount audit records cannot be changed.'))

    def unlink(self):
        raise AccessError(_('Discount audit records cannot be removed.'))

    def check_access_rule(self, operation):
        super().check_access_rule(operation)
        if any(event.company_id not in self.env.companies for event in self):
            raise AccessError(_('This discount belongs to another company.'))


class PosOrder(models.Model):
    _inherit = 'pos.order'

    baseer_global_discount_kind = fields.Selection([('percent', 'Percentage'), ('fixed', 'Fixed amount'), ('refund', 'Refund allocation')], readonly=True, copy=False)
    baseer_global_discount_value = fields.Char(readonly=True, copy=False)
    baseer_global_discount_gross = fields.Monetary(readonly=True, copy=False)
    baseer_global_discount_reason = fields.Char(readonly=True, copy=False)
    baseer_global_discount_locked = fields.Boolean(readonly=True, copy=False)
    baseer_global_discount_snapshot = fields.Json(readonly=True, copy=False)
    baseer_offline_draft_kind = fields.Selection([('percent', 'Percentage'), ('fixed', 'Fixed amount')], readonly=True, copy=False)
    baseer_offline_draft_value = fields.Char(readonly=True, copy=False)
    baseer_offline_draft_revision = fields.Integer(readonly=True, copy=False, default=0)
    baseer_offline_draft_command_uuid = fields.Char(readonly=True, copy=False)
    baseer_offline_draft_digest = fields.Char(readonly=True, copy=False)

    @api.model
    def _load_pos_data_fields(self, config):
        inherited = super()._load_pos_data_fields(config)
        private = {'baseer_global_discount_snapshot', 'baseer_offline_draft_command_uuid', 'baseer_offline_draft_digest'}
        return list(dict.fromkeys(inherited + sorted(_ORDER_METADATA - private))) if inherited else inherited

    def _check_legacy_discount_refund(self):
        sources = self.lines.refunded_orderline_id
        if sources.filtered(lambda line: line.baseer_global_discount_line or line.order_id.baseer_global_discount_locked):
            raise UserError(_('This order used the old invoice discount and cannot be refunded in the POS. Ask accounting to issue a credit note on its invoice.'))

    def _check_legacy_discount_sale(self):
        for order in self:
            old_product = order.config_id.baseer_global_discount_product_id
            if order.baseer_global_discount_locked or order.lines.filtered(
                lambda line: line.baseer_global_discount_line or (
                    old_product and old_product != order.config_id.discount_product_id
                    and line.product_id == old_product and line.price_unit < 0)
            ):
                raise UserError(_('This order contains an old invoice discount. Keep it for manager review.'))

    @api.model
    def sync_from_ui(self, orders):
        orders = deepcopy(orders)
        for order in orders:
            # A nonempty intent contains financial evidence, so do not silently
            # submit a sale after dropping it. The device keeps it for review.
            if (order.get('baseer_offline_discount_intent') or order.get('baseer_offline_draft_kind')
                    or order.get('baseer_global_discount_locked') or order.get('baseer_global_discount_kind')
                    or order.get('baseer_global_discount_gross')):
                raise UserError(_('This order contains an old invoice discount. Keep it for manager review.'))
            for key in ('baseer_offline_draft_command', 'baseer_offline_discount_intent',
                        'baseer_offline_discount_account_proofs', 'baseer_offline_discount_proof',
                        'baseer_offline_discount_digest', 'baseer_offline_discount_fingerprint'):
                order.pop(key, None)
            for key in _ORDER_METADATA:
                order.pop(key, None)
            existing_order = self._get_open_order(order)
            if existing_order and existing_order.state == 'draft':
                existing_order._check_legacy_discount_sale()
            session = self.env['pos.session'].browse(order.get('session_id')).exists()
            config = session.config_id
            old_product = config.baseer_global_discount_product_id
            for command in order.get('lines', []):
                if len(command) < 3 or not isinstance(command[2], dict):
                    continue
                vals = command[2]
                existing = self.env['pos.order.line'].browse(command[1]).exists() if command[0] == 1 else self.env['pos.order.line']
                marker = vals.get('baseer_global_discount_line') or (existing and existing.baseer_global_discount_line)
                product = vals.get('product_id', existing.product_id.id if existing else False)
                price = vals.get('price_unit', existing.price_unit if existing else 0)
                if marker or (old_product and old_product != config.discount_product_id and product == old_product.id and price < 0):
                    raise UserError(_('This order contains an old invoice discount. Keep it for manager review.'))
                for key in _LINE_METADATA:
                    vals.pop(key, None)
        return super().sync_from_ui(orders)

    def _process_saved_order(self, draft):
        self._check_legacy_discount_refund()
        self._check_legacy_discount_sale()
        return super()._process_saved_order(draft)

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.su and any(any(values.get(key) for key in _ORDER_METADATA) for values in values_list):
            raise AccessError(_('Historical invoice discount data is read-only.'))
        return super().create(values_list)

    def write(self, values):
        if not self.env.su and _ORDER_METADATA.intersection(values):
            raise AccessError(_('Historical invoice discount data is read-only.'))
        if values.get('state') in ('paid', 'done'):
            drafts = self.filtered(lambda order: order.state == 'draft')
            drafts._check_legacy_discount_refund()
            drafts._check_legacy_discount_sale()
        return super().write(values)


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    baseer_global_discount_line = fields.Boolean(readonly=True, copy=False)
    baseer_global_discount_source_id = fields.Many2one('pos.order.line', readonly=True, copy=False, ondelete='restrict', index=True)

    @api.model
    def _load_pos_data_fields(self, config):
        inherited = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(inherited + sorted(_LINE_METADATA))) if inherited else inherited

    @api.model
    def _check_legacy_refund_source(self, source_id):
        source = self.browse(source_id).exists() if source_id else self.browse()
        if source and (source.baseer_global_discount_line or source.order_id.baseer_global_discount_locked):
            raise UserError(_('This order used the old invoice discount and cannot be refunded in the POS. Ask accounting to issue a credit note on its invoice.'))

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if not self.env.su and any(values.get(key) for key in _LINE_METADATA):
                raise AccessError(_('Historical invoice discount data is read-only.'))
            self._check_legacy_refund_source(values.get('refunded_orderline_id'))
        return super().create(values_list)

    def write(self, values):
        if not self.env.su and _LINE_METADATA.intersection(values):
            raise AccessError(_('Historical invoice discount data is read-only.'))
        if values.get('refunded_orderline_id'):
            self._check_legacy_refund_source(values['refunded_orderline_id'])
        return super().write(values)
