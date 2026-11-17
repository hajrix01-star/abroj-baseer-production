"""Direct cash flow from liquidity movements and their reconciled counterparts.

Liquidity comprises cash-type accounts and bank/cash journal default and payment
method accounts, excluding suspense and configured excluded accounts. Set
baseer_report_engine.cash_flow_excluded_accounts to comma/space separated codes
or IDs. The journal filter applies to the liquidity
journal items. Each move's net cash effect is allocated by absolute counterpart
balance; reconciled receivable/payable portions are allocated by absolute
invoice line balance (including taxes), with the remainder treated as advances. Only
reconciliations dated on or before the period end are followed.
Beginning is TB(start - 1) plus liquidity on opening entries dated in the
period; opening moves include company and configured moves, moves named or
referenced with Opening or افتتاح, and moves with both liquidity and an
equity_unaffected line. Detection is bulk and restricted to selected companies.
Closing is TB(end). Opening and closing use the same conversion dates
as the account grid. A
rounding/exotic-move residual is assigned to unclassified cash flows so the
statement reconciles to liquidity balances for every period.
"""
from collections import defaultdict
from decimal import Decimal
import re

from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL

from .engine import _analytic_share, _fill_variation, _quantize


class BaseerCashFlow(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    @api.model
    def _cash_opening_moves(self):
        tokens = re.split(r'[,\s]+', self.env['ir.config_parameter'].sudo().get_param(
            'baseer_report_engine.cash_flow_opening_moves', '').strip())
        tokens = [token for token in tokens if token]
        domain = [('company_id', 'in', self.env.companies.ids)]
        names = self.env['account.move'].search(domain + [('name', 'in', tokens)]) if tokens else self.env['account.move']
        ids = [int(token) for token in tokens if token.isdecimal()]
        numbered = self.env['account.move'].search(domain + [('id', 'in', ids)]) if ids else self.env['account.move']
        matched = set(names.mapped('name')) | {str(move.id) for move in numbered}
        return (self.env.companies.mapped('account_opening_move_id') | names | numbered), [token for token in tokens if token not in matched]

    @api.model
    def _cash_flow_spec(self):
        return [
            ('beginning', _('Cash and cash equivalents, beginning of period'), 0, 'section', True),
            ('net', _('Net increase in cash and cash equivalents'), 0, 'section', False),
            ('operating', _('Cash flows from operating activities'), 2, 'line', False),
            ('advance_received', _('Advance Payments received from customers'), 4, 'line', True),
            ('operating_in', _('Cash received from operating activities'), 4, 'line', True),
            ('advance_paid', _('Advance payments made to suppliers'), 4, 'line', True),
            ('operating_out', _('Cash paid for operating activities'), 4, 'line', True),
            ('investing', _('Cash flows from investing & extraordinary activities'), 2, 'line', False),
            ('investing_in', _('Cash in'), 4, 'line', True), ('investing_out', _('Cash out'), 4, 'line', True),
            ('financing', _('Cash flows from financing activities'), 2, 'line', False),
            ('financing_in', _('Cash in'), 4, 'line', True), ('financing_out', _('Cash out'), 4, 'line', True),
            ('unclassified', _('Cash flows from unclassified activities'), 2, 'line', False),
            ('unclassified_in', _('Cash in'), 4, 'line', True), ('unclassified_out', _('Cash out'), 4, 'line', True),
            ('closing', _('Cash and cash equivalents, closing balance'), 0, 'section', True),
        ]

    @api.model
    def _cash_excluded_accounts(self):
        tokens = [s for s in re.split(r'[,\s]+', self.env['ir.config_parameter'].sudo().get_param(
            'baseer_report_engine.cash_flow_excluded_accounts', '').strip()) if s]
        accounts = self.env['account.account'].with_context(active_test=False)
        ids = [int(s) for s in tokens if s.isdecimal()]
        result = accounts.browse()
        for company in self.env.companies:
            result |= accounts.with_company(company).search([
                ('company_ids', 'in', company.id), '|', ('code', 'in', tokens), ('id', 'in', ids)])
        return result

    @api.model
    def _cash_liquidity_accounts(self):
        accounts = self.env['account.account'].with_context(active_test=False).search([
            ('company_ids', 'in', self.env.companies.ids), ('account_type', '=', 'asset_cash')])
        journals = self.env['account.journal'].search([('company_id', 'in', self.env.companies.ids), ('type', 'in', ('bank', 'cash'))])
        for journal in journals:
            accounts |= journal.default_account_id - journal.suspense_account_id
            methods = journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids
            accounts |= methods.mapped('payment_account_id') - journal.suspense_account_id
            # Odoo falls back to chart-default outstanding accounts when a
            # payment method has no explicit account.
            chart = self.env['account.chart.template'].with_context(allowed_company_ids=journal.company_id.root_id.ids)
            for method_lines, ref in (
                (journal.inbound_payment_method_line_ids, 'account_journal_payment_debit_account_id'),
                (journal.outbound_payment_method_line_ids, 'account_journal_payment_credit_account_id'),
            ):
                if any(not line.payment_account_id for line in method_lines):
                    default = chart.ref(ref, raise_if_not_found=False)
                    if default and default != journal.suspense_account_id:
                        accounts |= default
        return accounts - self._cash_excluded_accounts()

    @api.model
    def _cash_flow_data(self, options, columns):
        self.env.flush_all()
        liquidity = self._cash_liquidity_accounts()
        liquidity_ids = tuple(liquidity.ids)
        result = {c['key']: (defaultdict(Decimal), defaultdict(lambda: defaultdict(Decimal)), defaultdict(set)) for c in columns}
        if not liquidity_ids:
            return result
        model = self.env['account.move.line']
        domain = self._base_domain(options) + [('account_id', 'in', list(liquidity_ids))]
        source = model._search(domain + [('date', '<=', max(c['_end'] for c in columns))]).select(
            SQL('account_move_line.id'), SQL('account_move_line.move_id'), SQL('account_move_line.date'),
            SQL('account_move_line.account_id'), SQL('account_move_line.company_id'), SQL('account_move_line.balance'),
            SQL('account_move_line.analytic_distribution'))
        opening, _unknown = self._cash_opening_moves()
        # Determine flags from all period candidates, including zero-net moves.
        period_source = model._search(domain + [('date', '>=', min(c['_start'] for c in columns)),
                                              ('date', '<=', max(c['_end'] for c in columns))]).select(SQL('account_move_line.move_id'))
        self.env.cr.execute(SQL("""SELECT m.id FROM account_move m WHERE m.id IN (%s) AND
            (m.id IN %s OR m.name ILIKE '%%Opening%%' OR m.ref ILIKE '%%Opening%%'
             OR m.name ILIKE '%%افتتاح%%' OR m.ref ILIKE '%%افتتاح%%' OR EXISTS
             (SELECT 1 FROM account_move_line l JOIN account_account a ON a.id=l.account_id
              WHERE l.move_id=m.id AND a.account_type='equity_unaffected'))""", period_source, tuple(opening.ids) or (0,)))
        opening_ids = tuple(row[0] for row in self.env.cr.fetchall())
        companies = {company.id: company for company in self.env.companies}
        if options['analytic_account_ids']:
            self.env.cr.execute(SQL('SELECT account_id, company_id, date, move_id, balance, analytic_distribution FROM (%s) cash', source))
            selected = set(options['analytic_account_ids'])
            opening_set = set(opening_ids)
            for account_id, company_id, date, move_id, balance, distribution in self.env.cr.fetchall():
                share = _analytic_share(distribution, selected)
                if not share:
                    continue
                company = companies[company_id]
                amount = Decimal(str(balance or 0)) * share
                for c in columns:
                    details = result[c['key']][1]
                    key = (account_id, company_id)
                    if date < c['_start']:
                        details['beginning'][key] += self._convert(amount, company, c['_start'])
                    if date <= c['_end']:
                        details['closing'][key] += self._convert(amount, company, c['_end'])
                    if c['_start'] <= date <= c['_end'] and move_id in opening_set:
                        details['beginning'][key] += self._convert(amount, company, c['_end'])
        else:
            cases = []
            for c in columns:
                cases.extend([SQL('SUM(balance) FILTER (WHERE date < %s)', c['_start']),
                              SQL('SUM(balance) FILTER (WHERE date <= %s)', c['_end']),
                              SQL('SUM(balance) FILTER (WHERE date >= %s AND date <= %s AND move_id IN %s)',
                                  c['_start'], c['_end'], opening_ids or (0,))])
            self.env.cr.execute(SQL('SELECT account_id, company_id, %s FROM (%s) cash GROUP BY account_id, company_id', SQL(', ').join(cases), source))
            for row in self.env.cr.fetchall():
                account_id, company_id = row[:2]
                company = companies[company_id]
                for i, c in enumerate(columns):
                    beginning, closing, opening_balance = row[2 + i * 3:5 + i * 3]
                    details = result[c['key']][1]
                    if beginning is not None:
                        details['beginning'][(account_id, company_id)] += self._convert(beginning, company, c['_start'])
                    if closing is not None:
                        details['closing'][(account_id, company_id)] += self._convert(closing, company, c['_end'])
                    if opening_balance is not None:
                        details['beginning'][(account_id, company_id)] += self._convert(opening_balance, company, c['_end'])
        self.env.cr.execute(SQL('SELECT move_id, date, company_id, SUM(balance) FROM (%s) cash WHERE move_id NOT IN %s GROUP BY move_id, date, company_id HAVING SUM(balance) <> 0 ORDER BY move_id', model._search(domain + [('date', '>=', min(c['_start'] for c in columns)), ('date', '<=', max(c['_end'] for c in columns))]).select(SQL('account_move_line.move_id'), SQL('account_move_line.date'), SQL('account_move_line.company_id'), SQL('account_move_line.balance')), opening_ids or (0,)))
        cash_moves = self.env.cr.fetchall()
        move_ids = tuple(row[0] for row in cash_moves)
        by_move = defaultdict(list)
        counterpart_ids = []
        account_ids = set()
        if move_ids:
            self.env.cr.execute(SQL("""SELECT l.id, l.move_id, l.account_id, a.account_type, l.balance, l.company_id
                FROM account_move_line l JOIN account_account a ON a.id=l.account_id
                WHERE l.move_id IN %s AND l.account_id NOT IN %s ORDER BY l.id""", move_ids, liquidity_ids))
            for line_id, move_id, account_id, account_type, balance, company_id in self.env.cr.fetchall():
                by_move[move_id].append((line_id, account_id, account_type, Decimal(str(balance)), company_id))
                account_ids.add(account_id)
                if account_type in ('asset_receivable', 'liability_payable'):
                    counterpart_ids.append(line_id)
        partials_by_line = defaultdict(list)
        other_move_ids = set()
        if counterpart_ids:
            self.env.cr.execute(SQL("""SELECT p.debit_move_id, p.credit_move_id, p.max_date, p.amount,
                d.move_id, d.company_id, c.move_id, c.company_id FROM account_partial_reconcile p
                JOIN account_move_line d ON d.id=p.debit_move_id JOIN account_move_line c ON c.id=p.credit_move_id
                WHERE p.max_date <= %s AND (p.debit_move_id IN %s OR p.credit_move_id IN %s) ORDER BY p.id""",
                max(c['_end'] for c in columns), tuple(counterpart_ids), tuple(counterpart_ids)))
            counterpart_set = set(counterpart_ids)
            for debit, credit, date, amount, dm, dc, cm, cc in self.env.cr.fetchall():
                for line, other_move, other_company in ((debit, cm, cc), (credit, dm, dc)):
                    if line in counterpart_set:
                        partials_by_line[line].append((date, Decimal(str(amount)), other_move, other_company))
                        other_move_ids.add(other_move)
        invoice_by_move = defaultdict(list)
        if other_move_ids:
            self.env.cr.execute(SQL("""SELECT l.move_id, l.account_id, l.balance FROM account_move_line l
                JOIN account_account a ON a.id=l.account_id WHERE l.move_id IN %s AND l.account_id NOT IN %s
                AND a.account_type NOT IN ('asset_receivable', 'liability_payable') ORDER BY l.id""", tuple(other_move_ids), liquidity_ids))
            for move_id, account_id, balance in self.env.cr.fetchall():
                invoice_by_move[move_id].append((account_id, abs(Decimal(str(balance)))))
                account_ids.add(account_id)
        tags = {kind: self.env.ref('account.account_tag_' + kind).id for kind in ('operating', 'investing', 'financing')}
        membership = defaultdict(set)
        if account_ids:
            self.env.cr.execute(SQL('SELECT account_account_id, account_account_tag_id FROM account_account_account_tag WHERE account_account_id IN %s', tuple(account_ids)))
            for account_id, tag_id in self.env.cr.fetchall():
                membership[account_id].add(tag_id)
        kinds = {account_id: next ( (kind for kind, tag in tags.items() if tag in membership[account_id]), 'unclassified') for account_id in account_ids}
        rates = {}
        for c in columns:
            amounts, details, moves = result[c['key']]
            def add(code, account_id, company_id, value, move_id):
                key = (account_id, company_id)
                details[code][key] += value
                moves[(code, key)].add(move_id)
                moves[(code, None)].add(move_id)
            def classify(account_id, value, company_id, move_id):
                add(kinds[account_id] + ('_in' if value >= 0 else '_out'), account_id, company_id, value, move_id)
            for move_id, date, company_id, balance in cash_moves:
                if not c['_start'] <= date <= c['_end']:
                    continue
                lines = by_move[move_id]
                denominator = sum((abs(line[3]) for line in lines), Decimal(0))
                if not denominator:
                    continue
                rate_key = (company_id, c['_end'])
                if rate_key not in rates:
                    rates[rate_key] = self._ledger_convert(Decimal(1), companies[company_id], c['_end'])
                for line_id, account_id, account_type, balance_line, _company_id in lines:
                    share = Decimal(str(balance)) * abs(balance_line) / denominator
                    converted = (self._ledger_convert(share, companies[company_id], c['_end'])
                                 if companies[company_id].currency_id == self.env.company.currency_id
                                 else share * rates[rate_key])
                    if account_type not in ('asset_receivable', 'liability_payable'):
                        classify(account_id, converted, company_id, move_id)
                        continue
                    available = remaining = abs(balance_line)
                    for partial_date, amount, other_move, other_company in partials_by_line[line_id]:
                        if partial_date > c['_end'] or other_move == move_id or other_company != company_id:
                            continue
                        paid = min(remaining, amount)
                        items = invoice_by_move[other_move]
                        total = sum((item[1] for item in items), Decimal(0))
                        if not paid or not total:
                            continue
                        for item_account, item_balance in items:
                            classify(item_account, converted * paid / available * item_balance / total, company_id, move_id)
                        remaining -= paid
                    if remaining and available:
                        add('advance_received' if account_type == 'asset_receivable' else 'advance_paid', account_id, company_id, converted * remaining / available, move_id)
            currency = self.env.company.currency_id
            for code, rows in details.items():
                for key, value in list(rows.items()):
                    rows[key] = _quantize(value, currency)
                amounts[code] = sum(rows.values(), Decimal(0))
            net = amounts['closing'] - amounts['beginning']
            leaf_codes = [x[0] for x in self._cash_flow_spec() if x[4] and x[0] not in ('beginning', 'closing')]
            residual = net - sum((amounts[code] for code in leaf_codes), Decimal(0))
            if residual:
                code = 'unclassified_in' if residual > 0 else 'unclassified_out'
                details[code][(0, 0)] += residual
                amounts[code] += residual
            amounts['net'] = net
        return result

    @api.model
    def _cash_flow_compute(self, report, options):
        data = self._cash_flow_data(options, [c for c in options['columns'] if c['kind'] == 'period'])
        return data

    @api.model
    def _cash_flow_rows(self, options, code, data):
        currency = self.env.company.currency_id
        keys = set().union(*(set(d[1][code]) for d in data.values()))
        rows = []
        for account_id, company_id in sorted(keys):
            company = self.env['res.company'].browse(company_id)
            account = self.env['account.account'].with_company(company).browse(account_id) if account_id else False
            values = {key: d[1][code].get((account_id, company_id), Decimal(0)) for key, d in data.items()}
            _fill_variation(values, options['columns'])
            rows.append({'id': account_id, 'company_id': company_id, 'company_name': company.name if company else '',
                         'code': (account.code or '') if account else '', 'name': (account.name or '') if account else _('Exchange difference / rounding'),
                         'amounts': [self._serialize_amount(c, values.get(c['key']), currency, bool(account) and c['kind'] == 'period') for c in options['columns']]})
        return sorted(rows, key=lambda row: (row['code'], row['id'], row['company_id']))

    @api.model
    def _build_cash_flow(self, report, options, with_accounts=False):
        payload = self._build(report, options)
        payload['report']['report_kind'] = 'cash_flow'
        data = self._cash_flow_compute(report, options)
        rows = []
        for code, name, level, display, foldable in self._cash_flow_spec():
            values = {key: d[0][code] for key, d in data.items()}
            _fill_variation(values, options['columns'])
            rows.append({'code': code, 'name': name, 'level': level, 'display': display,
                         'foldable': foldable, 'has_accounts': foldable,
                         'hide_amounts': code in ('operating', 'investing', 'financing', 'unclassified'),
                         'amounts': [self._serialize_amount(c, values.get(c['key']), self.env.company.currency_id, foldable and c['kind'] == 'period') for c in options['columns']],
                         'accounts': self._cash_flow_rows(options, code, data) if with_accounts and foldable else []})
        payload['lines'] = rows
        payload['cash_opening_note'] = _('Includes opening entries dated in the period')
        payload['notes'].append(payload['cash_opening_note'])
        _opening, unknown = self._cash_opening_moves()
        payload['cash_notices'] = []
        excluded = self._cash_excluded_accounts()
        if excluded:
            codes = sorted({account.with_company(company).code for company in self.env.companies
                            for account in excluded if company in account.company_ids and account.with_company(company).code})
            text = _('Excluded from cash: %s') % ', '.join(codes)
            payload['cash_notices'].append({'text': text})
            payload['notes'].append(text)
        if unknown and self.env.user.has_group('base.group_system'):
            payload['cash_notices'].append({'text': _('Unknown opening entry tokens: %s') % ', '.join(unknown)})
        column = next((c for c in options['columns'] if c['kind'] == 'period'), None)
        if column:
            if excluded:
                totals = self._aggregate(
                    self._base_domain(options) + [('account_id', 'in', excluded.ids),
                                                  ('date', '<=', column['_end'])],
                    column['_end'], options['analytic_account_ids'])
                currency = self.env.company.currency_id
                entries = []
                for (account_id, company_id), figures in totals.items():
                    balance = _quantize(figures['balance'], currency)
                    if balance:
                        account = excluded.browse(account_id).with_company(self.env['res.company'].browse(company_id))
                        entries.append((account.code or '', account.name, company_id, balance))
                if entries:
                    items = ['%s %s: %.*f' % (code, name, currency.decimal_places, balance)
                             for code, name, company_id, balance in sorted(entries)]
                    text = _('Clearing accounts not reconciled, excluded from cash:') + ' ' + '; '.join(items)
                    payload['cash_notices'].append({'text': text})
                    payload['notes'].append(text)
            codes = [s for s in re.split(r'[,\s]+', self.env['ir.config_parameter'].sudo().get_param(
                'baseer_report_engine.cash_flow_transfer_accounts', '').strip()) if s]
            for company in self.env.companies:
                accounts = company.transfer_account_id
                if codes:
                    accounts |= self.env['account.account'].with_company(company).search([
                        ('company_ids', 'in', company.id), ('code', 'in', codes)])
                states = ['posted'] if options['posted_only'] else ['posted', 'draft']
                for account, balance in self.env['account.move.line']._read_group([
                    ('company_id', '=', company.id), ('account_id', 'in', accounts.ids),
                    ('parent_state', 'in', states), ('date', '>=', column['_start']),
                    ('date', '<=', column['_end'])], ['account_id'], ['balance:sum']):
                    if company.currency_id.is_zero(balance):
                        continue
                    account = account.with_company(company)
                    text = _('The liquidity transfer account %(account)s has a non-zero balance of %(amount)s for this period: some transfers are incomplete.') % {
                        'account': '%s %s' % (account.code or '', account.name),
                        'amount': '%.*f %s' % (company.currency_id.decimal_places, balance, company.currency_id.name)}
                    action = {'type': 'ir.actions.act_window', 'name': _('Journal Items'), 'res_model': 'account.move.line',
                              'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'target': 'current',
                              'domain': [('company_id', '=', company.id), ('account_id', '=', account.id),
                                         ('parent_state', 'in', states), ('date', '>=', column['date_from']), ('date', '<=', column['date_to'])]}
                    payload['cash_notices'].append({'text': text, 'action': action})
                    payload['notes'].append(text)
        return payload

    @api.model
    def _cash_flow_accounts(self, report, options, codes):
        allowed = {row[0] for row in self._cash_flow_spec() if row[4]}
        if any(code not in allowed for code in codes):
            raise ValidationError(_('Choose a report line that lists accounts.'))
        data = self._cash_flow_compute(report, options)
        return [{'line_code': code, 'accounts': self._cash_flow_rows(options, code, data)} for code in codes]

    @api.model
    def _cash_flow_action(self, report, options, code, column_key, account_id, company_id):
        column = next((c for c in options['columns'] if c['key'] == column_key and c['kind'] == 'period'), None)
        if not column or code not in {x[0] for x in self._cash_flow_spec() if x[4]}:
            raise ValidationError(_('The report options are not valid.'))
        _amounts, details, moves = self._cash_flow_data(options, [column])[column['key']]
        key = None
        if account_id:
            key = (account_id, company_id)
            if key not in details[code]:
                raise AccessError(_('Choose an account from this line.'))
            if code in ('beginning', 'closing'):
                raw = {k: v for k, v in options.items() if k != 'columns'}
                raw.update(preset='custom', date_from=column['date_from'], date_to=column['date_to'])
                return self.get_general_ledger_action('general_ledger', raw, account_id, company_id)
        ids = sorted(moves.get((code, key), set()))
        return {'type': 'ir.actions.act_window', 'name': _('Journal Items'), 'res_model': 'account.move.line',
                'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'target': 'current',
                'domain': [('move_id', 'in', ids)]}
