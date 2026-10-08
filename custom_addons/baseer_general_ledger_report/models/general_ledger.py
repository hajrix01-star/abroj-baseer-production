"""Read-only all-account general ledger from posted Odoo journal items."""

from collections import Counter
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain


class BaseerGeneralLedger(models.AbstractModel):
    _name = 'baseer.general.ledger.report'
    _description = 'Baseer Posted General Ledger'

    PAGE_SIZE = 100
    SECURITY_BATCH = 5000
    AGGREGATE_BATCH = 1000

    @staticmethod
    def _decimal(value):
        return Decimal(str(value or 0))

    @classmethod
    def _money(cls, value, currency):
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
        for model in ('res.company', 'account.journal', 'account.account',
                      'account.move', 'account.move.line'):
            self.env[model].browse().check_access('read')

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
    def _assert_complete_source(self, company, end, journal_ids):
        """Fail closed when AML record rules hide even a balanced posted move.

        SQL reads only a scoped row count, never journal amounts or source rows.
        All report values continue to come from access-controlled ORM reads.
        """
        domain = (Domain('company_id', '=', company.id)
                  & Domain('parent_state', '=', 'posted')
                  & Domain('date', '<=', end))
        query = ("SELECT COUNT(*) FROM account_move_line "
                 "WHERE company_id = %s AND parent_state = 'posted' AND date <= %s")
        params = [company.id, end]
        if journal_ids:
            domain &= Domain('journal_id', 'in', journal_ids)
            query += ' AND journal_id = ANY(%s)'
            params.append(journal_ids)
        AML = self.env['account.move.line'].with_context(active_test=False)
        AML.flush_model(['company_id', 'parent_state', 'date', 'journal_id'])
        readable_count = AML.search_count(domain)
        self.env.cr.execute(query, params)
        if readable_count != self.env.cr.fetchone()[0]:
            raise AccessError(_(
                'The complete posted journal source is not available for this report.'
            ))

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
        fiscal = company.compute_fiscalyear_dates(today)
        first = max(first, fiscal['date_from'])
        last = min(last, fiscal['date_to'])
        return {
            'companies': [{'id': row.id, 'name': row.display_name} for row in companies],
            'journals': [{'id': row.id, 'code': row.code, 'name': row.name}
                         for row in journals],
            'default_company_id': company.id,
            'default_date_from': fields.Date.to_string(first),
            'default_date_to': fields.Date.to_string(last),
        }

    @api.model
    def _filters(self, filters):
        self._check_accounting_access()
        if not isinstance(filters, dict) or set(filters) - {
            'company_id', 'date_from', 'date_to', 'journal_ids',
        }:
            raise ValidationError(_('Select a company and a period.'))
        company = self._company(filters.get('company_id'))
        try:
            start = fields.Date.to_date(filters.get('date_from'))
            end = fields.Date.to_date(filters.get('date_to'))
        except (TypeError, ValueError):
            raise ValidationError(_('Select valid start and end dates.')) from None
        if not start or not end or start > end:
            raise ValidationError(_('Select a valid period.'))
        fiscal = company.compute_fiscalyear_dates(start)
        if end > fiscal['date_to']:
            raise ValidationError(_('The period must stay within one fiscal year.'))
        journal_ids = filters.get('journal_ids', [])
        if (not isinstance(journal_ids, list) or len(journal_ids) > 100
                or any(type(item) is not int or item <= 0 for item in journal_ids)
                or len(journal_ids) != len(set(journal_ids))):
            raise ValidationError(_('Select valid journals.'))
        journals = self.env['account.journal'].with_context(active_test=False).browse(journal_ids)
        if len(journals.exists()) != len(journal_ids):
            raise AccessError(_('The selected journals are not available.'))
        journals.check_access('read')
        if any(row.company_id != company for row in journals):
            raise AccessError(_('The selected journals must belong to the report company.'))
        base = (Domain('company_id', '=', company.id)
                & Domain('parent_state', '=', 'posted'))
        if journal_ids:
            base &= Domain('journal_id', 'in', journal_ids)
        self._assert_complete_source(company, end, journal_ids)
        return company, start, end, fiscal['date_from'], journal_ids, base

    @api.model
    def _verify_links(self, lines):
        lines.check_access('read')
        lines.fetch(['company_id', 'move_id', 'account_id', 'journal_id'])
        lines.mapped('move_id').check_access('read')
        lines.mapped('account_id').check_access('read')
        lines.mapped('journal_id').check_access('read')

    @staticmethod
    def _merge_verified_batch(totals, verified_counts, grouped):
        grouped_counts = Counter()
        for account_id, _debit, _credit, count in grouped:
            grouped_counts[account_id] += count
        if grouped_counts != verified_counts:
            raise AccessError(_('The report source changed while reading. Retry.'))
        with localcontext() as context:
            context.prec = 60
            for account_id, debit, credit, count in grouped:
                item = totals.setdefault(account_id, {
                    'debit': Decimal('0'), 'credit': Decimal('0'), 'count': 0,
                })
                item['debit'] += Decimal(debit)
                item['credit'] += Decimal(credit)
                item['count'] += count

    @api.model
    def _group_verified(self, domain):
        """Sum exact NUMERIC values only for each ORM-verified AML batch.

        Odoo's NUMERIC-to-float converter can lose cents on a large SQL SUM.
        SQL therefore receives only IDs already permitted by the ORM, and
        returns decimal text. The record-rule search, link checks, and SQL
        share one transaction snapshot; no writes or commits occur between them.
        """
        AML = self.env['account.move.line'].with_context(
            active_test=False, prefetch_fields=False,
        )
        amount_fields = {'account_id', 'debit', 'credit'}
        if amount_fields - AML.fields_get(list(amount_fields)).keys():
            raise AccessError(_('The report amount fields are not available.'))
        AML.flush_model([
            'company_id', 'parent_state', 'date', 'journal_id',
            'account_id', 'debit', 'credit',
        ])
        totals = {}
        cursor = 0
        while True:
            lines = AML.search(domain & Domain('id', '>', cursor),
                               order='id', limit=self.SECURITY_BATCH)
            if not lines:
                break
            self._verify_links(lines)
            window_counts = Counter(line.account_id.id for line in lines)
            chunks = []
            recombined_counts = Counter()
            for offset in range(0, len(lines), self.AGGREGATE_BATCH):
                chunk = lines[offset:offset + self.AGGREGATE_BATCH]
                counts = Counter(line.account_id.id for line in chunk)
                chunks.append((chunk, counts))
                recombined_counts.update(counts)
            if recombined_counts != window_counts:
                raise AccessError(_('The report source changed while reading. Retry.'))
            for chunk, counts in chunks:
                self.env.cr.execute(
                    "SELECT account_id, SUM(debit)::text, SUM(credit)::text, COUNT(*) "
                    "FROM account_move_line WHERE id = ANY(%s) GROUP BY account_id",
                    [chunk.ids],
                )
                self._merge_verified_batch(totals, counts, self.env.cr.fetchall())
            cursor = lines[-1].id
            if len(lines) < self.SECURITY_BATCH:
                break
        return totals

    @staticmethod
    def _balance(groups, account_id):
        item = groups.get(account_id)
        return item['debit'] - item['credit'] if item else Decimal('0')

    @api.model
    def _accounts(self, ids, company):
        if not ids:
            return {}
        records = self.env['account.account'].with_context(active_test=False).browse(list(ids)).exists()
        if len(records) != len(ids):
            raise AccessError(_('The report source changed while reading. Retry.'))
        records.check_access('read')
        if any(company not in account.company_ids for account in records):
            raise AccessError(_('The report contains an account outside the company.'))
        return {row.id: row for row in records}

    @api.model
    def _snapshot(self, filters):
        company, start, end, fiscal_start, journal_ids, base = self._filters(filters)
        prior = self._group_verified(base & Domain('date', '<', fiscal_start))
        current_open = self._group_verified(
            base & Domain('date', '>=', fiscal_start) & Domain('date', '<', start),
        )
        period = self._group_verified(
            base & Domain('date', '>=', start) & Domain('date', '<=', end),
        )
        accounts = self._accounts(set(prior) | set(current_open) | set(period), company)
        return company, start, end, fiscal_start, journal_ids, prior, current_open, period, accounts

    @api.model
    def get_report(self, filters, page=1):
        if type(page) is not int or page < 1:
            raise ValidationError(_('Select a valid page.'))
        (company, start, end, fiscal_start, journal_ids, prior,
         current_open, period, accounts) = self._snapshot(filters)
        currency = company.currency_id
        rbf = Decimal('0')
        rbf_count = 0
        rows = []
        total_opening = total_debit = total_credit = Decimal('0')
        for account in accounts.values():
            old = self._balance(prior, account.id)
            year = self._balance(current_open, account.id)
            entry = period.get(account.id, {})
            debit = entry.get('debit', Decimal('0'))
            credit = entry.get('credit', Decimal('0'))
            if account.include_initial_balance:
                opening = old + year
            else:
                opening = year
                rbf += old
                rbf_count += prior.get(account.id, {}).get('count', 0)
            closing = opening + debit - credit
            total_opening += opening
            total_debit += debit
            total_credit += credit
            rows.append({
                'id': account.id, 'code': account.code or '',
                'name': account.name or '',
                'opening': self._money(opening, currency),
                'debit': self._money(debit, currency),
                'credit': self._money(credit, currency),
                'closing': self._money(closing, currency),
                'opening_negative': opening < 0,
                'closing_negative': closing < 0,
                'period_line_count': entry.get('count', 0),
                'opening_source_count': current_open.get(account.id, {}).get('count', 0)
                + (prior.get(account.id, {}).get('count', 0)
                   if account.include_initial_balance else 0),
            })
        rows.sort(key=lambda row: (row['code'], row['id']))
        count = len(rows)
        selected = rows[(page - 1) * self.PAGE_SIZE:page * self.PAGE_SIZE]
        total_opening += rbf
        total_closing = total_opening + total_debit - total_credit
        zero = self._money(Decimal('0'), currency)
        if (self._money(total_opening, currency) != zero
                or self._money(total_debit - total_credit, currency) != zero
                or self._money(total_closing, currency) != zero):
            raise AccessError(_(
                'The readable journal items do not form a balanced ledger. '
                'Check source access rights and accounting entries.'
            ))
        self._assert_complete_source(company, end, journal_ids)
        return {
            'company': {'id': company.id, 'name': company.display_name,
                        'currency_code': currency.name},
            'period': {'date_from': fields.Date.to_string(start),
                       'date_to': fields.Date.to_string(end),
                       'fiscal_start': fields.Date.to_string(fiscal_start)},
            'is_partial_journals': bool(journal_ids),
            'page': page, 'page_size': self.PAGE_SIZE, 'account_count': count,
            'page_count': (count + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
            'accounts': selected,
            'rbf': {'amount': self._money(rbf, currency), 'negative': rbf < 0,
                    'source_line_count': rbf_count},
            'total': {
                'opening': self._money(total_opening, currency),
                'debit': self._money(total_debit, currency),
                'credit': self._money(total_credit, currency),
                'closing': self._money(total_closing, currency),
                'opening_negative': total_opening < 0,
                'closing_negative': total_closing < 0,
            },
        }

    @api.model
    def get_rbf_accounts(self, filters, page=1):
        if type(page) is not int or page < 1:
            raise ValidationError(_('Select a valid page.'))
        company, _start, end, fiscal_start, journal_ids, base = self._filters(filters)
        groups = self._group_verified(base & Domain('date', '<', fiscal_start))
        accounts = self._accounts(set(groups), company)
        currency = company.currency_id
        rows = []
        for account in accounts.values():
            if account.include_initial_balance:
                continue
            amount = self._balance(groups, account.id)
            rows.append({'id': account.id, 'code': account.code or '',
                         'name': account.name or '',
                         'amount': self._money(amount, currency),
                         'negative': amount < 0,
                         'source_line_count': groups[account.id]['count']})
        rows.sort(key=lambda row: (row['code'], row['id']))
        self._assert_complete_source(company, end, journal_ids)
        return {'page': page, 'page_size': self.PAGE_SIZE,
                'account_count': len(rows),
                'accounts': rows[(page - 1) * self.PAGE_SIZE:page * self.PAGE_SIZE]}

    @api.model
    def _line_domain(self, filters, account_id, scope):
        if type(account_id) is not int or account_id <= 0 or scope not in ('period', 'rbf'):
            raise ValidationError(_('Select a valid account and source.'))
        company, start, end, fiscal_start, _journals, base = self._filters(filters)
        account = self._accounts({account_id}, company).get(account_id)
        if scope == 'rbf':
            if account.include_initial_balance:
                raise AccessError(_('This account is not part of the brought-forward result.'))
            domain = base & Domain('date', '<', fiscal_start)
        else:
            domain = base & Domain('date', '>=', start) & Domain('date', '<=', end)
        return company, account, domain & Domain('account_id', '=', account.id)

    @api.model
    def get_lines(self, filters, account_id, scope='period',
                  cursor_date=None, cursor_id=None):
        company, account, domain = self._line_domain(filters, account_id, scope)
        _company, start, end, fiscal_start, journal_ids, base = self._filters(filters)
        account_base = base & Domain('account_id', '=', account.id)
        opening = Decimal('0')
        if scope == 'period':
            opening_from = None if account.include_initial_balance else fiscal_start
            opening_domain = account_base & Domain('date', '<', start)
            if opening_from:
                opening_domain &= Domain('date', '>=', opening_from)
            opening = self._balance(self._group_verified(opening_domain), account.id)
        if (cursor_date is None) != (cursor_id is None):
            raise ValidationError(_('The page cursor is incomplete.'))
        AML = self.env['account.move.line'].with_context(active_test=False)
        after = domain
        if cursor_date is not None:
            try:
                cursor_day = fields.Date.to_date(cursor_date)
            except (TypeError, ValueError):
                raise ValidationError(_('The page cursor date is invalid.')) from None
            if type(cursor_id) is not int or cursor_id <= 0 or not cursor_day:
                raise ValidationError(_('The page cursor is invalid.'))
            cursor = AML.search(domain & Domain('id', '=', cursor_id)
                                & Domain('date', '=', cursor_day), limit=1)
            if not cursor:
                raise AccessError(_('The page cursor is not part of this report.'))
            self._verify_links(cursor)
            before = (Domain('date', '<', cursor_day)
                      | (Domain('date', '=', cursor_day) & Domain('id', '<=', cursor_id)))
            opening += self._balance(self._group_verified(domain & before), account.id)
            after &= (Domain('date', '>', cursor_day)
                      | (Domain('date', '=', cursor_day) & Domain('id', '>', cursor_id)))
        page = AML.search(after, order='date asc, id asc', limit=self.PAGE_SIZE + 1)
        self._verify_links(page)
        lines = page[:self.PAGE_SIZE]
        has_more = len(page) > self.PAGE_SIZE
        currency = company.currency_id
        entries = []
        running = opening
        for line in lines:
            running += self._decimal(line.debit) - self._decimal(line.credit)
            entries.append({
                'id': line.id, 'date': fields.Date.to_string(line.date),
                'move_id': line.move_id.id, 'move_name': line.move_id.name or '',
                'label': line.name or '',
                'debit': self._money(self._decimal(line.debit), currency),
                'credit': self._money(self._decimal(line.credit), currency),
                'running': self._money(running, currency),
                'running_negative': running < 0,
            })
        last = lines[-1] if has_more else None
        self._assert_complete_source(company, end, journal_ids)
        return {'account_id': account.id, 'scope': scope,
                'account_name': account.display_name, 'lines': entries,
                'next_cursor': {'date': fields.Date.to_string(last.date),
                                'id': last.id} if last else None}

    @api.model
    def get_account_action(self, filters, account_id, scope='period'):
        """Open the verified account source in Odoo's paginated Journal Items view."""
        _company, start, end, fiscal_start, journal_ids, base = self._filters(filters)
        if scope == 'opening':
            if type(account_id) is not int or account_id <= 0:
                raise ValidationError(_('Select a valid account and source.'))
            company = _company
            account = self._accounts({account_id}, company)[account_id]
            domain = (base & Domain('account_id', '=', account.id)
                      & Domain('date', '<', start))
            if not account.include_initial_balance:
                domain &= Domain('date', '>=', fiscal_start)
        else:
            company, account, domain = self._line_domain(filters, account_id, scope)
        source_scope = scope
        if account.id not in self._group_verified(domain):
            if scope != 'period':
                raise AccessError(_('The selected account is not available for this period.'))
            opening_domain = (base & Domain('account_id', '=', account.id)
                              & Domain('date', '<', start))
            if not account.include_initial_balance:
                opening_domain &= Domain('date', '>=', fiscal_start)
            if account.id not in self._group_verified(opening_domain):
                raise AccessError(_('The selected account has no visible source entries.'))
            source_scope = 'opening'
        action_domain = [
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
            ('account_id', '=', account.id),
        ]
        if source_scope == 'rbf':
            action_domain.append(('date', '<', fields.Date.to_string(fiscal_start)))
        elif source_scope == 'opening':
            action_domain.append(('date', '<', fields.Date.to_string(start)))
            if not account.include_initial_balance:
                action_domain.append(('date', '>=', fields.Date.to_string(fiscal_start)))
        else:
            action_domain.extend((
                ('date', '>=', fields.Date.to_string(start)),
                ('date', '<=', fields.Date.to_string(end)),
            ))
        if journal_ids:
            action_domain.append(('journal_id', 'in', journal_ids))
        self._assert_complete_source(company, end, journal_ids)
        return {
            'type': 'ir.actions.act_window',
            'name': (_('Opening Balance Journal Items') if source_scope == 'opening'
                     else _('Journal Items')),
            'res_model': 'account.move.line',
            'views': [[False, 'list'], [False, 'form']], 'target': 'current',
            'domain': action_domain,
        }

    @api.model
    def get_source_line(self, filters, line_id, scope='period'):
        if type(line_id) is not int or line_id <= 0:
            raise ValidationError(_('Select a valid source entry.'))
        company, start, end, fiscal_start, journal_ids, base = self._filters(filters)
        if scope not in ('period', 'rbf'):
            raise ValidationError(_('Select a valid source.'))
        domain = base & Domain('id', '=', line_id)
        if scope == 'rbf':
            domain &= Domain('date', '<', fiscal_start)
        else:
            domain &= Domain('date', '>=', start) & Domain('date', '<=', end)
        line = self.env['account.move.line'].with_context(active_test=False).search(
            domain, limit=1,
        )
        if not line:
            raise AccessError(_('The source entry is not available.'))
        self._verify_links(line)
        if company not in line.account_id.company_ids:
            raise AccessError(_('The source account is not available.'))
        if scope == 'rbf' and line.account_id.include_initial_balance:
            raise AccessError(_('The source entry is not part of the brought-forward result.'))
        self._assert_complete_source(company, end, journal_ids)
        return {'line_id': line.id, 'move_id': line.move_id.id}
