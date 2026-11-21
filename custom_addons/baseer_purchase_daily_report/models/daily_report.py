"""Read-only, narrowly scoped supplier bill projections for Baseer roles."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


PAGE_SIZE = 50
MAX_DAYS = 366
PAYMENT_STATES = frozenset(('all', 'not_paid', 'partial', 'in_payment', 'paid', 'reversed', 'blocked'))
ALLOWED_ROLES = (
    'baseer_access_roles.group_owner',
    'baseer_access_roles.group_accountant',
    'baseer_access_roles.group_cashier',  # Branch manager, not POS cashier.
)


def _decimal(value):
    return Decimal(str(value or 0))


def _money(value, currency):
    """Render using the document currency's decimal places and western digits."""
    digits = currency.decimal_places
    unit = Decimal(1).scaleb(-digits)
    value = _decimal(value).quantize(unit, rounding=ROUND_HALF_UP)
    # Avoid the confusing accounting presentation of negative zero.
    if not value:
        value = abs(value)
    return f'{value:,.{digits}f}'


def _quantity(value):
    # Preserve meaningful product precision in the read-only detail.
    value = _decimal(value).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
    return format(value, 'f').rstrip('0').rstrip('.') or '0'


class PurchaseDailyReport(models.AbstractModel):
    _name = 'baseer.purchase.daily.report'
    _description = 'Daily purchase report service'

    @api.model
    def _scope(self):
        # Authorize against the real user BEFORE any privileged data access.
        if not any(self.env.user.has_group(group) for group in ALLOWED_ROLES):
            raise AccessError(self.env._('You do not have access to the purchase report.'))
        company = self.env.company
        if company.id not in self.env.user.company_ids.ids:
            raise AccessError(self.env._('The active company is not available to you.'))
        return company

    @api.model
    def _date(self, value):
        if not isinstance(value, str):
            raise ValidationError(self.env._('Enter a valid date.'))
        try:
            result = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValidationError(self.env._('Enter a valid date.'))
        if result.isoformat() != value:
            raise ValidationError(self.env._('Enter a valid date.'))
        return result

    @api.model
    def _domain(self, company, first, last, status):
        if not isinstance(status, str) or status not in PAYMENT_STATES:
            raise ValidationError(self.env._('Choose a valid payment status.'))
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('invoice_date', '>=', first),
            ('invoice_date', '<=', last),
        ]
        if status != 'all':
            domain.append(('payment_state', '=', status))
        return domain

    @api.model
    def get_days(self, date_from, date_to, status='all'):
        company = self._scope()
        first, last = self._date(date_from), self._date(date_to)
        if first > last or (last - first).days + 1 > MAX_DAYS:
            raise ValidationError(self.env._('Choose a date range of at most 366 days.'))
        domain = self._domain(company, first, last, status)
        # The sole privileged query is bounded by the verified company/domain.
        rows = self.env['account.move'].sudo()._read_group(
            domain, ['invoice_date:day'],
            ['amount_total_signed:sum', 'amount_residual_signed:sum', '__count'],
        )
        currency = company.currency_id
        days = []
        for invoice_date, signed_total, signed_residual, count in rows:
            total, residual = -_decimal(signed_total), -_decimal(signed_residual)
            days.append({
                'date': fields.Date.to_string(invoice_date), 'count': count,
                'total': _money(total, currency), 'residual': _money(residual, currency),
                'settled': _money(total - residual, currency),
            })
        days.sort(key=lambda item: item['date'], reverse=True)
        return {'company': {'id': company.id, 'name': company.name, 'currency': currency.name}, 'days': days}

    @api.model
    def _bill_row(self, move):
        currency = move.currency_id
        company_currency = move.company_currency_id
        sign = -1 if move.move_type == 'in_refund' else 1
        return {
            'id': move.id, 'number': move.name or '',
            'vendor': move.partner_id.display_name or '', 'reference': move.ref or '',
            'date': fields.Date.to_string(move.invoice_date),
            'status': move.payment_state or 'not_paid', 'kind': move.move_type,
            'currency': currency.name,
            'total': _money(sign * _decimal(move.amount_total), currency),
            'residual': _money(sign * _decimal(move.amount_residual), currency),
            'company_total': _money(-_decimal(move.amount_total_signed), company_currency),
            'company_residual': _money(-_decimal(move.amount_residual_signed), company_currency),
        }

    @api.model
    def get_day(self, day, status='all', offset=0):
        company = self._scope()
        selected = self._date(day)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValidationError(self.env._('Choose a valid page.'))
        domain = self._domain(company, selected, selected, status)
        moves = self.env['account.move'].sudo()
        count = moves.search_count(domain)
        records = moves.search(domain, order='id desc', offset=offset, limit=PAGE_SIZE)
        return {
            'day': selected.isoformat(), 'rows': [self._bill_row(move) for move in records],
            'offset': offset, 'count': count, 'has_more': offset + len(records) < count,
        }

    @api.model
    def get_invoice(self, invoice_id):
        company = self._scope()
        if isinstance(invoice_id, bool) or not isinstance(invoice_id, int) or invoice_id <= 0:
            raise AccessError(self.env._('This purchase document is not available.'))
        # Revalidate type, state and exact company on every document request.
        move = self.env['account.move'].sudo().search([
            ('id', '=', invoice_id), ('company_id', '=', company.id),
            ('state', '=', 'posted'), ('move_type', 'in', ('in_invoice', 'in_refund')),
        ], limit=1)
        if not move:
            raise AccessError(self.env._('This purchase document is not available.'))
        result = self._bill_row(move)
        currency = move.currency_id
        sign = -1 if move.move_type == 'in_refund' else 1
        result.update({
            'due_date': fields.Date.to_string(move.invoice_date_due) if move.invoice_date_due else '',
            'untaxed': _money(sign * _decimal(move.amount_untaxed), currency),
            'tax': _money(sign * _decimal(move.amount_tax), currency),
            'settled': _money(sign * (_decimal(move.amount_total) - _decimal(move.amount_residual)), currency),
            'lines': [{
                'description': line.name or '',
                'kind': line.display_type,
                'quantity': _quantity(line.quantity),
                'discount': _quantity(line.discount),
                # Unit prices may have more precision than a currency amount.
                'unit_price': _quantity(line.price_unit),
                'subtotal': _money(sign * _decimal(line.price_subtotal), currency),
                'total': _money(sign * _decimal(line.price_total), currency),
            } for line in move.invoice_line_ids],
            # These native accounting adjustment lines are not included in
            # invoice_line_ids; present them independently rather than folding
            # them into the product subtotal or omitting their effect.
            'adjustments': [{
                'description': line.name or '', 'kind': line.display_type,
                'amount': _money(line.balance, move.company_currency_id),
            } for line in move.line_ids if line.display_type in (
                'discount', 'rounding', 'epd', 'non_deductible_product',
                'non_deductible_product_total', 'non_deductible_tax',
            )],
        })
        return result
