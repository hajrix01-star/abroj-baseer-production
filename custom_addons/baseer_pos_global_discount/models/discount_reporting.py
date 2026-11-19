"""Attribute owned invoice allowances to their sale/refund product, without financial writes."""
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import float_is_zero


def _replace_once(sql, pattern, replacement):
    result, count = re.subn(pattern, replacement, sql, flags=re.MULTILINE)
    if count != 1:
        raise ValidationError(_('The native POS report query changed. Review the invoice discount report integration before upgrading.'))
    return result


class ReportPosOrder(models.Model):
    _inherit = 'report.pos.order'

    total_discount = fields.Float(string='Line discounts (unit-price basis)')
    baseer_invoice_discount = fields.Float(string='Invoice discount (excl. VAT)', readonly=True)

    def _select(self):
        query = super()._select()
        # Preserve every inherited measure/category, including native rounding.
        # Allowances are converted and rounded individually below, exactly as
        # their former native rows, before attribution to the original SKU.
        for alias in ('price_subtotal_excl', 'price_total', 'margin'):
            query = _replace_once(
                query,
                rf'^(?P<indent>[ \t]+)(?P<expression>[^\n]+?) AS {alias}(?P<suffix>,[^\n]*)$',
                lambda match, field=alias: (
                    f"{match['indent']}({match['expression']} + "
                    f"COALESCE(baseer_discount_allocations.{field}, 0)) AS {field}{match['suffix']}"
                ),
            )
        return query + ', -COALESCE(baseer_discount_allocations.price_subtotal_excl, 0) AS baseer_invoice_discount'

    def _from(self):
        query = super()._from()
        # Filter in the existing INNER JOIN, not in a trailing WHERE: other
        # addons append their own joins (for example Baseer's root categories).
        query = _replace_once(
            query,
            r'INNER JOIN pos_order s ON \(s\.id=l\.order_id\)',
            """INNER JOIN pos_order s ON (s.id=l.order_id AND NOT (
                COALESCE(s.baseer_global_discount_locked, FALSE) AND (
                    COALESCE(l.baseer_global_discount_line, FALSE)
                    OR (
                        l.combo_parent_id IS NULL AND l.price_unit = 0
                        AND l.price_subtotal = 0 AND l.price_subtotal_incl = 0
                        AND EXISTS (
                            SELECT 1 FROM product_product gd_product
                            JOIN product_template gd_template ON gd_template.id = gd_product.product_tmpl_id
                            WHERE gd_product.id = l.product_id AND gd_template.type = 'combo'
                        )
                        AND EXISTS (
                            SELECT 1 FROM pos_order_line gd_child
                            WHERE gd_child.combo_parent_id = l.id AND gd_child.order_id = l.order_id
                        )
                    )
                )
            ))""",
        )
        return query + """
            LEFT JOIN LATERAL (
                SELECT
                    SUM(ROUND((SIGN(a.qty) * SIGN(a.price_unit) * ABS(a.price_subtotal))
                        / COALESCE(NULLIF(s.currency_rate, 0), 1.0), cu.decimal_places)) AS price_subtotal_excl,
                    SUM(ROUND((SIGN(a.qty) * SIGN(a.price_unit) * ABS(a.price_subtotal_incl))
                        / COALESCE(NULLIF(s.currency_rate, 0), 1.0), cu.decimal_places)) AS price_total,
                    SUM(((SIGN(a.qty) * SIGN(a.price_unit) * ABS(a.price_subtotal)) - COALESCE(a.total_cost, 0))
                        / COALESCE(NULLIF(s.currency_rate, 0), 1.0)) AS margin
                FROM pos_order_line a
                WHERE COALESCE(s.baseer_global_discount_locked, FALSE)
                    AND a.baseer_global_discount_line IS TRUE
                    AND a.baseer_global_discount_source_id = l.id
                    AND a.order_id = l.order_id
            ) baseer_discount_allocations ON TRUE
        """


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    baseer_global_discount_allocation_ids = fields.One2many(
        'pos.order.line', 'baseer_global_discount_source_id',
        string='Invoice discount allocations', readonly=True, copy=False,
    )

    @api.model_create_multi
    def create(self, values_list):
        if any('baseer_global_discount_allocation_ids' in values for values in values_list):
            raise AccessError(_('Invoice discount allocations are read-only.'))
        return super().create(values_list)

    def write(self, values):
        if 'baseer_global_discount_allocation_ids' in values:
            raise AccessError(_('Invoice discount allocations are read-only.'))
        return super().write(values)

    @api.depends(
        'price_subtotal', 'qty', 'price_unit', 'total_cost', 'product_id.type', 'order_id.is_refund',
        'order_id.baseer_global_discount_locked', 'baseer_global_discount_line',
        'baseer_global_discount_allocation_ids.price_subtotal',
        'baseer_global_discount_allocation_ids.qty',
        'baseer_global_discount_allocation_ids.price_unit',
        'baseer_global_discount_allocation_ids.total_cost',
        'baseer_global_discount_allocation_ids.baseer_global_discount_line',
        'baseer_global_discount_allocation_ids.order_id',
    )
    def _compute_margin(self):
        super()._compute_margin()
        for line in self.filtered(lambda item: item.order_id.baseer_global_discount_locked):
            if line.baseer_global_discount_line or line.product_id.type == 'combo':
                line.margin = 0
                line.margin_percent = 0
                continue
            allocations = line.baseer_global_discount_allocation_ids.filtered(
                lambda item: item.baseer_global_discount_line and item.order_id == line.order_id
            )
            # Match the native SQL report's canonical sign. Earlier managed
            # refunds stored signed subtotals; new refunds use native subtotal
            # orientation. This display-only projection supports both without
            # rewriting historical financial fields.
            def signed_revenue(item):
                return (((item.qty > 0) - (item.qty < 0))
                        * ((item.price_unit > 0) - (item.price_unit < 0))
                        * abs(item.price_subtotal))
            allocated_revenue = sum(signed_revenue(item) for item in allocations)
            net_revenue = signed_revenue(line) + allocated_revenue
            line.margin = net_revenue - line.total_cost - sum(allocations.mapped('total_cost'))
            line.margin_percent = (
                line.margin / net_revenue
                if not float_is_zero(net_revenue, precision_rounding=line.currency_id.rounding) else 0
            )
