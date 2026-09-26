from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class BaseerPosProtectedItemCancellation(models.Model):
    _name = 'baseer.pos.protected_item_cancellation'
    _description = 'Baseer POS Protected Item Cancellation'
    _order = 'event_at desc, id desc'
    _check_company_auto = False

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    order_id = fields.Many2one('pos.order', required=True, ondelete='restrict', readonly=True, index=True)
    pos_config_id = fields.Many2one('pos.config', required=True, ondelete='restrict', readonly=True, index=True)
    session_id = fields.Many2one('pos.session', required=True, ondelete='restrict', readonly=True, index=True)
    cashier_id = fields.Many2one('res.users', required=True, ondelete='restrict', readonly=True, index=True)
    action_uuid = fields.Char(required=True, readonly=True, index=True)
    request_fingerprint = fields.Char(readonly=True)
    request_payload = fields.Json(readonly=True)
    event_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True, index=True)
    order_reference = fields.Char(required=True, readonly=True, index=True)
    source_product_id = fields.Many2one('product.product', required=True, ondelete='restrict', readonly=True, index=True)
    source_line_uuid = fields.Char(required=True, readonly=True, index=True)
    source_quantity = fields.Float(required=True, readonly=True)
    source_gross = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', required=True, ondelete='restrict', readonly=True)
    reason_code = fields.Char(required=True, readonly=True, index=True)
    reason_note = fields.Char(readonly=True)
    source_snapshot = fields.Json(required=True, readonly=True)

    _order_action_uuid_unique = models.Constraint(
        'unique(order_id, action_uuid)', 'A protected item cancellation may only be recorded once per order.')

    @api.model
    def _normalize_action(self, raw):
        if not isinstance(raw, dict):
            raise ValidationError(_('The protected item cancellation request is invalid.'))
        source_uuid = raw.get('source_line_uuid')
        if not isinstance(source_uuid, str) or not source_uuid.strip() or len(source_uuid) > 128:
            raise ValidationError(_('The protected order line is invalid.'))
        action_uuid = self.env['baseer.pos.substitution']._canonical_uuid(raw.get('action_uuid'))
        reason_code, reason_note = self.env['baseer.print.cancellation']._normalized_reason(
            raw.get('reason_code'), raw.get('reason_note') or '',
        )
        return {
            'action_uuid': action_uuid,
            'source_line_uuid': source_uuid.strip(),
            'reason_code': reason_code,
            'reason_note': reason_note,
        }

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('baseer_protected_item_cancellation_internal'):
            raise AccessError(_('Protected item cancellation records are created only by the POS workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Protected item cancellation records are immutable.'))

    def unlink(self):
        raise AccessError(_('Protected item cancellation records cannot be deleted.'))
