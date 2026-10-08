"""Read-only, posted P&L in the company's currency."""

from collections import Counter
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain


SECTION_KEYS = (
    'income', 'income_other', 'expense_direct_cost',
    'expense', 'expense_other', 'expense_depreciation',
)
EXPENSE_KEYS = frozenset((
    'expense_direct_cost', 'expense', 'expense_other', 'expense_depreciation',
))
PERIOD_KINDS = frozenset(('month', 'quarter', 'fiscal_year', 'custom'))
COMPARISON_KINDS = frozenset((
    'none', 'previous_period', 'previous_periods', 'same_period_last_year', 'custom',
))
SECTION_GROUPS = {
    # Odoo presents depreciation together with operating expenses.  The
    # individual account type remains addressable for the legacy detail API.
    'expense': ('expense', 'expense_depreciation'),
}


class BaseerProfitLossReport(models.AbstractModel):
    _name = 'baseer.profit.loss.report'
    _description = 'Baseer Posted Profit and Loss'

    PAGE_SIZE = 100
    SECURITY_BATCH = 1000

    @staticmethod
    def _decimal(value):
        return Decimal(str(value or 0))

    @classmethod
    def _format_money(cls, value, currency):
        increment = cls._decimal(currency.rounding)
        if increment <= 0:
            raise ValidationError(_('The company currency has an invalid rounding increment.'))
        with localcontext() as context:
            context.prec = max(28, len(value.as_tuple().digits)
                               + len(increment.as_tuple().digits) + 4)
            rounded = ((value / increment).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                       * increment)
        if not rounded:
            rounded = abs(rounded)
        return f'{rounded:,.{int(currency.decimal_places)}f}'

    @api.model
    def _check_accounting_access(self):
        if not any(self.env.user.has_group(group) for group in (
            'account.group_account_readonly',
            'account.group_account_user',
            'account.group_account_manager',
        )):
            raise AccessError(_('Accounting access is required.'))
        for name in ('res.company', 'account.journal', 'account.account',
                     'account.move', 'account.move.line'):
            self.env[name].browse().check_access('read')

    @api.model
    def _company(self, company_id):
        if type(company_id) is not int or company_id not in self.env.companies.ids:
            raise AccessError(_('The selected company is not allowed.'))
        company = self.env['res.company'].browse(company_id).exists()
        if not company:
            raise AccessError(_('The selected company is not allowed.'))
        company.check_access('read')
        return company

    @api.model
    def get_context(self, company_id=None):
        self._check_accounting_access()
        company = self._company(company_id if company_id is not None else self.env.company.id)
        companies = self.env['res.company'].search([
            ('id', 'in', self.env.companies.ids),
        ], order='name, id')
        companies.check_access('read')
        journals = self.env['account.journal'].with_context(active_test=False).search([
            ('company_id', '=', company.id),
        ], order='code, id')
        journals.check_access('read')
        today = fields.Date.context_today(self)
        first = date(today.year, today.month, 1)
        last = date(today.year, today.month, monthrange(today.year, today.month)[1])
        currency = company.currency_id
        return {
            'companies': [{'id': item.id, 'name': item.display_name} for item in companies],
            'default_company_id': company.id,
            'default_date_from': fields.Date.to_string(first),
            'default_date_to': fields.Date.to_string(last),
            'default_filters': {
                'company_id': company.id,
                'period': {
                    'kind': 'month',
                    'anchor_date': fields.Date.to_string(today),
                    'direction': 0,
                },
                'comparison': {'kind': 'none', 'order': 'descending'},
                'journal_ids': [],
            },
            'journals': [{'id': item.id, 'code': item.code, 'name': item.name}
                         for item in journals],
            'currency_code': currency.name,
            'currency_symbol': currency.symbol or currency.name,
            'currency_digits': int(currency.decimal_places),
        }

    @api.model
    def _base_filters(self, filters):
        self._check_accounting_access()
        if not isinstance(filters, dict):
            raise ValidationError(_('Select a company and a period.'))
        company = self._company(filters.get('company_id'))
        journal_ids = filters.get('journal_ids', [])
        if (not isinstance(journal_ids, list)
                or any(type(item) is not int or item <= 0 for item in journal_ids)
                or len(journal_ids) != len(set(journal_ids))):
            raise ValidationError(_('Select valid journals.'))
        journals = self.env['account.journal'].with_context(active_test=False).browse(journal_ids)
        if len(journals.exists()) != len(journal_ids):
            raise AccessError(_('The selected journals are not available.'))
        journals.check_access('read')
        if any(journal.company_id != company for journal in journals):
            raise AccessError(_('The selected journals must belong to the report company.'))
        return company, journal_ids

    @api.model
    def _period_input(self, filters):
        """Accept the new nested contract and the prior flat date contract.

        Date arithmetic is deliberately kept here, on the server.  The web
        client only sends an anchor and a navigation direction.
        """
        period = filters.get('period')
        if period is not None and not isinstance(period, dict):
            raise ValidationError(_('Select a valid report period.'))
        period = period or {}
        kind = period.get('kind', filters.get('period_mode'))
        if kind is None:
            # Existing integrations only supplied two dates; preserve them as a
            # custom period instead of silently changing their meaning.
            kind = 'custom'
        if kind not in PERIOD_KINDS:
            raise ValidationError(_('Select a valid report period.'))
        anchor = period.get('anchor_date', filters.get('anchor_date'))
        direction = period.get('direction', filters.get('period_direction', 0))
        if type(direction) is not int or direction not in (-1, 0, 1):
            raise ValidationError(_('Select a valid period direction.'))
        date_from = period.get('date_from', filters.get('date_from'))
        date_to = period.get('date_to', filters.get('date_to'))
        return kind, anchor, direction, date_from, date_to

    @api.model
    def _as_date(self, value, message):
        try:
            result = fields.Date.to_date(value)
        except (TypeError, ValueError):
            result = None
        if not result:
            raise ValidationError(message)
        return result

    @api.model
    def _month_bounds(self, anchor):
        return date(anchor.year, anchor.month, 1), date(
            anchor.year, anchor.month, monthrange(anchor.year, anchor.month)[1],
        )

    @api.model
    def _quarter_bounds(self, anchor):
        first_month = ((anchor.month - 1) // 3) * 3 + 1
        start = date(anchor.year, first_month, 1)
        last_month = first_month + 2
        return start, date(anchor.year, last_month, monthrange(anchor.year, last_month)[1])

    @api.model
    def _shift_month(self, anchor, months):
        ordinal = anchor.year * 12 + anchor.month - 1 + months
        year, month0 = divmod(ordinal, 12)
        month = month0 + 1
        return date(year, month, min(anchor.day, monthrange(year, month)[1]))

    @api.model
    def _shift_year(self, value, years):
        year = value.year + years
        return date(year, value.month, min(value.day, monthrange(year, value.month)[1]))

    @api.model
    def _shift_anchor(self, company, kind, anchor, direction):
        if not direction:
            return anchor
        if kind == 'month':
            return self._shift_month(anchor, direction)
        if kind == 'quarter':
            return self._shift_month(anchor, direction * 3)
        if kind == 'fiscal_year':
            fiscal = company.compute_fiscalyear_dates(anchor)
            boundary = fiscal['date_to'] + timedelta(days=1) if direction > 0 else fiscal['date_from'] - timedelta(days=1)
            return boundary
        raise ValidationError(_('Custom dates cannot be navigated.'))

    @api.model
    def _current_period(self, company, filters):
        kind, anchor_value, direction, date_from, date_to = self._period_input(filters)
        if kind == 'custom':
            if direction:
                raise ValidationError(_('Custom dates cannot be navigated.'))
            start = self._as_date(date_from, _('Select valid start and end dates.'))
            end = self._as_date(date_to, _('Select valid start and end dates.'))
            if start > end or (end - start).days >= 366:
                raise ValidationError(_('Select a period of no more than 366 days.'))
            return kind, start, end, start
        anchor = self._as_date(anchor_value or date_from or fields.Date.context_today(self),
                               _('Select a valid report period.'))
        anchor = self._shift_anchor(company, kind, anchor, direction)
        if kind == 'month':
            start, end = self._month_bounds(anchor)
        elif kind == 'quarter':
            start, end = self._quarter_bounds(anchor)
        else:
            fiscal = company.compute_fiscalyear_dates(anchor)
            start, end = fiscal['date_from'], fiscal['date_to']
        return kind, start, end, anchor

    @api.model
    def _comparison_input(self, filters):
        comparison = filters.get('comparison')
        if comparison is not None and not isinstance(comparison, dict):
            raise ValidationError(_('Select a valid comparison.'))
        comparison = comparison or {}
        kind = comparison.get('kind', filters.get('comparison_mode', 'none'))
        if kind not in COMPARISON_KINDS:
            raise ValidationError(_('Select a valid comparison.'))
        count = comparison.get('count', filters.get('comparison_count', 1))
        order = comparison.get('order', filters.get('comparison_order', 'descending'))
        if order not in ('ascending', 'descending'):
            raise ValidationError(_('Select a valid comparison order.'))
        if kind == 'previous_period':
            # The client contract uses the plural name; accept the first draft
            # singular name as a compatibility alias at this boundary only.
            kind = 'previous_periods'
        if kind == 'previous_periods':
            if type(count) is not int or count not in (1, 2, 3):
                raise ValidationError(_('Select one to three previous periods.'))
        elif count != 1:
            raise ValidationError(_('Select a valid comparison count.'))
        return kind, count, order, comparison

    @api.model
    def _previous_period(self, company, kind, start, end, ordinal):
        if kind == 'month':
            anchor = self._shift_month(start, -ordinal)
            return self._month_bounds(anchor)
        if kind == 'quarter':
            anchor = self._shift_month(start, -3 * ordinal)
            return self._quarter_bounds(anchor)
        if kind == 'fiscal_year':
            anchor = start - timedelta(days=1)
            for _unused in range(ordinal - 1):
                anchor = company.compute_fiscalyear_dates(anchor)['date_from'] - timedelta(days=1)
            fiscal = company.compute_fiscalyear_dates(anchor)
            return fiscal['date_from'], fiscal['date_to']
        # Both boundaries are inclusive.  Use the number of calendar days,
        # rather than the date delta, so a one-day period still advances for
        # every comparison and adjacent periods never share a date.
        span = (end - start).days + 1
        previous_end = start - timedelta(days=1 + span * (ordinal - 1))
        return previous_end - timedelta(days=span - 1), previous_end

    @api.model
    def _period_label(self, start, end):
        # A locale-neutral fallback.  The OWL view may render a richer localized
        # label, but it never has to infer accounting dates itself.
        return fields.Date.to_string(start) if start == end else '%s — %s' % (
            fields.Date.to_string(start), fields.Date.to_string(end),
        )

    @api.model
    def _period_display_label(self, kind, start, end):
        """Return a compact, server-derived caption for an already resolved period."""
        if kind == 'month':
            month_names = (
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December',
            )
            arabic_month_names = (
                'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
                'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر',
            )
            names = arabic_month_names if (self.env.lang or '').startswith('ar') else month_names
            return '%s %s' % (names[start.month - 1], start.year)
        if kind == 'quarter':
            quarter = ((start.month - 1) // 3) + 1
            return (_('ربع %s %s') % (quarter, start.year)
                    if (self.env.lang or '').startswith('ar')
                    else 'Q%s %s' % (quarter, start.year))
        if kind == 'fiscal_year':
            return str(end.year)
        return self._period_label(start, end)

    @api.model
    def _period_payload(self, key, role, kind, start, end):
        return {
            'key': key, 'role': role,
            'label': self._period_label(start, end),
            'display_label': self._period_display_label(kind, start, end),
            'date_from': fields.Date.to_string(start),
            'date_to': fields.Date.to_string(end),
        }

    @api.model
    def _period_options(self, company, anchor):
        """Expose only pre-resolved labels; the browser never derives report dates."""
        month_start, month_end = self._month_bounds(anchor)
        quarter_start, quarter_end = self._quarter_bounds(anchor)
        fiscal = company.compute_fiscalyear_dates(anchor)
        return [
            {'kind': 'month', 'display_label': self._period_display_label('month', month_start, month_end)},
            {'kind': 'quarter', 'display_label': self._period_display_label('quarter', quarter_start, quarter_end)},
            {'kind': 'fiscal_year', 'display_label': self._period_display_label('fiscal_year', fiscal['date_from'], fiscal['date_to'])},
            {'kind': 'custom', 'display_label': _('Custom Dates')},
        ]

    @api.model
    def _resolve_periods(self, company, filters):
        kind, start, end, anchor = self._current_period(company, filters)
        comparison_kind, count, order, comparison = self._comparison_input(filters)
        periods = [self._period_payload('current', 'primary', kind, start, end)]
        comparisons = []
        if comparison_kind == 'previous_periods':
            for ordinal in range(1, count + 1):
                previous_start, previous_end = self._previous_period(
                    company, kind, start, end, ordinal,
                )
                comparisons.append(self._period_payload(
                    f'previous_{ordinal}', 'comparison', kind, previous_start, previous_end,
                ))
        elif comparison_kind == 'same_period_last_year':
            previous_start, previous_end = self._shift_year(start, -1), self._shift_year(end, -1)
            comparisons.append(self._period_payload(
                'last_year', 'comparison', kind, previous_start, previous_end,
            ))
        elif comparison_kind == 'custom':
            previous_start = self._as_date(
                comparison.get('date_from', filters.get('comparison_date_from')),
                _('Select valid comparison dates.'),
            )
            previous_end = self._as_date(
                comparison.get('date_to', filters.get('comparison_date_to')),
                _('Select valid comparison dates.'),
            )
            if previous_start > previous_end or (previous_end - previous_start).days >= 366:
                raise ValidationError(_('Select comparison dates of no more than 366 days.'))
            comparisons.append(self._period_payload(
                'custom', 'comparison', 'custom', previous_start, previous_end,
            ))
        if order == 'ascending':
            comparisons.reverse()
        periods.extend(comparisons)
        return periods, {
            'kind': kind, 'anchor_date': fields.Date.to_string(anchor), 'direction': 0,
            'options': self._period_options(company, anchor),
        }, {
            'kind': comparison_kind, 'count': count, 'order': order,
        }

    @api.model
    def _domain(self, company, start, end, journal_ids):
        domain = (Domain('company_id', '=', company.id)
                  & Domain('parent_state', '=', 'posted')
                  & Domain('date', '>=', start)
                  & Domain('date', '<=', end)
                  & Domain('account_id.account_type', 'in', list(SECTION_KEYS)))
        if journal_ids:
            domain &= Domain('journal_id', 'in', journal_ids)
        return domain

    @api.model
    def _scope(self, filters):
        company, journal_ids = self._base_filters(filters)
        periods, period_control, comparison_control = self._resolve_periods(company, filters)
        for period in periods:
            period['domain'] = self._domain(
                company, fields.Date.to_date(period['date_from']),
                fields.Date.to_date(period['date_to']), journal_ids,
            )
        return company, journal_ids, periods, period_control, comparison_control

    @api.model
    def _filters(self, filters, period_key='current'):
        """Backward compatible one-period scope for lazy detail methods."""
        company, journal_ids, periods, _period_control, _comparison_control = self._scope(filters)
        if not isinstance(period_key, str):
            raise ValidationError(_('Select a valid report period.'))
        selected = next((period for period in periods if period['key'] == period_key), None)
        if not selected:
            raise AccessError(_('The selected report period is not available.'))
        return (company, fields.Date.to_date(selected['date_from']),
                fields.Date.to_date(selected['date_to']), journal_ids, selected['domain'])

    @api.model
    def _verified_groups(self, domain):
        """Aggregate only AML IDs whose linked records have all passed read rules.

        AML record rules are applied by search. A linked move, account or journal
        can have an independent rule; checking each batch before aggregation avoids
        publishing a total whose source the caller cannot read. No sudo or cap.
        """
        AML = self.env['account.move.line'].with_context(active_test=False)
        totals = {}
        cursor = 0
        while True:
            lines = AML.search(domain & Domain('id', '>', cursor),
                               order='id', limit=self.SECURITY_BATCH)
            if not lines:
                break
            self._verify_links(lines)
            # Group the verified set, not the broader domain: concurrent additions
            # cannot enter the result after the linked-record checks.
            grouped = AML._read_group(
                domain & Domain('id', 'in', lines.ids), ['account_id'],
                ['debit:sum', 'credit:sum', '__count'],
            )
            verified_counts = Counter(line.account_id.id for line in lines)
            grouped_counts = {}
            for account, debit, credit, count in grouped:
                if account.id not in verified_counts:
                    raise AccessError(_('The report source changed while reading. Retry.'))
                current = totals.setdefault(account.id, {
                    'account': account, 'debit': Decimal('0'),
                    'credit': Decimal('0'), 'count': 0,
                })
                # ORM sums are converted once at the trusted batch boundary;
                # all section and profit arithmetic stays Decimal thereafter.
                current['debit'] += self._decimal(debit)
                current['credit'] += self._decimal(credit)
                current['count'] += count
                grouped_counts[account.id] = count
            if grouped_counts != verified_counts:
                raise AccessError(_('The report source changed while reading. Retry.'))
            cursor = lines[-1].id
            if len(lines) < self.SECURITY_BATCH:
                break
        return totals

    @api.model
    def _verify_links(self, lines):
        lines.check_access('read')
        lines.mapped('move_id').check_access('read')
        lines.mapped('journal_id').check_access('read')
        lines.mapped('account_id').check_access('read')

    @api.model
    def _section_rows(self, domain):
        rows = {key: [] for key in SECTION_KEYS}
        for entry in self._verified_groups(domain).values():
            account = entry['account']
            section = account.account_type
            if section not in rows:
                raise AccessError(_('The report source changed while reading. Retry.'))
            raw = (entry['debit'] - entry['credit'] if section in EXPENSE_KEYS
                   else entry['credit'] - entry['debit'])
            rows[section].append({**entry, 'raw': raw})
        return rows

    @api.model
    def _period_amount(self, value, currency):
        return {
            'amount': self._format_money(value, currency),
            'negative': value < 0,
        }

    @api.model
    def _report_rows(self, grouped_by_period, periods, currency):
        """Build Odoo-style summary rows without moving financial arithmetic to JS."""
        totals = {}
        for period in periods:
            key = period['key']
            grouped = grouped_by_period[key]
            raw = {section: sum((row['raw'] for row in grouped[section]), Decimal('0'))
                   for section in SECTION_KEYS}
            operating_expense = raw['expense'] + raw['expense_depreciation']
            gross = raw['income'] - raw['expense_direct_cost']
            operating = gross - operating_expense
            other_net = raw['income_other'] - raw['expense_other']
            totals[key] = {
                'income': raw['income'],
                'cost_of_sales': raw['expense_direct_cost'],
                'gross_profit': gross,
                'expense': operating_expense,
                'net_operating_income': operating,
                'other_income': raw['income_other'],
                'other_expense': raw['expense_other'],
                'net_other_income': other_net,
                'net_income': operating + other_net,
            }

        natural_amount_keys = frozenset((
            'cost_of_sales', 'expense', 'other_expense',
        ))

        def amounts(total_key):
            # Debit-nature sections already have their natural positive sign in
            # totals. Formula rows retain their signed financial result.
            natural = total_key in natural_amount_keys
            return {
                period['key']: self._period_amount(
                    totals[period['key']][total_key] if natural
                    else totals[period['key']][total_key],
                    currency,
                )
                for period in periods
            }

        return [
            {'key': 'income', 'kind': 'section', 'level': 0, 'label': _('Income'),
             'section': 'income', 'expandable': True, 'amounts': amounts('income')},
            {'key': 'cost_of_sales', 'kind': 'detail', 'level': 0, 'label': _('Cost of Sales'),
             'section': 'expense_direct_cost', 'expandable': True,
             'amounts': amounts('cost_of_sales')},
            {'key': 'gross_profit', 'kind': 'result', 'level': 0, 'label': _('Gross Profit'),
             'amounts': amounts('gross_profit')},
            {'key': 'expense', 'kind': 'section', 'level': 0, 'label': _('Expense'),
             'section': 'expense', 'expandable': True, 'amounts': amounts('expense')},
            {'key': 'net_operating_income', 'kind': 'result', 'level': 0,
             'label': _('Net Operating Income'), 'amounts': amounts('net_operating_income')},
            {'key': 'other_income', 'kind': 'detail', 'level': 0, 'label': _('Other Income'),
             'section': 'income_other', 'expandable': True, 'amounts': amounts('other_income')},
            {'key': 'other_expense', 'kind': 'detail', 'level': 0, 'label': _('Other Expense'),
             'section': 'expense_other', 'expandable': True,
             'amounts': amounts('other_expense')},
            {'key': 'net_other_income', 'kind': 'result', 'level': 0,
             'label': _('Net Other Income'), 'amounts': amounts('net_other_income')},
            {'key': 'net_income', 'kind': 'result', 'level': 0, 'label': _('Net Income'),
             'amounts': amounts('net_income')},
        ], totals

    @api.model
    def get_report(self, filters):
        company, journal_ids, periods, period_control, comparison_control = self._scope(filters)
        grouped_by_period = {
            period['key']: self._section_rows(period['domain']) for period in periods
        }
        currency = company.currency_id
        rows, totals = self._report_rows(grouped_by_period, periods, currency)
        # Preserve the old current-column envelope for callers that have not
        # yet moved to rows/periods.  New work must consume the keyed rows.
        grouped = grouped_by_period['current']
        current_period = next(period for period in periods if period['key'] == 'current')
        raw_totals = {key: sum((row['raw'] for row in grouped[key]), Decimal('0'))
                      for key in SECTION_KEYS}
        gross = totals['current']['gross_profit']
        net = totals['current']['net_income']
        sections = []
        for key in SECTION_KEYS:
            display = -raw_totals[key] if key in EXPENSE_KEYS else raw_totals[key]
            sections.append({
                'key': key,
                'amount': self._format_money(display, currency),
                'negative': display < 0,
                'account_count': len(grouped[key]),
            })
        return {
            'company': {
                'id': company.id, 'name': company.display_name,
                'currency_code': currency.name,
                'currency_symbol': currency.symbol or currency.name,
                'currency_digits': int(currency.decimal_places),
            },
            'period': {'date_from': current_period['date_from'],
                       'date_to': current_period['date_to']},
            'period_controls': period_control,
            'comparison_controls': comparison_control,
            'periods': [{key: value for key, value in period.items() if key != 'domain'}
                        for period in periods],
            'rows': rows,
            'is_partial_journals': bool(journal_ids),
            'sections': sections,
            'gross_profit': {'amount': self._format_money(gross, currency),
                             'negative': gross < 0},
            'net_profit': {'amount': self._format_money(net, currency),
                           'negative': net < 0},
        }

    @api.model
    def get_accounts(self, filters, section, page=1):
        if section not in SECTION_KEYS:
            raise ValidationError(_('Select a profit and loss section.'))
        if type(page) is not int or page < 1:
            raise ValidationError(_('Select a valid page.'))
        company, _journal_ids, periods, _period_control, _comparison_control = self._scope(filters)
        section_keys = SECTION_GROUPS.get(section, (section,))
        grouped_by_period = {
            period['key']: self._section_rows(period['domain']) for period in periods
        }
        by_account = {}
        for period in periods:
            for section_key in section_keys:
                for row in grouped_by_period[period['key']][section_key]:
                    current = by_account.setdefault(row['account'].id, {
                        'account': row['account'], 'rows': {},
                    })
                    current['rows'][period['key']] = row
        ordered = sorted(by_account.values(), key=lambda row: (
            row['account'].code or '', row['account'].id,
        ))
        start = (page - 1) * self.PAGE_SIZE
        selected = ordered[start:start + self.PAGE_SIZE]
        currency = company.currency_id
        accounts = []
        for row in selected:
            account = row['account']
            amounts = {}
            counts = {}
            for period in periods:
                source = row['rows'].get(period['key'])
                raw = source['raw'] if source else Decimal('0')
                amounts[period['key']] = self._period_amount(raw, currency)
                counts[period['key']] = source['count'] if source else 0
            current_raw = row['rows'].get('current', {}).get('raw', Decimal('0'))
            accounts.append({
                'id': account.id, 'code': account.code or '',
                'name': account.name or '',
                'amount': self._format_money(current_raw, currency),
                'negative': current_raw < 0,
                'move_line_count': counts['current'],
                'amounts': amounts, 'move_line_counts': counts,
            })
        total_amounts = {}
        for period in periods:
            raw = sum((row['raw'] for key in section_keys
                       for row in grouped_by_period[period['key']][key]), Decimal('0'))
            total_amounts[period['key']] = self._period_amount(raw, currency)
        return {
            'section': section, 'page': page, 'page_size': self.PAGE_SIZE,
            'total_count': len(ordered),
            'total_amount': total_amounts['current']['amount'],
            'total_amounts': total_amounts,
            'accounts': accounts,
        }

    @api.model
    def get_lines(self, filters, account_id, page=1, period_key='current'):
        """Return a guarded page of source AMLs; every linked move remains readable."""
        if type(account_id) is not int or account_id <= 0:
            raise ValidationError(_('Select a profit and loss account.'))
        if type(page) is not int or page < 1:
            raise ValidationError(_('Select a valid page.'))
        company, _start, _end, _journal_ids, domain = self._filters(filters, period_key)
        account = self.env['account.account'].with_context(active_test=False).browse(account_id)
        if not account.exists():
            raise AccessError(_('The selected account is not available.'))
        account.check_access('read')
        if company not in account.company_ids or account.account_type not in SECTION_KEYS:
            raise AccessError(_('The selected account is not available for this company.'))
        domain &= Domain('account_id', '=', account.id)
        AML = self.env['account.move.line'].with_context(active_test=False)
        grouped = self._verified_groups(domain).get(account.id)
        debit = grouped['debit'] if grouped else Decimal('0')
        credit = grouped['credit'] if grouped else Decimal('0')
        count = grouped['count'] if grouped else 0
        income = account.account_type not in EXPENSE_KEYS
        total = credit - debit if income else debit - credit
        selected = AML.search(domain, order='date asc, id asc',
                              offset=(page - 1) * self.PAGE_SIZE,
                              limit=self.PAGE_SIZE)
        self._verify_links(selected)
        currency = company.currency_id
        rows = []
        for line in selected:
            debit, credit = self._decimal(line.debit), self._decimal(line.credit)
            raw = credit - debit if income else debit - credit
            display = raw
            rows.append({
                'id': line.id,
                'date': fields.Date.to_string(line.date),
                'move_id': line.move_id.id,
                'move_name': line.move_id.name or '',
                'label': line.name or '',
                'debit': self._format_money(debit, currency),
                'credit': self._format_money(credit, currency),
                'amount': self._format_money(display, currency),
                'negative': display < 0,
            })
        display_total = total
        return {
            'account_id': account.id, 'period_key': period_key, 'page': page,
            'page_size': self.PAGE_SIZE,
            'total_count': count,
            'total_amount': self._format_money(display_total, currency),
            'lines': rows,
        }

    @api.model
    def get_account_action(self, filters, account_id, period_key='current'):
        """Return the native Journal Items action for one verified report account.

        The report stays a compact summary.  Odoo's list view owns searching,
        paging and large result sets instead of inserting them below the report.
        """
        if type(account_id) is not int or account_id <= 0:
            raise ValidationError(_('Select a profit and loss account.'))
        company, start, end, journal_ids, domain = self._filters(filters, period_key)
        account = self.env['account.account'].with_context(active_test=False).browse(account_id)
        if not account.exists():
            raise AccessError(_('The selected account is not available.'))
        account.check_access('read')
        if company not in account.company_ids or account.account_type not in SECTION_KEYS:
            raise AccessError(_('The selected account is not available for this company.'))
        if account.id not in self._verified_groups(domain & Domain('account_id', '=', account.id)):
            raise AccessError(_('The selected account is not available for this period.'))

        action_domain = [
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', fields.Date.to_string(start)),
            ('date', '<=', fields.Date.to_string(end)),
            ('account_id', '=', account.id),
        ]
        if journal_ids:
            action_domain.append(('journal_id', 'in', journal_ids))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Items'),
            'res_model': 'account.move.line',
            'views': [[False, 'list'], [False, 'form']],
            'target': 'current',
            'domain': action_domain,
        }

    @api.model
    def get_source_line(self, filters, line_id, period_key='current'):
        """Recheck one source immediately before opening its AML form."""
        if type(line_id) is not int or line_id <= 0:
            raise ValidationError(_('Select a source entry.'))
        _company, _start, _end, _journal_ids, domain = self._filters(filters, period_key)
        line = self.env['account.move.line'].with_context(active_test=False).search(
            domain & Domain('id', '=', line_id), limit=1,
        )
        if not line:
            raise AccessError(_('The source entry is not available.'))
        self._verify_links(line)
        return {'line_id': line.id, 'move_id': line.move_id.id}
