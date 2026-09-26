import json
import math
from uuid import UUID

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class BaseerPosSubstitution(models.Model):
    _name = 'baseer.pos.substitution'
    _description = 'Baseer POS Product Substitution'
    _order = 'event_at desc, id desc'
    _check_company_auto = False

    company_id = fields.Many2one('res.company', required=True, index=True, readonly=True)
    order_id = fields.Many2one('pos.order', required=True, ondelete='restrict', index=True, readonly=True)
    pos_config_id = fields.Many2one('pos.config', required=True, ondelete='restrict', index=True, readonly=True)
    session_id = fields.Many2one('pos.session', required=True, ondelete='restrict', index=True, readonly=True)
    cashier_id = fields.Many2one('res.users', required=True, ondelete='restrict', index=True, readonly=True)
    action_uuid = fields.Char(required=True, readonly=True, index=True)
    request_fingerprint = fields.Char(readonly=True)
    request_payload = fields.Json(readonly=True)
    event_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True, index=True)
    order_reference = fields.Char(required=True, readonly=True, index=True)
    source_product_id = fields.Many2one('product.product', required=True, ondelete='restrict', readonly=True, index=True)
    source_line_uuid = fields.Char(required=True, readonly=True, index=True)
    source_quantity = fields.Float(required=True, readonly=True)
    source_gross = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    replacement_gross = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', required=True, ondelete='restrict', readonly=True)
    replacement_product_ids = fields.Many2many(
        'product.product', 'baseer_substitution_event_product_rel', 'event_id', 'product_id',
        string='Replacement products', readonly=True,
    )
    reason_note = fields.Char(readonly=True)
    source_snapshot = fields.Json(required=True, readonly=True)
    replacement_snapshot = fields.Json(required=True, readonly=True)

    _order_action_uuid_unique = models.Constraint(
        'unique(order_id, action_uuid)', 'A product substitution action may only be recorded once per order.')

    @api.model
    def _canonical_uuid(self, value):
        if not isinstance(value, str):
            raise ValidationError(_('The substitution action identifier is invalid.'))
        try:
            return str(UUID(value))
        except (ValueError, AttributeError, TypeError):
            raise ValidationError(_('The substitution action identifier is invalid.'))

    @api.model
    def _normalize_action(self, raw):
        if not isinstance(raw, dict):
            raise ValidationError(_('The substitution request is invalid.'))
        source_uuid = raw.get('source_line_uuid')
        if not isinstance(source_uuid, str) or not source_uuid.strip() or len(source_uuid) > 128:
            raise ValidationError(_('The protected order line is invalid.'))
        reason_note = raw.get('reason_note') or ''
        if not isinstance(reason_note, str) or len(reason_note.strip()) > 250:
            raise ValidationError(_('The substitution note is invalid.'))
        requested = raw.get('replacements')
        if not isinstance(requested, list) or not requested or len(requested) > 20:
            raise ValidationError(_('Choose one or more replacement products.'))
        replacements = []
        seen = set()
        for item in requested:
            if not isinstance(item, dict) or isinstance(item.get('product_id'), bool):
                raise ValidationError(_('A replacement product is invalid.'))
            product_id = item.get('product_id')
            quantity = item.get('quantity')
            line_uuid = item.get('line_uuid')
            if not isinstance(product_id, int) or product_id <= 0 or product_id in seen:
                raise ValidationError(_('A replacement product is invalid.'))
            if not isinstance(line_uuid, str) or not line_uuid.strip() or len(line_uuid) > 128:
                raise ValidationError(_('A replacement order line is invalid.'))
            if (isinstance(quantity, bool) or not isinstance(quantity, (int, float))
                    or not math.isfinite(quantity) or quantity <= 0 or quantity > 1000):
                raise ValidationError(_('A replacement quantity is invalid.'))
            seen.add(product_id)
            replacements.append({
                'product_id': product_id, 'quantity': quantity, 'line_uuid': line_uuid.strip(),
            })
        return {
            'action_uuid': self._canonical_uuid(raw.get('action_uuid')),
            'source_line_uuid': source_uuid.strip(),
            'reason_note': reason_note.strip(),
            'replacements': replacements,
        }

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.context.get('baseer_substitution_internal'):
            raise AccessError(_('Substitution audit records are created only by the Point of Sale workflow.'))
        return super().create(values_list)

    def write(self, values):
        raise AccessError(_('Substitution audit records are immutable.'))

    def unlink(self):
        raise AccessError(_('Substitution audit records cannot be deleted.'))

    def _snapshot_text(self):
        return json.dumps(self.source_snapshot, ensure_ascii=False)
