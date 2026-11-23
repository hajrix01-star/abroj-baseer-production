"""Read-only, posted P&L in the company's currency."""

from collections import Counter
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from .revenue_channels import (
    UNALLOCATED, allocate_channels, tender_matches_order, reconcile_order_amounts,
    noorix_gross_channels, estimate_noorix_net,
)


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


class NoorixSourceConflict(ValidationError):
    """Conflicting identities must never become an unallocated fallback."""


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
    def _tax_inclusive(self, filters):
        if not isinstance(filters, dict) or type(filters.get('tax_inclusive', True)) is not bool:
            raise ValidationError(_('Select a valid tax display option.'))
        return filters.get('tax_inclusive', True)

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
    def _verified_groups(self, domain, *, adjustments_out=None, tax_evidence_out=None):
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
        if self.env.context.get('_baseer_pl_inclusive'):
            if tax_evidence_out is None:
                adjustments = self._inclusive_adjustments(domain)
            else:
                adjustments = self._inclusive_adjustments(domain, evidence_out=tax_evidence_out)
            if adjustments_out is not None:
                adjustments_out.update(adjustments)
            for line, delta in adjustments.items():
                entry = totals.get(line.account_id.id)
                if entry is not None:
                    if line.account_id.account_type in EXPENSE_KEYS:
                        entry['debit'] += delta
                    else:
                        entry['credit'] += delta
        return totals

    def _inclusive_adjustments(self, domain, *, noorix_sources=None, evidence_out=None):
        """Return proved tax additions on visible P&L lines, or refuse ambiguity."""
        AML = self.env['account.move.line'].with_context(active_test=False)
        visible = AML.search(domain)
        self._verify_links(visible)
        if evidence_out is not None:
            evidence_out['line_ids'] = frozenset(visible.ids)
            evidence_out['noorix_sources'] = {}
        moves = visible.mapped('move_id')
        if not moves:
            return {}
        # Tax and other P&L lines on each entry must all be readable before
        # amounts can be attributed to a single account.
        seen = AML._search([('move_id', 'in', moves.ids)])
        hidden = Domain('id', 'in', moves.ids) & Domain('line_ids', 'any!', Domain('id', 'not in', seen))
        if self.env['account.move'].search_count(hidden, limit=1):
            raise AccessError(_('Some tax source lines are not available. Select the tax-exclusive report.'))
        all_lines = moves.mapped('line_ids')
        self._verify_links(all_lines)
        all_lines.tax_line_id.check_access('read')
        all_lines.tax_repartition_line_id.check_access('read')
        all_lines.tax_tag_ids.check_access('read')
        all_lines.tax_ids.check_access('read')
        dates = [line.date for line in visible if line.date]
        noorix = {}
        if dates:
            companies = moves.mapped('company_id')
            if len(companies) != 1:
                raise AccessError(_('Tax-inclusive entries must belong to one company.'))
            noorix, _incomplete = self._verified_noorix_gross_channels(
                companies[0], min(dates), max(dates), domain)
            if noorix_sources is not None:
                noorix_sources.update(noorix)
            if evidence_out is not None:
                evidence_out['noorix_sources'].update(noorix)
        result = {}
        visible_ids = set(visible.ids)
        for move in moves:
            entries = move.line_ids.filtered(lambda item: item.account_id.account_type in SECTION_KEYS)
            taxes = move.line_ids.filtered(lambda item: item.tax_line_id or item.tax_repartition_line_id
                                           or (item.tax_tag_ids and item.account_id.internal_group == 'liability'))
            if not taxes:
                continue
            if any(line.account_id.account_type in SECTION_KEYS for line in taxes):
                raise ValidationError(_('A tax line is already included in a profit and loss account. Select the tax-exclusive report.'))
            accounts = entries.account_id
            if not entries:
                continue
            account = accounts[0] if len(accounts) == 1 else None
            noorix_source = noorix.get((move.id, account.id)) if account else None
            if noorix_source is not None:
                noorix_channels, _funding_accounts = noorix_source
                sign = Decimal('1') if account.account_type in EXPENSE_KEYS else Decimal('-1')
                amount = sum((sign * self._decimal(line.balance) for line in taxes), Decimal('0'))
                net = -sum((self._decimal(line.balance) for line in entries), Decimal('0'))
                if sum(noorix_channels.values(), Decimal('0')) != net + amount:
                    raise ValidationError(_('The Noorix tax-inclusive amount no longer reconciles. Select the tax-exclusive report.'))
                target = next((line for line in entries if line.id in visible_ids), None)
                if target:
                    result[target] = amount
            else:
                tax_ids = set(taxes.mapped('tax_line_id').ids)
                base_ids = set(entries.mapped('tax_ids').ids)
                if not tax_ids or not tax_ids.issubset(base_ids) or any(not line.tax_line_id for line in taxes):
                    raise ValidationError(_('The tax-inclusive allocation cannot be proved for a source entry. Select the tax-exclusive report.'))
                if tax_ids != base_ids or any(len(entries.filtered(lambda line: tax in line.tax_ids).account_id) != 1
                       for tax in taxes.mapped('tax_line_id')):
                    allocated = self._native_invoice_tax_adjustments(move, entries, taxes)
                    for line, amount in allocated.items():
                        if line.id in visible_ids:
                            result[line] = result.get(line, Decimal('0')) + amount
                    continue
                for tax_line in taxes:
                    owners = entries.filtered(lambda line: tax_line.tax_line_id in line.tax_ids).account_id
                    if len(owners) != 1:
                        raise ValidationError(_('The posted tax cannot be assigned to one profit and loss account. Select the tax-exclusive report.'))
                    owner = owners[0]
                    target = next((line for line in entries if line.account_id == owner and line.id in visible_ids), None)
                    if target:
                        sign = Decimal('1') if owner.account_type in EXPENSE_KEYS else Decimal('-1')
                        result[target] = result.get(target, Decimal('0')) + sign * self._decimal(tax_line.balance)
        if evidence_out is not None:
            evidence_out['adjustments'] = result
        return result

    def _native_invoice_tax_adjustments(self, move, entries, taxes):
        """Reconcile Odoo's rounded invoice tax details to every posted tax line."""
        error = _('The posted tax cannot be assigned to one profit and loss account. Select the tax-exclusive report.')
        if not move.is_invoice(include_receipts=True):
            raise ValidationError(error)
        currency = move.company_id.currency_id
        if move.currency_id != currency:
            raise ValidationError(error)
        bases, _tax_lines = move._get_rounded_base_and_tax_lines()
        self.env['account.tax']._add_accounting_data_in_base_lines_tax_details(bases, move.company_id)
        source_lines = move.line_ids.filtered(lambda line: line.display_type == 'product')
        by_id = {base['record'].id: base for base in bases
                 if base['record']._name == 'account.move.line' and base['record'].move_id == move
                 and base['record'].display_type == 'product'}
        if len(by_id) != len(bases) or set(by_id) != set(source_lines.ids) or set(entries.ids) != set(source_lines.ids):
            raise ValidationError(error)

        def money(value):
            return self._decimal(currency.round(float(value or 0)))

        expected, actual, allocated, observed_taxes = {}, {}, {}, set()
        for line in source_lines:
            details = by_id[line.id].get('tax_details') or {}
            if 'total_excluded' not in details or 'taxes_data' not in details:
                raise ValidationError(error)
            if abs(money(details['total_excluded'])) != abs(money(line.balance)):
                raise ValidationError(error)
            for item in details['taxes_data']:
                tax = item.get('tax')
                if not tax or tax.amount < 0 or not line.balance:
                    raise ValidationError(error)
                tax.check_access('read')
                observed_taxes.add(tax.id)
                amount = money(item.get('tax_amount'))
                reps = item.get('tax_reps_data') or []
                if sum((money(rep.get('tax_amount')) for rep in reps), Decimal('0')) != amount:
                    raise ValidationError(error)
                for rep in reps:
                    repartition, account = rep.get('tax_rep'), rep.get('account')
                    if not money(rep.get('tax_amount')):
                        continue
                    if not repartition or not account:
                        raise ValidationError(error)
                    repartition.check_access('read')
                    account.check_access('read')
                    value = abs(money(rep.get('tax_amount'))).copy_sign(self._decimal(line.balance))
                    key = (tax.id, repartition.id, account.id)
                    expected[key] = expected.get(key, Decimal('0')) + value
                    sign = Decimal('1') if line.account_id.account_type in EXPENSE_KEYS else Decimal('-1')
                    allocated[line] = allocated.get(line, Decimal('0')) + sign * value
        for line in taxes:
            key = (line.tax_line_id.id, line.tax_repartition_line_id.id, line.account_id.id)
            actual[key] = actual.get(key, Decimal('0')) + money(line.balance)
        if observed_taxes != set(entries.mapped('tax_ids').ids):
            raise ValidationError(error)
        if {k: v for k, v in expected.items() if v} != {k: v for k, v in actual.items() if v}:
            raise ValidationError(error)
        return allocated

    @api.model
    def _verify_links(self, lines):
        lines.check_access('read')
        lines.mapped('move_id').check_access('read')
        lines.mapped('journal_id').check_access('read')
        lines.mapped('account_id').check_access('read')

    @api.model
    def _section_rows(self, domain, *, adjustments_out=None, tax_evidence_out=None):
        rows = {key: [] for key in SECTION_KEYS}
        verified = self._verified_groups(
            domain, adjustments_out=adjustments_out, tax_evidence_out=tax_evidence_out,
        )
        for entry in verified.values():
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
    def _dashboard_percentage(self, numerator, denominator):
        """Return a display-only percentage calculated beside the ledger totals.

        The browser receives a ready-to-display value and never parses or
        aggregates money.  A zero denominator is deliberately unavailable,
        rather than being presented as an invented 0% result.
        """
        # A margin/share has no interpretable denominator when net revenue is
        # zero or negative (for example a full sales reversal).  Do not turn a
        # return period into an artificial signed percentage.
        if denominator <= 0:
            return {'available': False, 'display': '', 'negative': False}
        with localcontext() as context:
            context.prec = max(28, len(numerator.as_tuple().digits)
                               + len(denominator.as_tuple().digits) + 6)
            value = (numerator * Decimal('100') / abs(denominator)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )
        return {
            'available': True,
            'display': f'{value:,.2f}%',
            'negative': value < 0,
        }

    @api.model
    def _dashboard_change(self, current, comparison, higher_is_favorable=True):
        if comparison is None or not comparison:
            return {'available': False, 'display': '', 'direction': 'flat', 'tone': 'neutral'}
        with localcontext() as context:
            context.prec = max(28, len(current.as_tuple().digits)
                               + len(comparison.as_tuple().digits) + 6)
            value = ((current - comparison) * Decimal('100') / abs(comparison)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )
        direction = 'up' if value > 0 else ('down' if value < 0 else 'flat')
        favorable = value > 0 if higher_is_favorable else value < 0
        return {
            'available': True,
            'display': f'{value:,.2f}%',
            'direction': direction,
            'tone': 'positive' if favorable else ('negative' if value else 'neutral'),
        }

    @api.model
    def _dashboard_margin_change(self, current, comparison):
        if (comparison is None or current['income'] <= 0
                or comparison['income'] <= 0):
            return {'available': False, 'display': '', 'direction': 'flat', 'tone': 'neutral'}
        with localcontext() as context:
            context.prec = max(28, *(len(value.as_tuple().digits) for value in (
                current['gross_profit'], current['income'], comparison['gross_profit'],
                comparison['income'],
            )))
            current_margin = current['gross_profit'] * Decimal('100') / abs(current['income'])
            comparison_margin = comparison['gross_profit'] * Decimal('100') / abs(comparison['income'])
            difference = (current_margin - comparison_margin).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )
        return {
            'available': True,
            'display': f'{difference:,.2f} pp',
            'direction': 'up' if difference > 0 else ('down' if difference < 0 else 'flat'),
            'tone': 'positive' if difference > 0 else ('negative' if difference < 0 else 'neutral'),
        }

    @api.model
    def _dashboard_payload(self, grouped_by_period, totals, periods, currency, journal_ids):
        """Build a visual P&L projection from the already verified ledger groups.

        This is intentionally a projection of ``_report_rows`` inputs, never a
        second accounting query.  It keeps the dashboard, table and exported
        report reconciled to exactly the same posted move lines.
        """
        current = totals['current']
        comparison_period = next((period for period in periods
                                  if period['key'] != 'current'), None)
        comparison = totals.get(comparison_period['key']) if comparison_period else None

        card_keys = (
            'income', 'cost_of_sales', 'gross_profit', 'expense', 'net_income',
        )
        cards = []
        for key in card_keys:
            cards.append({
                'key': key,
                'value': self._period_amount(current[key], currency),
                'change': self._dashboard_change(
                    current[key], comparison[key] if comparison else None,
                    higher_is_favorable=key not in ('cost_of_sales', 'expense'),
                ),
            })
        cards.insert(3, {
            'key': 'gross_margin',
            'value': self._dashboard_percentage(current['gross_profit'], current['income']),
            'change': self._dashboard_margin_change(current, comparison),
        })

        waterfall_values = (
            ('income', current['income']),
            ('cost_of_sales', -current['cost_of_sales']),
            ('expense', -current['expense']),
            ('net_other_income', current['net_other_income']),
            ('net_income', current['net_income']),
        )
        maximum = max((abs(value) for _key, value in waterfall_values), default=Decimal('0'))
        maximum = maximum or Decimal('1')
        waterfall = []
        for key, value in waterfall_values:
            width = int((abs(value) * Decimal('100') / maximum).quantize(
                Decimal('1'), rounding=ROUND_HALF_UP,
            ))
            waterfall.append({
                'key': key,
                'amount': self._period_amount(value, currency),
                'visual_width': width,
                'tone': 'positive' if value > 0 else ('negative' if value < 0 else 'neutral'),
            })

        revenue_rows = grouped_by_period['current']['income'] + grouped_by_period['current']['income_other']
        revenue_total = current['income'] + current['other_income']
        revenue_accounts = []
        for entry in sorted(revenue_rows, key=lambda item: (
                -item['raw'], item['account'].code or '', item['account'].id,
        ))[:5]:
            account = entry['account']
            revenue_accounts.append({
                'id': account.id,
                'code': account.code or '',
                'name': account.name or '',
                'amount': self._period_amount(entry['raw'], currency),
                'share': self._dashboard_percentage(entry['raw'], revenue_total),
            })

        notes = ['posted_only']
        if journal_ids:
            notes.append('partial_journals')
        notes.append('comparison_available' if comparison else 'comparison_unavailable')
        if current['income'] <= 0:
            notes.append('gross_margin_unavailable')
        if revenue_total <= 0:
            notes.append('revenue_share_unavailable')
        return {
            'cards': cards,
            'waterfall': waterfall,
            'revenue_accounts': revenue_accounts,
            'notes': notes,
        }

    @api.model
    def get_report(self, filters):
        self = self.with_context(_baseer_pl_inclusive=self._tax_inclusive(filters))
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
            'dashboard': self._dashboard_payload(
                grouped_by_period, totals, periods, currency, journal_ids,
            ),
        }

    @api.model
    def action_print(self, filters):
        """Choose A4 orientation without doing a second financial aggregation."""
        if not isinstance(filters, dict) or filters.get('company_id') != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        _company, _journals, periods, _period_control, _comparison_control = self._scope(filters)
        report_id = ('action_profit_loss_pdf_landscape' if len(periods) > 1
                     else 'action_profit_loss_pdf_portrait')
        return self.env.ref(f'baseer_profit_loss_report.{report_id}').report_action(
            [], data={'filters': filters}, config=False,
        )

    @api.model
    def get_accounts(self, filters, section, page=1):
        self = self.with_context(_baseer_pl_inclusive=self._tax_inclusive(filters))
        if section not in SECTION_KEYS:
            raise ValidationError(_('Select a profit and loss section.'))
        if type(page) is not int or page < 1:
            raise ValidationError(_('Select a valid page.'))
        company, _journal_ids, periods, _period_control, _comparison_control = self._scope(filters)
        # A detail request only needs this section, including its displayed
        # child types. Tax allocation still inspects the complete source move.
        section_domain = Domain('account_id.account_type', 'in',
                                list(SECTION_GROUPS.get(section, (section,))))
        tax_evidence = ({} if self.env.context.get('_baseer_pl_inclusive')
                        and section in ('income', 'income_other') else None)
        grouped_by_period = {}
        for period in periods:
            domain = period['domain'] & section_domain
            if tax_evidence is None:
                grouped_by_period[period['key']] = self._section_rows(domain)
            else:
                evidence = tax_evidence.setdefault(period['key'], {})
                grouped_by_period[period['key']] = self._section_rows(
                    domain, tax_evidence_out=evidence,
                )
        return self._account_section(company, periods, grouped_by_period, section,
                                     page=page, tax_evidence=tax_evidence)

    def _account_section(self, company, periods, grouped_by_period, section, page=None,
                         channel_periods=None, tax_evidence=None):
        """Project already verified request-local groups; None selects the full section."""
        section_keys = SECTION_GROUPS.get(section, (section,))
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
        start = (page - 1) * self.PAGE_SIZE if page is not None else 0
        selected = ordered[start:start + self.PAGE_SIZE] if page is not None else ordered
        currency = company.currency_id
        accounts = []
        if channel_periods is None:
            channel_periods = {
                period['key']: self._revenue_channels(
                    company, period['domain'] & Domain('account_id', 'in',
                        [item['account'].id for item in selected]),
                    **({'_tax_evidence': tax_evidence[period['key']]} if tax_evidence is not None else {}))
                for period in periods
            } if section in ('income', 'income_other') else {}
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
                'channels': self._channel_period_payload(
                    account.id, periods, channel_periods, currency),
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

    def _order_channels(self, order, amount, company, _payment_ids=None):
        """Use original payment method IDs, not channel names or inference."""
        try:
            order.check_access('read')
            if order.company_id != company or order.currency_id != company.currency_id:
                return {UNALLOCATED: ('', amount)}
            payments = order.payment_ids
            payments.check_access('read')
            if _payment_ids is None:
                self.env['pos.payment'].flush_model(['pos_order_id'])
                self.env.cr.execute('SELECT id FROM pos_payment WHERE pos_order_id=%s', [order.id])
                _payment_ids = {item[0] for item in self.env.cr.fetchall()}
            if set(payments.ids) != _payment_ids:
                return {UNALLOCATED: ('', amount)}
            methods = payments.payment_method_id
            methods.check_access('read')
            if any(method.company_id != company for method in methods):
                return {UNALLOCATED: ('', amount)}
            tenders = [
                ('payment_%s' % payment.payment_method_id.id,
                 payment.payment_method_id.name, self._decimal(payment.amount))
                for payment in payments.sorted('id')
            ]
            rounding = self._decimal(company.currency_id.rounding)
            total = self._decimal(order.amount_total)
            total = -abs(total) if order.is_refund else total
            if not tender_matches_order(tenders, total, rounding):
                return {UNALLOCATED: ('', amount)}
            return allocate_channels(amount, tenders, rounding)
        except AccessError:
            return {UNALLOCATED: ('', amount)}

    def _channel_child_ids(self, orders):
        """Fresh identity-only inverse census for already searched POS parents.

        Never a financial source or a visibility grant. Each caller still checks
        each declared child relation's access and exact IDs at the scalar boundary.
        """
        order_ids = sorted(set(orders.ids))
        result = {'lines': {}, 'payments': {}}
        if not order_ids:
            return result
        self.env['pos.order.line'].flush_model(['order_id'])
        self.env['pos.payment'].flush_model(['pos_order_id'])
        for offset in range(0, len(order_ids), 1000):
            selected = order_ids[offset:offset + 1000]
            for key, query in (
                ('lines', 'SELECT order_id, id FROM pos_order_line WHERE order_id=ANY(%s)'),
                ('payments', 'SELECT pos_order_id, id FROM pos_payment WHERE pos_order_id=ANY(%s)'),
            ):
                result[key].update({order_id: set() for order_id in selected})
                self.env.cr.execute(query, [selected])
                while batch := self.env.cr.fetchmany(1000):
                    for order_id, child_id in batch:
                        result[key][order_id].add(child_id)
        return result

    @staticmethod
    def _claim_export_channel(budget, account_id, channel_key):
        if budget is None:
            return
        key = (account_id, channel_key)
        if key not in budget['keys']:
            if len(budget['keys']) >= budget['limit']:
                raise ValidationError(_('The export is limited to 5,000 rows. Narrow the period or selected journals.'))
            budget['keys'].add(key)

    def _native_channel_accounts(self, orders, line_ids_by_order):
        """Prepare unchanged native bases in bounded chunks, then prove accounts.

        Nothing is returned until every child relation, native result identity,
        and account has passed. The caller retains its move/account-local fallback.
        """
        source_ids = []
        for order in orders:
            lines = order.lines
            lines.check_access('read')
            if set(lines.ids) != line_ids_by_order[order.id]:
                raise AccessError(_('POS source is not available.'))
            source_ids.extend(lines.ids)
        if len(set(source_ids)) != len(source_ids):
            raise AccessError(_('POS source is not available.'))
        source_lines = self.env['pos.order.line'].browse(source_ids)
        prepared = {}
        for offset in range(0, len(source_lines), 1000):
            chunk = source_lines[offset:offset + 1000]
            chunk = chunk.with_prefetch(chunk.ids)
            bases = chunk._prepare_tax_base_line_values()
            expected, seen, accounts_by_env = set(chunk.ids), set(), {}
            for base in bases:
                record = base['record']
                if record._name != 'pos.order.line' or len(record) != 1 or record.id not in expected or record.id in seen:
                    raise AccessError(_('POS source is not available.'))
                seen.add(record.id)
                account = base.get('account_id')
                if account:
                    # Keep the exact environment returned by native preparation:
                    # do not change company, user or fiscal-position context.
                    accounts_by_env[account.env] = accounts_by_env.get(account.env, account.browse()) | account
                prepared[record.id] = account
            if seen != expected:
                raise AccessError(_('POS source is not available.'))
            for accounts in accounts_by_env.values():
                accounts.check_access('read')
        return prepared

    def _closed_pos_accounting_amounts(self, orders, move, company, line_ids_by_order,
                                       original_session_move=None):
        """Rebuild the read-only tax bases used by native POS session posting."""
        sessions = orders.session_id
        currency = company.currency_id
        session_move = original_session_move or move
        if (len(sessions) != 1 or sessions.state != 'closed' or sessions.move_id != session_move
                or sessions.company_id != company or sessions.currency_id != currency
                or move.state != 'posted' or move.company_id != company
                or move.currency_id != currency
                or session_move.state != 'posted' or session_move.company_id != company
                or session_move.currency_id != currency or session_move.journal_id != move.journal_id
                or any(order.account_move or order.currency_id != currency for order in orders)):
            return None

        move_lines = move.line_ids
        move_lines.check_access('read')
        Move = self.env['account.move']
        if Move.search_count(Domain('id', '=', move.id) & Domain(
                'line_ids', 'any!', Domain('id', 'not in', move_lines.ids)), limit=1):
            return None
        self._verify_links(move_lines)
        if any(line.company_id != company or line.currency_id != currency for line in move_lines):
            return None
        move_lines.tax_repartition_line_id.check_access('read')
        move_lines.tax_line_id.check_access('read')

        def minor_amount(value):
            return self._decimal(currency.round(value))

        def add(amounts, key, value):
            if value:
                amounts[key] = amounts.get(key, Decimal('0')) + value

        def nonzero(amounts):
            return {key: amount for key, amount in amounts.items() if amount}

        ledger_revenue, ledger_tax = {}, {}
        for line in move_lines:
            if line.tax_repartition_line_id:
                if not line.tax_line_id:
                    return None
                add(ledger_tax, line.tax_line_id.id, self._decimal(line.balance))
            elif line.account_id.account_type in ('income', 'income_other'):
                add(ledger_revenue, line.account_id.id, -self._decimal(line.balance))
        # Saved POS order totals prove the net at order level, but do not
        # disambiguate a historical split between multiple income accounts.
        if len(nonzero(ledger_revenue)) != 1:
            return None
        income_account_id = next(iter(nonzero(ledger_revenue)))

        Tax = self.env['account.tax']
        reconstructed_revenue, reconstructed_tax = {}, {}
        by_order = {}
        for order in orders:
            bases = order.with_context(linked_to_pos=True)._prepare_tax_base_line_values()
            records = [base['record'] for base in bases]
            if (any(record._name != 'pos.order.line' or len(record) != 1 for record in records)
                    or len(records) != len(line_ids_by_order[order.id])
                    or {record.id for record in records} != line_ids_by_order[order.id]):
                return None
            Tax.browse(sorted({tax.id for base in bases for tax in base['tax_ids']})).check_access('read')
            Tax._add_tax_details_in_base_lines(bases, company)
            Tax._round_base_lines_tax_details(bases, company)
            taxes = Tax.browse(sorted({item['tax'].id for base in bases
                                      for item in base['tax_details']['taxes_data']}))
            taxes.check_access('read')
            if any(tax.company_id != company for tax in taxes):
                return None
            order_amounts = {}
            gross = Decimal('0')
            tax_total = Decimal('0')
            for base in bases:
                account = base['account_id']
                account.check_access('read')
                if not account or company not in account.company_ids:
                    return None
                details = base['tax_details']
                sign = base['sign']
                # Same signed base amount as account.tax._prepare_tax_lines.
                # Tags and repartition-line generation are unnecessary here.
                net = -sign * minor_amount(details['total_excluded_currency']
                                           + details['delta_total_excluded_currency'])
                if net and account.id != income_account_id:
                    return None
                gross += net
                add(order_amounts, account.id, net)
                add(reconstructed_revenue, account.id, net)
                for item in details['taxes_data']:
                    if item['is_reverse_charge']:
                        return None
                    value = sign * minor_amount(item['tax_amount_currency'])
                    gross -= value
                    tax_total -= value
                    add(reconstructed_tax, item['tax'].id, value)
            total = minor_amount(order.amount_total)
            saved_tax = minor_amount(order.amount_tax)
            if order.is_refund:
                total, saved_tax = -abs(total), -abs(saved_tax)
            if gross != total or tax_total != saved_tax:
                return None
            by_order[order.id] = order_amounts
        if (nonzero(reconstructed_revenue) != nonzero(ledger_revenue)
                or nonzero(reconstructed_tax) != nonzero(ledger_tax)):
            return None
        return by_order

    def _channel_move_census(self, company, move_ids):
        """Batch only identity checks for the caller's already verified moves."""
        self.env['pos.order'].flush_model(['company_id', 'state', 'account_move', 'session_id'])
        self.env['pos.session'].flush_model(['move_id'])
        self.env.cr.execute('''SELECT COALESCE(o.account_move, s.move_id), array_agg(o.id)
            FROM pos_order o LEFT JOIN pos_session s ON s.id=o.session_id
            WHERE o.company_id=%s AND o.state IN ('paid', 'done', 'invoiced')
              AND (o.account_move=ANY(%s) OR (o.account_move IS NULL AND s.move_id=ANY(%s)))
            GROUP BY 1''', [company.id, move_ids, move_ids])
        orders = {move_id: set(ids) for move_id, ids in self.env.cr.fetchall()}
        self.env['account.partial.reconcile'].flush_model(['debit_move_id', 'credit_move_id'])
        self.env.cr.execute('''WITH linked AS (
            SELECT p.id, d.move_id AS scoped_move, d.move_id AS debit_move, c.move_id AS credit_move
            FROM account_move_line d
            JOIN account_partial_reconcile p ON p.debit_move_id=d.id
            JOIN account_move_line c ON c.id=p.credit_move_id
            WHERE d.move_id=ANY(%s)
            UNION
            SELECT p.id, c.move_id, d.move_id, c.move_id
            FROM account_move_line c
            JOIN account_partial_reconcile p ON p.credit_move_id=c.id
            JOIN account_move_line d ON d.id=p.debit_move_id
            WHERE c.move_id=ANY(%s)
        )
        SELECT scoped_move, array_agg(linked.id) FROM linked
        JOIN account_move dm ON dm.id=debit_move
        JOIN account_move cm ON cm.id=credit_move
        WHERE dm.ref LIKE 'POS-%%-ADMIN-CORRECTION-%%' OR cm.ref LIKE 'POS-%%-ADMIN-CORRECTION-%%'
        GROUP BY scoped_move''', [move_ids, move_ids])
        return orders, dict(self.env.cr.fetchall())

    def _pos_correction_pair(self, move, company, partial_ids):
        """Prove one isolated, explicitly reconciled POS correction, or return None.

        The census supplies IDs only. Values and relationships still require
        the caller's ORM access checks.
        """
        if (move.state != 'posted' or move.company_id != company
                or move.currency_id != company.currency_id):
            return None
        move.check_access('read')
        Partial = self.env['account.partial.reconcile']
        suspected = bool((move.ref or '').startswith('POS-') and '-ADMIN-CORRECTION-' in move.ref)
        if not partial_ids:
            return {} if suspected else None
        move_lines = move.line_ids
        move_lines.check_access('read')
        self._verify_links(move_lines)
        if self.env['account.move'].search_count(Domain('id', '=', move.id) & Domain(
                'line_ids', 'any!', Domain('id', 'not in', move_lines.ids)), limit=1):
            return {}
        Partial.browse().check_access('read')
        partials = Partial.browse(partial_ids).exists()
        partials.check_access('read')
        candidates = []
        pattern = re.compile(r'^POS-([1-9][0-9]*)-ADMIN-CORRECTION-([0-9]{8})$')
        for partial in partials:
            debit, credit = partial.debit_move_id, partial.credit_move_id
            (debit | credit).check_access('read')
            (debit.move_id | credit.move_id).check_access('read')
            for correction_line, original_line in ((debit, credit), (credit, debit)):
                correction = correction_line.move_id
                match = pattern.fullmatch(correction.ref or '')
                if not match or (move != correction and move != original_line.move_id):
                    continue
                expected = correction.ref + ' / reverse ONLY original closing difference'
                if correction_line.name not in (expected + str(original_line.id),
                                                 expected + ' ' + str(original_line.id)):
                    continue
                candidates.append((partial, original_line, correction_line, match))
        if len(candidates) != 1:
            return {}
        partial, original_line, correction_line, match = candidates[0]
        original, correction = original_line.move_id, correction_line.move_id
        if len(match[1]) > 10:
            return {}
        order_id = int(match[1])
        if order_id > 2147483647:
            return {}
        if (original == correction or original.state != 'posted' or correction.state != 'posted'
                or original.move_type != 'entry' or correction.move_type != 'entry'
                or original.company_id != company or correction.company_id != company
                or original.currency_id != company.currency_id or correction.currency_id != company.currency_id
                or original.journal_id != correction.journal_id
                or original_line.company_id != company or correction_line.company_id != company
                or original_line.currency_id != company.currency_id or correction_line.currency_id != company.currency_id
                or original_line.account_id != correction_line.account_id
                or original_line.account_id.account_type != 'asset_receivable'
                or not original_line.full_reconcile_id
                or original_line.full_reconcile_id != correction_line.full_reconcile_id
                or partial.full_reconcile_id != original_line.full_reconcile_id
                or self._decimal(original_line.balance) >= 0
                or self._decimal(correction_line.balance) != -self._decimal(original_line.balance)
                or self._decimal(partial.amount) != abs(self._decimal(original_line.balance))):
            return {}
        original_line.full_reconcile_id.check_access('read')
        try:
            correction_date = date(int(match[2][:4]), int(match[2][4:6]), int(match[2][6:]))
        except ValueError:
            return {}
        if correction.date != correction_date:
            return {}
        # Both reconciliation endpoints must have exactly this one complete edge.
        for line in (original_line, correction_line):
            self.env.cr.execute('''SELECT id FROM account_partial_reconcile
                WHERE debit_move_id=%s OR credit_move_id=%s''', [line.id, line.id])
            if {row[0] for row in self.env.cr.fetchall()} != {partial.id}:
                return {}
            visible = line.matched_debit_ids | line.matched_credit_ids
            visible.check_access('read')
            if visible.ids != partial.ids:
                return {}
            if (self._decimal(line.amount_currency) != self._decimal(line.balance)
                    or self._decimal(partial.debit_amount_currency) != self._decimal(partial.amount)
                    or self._decimal(partial.credit_amount_currency) != self._decimal(partial.amount)):
                return {}

        # A second correction or a hidden competing reference makes linkage ambiguous.
        ref_prefix = 'POS-%s-ADMIN-CORRECTION-' % order_id
        Move = self.env['account.move']
        refs = Move.search([('company_id', '=', company.id), ('ref', '=like', ref_prefix + '%'),
                            ('state', '!=', 'cancel')])
        refs.check_access('read')
        Move.flush_model(['company_id', 'ref', 'state'])
        self.env.cr.execute('''SELECT id FROM account_move WHERE company_id=%s
            AND ref LIKE %s AND state != 'cancel' ''', [company.id, ref_prefix + '%'])
        if set(refs.ids) != {row[0] for row in self.env.cr.fetchall()} or refs.ids != correction.ids:
            return {}
        Order = self.env['pos.order']
        Order.browse().check_access('read')
        Order.flush_model(['company_id', 'state', 'account_move', 'session_id'])
        self.env['pos.session'].flush_model(['move_id'])
        # The correction must not already own native POS orders by either path.
        self.env.cr.execute('''SELECT o.id FROM pos_order o LEFT JOIN pos_session s ON s.id=o.session_id
            WHERE o.account_move=%s OR s.move_id=%s''', [correction.id, correction.id])
        if self.env.cr.fetchone():
            return {}
        order = Order.browse(order_id).exists()
        order.check_access('read')
        if (not order or order.company_id != company or order.currency_id != company.currency_id
                or order.state not in ('paid', 'done') or order.is_refund or order.is_invoiced
                or order.account_move or self._decimal(order.amount_total) <= 0
                or self._decimal(order.amount_total) != self._decimal(partial.amount)):
            return {}
        session = order.session_id
        session.check_access('read')
        if (not session or session.state != 'closed' or session.company_id != company
                or session.currency_id != company.currency_id or session.move_id != original
                or session.config_id.journal_id != original.journal_id):
            return {}
        orders = Order.search([
            ('company_id', '=', company.id), ('state', 'in', ('paid', 'done', 'invoiced')),
            '|', ('account_move', '=', original.id),
            '&', ('account_move', '=', False), ('session_id.move_id', '=', original.id),
        ])
        orders.check_access('read')
        self.env.cr.execute('''SELECT o.id FROM pos_order o LEFT JOIN pos_session s ON s.id=o.session_id
            WHERE o.state IN ('paid','done','invoiced')
            AND (o.account_move=%s OR (o.account_move IS NULL AND s.move_id=%s))''',
            [original.id, original.id])
        if set(orders.ids) != {row[0] for row in self.env.cr.fetchall()} or order not in orders:
            return {}
        remaining = orders - order
        if (not remaining or remaining.session_id != session
                or any(item.account_move or item.is_invoiced for item in remaining)):
            return {}
        census = self._channel_child_ids(orders)
        self._native_channel_accounts(orders, census['lines'])
        original_basis = self._closed_pos_accounting_amounts(remaining, original, company, census['lines'])
        correction_basis = self._closed_pos_accounting_amounts(
            order, correction, company, census['lines'], original_session_move=original)
        if original_basis is None or correction_basis is None:
            return {}
        original_accounts = {key for amounts in original_basis.values() for key, value in amounts.items() if value}
        correction_accounts = {key for amounts in correction_basis.values() for key, value in amounts.items() if value}
        if len(original_accounts) != 1 or original_accounts != correction_accounts:
            return {}
        account_id = next(iter(original_accounts))
        # Every payment must be independently visible and reconcilable to its order.
        for item in orders:
            portions = self._order_channels(item, original_basis[item.id].get(account_id, Decimal('0'))
                                            if item != order else correction_basis[item.id].get(account_id, Decimal('0')),
                                            company, _payment_ids=census['payments'][item.id])
            if not portions or UNALLOCATED in portions:
                return {}
        return {
            original.id: (remaining, original_basis, census),
            correction.id: (order, correction_basis, census),
        }

    @api.model
    def _revenue_channels(self, company, domain, provenance=None, _export_channel_budget=None, _tax_evidence=None):
        """Only attribute a whole move/account after exact POS net matching."""
        lines = self.env['account.move.line'].search(domain)
        self._verify_links(lines)
        posted_by_move_account = {}
        for line in lines:
            key = (line.move_id.id, line.account_id.id)
            posted_by_move_account[key] = posted_by_move_account.get(key, Decimal('0')) - self._decimal(line.balance)
        grouped = dict(posted_by_move_account)
        noorix = {}
        method_by_account = {}
        approved_mappings = []
        inclusive = self.env.context.get('_baseer_pl_inclusive')
        if inclusive:
            # Reuse verified data only if this page contains exactly the same
            # visible source lines. Different pages require a fresh proof.
            if (_tax_evidence and _tax_evidence.get('line_ids') == frozenset(lines.ids)
                    and 'adjustments' in _tax_evidence):
                noorix.update(_tax_evidence['noorix_sources'])
                adjustments = _tax_evidence['adjustments']
            else:
                adjustments = self._inclusive_adjustments(domain, noorix_sources=noorix)
            for line, delta in adjustments.items():
                key = (line.move_id.id, line.account_id.id)
                grouped[key] = grouped.get(key, Decimal('0')) + delta
        dates = [line.date for line in lines if line.date]
        if dates and not inclusive:
            try:
                noorix, _incomplete = self._verified_noorix_gross_channels(
                    company, min(dates), max(dates), domain)
            except AccessError:
                # Report-only users retain the posted net, without learning
                # whether an inaccessible source or evidence record exists.
                noorix = {}
        if noorix and dates:
            if inclusive:
                method_by_account = self._noorix_payment_methods(company)
            try:
                approved_mappings = self._noorix_display_mappings(company, min(dates), max(dates))
            except AccessError:
                if inclusive:
                    raise
                noorix = {}
        result = {}
        # Only IDs are reused within this invocation; no context, cross-request,
        # amount or visibility cache. Guard failures retain their original scope.
        child_ids = {'lines': {}, 'payments': {}}
        accounting_amounts = {}
        correction_pairs = {}
        order_census = None
        for (move_id, account_id), amount in grouped.items():
            allocation = {UNALLOCATED: ('', amount)}
            posted_net = posted_by_move_account.get((move_id, account_id), Decimal('0'))
            source = noorix.get((move_id, account_id))
            if source is not None and not inclusive:
                source_channels, _funding_accounts = source
                move = lines.env['account.move'].browse(move_id)
                estimated = self._noorix_net_estimate(move, company, posted_net,
                                                       source_channels, approved_mappings)
                if estimated is not None:
                    allocation = estimated
                source = False  # Do not mix this source with POS attribution.
            if source:
                source_channels, funding_accounts = source
                names = {
                    'cash': ('نقدي', 'Cash'), 'bank': ('بنك', 'Bank'),
                    'keeta': ('كيتا', 'Keeta'), 'hunger': ('هنقرستيشن', 'HungerStation'),
                    'jahez': ('جاهز', 'Jahez'),
                }
                arabic = (self.env.lang or '').startswith('ar')
                allocation = {}
                account_counts = Counter(funding_accounts.values())
                for key, value in source_channels.items():
                    account_id_for_channel = funding_accounts[key]
                    source_date = lines.env['account.move'].browse(move_id).date
                    selected = [item for item in approved_mappings
                                if item[0] == key and item[1] <= source_date <= item[2]]
                    if selected:
                        method = selected[0][3]
                    else:
                        method = (method_by_account.get(account_id_for_channel)
                                  if account_counts[account_id_for_channel] == 1 else None)
                    channel = 'payment_' + str(method.id) if method else 'noorix_' + key
                    name = method.display_name if method else names[key][0 if arabic else 1]
                    previous = allocation.get(channel, (name, Decimal('0')))
                    allocation[channel] = (name, previous[1] + value)
            if source is None and not (not inclusive and
                                       'NOORIX-SALES' in (lines.env['account.move'].browse(move_id).ref or '').upper()):
                try:
                    Order = self.env['pos.order']
                    Order.browse().check_access('read')
                    if order_census is None:
                        move_ids = sorted({key[0] for key in grouped})
                        move_orders, correction_census = self._channel_move_census(company, move_ids)
                        verified_orders = Order.search([
                            ('id', 'in', sorted({order_id for ids in move_orders.values() for order_id in ids})),
                            ('company_id', '=', company.id), ('state', 'in', ('paid', 'done', 'invoiced')),
                        ])
                        order_rank = {order_id: index for index, order_id in enumerate(verified_orders.ids)}
                        order_census = move_orders
                    order_ids = order_census.get(move_id, set())
                    # Rules may silently hide some orders. IDs are used only to
                    # prove completeness, never to expose hidden amounts/names.
                    if not order_ids <= order_rank.keys():
                        raise AccessError(_('POS source is not available.'))
                    orders = Order.browse(sorted(order_ids, key=order_rank.__getitem__))
                    orders.check_access('read')
                    orders.session_id.check_access('read')
                    if move_id not in correction_pairs:
                        try:
                            pair = self._pos_correction_pair(
                                lines.env['account.move'].browse(move_id), company,
                                correction_census.get(move_id, []))
                        except UserError:
                            # A failed correction proof must not fall back to an
                            # ordinary POS attribution of the same source.
                            pair = {}
                        correction_pairs[move_id] = pair
                        if pair:
                            correction_pairs.update({key: pair for key in pair})
                    pair = correction_pairs[move_id]
                    order_amounts = None
                    payment_census = child_ids['payments']
                    if pair is not None:
                        if move_id in pair:
                            pair_orders, basis, census = pair[move_id]
                            rebuilt = [(item, basis[item.id].get(account_id, Decimal('0'))) for item in pair_orders]
                            if sum((net for _order, net in rebuilt), Decimal('0')) == posted_net:
                                order_amounts = rebuilt
                                payment_census = census['payments']
                    else:
                        missing = orders.filtered(lambda order: order.id not in child_ids['lines'])
                        if missing:
                            census = self._channel_child_ids(missing)
                            for key in child_ids:
                                child_ids[key].update(census[key])
                        prepared_accounts = self._native_channel_accounts(orders, child_ids['lines'])
                        order_amounts = []
                        for order in orders:
                            net = Decimal('0')
                            for source in order.lines:
                                account = prepared_accounts[source.id]
                                if account and account.id == account_id:
                                    subtotal = self._decimal(source.price_subtotal)
                                    net += -abs(subtotal) if order.is_refund else subtotal
                            order_amounts.append((order, net))
                        order_amounts = reconcile_order_amounts(
                            order_amounts, posted_net, self._decimal(company.currency_id.rounding))
                        if order_amounts is None and orders:
                            if move_id not in accounting_amounts:
                                move = lines.env['account.move'].browse(move_id)
                                try:
                                    accounting_amounts[move_id] = self._closed_pos_accounting_amounts(
                                        orders, move, company, child_ids['lines'])
                                except UserError:
                                    accounting_amounts[move_id] = None
                            recovered = accounting_amounts[move_id]
                            if recovered is not None:
                                rebuilt = [(order, recovered[order.id].get(account_id, Decimal('0')))
                                           for order in orders]
                                if sum((net for _order, net in rebuilt), Decimal('0')) == posted_net:
                                    order_amounts = rebuilt
                    if order_amounts is not None and inclusive:
                        gross_orders = [(order, -abs(self._decimal(order.amount_total)) if order.is_refund
                                         else self._decimal(order.amount_total))
                                        for order, _net in order_amounts]
                        if sum((gross for _order, gross in gross_orders), Decimal('0')) == amount:
                            order_amounts = gross_orders
                        else:
                            order_amounts = None
                    if order_amounts is not None:
                        allocation = {}
                        for order, net in order_amounts:
                            for key, (name, value) in self._order_channels(
                                    order, net, company, _payment_ids=payment_census[order.id]).items():
                                prior = allocation.get(key, (name, Decimal('0')))
                                allocation[key] = (name, prior[1] + value)
                except (AccessError, KeyError):
                    # POS is an optional source for an accounting-only installation.
                    pass
            target = result.setdefault(account_id, {})
            for key, (name, value) in allocation.items():
                self._claim_export_channel(_export_channel_budget, account_id, key)
                if provenance is not None:
                    provenance.append({'move_id': move_id, 'account_id': account_id,
                                       'channel_key': key, 'name': name, 'value': value})
                previous = target.get(key, (name, Decimal('0')))
                target[key] = (name, previous[1] + value)
        return result

    def _noorix_net_estimate(self, move, company, posted_net, source_channels, mappings):
        """Return explicitly labelled management estimates, never actual tax."""
        if (move.move_type != 'entry' or company.currency_id.name != 'SAR'
                or self._decimal(company.currency_id.rounding) != Decimal('0.01')
                or 'pos.order' not in self.env):
            return None
        # Legacy untagged imports lack a stable external identity. If another
        # posted summary names the same source and day, at least one untagged
        # entry prevents us from proving that they represent distinct sales.
        # Test existence only: competitors hidden by record rules are never read.
        ref = move.ref or ''
        branch = re.search(r'NOORIX-SALES[ \t]+([A-Z][A-Z0-9_-]*)[ \t]+', ref)
        if not branch:
            return None
        tagged = bool(re.search(r'(?<!\S)src:([A-Za-z0-9_-]+)(?=\s|$)', ref))
        ref_pattern = r'NOORIX-SALES[[:space:]]+' + re.escape(branch[1]) + r'[[:space:]]+'
        self.env['account.move'].flush_model(['company_id', 'state', 'date', 'ref'])
        self.env.cr.execute('''SELECT 1 FROM account_move
                               WHERE company_id=%s AND state='posted' AND date=%s AND id<>%s
                                 AND ref ~ %s
                                 AND (%s OR ref !~ %s)
                               LIMIT 1''', [company.id, move.date, move.id, ref_pattern,
                                            not tagged, r'(^|[[:space:]])src:[A-Za-z0-9_-]+([[:space:]]|$)'])
        if self.env.cr.fetchone():
            return None
        # An existence-only census prevents duplicate attribution even if a POS
        # order is hidden by a record rule; no hidden values are disclosed.
        self.env['pos.order'].flush_model(['account_move', 'session_id'])
        self.env['pos.session'].flush_model(['move_id'])
        self.env.cr.execute('''SELECT 1 FROM pos_order o LEFT JOIN pos_session s ON s.id=o.session_id
                               WHERE o.account_move=%s OR s.move_id=%s LIMIT 1''', [move.id, move.id])
        if self.env.cr.fetchone():
            return None
        by_method, methods = {}, {}
        for key, gross in source_channels.items():
            selected = [item for item in mappings if item[0] == key and item[1] <= move.date <= item[2]]
            if len(selected) != 1 or not selected[0][3]:
                return None
            method = selected[0][3]
            if method.company_id != company or method.id in methods:
                return None
            methods[method.id] = method
            by_method[method.id] = gross
        portions = estimate_noorix_net(posted_net, by_method)
        if portions is None:
            return None
        ar = (self.env.lang or '').startswith('ar')
        suffix = ' — تقديري إداري' if ar else ' — management estimate'
        return {'estimated_payment_%s' % method_id:
                (methods[method_id].display_name + suffix, amount)
                for method_id, amount in portions.items()}

    def _noorix_display_mappings(self, company, start, end):
        """Load only authorized, explicit mappings; unavailable methods remain separate."""
        Mapping = self.env['baseer.pl.noorix.channel.mapping']
        mappings = Mapping.search([('company_id', '=', company.id), ('date_from', '<=', end),
                                   ('date_to', '>=', start)])
        mappings.check_access('read')
        Mapping.flush_model(['company_id', 'date_from', 'date_to'])
        self.env.cr.execute('''SELECT id FROM baseer_pl_noorix_channel_mapping
            WHERE company_id=%s AND date_from<=%s AND date_to>=%s''', [company.id, end, start])
        if set(mappings.ids) != {row[0] for row in self.env.cr.fetchall()}:
            raise AccessError(_('A payment display mapping is not available.'))
        if not mappings:
            return []
        active = mappings.filtered(lambda item: not item.revoked)
        for index, mapping in enumerate(active):
            if any(other.date_from <= mapping.date_to and other.date_to >= mapping.date_from
                   and (other.source_channel == mapping.source_channel
                        or other.payment_method_id == mapping.payment_method_id)
                   for other in active[index + 1:]):
                raise ValidationError(_('Conflicting payment display mappings require review.'))
        try:
            Method = self.env['pos.payment.method'].with_context(active_test=False)
            methods = Method.search([('company_id', '=', company.id),
                                     ('id', 'in', mappings.mapped('payment_method_id'))])
            methods.check_access('read')
            by_id = {method.id: method for method in methods}
        except (AccessError, KeyError):
            by_id = {}
        return [(mapping.source_channel, mapping.date_from, mapping.date_to,
                 None if mapping.revoked else by_id.get(mapping.payment_method_id))
                for mapping in mappings.sorted(key=lambda item: (item.revoked, item.id))]

    @api.model
    def _verified_noorix_gross_channels(self, company, start, end, domain):
        """Prove only selected Noorix entries, without reading unrelated amounts."""
        if 'baseer.noorix.sales.evidence' not in self.env:
            return {}, []
        Line = self.env['account.move.line']
        scoped = Line.search(domain)
        self._verify_links(scoped)
        moves = scoped.mapped('move_id').filtered(
            lambda move: 'NOORIX-SALES' in (move.ref or '').upper())
        if not moves:
            return {}, []
        Evidence = self.env['baseer.noorix.sales.evidence'].with_company(company)
        Evidence.check_access('read')
        Evidence._ledger_check_complete_lines(moves)
        candidates = Evidence._ledger_tax_candidates(moves)
        evidence = Evidence.search([('move_id', 'in', moves.ids)])
        # Existence-only guard; no hidden identity or value is exposed.
        self.env.cr.execute(
            'SELECT 1 FROM baseer_noorix_sales_evidence WHERE move_id=ANY(%s) AND NOT (id=ANY(%s)) LIMIT 1',
            [moves.ids, evidence.ids])
        if self.env.cr.fetchone():
            raise AccessError(_('A Noorix source has inaccessible reporting evidence.'))
        evidence_amounts = evidence._validated_amounts()
        by_move = {}
        for line in scoped:
            by_move.setdefault(line.move_id.id, set()).add(line.account_id.id)
        sources, incomplete = {}, []
        seen = set()
        Move = self.env['account.move']
        for move in moves:
            try:
                if move.reversed_entry_id or Move.search_count(
                        Domain('id', '=', move.id) & Domain('reversal_move_ids', 'any!', Domain([])), limit=1):
                    incomplete.append(move.id)
                    continue
                identity = Evidence._ledger_source_identity(move, company)
                if identity in seen:
                    raise NoorixSourceConflict(_('A Noorix source identity is represented more than once.'))
                seen.add(identity)
                # Existing tagged source identities must be unique across the
                # company even if a competing entry is outside these journals.
                source_id = identity[2]
                if isinstance(source_id, str):
                    search = [('company_id', '=', company.id), ('state', '=', 'posted'),
                              ('ref', 'ilike', 'src:' + source_id)]
                    visible = Move.search(search).filtered(
                        lambda other: source_id in re.findall(r'(?<!\S)src:([A-Za-z0-9_-]+)(?=\s|$)', other.ref or '', re.IGNORECASE))
                    Move.flush_model(['company_id', 'state', 'ref'])
                    self.env.cr.execute(
                        'SELECT id FROM account_move WHERE company_id=%s AND state=%s AND ref ~ %s',
                        [company.id, 'posted', r'(^|[[:space:]])[sS][rR][cC]:' + source_id + r'([[:space:]]|$)'])
                    if set(visible.ids) != {row[0] for row in self.env.cr.fetchall()}:
                        raise AccessError(_('A competing Noorix source is not available.'))
                    for other in visible - move:
                        tokens = re.findall(r'(?<!\S)src:([A-Za-z0-9_-]+)(?=\s|$)', other.ref or '')
                        if tokens == [source_id] and Evidence._ledger_source_identity(other, company) == identity:
                            raise NoorixSourceConflict(_('A Noorix source identity is represented more than once.'))
                linked = evidence.filtered(lambda item: item.move_id == move)
                if len(linked) > 1:
                    raise NoorixSourceConflict(_('A Noorix entry has conflicting evidence.'))
                if linked:
                    amount = evidence_amounts[linked.id]
                elif not any(line.tax_ids or line.tax_line_id or line.tax_repartition_line_id or line.tax_tag_ids
                             for line in move.line_ids):
                    amount = self._noorix_untaxed_amount(move, company)
                else:
                    amount = Evidence._ledger_sales_amount(move, company, candidates)
                result = noorix_gross_channels({'original': True, 'move': move, 'amount': amount}, company)
                if result is None or result[0] not in by_move[move.id]:
                    incomplete.append(move.id)
                    continue
                account_id, amounts, funding_accounts = result
                sources[(move.id, account_id)] = (amounts, funding_accounts)
            except NoorixSourceConflict:
                raise
            except ValidationError:
                # Unsupported selected entries remain visible as incomplete.
                # The inclusive amount collector will refuse ambiguity.
                incomplete.append(move.id)
        return sources, incomplete

    def _noorix_untaxed_amount(self, move, company):
        """Prove an original, all-visible, untaxed sales and funding entry."""
        error = _('The Noorix source is not a proved tax-free sale.')
        revenue = funding = Decimal('0')
        for line in move.line_ids:
            line.check_access('read')
            line.account_id.check_access('read')
            line.tax_ids.check_access('read')
            line.tax_line_id.check_access('read')
            line.tax_repartition_line_id.check_access('read')
            line.tax_tag_ids.check_access('read')
            if (line.company_id != company or company not in line.account_id.company_ids
                    or line.currency_id != company.currency_id or line.tax_ids or line.tax_line_id
                    or line.tax_repartition_line_id or line.tax_tag_ids):
                raise ValidationError(error)
            value = self._decimal(line.balance)
            if line.account_id.account_type in ('income', 'income_other'):
                if value > 0:
                    raise ValidationError(error)
                revenue -= value
            elif line.account_id.internal_group == 'asset':
                if value < 0:
                    raise ValidationError(error)
                funding += value
            else:
                raise ValidationError(error)
        if revenue <= 0 or revenue != funding:
            raise ValidationError(error)
        return revenue

    def _noorix_payment_methods(self, company):
        """Match ledger accounts to one visible, explicitly configured POS method."""
        try:
            Method = self.env['pos.payment.method'].with_context(active_test=False)
            methods = Method.search([('company_id', '=', company.id)])
            methods.check_access('read')
            Method.flush_model(['company_id'])
            self.env.cr.execute('SELECT id FROM pos_payment_method WHERE company_id=%s', [company.id])
            if set(methods.ids) != {row[0] for row in self.env.cr.fetchall()}:
                return {}
            methods.journal_id.check_access('read')
            methods.receivable_account_id.check_access('read')
            methods.outstanding_account_id.check_access('read')
            methods.journal_id.default_account_id.check_access('read')
        except AccessError:
            return {}
        candidates = {}
        for method in methods:
            accounts = method.receivable_account_id | method.outstanding_account_id | method.journal_id.default_account_id
            for account in accounts:
                candidates.setdefault(account.id, set()).add(method.id)
        return {account_id: methods.browse(next(iter(ids))) for account_id, ids in candidates.items() if len(ids) == 1}

    def _channel_period_payload(self, account_id, periods, channel_periods, currency):
        keys = {}
        for period in periods:
            keys.update(channel_periods.get(period['key'], {}).get(account_id, {}))
        return [{'key': key, 'name': (name or self._unallocated_channel_label()),
                 'amounts': {period['key']: self._period_amount(
                     channel_periods.get(period['key'], {}).get(account_id, {}).get(
                         key, ('', Decimal('0')))[1], currency) for period in periods}}
                for key, (name, _value) in sorted(keys.items())]

    def _unallocated_channel_label(self):
        return ('غير موزع حسب طريقة الدفع' if (self.env.lang or '').startswith('ar')
                else _('Unallocated by payment method'))

    @api.model
    def get_lines(self, filters, account_id, page=1, period_key='current'):
        """Return a guarded page of source AMLs; every linked move remains readable."""
        self = self.with_context(_baseer_pl_inclusive=self._tax_inclusive(filters))
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
        adjustments = self._inclusive_adjustments(domain) if self.env.context.get('_baseer_pl_inclusive') else {}
        for line in selected:
            debit, credit = self._decimal(line.debit), self._decimal(line.credit)
            raw = credit - debit if income else debit - credit
            display = raw + adjustments.get(line, Decimal('0'))
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
