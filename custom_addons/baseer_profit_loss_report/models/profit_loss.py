"""Read-only, posted P&L in the company's currency."""

from collections import Counter
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain


SECTION_KEYS = (
    'income', 'income_other', 'expense_direct_cost',
    'expense', 'expense_depreciation',
)
EXPENSE_KEYS = frozenset(('expense_direct_cost', 'expense', 'expense_depreciation'))


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
        return f'{rounded:.{int(currency.decimal_places)}f}'

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
            'journals': [{'id': item.id, 'code': item.code, 'name': item.name}
                         for item in journals],
            'currency_code': currency.name,
            'currency_symbol': currency.symbol or currency.name,
            'currency_digits': int(currency.decimal_places),
        }

    @api.model
    def _filters(self, filters):
        self._check_accounting_access()
        if not isinstance(filters, dict):
            raise ValidationError(_('Select a company and a period.'))
        company = self._company(filters.get('company_id'))
        try:
            start = fields.Date.to_date(filters.get('date_from'))
            end = fields.Date.to_date(filters.get('date_to'))
        except (TypeError, ValueError):
            raise ValidationError(_('Select valid start and end dates.')) from None
        if not start or not end or start > end or (end - start).days >= 366:
            raise ValidationError(_('Select a period of no more than 366 days.'))
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
        domain = (Domain('company_id', '=', company.id)
                  & Domain('parent_state', '=', 'posted')
                  & Domain('date', '>=', start)
                  & Domain('date', '<=', end)
                  & Domain('account_id.account_type', 'in', list(SECTION_KEYS)))
        if journal_ids:
            domain &= Domain('journal_id', 'in', journal_ids)
        return company, start, end, journal_ids, domain

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
    def get_report(self, filters):
        company, start, end, journal_ids, domain = self._filters(filters)
        grouped = self._section_rows(domain)
        raw_totals = {key: sum((row['raw'] for row in grouped[key]), Decimal('0'))
                      for key in SECTION_KEYS}
        gross = raw_totals['income'] - raw_totals['expense_direct_cost']
        net = (gross + raw_totals['income_other'] - raw_totals['expense']
               - raw_totals['expense_depreciation'])
        currency = company.currency_id
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
            'period': {'date_from': fields.Date.to_string(start),
                       'date_to': fields.Date.to_string(end)},
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
        company, _start, _end, _journal_ids, domain = self._filters(filters)
        grouped = self._section_rows(domain)[section]
        grouped.sort(key=lambda row: (row['account'].code or '', row['account'].id))
        total = sum((row['raw'] for row in grouped), Decimal('0'))
        start = (page - 1) * self.PAGE_SIZE
        selected = grouped[start:start + self.PAGE_SIZE]
        currency = company.currency_id
        accounts = []
        for row in selected:
            account = row['account']
            display = -row['raw'] if section in EXPENSE_KEYS else row['raw']
            accounts.append({
                'id': account.id, 'code': account.code or '',
                'name': account.name or '',
                'amount': self._format_money(display, currency),
                'negative': display < 0,
                'move_line_count': row['count'],
            })
        display_total = -total if section in EXPENSE_KEYS else total
        return {
            'section': section, 'page': page, 'page_size': self.PAGE_SIZE,
            'total_count': len(grouped),
            'total_amount': self._format_money(display_total, currency),
            'accounts': accounts,
        }

    @api.model
    def get_lines(self, filters, account_id, page=1):
        """Return a guarded page of source AMLs; every linked move remains readable."""
        if type(account_id) is not int or account_id <= 0:
            raise ValidationError(_('Select a profit and loss account.'))
        if type(page) is not int or page < 1:
            raise ValidationError(_('Select a valid page.'))
        company, _start, _end, _journal_ids, domain = self._filters(filters)
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
            display = raw if income else -raw
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
        display_total = total if income else -total
        return {
            'account_id': account.id, 'page': page,
            'page_size': self.PAGE_SIZE,
            'total_count': count,
            'total_amount': self._format_money(display_total, currency),
            'lines': rows,
        }

    @api.model
    def get_source_line(self, filters, line_id):
        """Recheck one source immediately before opening its AML form."""
        if type(line_id) is not int or line_id <= 0:
            raise ValidationError(_('Select a source entry.'))
        _company, _start, _end, _journal_ids, domain = self._filters(filters)
        line = self.env['account.move.line'].with_context(active_test=False).search(
            domain & Domain('id', '=', line_id), limit=1,
        )
        if not line:
            raise AccessError(_('The source entry is not available.'))
        self._verify_links(line)
        return {'line_id': line.id, 'move_id': line.move_id.id}
