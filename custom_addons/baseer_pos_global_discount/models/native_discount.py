import hashlib
import json
import math
from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_fixed_discount_enabled = fields.Boolean(string='Fixed discount enabled')
    baseer_fixed_discount_max_amount = fields.Monetary(string='Maximum fixed discount', currency_field='currency_id', help='Zero means no additional cap.')
    baseer_fixed_discount_allowed = fields.Selection([('all', 'All cashiers allowed to discount'), ('managers', 'Managers only')], default='managers', required=True, string='Fixed discount access')

    @api.constrains('baseer_fixed_discount_max_amount')
    def _check_fixed_discount_max_amount(self):
        if any(config.baseer_fixed_discount_max_amount < 0 for config in self):
            raise ValidationError(_('The fixed discount limit cannot be negative.'))

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(result + ['baseer_fixed_discount_enabled', 'baseer_fixed_discount_max_amount', 'baseer_fixed_discount_allowed'])) if result else result


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_baseer_fixed_discount_enabled = fields.Boolean(related='pos_config_id.baseer_fixed_discount_enabled', readonly=False)
    pos_baseer_fixed_discount_max_amount = fields.Monetary(related='pos_config_id.baseer_fixed_discount_max_amount', readonly=False, currency_field='baseer_global_discount_currency_id')
    pos_baseer_fixed_discount_allowed = fields.Selection(related='pos_config_id.baseer_fixed_discount_allowed', readonly=False)


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    baseer_discount_share_incl = fields.Monetary(string='Invoice discount share (incl. tax)', readonly=True, copy=False)
    baseer_discount_share_excl = fields.Monetary(string='Invoice discount share (excl. tax)', readonly=True, copy=False)

    baseer_discount_kind = fields.Selection([('percent', 'Percentage'), ('fixed', 'Fixed amount')], string='Discount kind')
    baseer_discount_input = fields.Float(string='Discount input')
    baseer_discount_approved_by_user_id = fields.Many2one('res.users', string='Discount approving user')
    baseer_discount_approved_by_employee = fields.Integer(string='Discount approving employee ID')
    baseer_discount_approved_by_employee_name = fields.Char(string='Discount approving employee')

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(result + ['baseer_discount_share_incl', 'baseer_discount_share_excl', 'baseer_discount_kind', 'baseer_discount_input', 'baseer_discount_approved_by_user_id', 'baseer_discount_approved_by_employee', 'baseer_discount_approved_by_employee_name'])) if result else result


class PosOrder(models.Model):
    _inherit = 'pos.order'

    baseer_discount_logged_signature = fields.Char(copy=False, readonly=True)

    @api.model
    def _process_order(self, order, existing_order):
        # This audit marker is server-owned, even if a client sends readonly fields.
        order.pop('baseer_discount_logged_signature', None)
        order_id = super()._process_order(order, existing_order)
        self.browse(order_id)._baseer_validate_native_discount()
        return order_id

    def _baseer_allocate_native_shares(self, discounts):
        self.ensure_one()
        sources = (self.lines - discounts).filtered(
            lambda line: not (self.config_id.tip_product_id and line.product_id == self.config_id.tip_product_id))
        sources.write({'baseer_discount_share_incl': 0, 'baseer_discount_share_excl': 0})
        groups = defaultdict(list)
        for line in sources:
            groups[tuple(sorted(line.tax_ids_after_fiscal_position.ids))].append(line)
        for discount in discounts:
            lines = groups[tuple(sorted(discount.tax_ids.ids))]
            for field, subtotal in [('baseer_discount_share_incl', 'price_subtotal_incl'),
                                    ('baseer_discount_share_excl', 'price_subtotal')]:
                weights = [max(Decimal(str(getattr(line, subtotal))), Decimal(0)) for line in lines]
                total = sum(weights)
                units = int((Decimal(str(abs(self.currency_id.round(getattr(discount, subtotal))))) /
                             Decimal(str(self.currency_id.rounding))).to_integral_value())
                if not total:
                    if units:
                        raise UserError(_('The discount lines do not match the approved discount.'))
                    continue
                exact = [Decimal(units) * weight / total for weight in weights]
                allocated = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
                for index in sorted(range(len(lines)), key=lambda i: (-(exact[i] - allocated[i]), lines[i].id))[:units - sum(allocated)]:
                    allocated[index] += 1
                sign = -1 if getattr(discount, subtotal) < 0 else 1
                for line, amount in zip(lines, allocated):
                    line[field] = self.currency_id.round(getattr(line, field) + sign * amount * self.currency_id.rounding)

    def _baseer_validate_native_refund_discount(self, order):
        if order.baseer_global_discount_locked or order.lines.filtered('baseer_global_discount_line'):
            return
        sources = order.lines.filtered('refunded_orderline_id')
        originals = sources.refunded_orderline_id
        if not originals or any(line.order_id.baseer_global_discount_locked or line.baseer_global_discount_line for line in originals):
            return
        if not any(originals.mapped('baseer_discount_share_incl')) and not any(originals.mapped('baseer_discount_share_excl')):
            return
        expected = defaultdict(lambda: [0.0, 0.0])
        currency = order.currency_id
        for line in sources.sorted('id'):
            original = line.refunded_orderline_id
            if (original.product_id == original.order_id.config_id.discount_product_id
                    or set(line.tax_ids.ids) != set(original.tax_ids.ids) or line.qty >= 0):
                raise UserError(_('The discount lines do not match the approved discount.'))
            previous = original.refund_orderline_ids.filtered(lambda item: item.id != line.id and item.order_id.state != 'cancel' and (item.order_id != order or item.id < line.id))
            qty = sum(abs(item.qty) for item in previous) + abs(line.qty)
            if not original.qty or qty > abs(original.qty) + 1e-8:
                raise UserError(_('The discount lines do not match the approved discount.'))
            values = {}
            for field in ('baseer_discount_share_excl', 'baseer_discount_share_incl'):
                share = getattr(original, field)
                amount = currency.round(-share - sum(previous.mapped(field))) if qty >= abs(original.qty) - 1e-8 else currency.round(-share * abs(line.qty / original.qty))
                values[field] = amount
            line.write(values)
            key = tuple(sorted(line.tax_ids_after_fiscal_position.ids))
            expected[key][0] += values['baseer_discount_share_excl']
            expected[key][1] += values['baseer_discount_share_incl']
        discounts = order.lines.filtered(lambda line: line.product_id == order.config_id.discount_product_id and not line.refunded_orderline_id)
        actual = defaultdict(lambda: [0.0, 0.0])
        bases = order._gd_tax_base_lines(discounts)
        for line, base in zip(discounts, bases):
            details = base['tax_details']
            calculated_excl = details['total_excluded_currency'] + details.get('delta_total_excluded_currency', 0)
            calculated_incl = calculated_excl + sum(item['tax_amount_currency'] for item in details['taxes_data'])
            if (not currency.is_zero(abs(calculated_excl) - abs(line.price_subtotal))
                    or not currency.is_zero(abs(calculated_incl) - abs(line.price_subtotal_incl))):
                raise UserError(_('The discount lines do not match the approved discount.'))
            key = tuple(sorted(line.tax_ids.ids))
            # Native refund lines have negative quantity and negative unit price.
            actual[key][0] += abs(line.price_subtotal) if line.qty * line.price_unit > 0 else -abs(line.price_subtotal)
            actual[key][1] += abs(line.price_subtotal_incl) if line.qty * line.price_unit > 0 else -abs(line.price_subtotal_incl)
        keys = set(expected) | set(actual)
        if any(not currency.is_zero(expected[key][i] - actual[key][i]) for key in keys for i in (0, 1)):
            raise UserError(_('The discount lines do not match the approved discount.'))

    def _baseer_validate_native_discount(self):
        for order in self:
            if order.is_refund or order.lines.refunded_orderline_id:
                order._baseer_validate_native_refund_discount(order)
                continue
            if order.baseer_global_discount_locked or order.lines.filtered('baseer_global_discount_line'):
                continue
            config = order.config_id
            discounts = order.lines.filtered(lambda line: line.product_id == config.discount_product_id)
            if not discounts or not config.discount_product_id:
                order.lines.write({'baseer_discount_share_incl': 0, 'baseer_discount_share_excl': 0})
                continue
            fail = _('The discount lines do not match the approved discount.')
            kinds = {line.baseer_discount_kind or 'percent' for line in discounts}
            if len(kinds) != 1:
                raise UserError(fail)
            kind = kinds.pop()
            allowed_users = config.employee_ids.user_id if 'employee_ids' in config._fields else self.env['res.users']
            if allowed_users and self.env.user not in allowed_users and not self.env.user.has_group('point_of_sale.group_pos_manager') and order.user_id != self.env.user:
                raise UserError(_('You are not a cashier for this point of sale.'))
            if kind == 'percent':
                values = [line.baseer_discount_input if line.baseer_discount_kind else (line.extra_tax_data or {}).get('discount_percentage') for line in discounts]
                if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or v > 100 for v in values) or len(set(values)) != 1:
                    raise UserError(fail)
                if values[0] > config.baseer_global_discount_max_percent:
                    raise UserError(_('The discount exceeds the permitted percentage or invoice total.'))
                value = values[0]
                approver = self.env.user
                order._baseer_check_native_tax_groups(discounts, 'percent', value, fail)
            elif kind == 'fixed':
                if not config.baseer_fixed_discount_enabled:
                    raise UserError(_('Fixed invoice discount is not enabled for this POS.'))
                identities = {(line.baseer_discount_approved_by_user_id.id, line.baseer_discount_approved_by_employee) for line in discounts}
                values = {line.baseer_discount_input for line in discounts}
                if len(identities) != 1 or len(values) != 1:
                    raise UserError(fail)
                user_id, employee_id = identities.pop()
                value = values.pop()
                if not math.isfinite(value) or value <= 0:
                    raise UserError(fail)
                employee = self.env['hr.employee'].browse(employee_id).exists() if employee_id and 'hr.employee' in self.env else False
                if employee_id:
                    if not employee or 'advanced_employee_ids' not in config._fields:
                        raise UserError(_('You are not allowed to approve a fixed invoice discount.'))
                    allowed = config.basic_employee_ids | config.advanced_employee_ids | config.minimal_employee_ids
                    if allowed and employee not in allowed:
                        raise UserError(_('You are not allowed to approve a fixed invoice discount.'))
                    manager = employee in config.advanced_employee_ids or bool(employee.user_id and employee.user_id.has_group('point_of_sale.group_pos_manager'))
                    approver = employee
                else:
                    if user_id != self.env.user.id:
                        raise UserError(_('You are not allowed to approve a fixed invoice discount.'))
                    manager = self.env.user.has_group('point_of_sale.group_pos_manager')
                    approver = self.env.user
                if config.baseer_fixed_discount_allowed == 'managers' and not manager:
                    raise UserError(_('You are not allowed to approve a fixed invoice discount.'))
                sources = order.lines - discounts
                sources = sources.filtered(lambda line: not (config.tip_product_id and line.product_id == config.tip_product_id))
                tax = self.env['account.tax']
                bases = order._gd_tax_base_lines(sources)
                eligible = tax._prepare_discountable_base_lines(bases, order.company_id)
                total = sum(base['tax_details']['total_included_currency'] for base in eligible)
                actual = -sum(discounts.mapped('price_subtotal_incl'))
                rounding = order.currency_id.rounding
                if config.baseer_fixed_discount_max_amount > 0 and actual > config.baseer_fixed_discount_max_amount + 1e-8:
                    raise UserError(_('The fixed discount exceeds the allowed maximum.'))
                if actual > total + 1e-8:
                    raise UserError(_('The fixed discount exceeds the order total.'))
                expected_amount = min(value, total, config.baseer_fixed_discount_max_amount or value)
                if abs(actual - order.currency_id.round(expected_amount)) > rounding + 1e-8:
                    raise UserError(fail)
                order._baseer_check_native_tax_groups(discounts, 'fixed', expected_amount, fail, bases)
            else:
                raise UserError(fail)
            order._baseer_allocate_native_shares(discounts)
            signature = hashlib.sha256(json.dumps([kind, value, approver._name, approver.id]).encode()).hexdigest()
            if order.baseer_discount_logged_signature != signature:
                timestamp = fields.Datetime.now().replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('Asia/Riyadh')).strftime('%Y-%m-%d %H:%M:%S')
                label = 'ثابت' if kind == 'fixed' else 'نسبة'
                order.message_post(body=f'خصم فاتورة {label} {value:.2f} — اعتمده {approver.name} — {timestamp} Asia/Riyadh')
                order.baseer_discount_logged_signature = signature

    def _baseer_check_native_tax_groups(self, discounts, kind, value, fail, bases=None):
        self.ensure_one()
        tax = self.env['account.tax']
        if bases is None:
            sources = (self.lines - discounts).filtered(
                lambda line: not (self.config_id.tip_product_id and line.product_id == self.config_id.tip_product_id))
            bases = self._gd_tax_base_lines(sources)
        expected = tax._prepare_global_discount_lines(bases, self.company_id, kind, value)
        actual = self._gd_tax_base_lines(discounts)
        def groups(lines):
            result = defaultdict(lambda: [0.0, 0.0])
            for base in lines:
                key = tuple(sorted(base['tax_ids'].ids))
                details = base['tax_details']
                result[key][0] += details['total_excluded_currency'] + details.get('delta_total_excluded_currency', 0)
                result[key][1] += details['total_included_currency']
            return result
        wanted, got = groups(expected), groups(actual)
        tolerance = self.currency_id.rounding + 1e-8
        if set(wanted) != set(got) or any(abs(wanted[k][i] - got[k][i]) > tolerance for k in wanted for i in (0, 1)):
            raise UserError(fail)
        if any(abs(line.price_subtotal_incl - base['tax_details']['total_included_currency']) > tolerance for line, base in zip(discounts, actual)):
            raise UserError(fail)
