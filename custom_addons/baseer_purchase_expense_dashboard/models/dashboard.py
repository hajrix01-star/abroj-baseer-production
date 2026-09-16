"""Read-only, company-scoped supplier-bill analytics for Baseer dashboards."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


ZERO = Decimal('0')
HUNDRED = Decimal('100')
MAX_PERIOD_DAYS = 366
TOP_ROWS = 10


def _amount(value, currency):
    """Round a source aggregate once, in its company-currency authority."""
    rounding = Decimal(str(currency.rounding or 0.01))
    return Decimal(str(value or 0)).quantize(rounding, rounding=ROUND_HALF_UP)


def _card(value):
    return {'value': str(value), 'display': f'{value:,.2f}'}


def _ratio(cost, sales):
    """Return a server-owned analytical ratio; never let the browser calculate it."""
    if sales <= ZERO:
        return {'available': False, 'value': None, 'display': '—'}
    value = (cost * HUNDRED / sales).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {'available': True, 'value': str(value), 'display': f'{value:,.2f}'}


def _month_start(value, offset=0):
    index = value.year * 12 + value.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def _spend_percentages(distribution, spend_ids):
    """Project joint native dimensions onto spend; malformed lines stay unclassified."""
    if not isinstance(distribution, dict):
        return {False: HUNDRED}
    shares = {}
    try:
        for key, raw_percentage in distribution.items():
            identities = key.split(',')
            if any(not value or not value.isascii() or not value.isdecimal() for value in identities):
                return {False: HUNDRED}
            ids = {int(value) for value in identities}
            if len(ids) != len(identities):
                return {False: HUNDRED}
            percentage = Decimal(str(raw_percentage))
            if not ids or any(value <= 0 for value in ids) or not percentage.is_finite() or percentage < ZERO:
                return {False: HUNDRED}
            selected = ids & spend_ids
            if len(selected) > 1 or percentage > HUNDRED:
                return {False: HUNDRED}
            if selected:
                account_id = next(iter(selected))
                shares[account_id] = shares.get(account_id, ZERO) + percentage
    except (AttributeError, TypeError, ValueError, InvalidOperation):
        return {False: HUNDRED}
    total = sum(shares.values(), ZERO)
    if total > HUNDRED:
        return {False: HUNDRED}
    if total < HUNDRED:
        shares[False] = HUNDRED - total
    return {key: value for key, value in shares.items() if value}


def _allocate_spend(gross, shares, currency):
    """Allocate integer currency units with stable largest remainders, then restore sign."""
    quantum = Decimal(str(currency.rounding or 0.01))
    units = (abs(gross) / quantum).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    exact = {key: units * percentage / HUNDRED for key, percentage in shares.items()}
    allocated = {key: value.quantize(Decimal('1'), rounding=ROUND_DOWN) for key, value in exact.items()}
    remaining = int(units - sum(allocated.values(), ZERO))
    # Tie-break by native account identity; residual is last. Never use binary floats.
    order = sorted(exact, key=lambda key: (-(exact[key] - allocated[key]), key is False, key))
    for key in order[:remaining]:
        allocated[key] += 1
    sign = -1 if gross < ZERO else 1
    return {key: value * quantum * sign for key, value in allocated.items()}


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
            domain, [], ['amount_total_signed:sum', 'amount_residual_signed:sum', '__count'],
        )
        values = values[0] if values else {}
        total = -_amount(values.get('amount_total_signed:sum', ZERO), currency)
        residual = -_amount(values.get('amount_residual_signed:sum', ZERO), currency)
        return total, residual, _amount(total - residual, currency), values.get('__count', 0)

    def _baseer_monthly_movement(self, company, currency, first, last):
        """One grouped native query instead of one aggregate per calendar month.

        The secured ORM subquery carries the caller's read ACL and record-rule
        domain into the grouped query. It is not a company-filter substitute.
        """
        query = self.env['account.move']._search(self._baseer_purchase_domain(company, first, last))
        self.env.cr.execute(SQL("""
            SELECT date_trunc('month', invoice_date)::date,
                   COALESCE(SUM(-amount_total_signed), 0),
                   COALESCE(SUM(-amount_residual_signed), 0)
              FROM account_move
             WHERE id IN (%s)
             GROUP BY date_trunc('month', invoice_date)::date
             ORDER BY date_trunc('month', invoice_date)::date
        """, query.select()))
        grouped = {
            month: (_amount(total, currency), _amount(residual, currency))
            for month, total, residual in self.env.cr.fetchall()
        }
        rows = []
        cursor = first.replace(day=1)
        while cursor <= last:
            total, residual = grouped.get(cursor, (ZERO, ZERO))
            paid = _amount(total - residual, currency)
            rows.append({
                'key': cursor.strftime('%Y-%m'),
                'label': cursor.strftime('%m/%Y'),
                'total': _card(total),
                'paid': _card(paid),
            })
            cursor = _month_start(cursor, 1)
        return rows

    def _baseer_approved_pos_gross_sales(self, company, first, last, currency):
        """Read one approved POS gross-sales aggregate after dashboard authorisation only."""
        Summary = self.env['baseer.pos.summary'].sudo()
        values = Summary.formatted_read_group([
            ('company_id', '=', company.id),
            ('business_date', '>=', first),
            ('business_date', '<=', last),
            ('state', '=', 'approved'),
        ], [], ['amount_gross:sum'])
        value = values[0].get('amount_gross:sum', ZERO) if values else ZERO
        return _amount(value, currency)

    def _baseer_supplier_rows(self, domain, currency, gross_sales):
        grouped = self.env['account.move'].formatted_read_group(
            domain, ['commercial_partner_id'], ['amount_total_signed:sum'],
            order='amount_total_signed:sum ASC, commercial_partner_id ASC', limit=TOP_ROWS,
        )
        rows = []
        for row in grouped:
            partner = row.get('commercial_partner_id')
            if not partner:
                continue
            total = -_amount(row.get('amount_total_signed:sum', ZERO), currency)
            rows.append({
                'id': partner[0], 'name': partner[1], 'total': _card(total),
                'sales_ratio': _ratio(total, gross_sales),
            })
        return rows

    def _baseer_category_rows(self, company, currency, first, last, gross_sales):
        """Read stored native spend allocations without consulting current supplier defaults."""
        Line = self.env['account.move.line']
        line_query = Line._search([
            ('move_id.company_id', '=', company.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
            ('move_id.invoice_date', '>=', first),
            ('move_id.invoice_date', '<=', last),
            ('move_id.currency_id', '=', currency.id),
            ('display_type', '=', 'product'),
        ])
        # Move and line record rules are independent: both must authorize the
        # source, even when a user's line rules are less restrictive than bills.
        move_query = self.env['account.move']._search(
            self._baseer_purchase_domain(company, first, last),
        )
        Line.flush_model(['analytic_distribution', 'balance', 'price_subtotal', 'price_total'])
        self.env.cr.execute(SQL("""
            WITH visible_lines AS (
                SELECT id, move_id, analytic_distribution, balance, price_subtotal, price_total
                  FROM account_move_line WHERE id IN (%s) AND move_id IN (%s)
            ), visible_counts AS (
                SELECT move_id, COUNT(*) AS line_count FROM visible_lines GROUP BY move_id
            )
            SELECT line.id, line.move_id, line.analytic_distribution,
                   line.balance, line.price_subtotal, line.price_total,
                   CASE WHEN visible.line_count = (
                       SELECT COUNT(*) FROM account_move_line AS all_lines
                        WHERE all_lines.move_id = line.move_id AND all_lines.display_type = 'product'
                   ) THEN -move.amount_total_signed ELSE NULL END
              FROM visible_lines AS line
              JOIN visible_counts AS visible ON visible.move_id = line.move_id
              JOIN account_move AS move ON move.id = line.move_id
        """, line_query.select(), move_query.select()))
        source_rows = self.env.cr.fetchall()
        if not source_rows:
            return []
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        # Only dictionary names are elevated, after the caller's secured line query.
        # Ordinary bill accountants have no analytic-plan administration ACL.
        Account = self.env['account.analytic.account'].sudo().with_context(active_test=False)
        accounts = Account.search([
            ('plan_id', 'child_of', root.id),
            ('company_id', 'in', [False, company.id]),
        ]) if root else Account.browse()
        spend_ids = set(accounts.ids)
        metadata = {}
        for account in accounts:
            plan = account.plan_id
            # The existing two-level view retains deeper plan names as a path.
            path = [plan.name]
            ancestor = plan.parent_id
            while ancestor and ancestor != root:
                path.insert(0, ancestor.name)
                ancestor = ancestor.parent_id
            metadata[account.id] = (plan.id, ' / '.join(path), account.name)
        bills = {}
        quantum = Decimal(str(currency.rounding or 0.01))
        for line_id, move_id, distribution, balance, subtotal, total, bill_total in source_rows:
            balance = Decimal(str(balance or 0))
            subtotal = Decimal(str(subtotal or 0))
            gross = balance if not subtotal else balance * Decimal(str(total or 0)) / subtotal
            gross = (gross / quantum).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * quantum
            bill = bills.setdefault(move_id, {'total': bill_total, 'lines': []})
            bill['lines'].append({'id': line_id, 'gross': gross, 'distribution': distribution})
        totals = {}
        for bill in bills.values():
            if bill['total'] is not None:
                # Native global VAT rounding may leave a cent between summed line
                # gross amounts and the posted invoice. Preserve that invoice's
                # signed authority on the largest line, with stable ID tie-break.
                # The SQL intentionally withholds totals for partially visible bills.
                residual = Decimal(str(bill['total'])) - sum(line['gross'] for line in bill['lines'])
                largest = min(bill['lines'], key=lambda line: (-abs(line['gross']), line['id']))
                largest['gross'] += residual
            for line in bill['lines']:
                shares = _spend_percentages(line['distribution'], spend_ids)
                for account_id, amount in _allocate_spend(line['gross'], shares, currency).items():
                    totals[account_id] = totals.get(account_id, ZERO) + amount
        parents = {}
        for account_id, amount in totals.items():
            parent_id, parent_name, child_name = metadata.get(
                account_id, (False, self.env._('Unclassified'), None),
            )
            parent = parents.setdefault(parent_id, {
                'id': parent_id, 'name': parent_name, 'amount': ZERO, 'children': [],
            })
            parent['amount'] += amount
            if account_id:
                parent['children'].append({
                    'id': account_id, 'name': child_name, 'amount': amount,
                })
        rows = []
        for parent in sorted(parents.values(), key=lambda item: (-item['amount'], item['name'])):
            amount = _amount(parent['amount'], currency)
            children = [{
                'id': child['id'], 'name': child['name'],
                'total': _card(_amount(child['amount'], currency)),
                'sales_ratio': _ratio(_amount(child['amount'], currency), gross_sales),
            } for child in sorted(parent['children'], key=lambda item: (-item['amount'], item['name']))]
            rows.append({
                'id': parent['id'], 'name': parent['name'],
                'total': _card(amount), 'sales_ratio': _ratio(amount, gross_sales),
                'children': children,
            })
        return rows

    @api.readonly
    def get_baseer_supplier_bill_metrics(self, filters=None):
        """Return bounded aggregates; no supplier-bill or POS source records are exposed."""
        self._baseer_purchase_assert_access()
        if filters is not None and (not isinstance(filters, dict) or set(filters) != {'native'}):
            raise ValidationError(self.env._('Choose valid dashboard filters.'))
        first, last = self._baseer_purchase_period((filters or {}).get('native'))
        company, currency = self.env.company, self.env.company.currency_id
        domain = self._baseer_purchase_domain(company, first, last)
        Move = self.env['account.move']
        total, residual, paid, count = self._baseer_purchase_totals(domain, currency)
        foreign_count = Move.search_count(self._baseer_purchase_domain(company, first, last, same_currency=False) + [
            ('currency_id', '!=', currency.id),
        ])
        gross_sales = self._baseer_approved_pos_gross_sales(company, first, last, currency)

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
            'timeline': self._baseer_monthly_movement(company, currency, first, last),
            'vendors': self._baseer_supplier_rows(domain, currency, gross_sales),
            'categories': self._baseer_category_rows(company, currency, first, last, gross_sales),
            'ratios': {'available': gross_sales > ZERO},
            'foreign_currency_count': foreign_count,
            'source_action': action,
        }
