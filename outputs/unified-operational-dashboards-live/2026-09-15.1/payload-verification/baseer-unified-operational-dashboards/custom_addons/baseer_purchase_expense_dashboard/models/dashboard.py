"""Read-only accounting dashboard over Odoo's native supplier bills."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


ZERO = Decimal('0')
HUNDRED = Decimal('100')
MAX_PERIOD_DAYS = 366


def _amount(value, currency):
    """Apply the company currency precision once, in the source authority."""
    rounding = Decimal(str(currency.rounding or 0.01))
    return Decimal(str(value or 0)).quantize(rounding, rounding=ROUND_HALF_UP)


def _card(value):
    return {
        'value': str(value),
        'display': f'{value:,.2f}',
    }


def _month_start(value, offset=0):
    index = value.year * 12 + value.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


class PurchaseExpenseDashboard(models.Model):
    _inherit = 'spreadsheet.dashboard'

    baseer_dashboard_kind = fields.Selection(
        selection_add=[('supplier_bills', 'Supplier bills and expenses')],
        ondelete={'supplier_bills': 'cascade'},
    )

    def _baseer_purchase_period(self, raw):
        """Accept only bounded native date-filter values; default to 90 days."""
        today = fields.Date.context_today(self.with_context(tz='Asia/Riyadh'))
        if raw in (None, False):
            return today - timedelta(days=89), today
        if not isinstance(raw, dict):
            raise ValidationError(self.env._('Choose a valid dashboard date filter.'))
        kind = raw.get('type')
        try:
            if kind == 'range' and set(raw) == {'type', 'from', 'to'}:
                first, last = fields.Date.to_date(raw['from']), fields.Date.to_date(raw['to'])
            elif kind == 'relative' and set(raw) == {'type', 'period'}:
                period = raw['period']
                lengths = {
                    'today': 1, 'yesterday': 1, 'last_7_days': 7,
                    'last_30_days': 30, 'last_90_days': 90,
                }
                if period in lengths:
                    last = today - timedelta(days=1) if period == 'yesterday' else today
                    first = last - timedelta(days=lengths[period] - 1)
                elif period == 'month_to_date':
                    first, last = today.replace(day=1), today
                elif period == 'last_month':
                    first, last = _month_start(today, -1), today.replace(day=1) - timedelta(days=1)
                elif period == 'year_to_date':
                    first, last = today.replace(month=1, day=1), today
                else:
                    raise ValueError
            elif kind == 'month' and set(raw) == {'type', 'month', 'year'}:
                first = date(int(raw['year']), int(raw['month']), 1)
                last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
            elif kind == 'quarter' and set(raw) == {'type', 'quarter', 'year'}:
                first = date(int(raw['year']), (int(raw['quarter']) - 1) * 3 + 1, 1)
                last = _month_start(first, 3) - timedelta(days=1)
            elif kind == 'year' and set(raw) == {'type', 'year'}:
                first, last = date(int(raw['year']), 1, 1), date(int(raw['year']), 12, 31)
            else:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValidationError(self.env._('Choose a valid dashboard date filter.')) from None
        if not first or not last or first > last or (last - first).days + 1 > MAX_PERIOD_DAYS:
            raise ValidationError(self.env._('Choose a date range of at most 366 days.'))
        return first, last

    def _baseer_purchase_domain(self, company, first, last, *, same_currency=True):
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('invoice_date', '>=', first),
            ('invoice_date', '<=', last),
        ]
        if same_currency:
            domain.append(('currency_id', '=', company.currency_id.id))
        return domain

    def _baseer_purchase_assert_access(self):
        self.ensure_one()
        self.check_access('read')
        self.check_access_rule('read')
        if self.baseer_dashboard_kind != 'supplier_bills' or not self.is_published:
            raise AccessError(self.env._('This supplier-bills dashboard is not available.'))
        if self.company_ids and self.env.company not in self.company_ids:
            raise AccessError(self.env._('This dashboard is not available for the active company.'))
        user = self.env.user
        allowed = user.has_group('account.group_account_invoice') or user.has_group('baseer_access_roles.group_owner')
        if not allowed or (self.group_ids and not (self.group_ids & user.all_group_ids)):
            raise AccessError(self.env._('Accounting access is required to view supplier bills and expenses.'))
        self.env['account.move'].check_access('read')

    def _baseer_purchase_totals(self, domain, currency):
        values = self.env['account.move'].formatted_read_group(
            domain, [], ['amount_total_signed:sum', 'amount_residual_signed:sum'],
        )
        values = values[0] if values else {}
        total = -_amount(values.get('amount_total_signed:sum', ZERO), currency)
        residual = -_amount(values.get('amount_residual_signed:sum', ZERO), currency)
        return total, residual, _amount(total - residual, currency)

    @api.readonly
    def get_baseer_supplier_bill_metrics(self, filters=None):
        """Return company-safe, currency-safe aggregates; never source documents."""
        self._baseer_purchase_assert_access()
        if filters is not None and (not isinstance(filters, dict) or set(filters) != {'native'}):
            raise ValidationError(self.env._('Choose valid dashboard filters.'))
        first, last = self._baseer_purchase_period((filters or {}).get('native'))
        company, currency = self.env.company, self.env.company.currency_id
        domain = self._baseer_purchase_domain(company, first, last)
        Move = self.env['account.move']
        total, residual, paid = self._baseer_purchase_totals(domain, currency)
        count = Move.search_count(domain)
        foreign_count = Move.search_count(self._baseer_purchase_domain(company, first, last, same_currency=False) + [
            ('currency_id', '!=', currency.id),
        ])

        timeline = []
        cursor = first.replace(day=1)
        while cursor <= last:
            end = min(last, _month_start(cursor, 1) - timedelta(days=1))
            month_total, _month_residual, _month_paid = self._baseer_purchase_totals(
                domain + [('invoice_date', '>=', cursor), ('invoice_date', '<=', end)], currency,
            )
            timeline.append({
                'key': cursor.strftime('%Y-%m'),
                'label': cursor.strftime('%m/%Y'),
                'total': _card(month_total),
                'paid': _card(_month_paid),
                '_amount': month_total,
            })
            cursor = _month_start(cursor, 1)
        maximum = max((row['_amount'] for row in timeline), default=ZERO)
        for row in timeline:
            amount = row.pop('_amount')
            percent = (amount * HUNDRED / maximum).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if maximum > ZERO else ZERO
            row['height_percent'] = str(percent)

        grouped = Move.formatted_read_group(
            domain, ['commercial_partner_id'], ['amount_total_signed:sum'],
            order='amount_total_signed:sum ASC', limit=10,
        )
        vendors = []
        for row in grouped:
            partner = row.get('commercial_partner_id')
            if not partner:
                continue
            vendors.append({
                'id': partner[0],
                'name': partner[1],
                'total': _card(-_amount(row.get('amount_total_signed:sum', ZERO), currency)),
            })

        action = {
            'type': 'ir.actions.act_window',
            'name': self.env._('Supplier bills and expenses'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': domain,
            'context': {'create': False, 'allowed_company_ids': [company.id]},
        }
        return {
            'company': {'id': company.id, 'name': company.name, 'currency': currency.name},
            'filters': {'date_from': first.isoformat(), 'date_to': last.isoformat()},
            'cards': {
                'count': {'value': count, 'display': f'{count:,}'},
                'total': _card(total), 'residual': _card(residual), 'paid': _card(paid),
            },
            'timeline': timeline,
            'vendors': vendors,
            'foreign_currency_count': foreign_count,
            'source_action': action,
        }
