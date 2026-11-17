"""Direct cash flow from liquidity movements and their reconciled counterparts.

Liquidity comprises cash-type accounts and bank/cash payment method accounts,
excluding suspense accounts. The journal filter applies to the liquidity
journal items. Each move's net cash effect is allocated by absolute counterpart
balance; reconciled receivable/payable portions are allocated by absolute
invoice line balance (including taxes), with the remainder treated as advances. Only
reconciliations dated on or before the period end are followed.
Opening and closing use the same conversion dates as the account grid. A
rounding/exotic-move residual is assigned to unclassified cash flows so the
statement reconciles to liquidity balances for every period.
"""
from collections import defaultdict
from decimal import Decimal

from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError

from .engine import _fill_variation, _quantize


class BaseerCashFlow(models.AbstractModel):
    _inherit = 'baseer.report.engine'

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
    def _cash_liquidity_accounts(self):
        accounts = self.env['account.account'].with_context(active_test=False).search([
            ('company_ids', 'in', self.env.companies.ids), ('account_type', '=', 'asset_cash')])
        journals = self.env['account.journal'].search([('company_id', 'in', self.env.companies.ids), ('type', 'in', ('bank', 'cash'))])
        for journal in journals:
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
        return accounts

    @api.model
    def _cash_flow_data(self, options, column):
        liquidity = self._cash_liquidity_accounts()
        # Aggregate historical balances with the same machinery as the TB.
        domain = self._base_domain(options) + [('account_id', 'in', liquidity.ids)]
        amounts = defaultdict(Decimal)
        details = defaultdict(lambda: defaultdict(Decimal))
        moves = defaultdict(set)
        currency = self.env.company.currency_id

        def add(code, account, company, value, move=None):
            key = (account.id, company.id)
            details[code][key] += value
            amounts[code] += value
            if move:
                moves[(code, key)].add(move.id)
                moves[(code, None)].add(move.id)

        for code, date_domain, on_date in (
            ('beginning', [('date', '<', column['_start'])], column['_start']),
            ('closing', [('date', '<=', column['_end'])], column['_end']),
        ):
            totals = self._aggregate(domain + date_domain, on_date, options['analytic_account_ids'])
            for key, figures in totals.items():
                details[code][key] += figures['balance']

        period_domain = domain + [('date', '>=', column['_start']), ('date', '<=', column['_end'])]
        grouped = self.env['account.move.line']._read_group(period_domain, ['move_id', 'company_id'], ['balance:sum'])
        move_ids = [move.id for move, company, balance in grouped if move and balance]
        all_lines = self.env['account.move.line'].search([('move_id', 'in', move_ids)])
        liquidity_ids = set(liquidity.ids)
        by_move = defaultdict(list)
        counterpart_ids = []
        for line in all_lines:
            if line.account_id.id not in liquidity_ids:
                by_move[line.move_id.id].append(line)
                if line.account_id.account_type in ('asset_receivable', 'liability_payable'):
                    counterpart_ids.append(line.id)
        partials = self.env['account.partial.reconcile'].search([
            ('max_date', '<=', column['_end']), '|',
            ('debit_move_id', 'in', counterpart_ids), ('credit_move_id', 'in', counterpart_ids),
        ], order='id')
        partials_by_line = defaultdict(list)
        other_move_ids = set()
        counterpart_set = set(counterpart_ids)
        for partial in partials:
            for line, other in ((partial.debit_move_id, partial.credit_move_id),
                                (partial.credit_move_id, partial.debit_move_id)):
                if line.id in counterpart_set:
                    partials_by_line[line.id].append((partial, other))
                    other_move_ids.add(other.move_id.id)
        invoice_lines = self.env['account.move.line'].search([('move_id', 'in', list(other_move_ids))])
        invoice_by_move = defaultdict(list)
        for line in invoice_lines:
            if line.account_id.id not in liquidity_ids and line.account_id.account_type not in ('asset_receivable', 'liability_payable'):
                invoice_by_move[line.move_id.id].append(line)
        tags = {kind: self.env.ref('account.account_tag_' + kind).id for kind in ('operating', 'investing', 'financing')}

        def classify(account, value, company, move):
            kind = next((kind for kind, tag in tags.items() if tag in account.tag_ids.ids), 'unclassified')
            add(kind + ('_in' if value >= 0 else '_out'), account, company, value, move)

        for move, company, balance in grouped:
            cash = Decimal(str(balance or 0))
            counterparts = by_move[move.id]
            denominator = sum((abs(Decimal(str(l.balance))) for l in counterparts), Decimal(0))
            if not cash or not denominator:
                continue
            for line in counterparts:
                share = cash * abs(Decimal(str(line.balance))) / denominator
                converted = self._ledger_convert(share, company, column['_end'])
                if line.account_id.account_type not in ('asset_receivable', 'liability_payable'):
                    classify(line.account_id, converted, company, move)
                    continue
                available = abs(Decimal(str(line.balance)))
                remaining = available
                for partial, other in partials_by_line[line.id]:
                    if other.move_id == move or other.company_id != company:
                        continue
                    paid = min(remaining, Decimal(str(partial.amount)))
                    items = invoice_by_move[other.move_id.id]
                    total = sum((abs(Decimal(str(l.balance))) for l in items), Decimal(0))
                    if not paid or not total:
                        continue
                    for item in items:
                        classify(item.account_id, converted * paid / available * abs(Decimal(str(item.balance))) / total, company, move)
                    remaining -= paid
                if remaining and available:
                    code = 'advance_received' if line.account_id.account_type == 'asset_receivable' else 'advance_paid'
                    add(code, line.account_id, company, converted * remaining / available, move)
        leaf_codes = [x[0] for x in self._cash_flow_spec() if x[4] and x[0] not in ('beginning', 'closing')]
        # Quantize totals and detail rows consistently, including cross-company conversion.
        for code, rows in details.items():
            for key, value in list(rows.items()):
                rows[key] = _quantize(value, currency)
            amounts[code] = sum(rows.values(), Decimal(0))
        net = amounts['closing'] - amounts['beginning']
        residual = net - sum((amounts[c] for c in leaf_codes), Decimal(0))
        if residual:
            code = 'unclassified_in' if residual > 0 else 'unclassified_out'
            details[code][(0, 0)] += residual
            amounts[code] += residual
        amounts['net'] = net
        return amounts, details, moves

    @api.model
    def _cash_flow_compute(self, report, options):
        data = {c['key']: self._cash_flow_data(options, c) for c in options['columns'] if c['kind'] == 'period'}
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
        _amounts, details, moves = self._cash_flow_data(options, column)
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
