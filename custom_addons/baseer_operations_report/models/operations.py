"""A deliberately incomplete, read-only gross-operations calculator.

The source of an operation is its posted invoice product line or its original
approved POS order line.  Ledger entries are never added as a third channel:
POS session moves, their reversals, nonrecoverable tax AML, and later POS
invoices would otherwise duplicate an original operation.
"""

from collections import Counter
from datetime import timedelta
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.baseer_profit_loss_report.models.profit_loss import (
    EXPENSE_KEYS, SECTION_GROUPS, SECTION_KEYS,
)


ROW_KEYS = (
    'income', 'cost_of_sales', 'gross_profit', 'expense',
    'net_operating_income', 'other_income', 'other_expense',
    'net_other_income', 'net_income',
)
INVOICE_TYPES = ('out_invoice', 'out_refund')
POS_STATES = ('paid', 'done', 'invoiced')


class BaseerOperationsReport(models.AbstractModel):
    _name = 'baseer.operations.report'
    _description = 'Baseer Limited Gross Operations Source'

    @staticmethod
    def _decimal(value):
        return Decimal(str(value or 0))

    @api.model
    def _deny_incomplete_source(self):
        raise AccessError(_('An operations source is unavailable or changed while reading.'))

    @api.model
    def _require_read(self, names):
        for name in names:
            self.env[name].browse().check_access('read')

    @api.model
    def _assert_visible(self, table, domain, params, records):
        """SQL only detects a hidden ID; no unruled amount enters the report."""
        self.env.cr.execute('SELECT id FROM ' + table + ' WHERE ' + domain, params)
        if set(row[0] for row in self.env.cr.fetchall()) != set(records.ids):
            self._deny_incomplete_source()
        records.check_access('read')

    @api.model
    def _scope(self, filters):
        if not isinstance(filters, dict):
            raise ValidationError(_('Select a report period.'))
        # The existing P&L server-side parser is the period/journal contract.
        # A caller cannot select a different company even if it is allowed.
        scoped = dict(filters)
        if scoped.get('company_id', self.env.company.id) != self.env.company.id:
            raise AccessError(_('Only the active company may be reported.'))
        scoped['company_id'] = self.env.company.id
        pl = self.env['baseer.profit.loss.report']
        company, journal_ids = pl._base_filters(scoped)
        periods, period_control, comparison_control = pl._resolve_periods(company, scoped)
        self._require_read((
            'account.move', 'account.move.line', 'account.account',
            'account.tax', 'account.tax.repartition.line', 'account.journal',
            'pos.order', 'pos.order.line', 'pos.session', 'pos.config',
            'product.product', 'account.fiscal.position',
            'account.bank.statement.line', 'account.partial.reconcile',
        ))
        return company, journal_ids, periods, period_control, comparison_control

    @api.model
    def _invoice_records(self, company, start, end, journal_ids):
        domain = [
            ('company_id', '=', company.id), ('state', '=', 'posted'),
            ('move_type', 'in', INVOICE_TYPES),
            ('date', '>=', start), ('date', '<=', end),
        ]
        sql = "company_id=%s AND state='posted' AND move_type IN %s AND date >= %s AND date <= %s"
        params = [company.id, INVOICE_TYPES, start, end]
        if journal_ids:
            domain.append(('journal_id', 'in', journal_ids))
            sql += ' AND journal_id = ANY(%s)'
            params.append(journal_ids)
        moves = self.env['account.move'].search(domain, order='id')
        self.env['account.move'].flush_model([
            'company_id', 'state', 'move_type', 'date', 'journal_id',
        ])
        self._assert_visible('account_move', sql, params, moves)
        return moves

    @api.model
    def _pos_records(self, company, start, end, journal_ids):
        # date_order is stored as a UTC datetime. The source contract uses its
        # stored date; local business-day conversion needs a separate GO.
        next_day = end + timedelta(days=1)
        domain = [
            ('company_id', '=', company.id), ('source', 'in', ('pos', 'baseer_summary')),
            ('state', 'in', POS_STATES),
            ('date_order', '>=', fields.Datetime.to_string(start)),
            ('date_order', '<', fields.Datetime.to_string(next_day)),
        ]
        sql = ('company_id=%s AND source IN %s AND state IN %s '
               'AND date_order >= %s AND date_order < %s')
        params = [company.id, ('pos', 'baseer_summary'), POS_STATES, start, next_day]
        orders = self.env['pos.order'].search(domain, order='id')
        self.env['pos.order'].flush_model([
            'company_id', 'source', 'state', 'date_order',
        ])
        self._assert_visible('pos_order', sql, params, orders)
        if journal_ids:
            # Never silently drop an order because its config/journal link is
            # hidden or absent. Verify links before applying the user filter.
            for order in orders:
                session = order.session_id
                if not session or not session.config_id or not session.config_id.journal_id:
                    self._deny_incomplete_source()
                session.check_access('read')
                session.config_id.check_access('read')
                session.config_id.journal_id.check_access('read')
            orders = orders.filtered(
                lambda order: order.session_id.config_id.journal_id.id in journal_ids,
            )
        return orders

    @api.model
    def _invoice_lines(self, move):
        lines = move.invoice_line_ids
        lines.check_access('read')
        source_lines = lines.filtered(lambda line: line.display_type == 'product')
        self.env['account.move.line'].flush_model(['move_id', 'display_type'])
        self._assert_visible('account_move_line',
                             'move_id=%s AND display_type=%s',
                             [move.id, 'product'], source_lines)
        return source_lines

    @api.model
    def _pos_lines(self, order):
        lines = order.lines
        self.env['pos.order.line'].flush_model(['order_id'])
        self._assert_visible('pos_order_line', 'order_id=%s', [order.id], lines)
        return lines

    @api.model
    def _record(self, sections, section, account, amount, source):
        if section not in SECTION_KEYS:
            self._deny_incomplete_source()
        account.check_access('read')
        entry = sections[section].setdefault(account.id, {
            'account': account, 'raw': Decimal('0'), 'count': 0,
            'source_counts': Counter(),
        })
        entry['raw'] += amount
        entry['count'] += 1
        entry['source_counts'][source] += 1

    @api.model
    def _invoice_amounts(self, move, company, sections, excluded):
        move.check_access('read')
        move.journal_id.check_access('read')
        if move.company_id != company:
            self._deny_incomplete_source()
        # A linked original order may be outside this report period. Compare
        # the unruled link IDs with the visible relation before classifying
        # the invoice; a hidden order must never turn into a second sale.
        self.env['pos.order'].flush_model(['account_move'])
        self.env.cr.execute(
            'SELECT id FROM pos_order WHERE account_move = %s', (move.id,),
        )
        linked_ids = {row[0] for row in self.env.cr.fetchall()}
        linked_orders = self.env['pos.order'].browse(sorted(linked_ids))
        linked_orders.check_access('read')
        if linked_ids:
            for order in linked_orders:
                if order.account_move != move or order.company_id != company:
                    self._deny_incomplete_source()
            excluded['linked_pos_invoice'] += 1
            return
        source_lines = self._invoice_lines(move)
        source_lines.mapped('account_id').check_access('read')
        source_lines.mapped('tax_ids').check_access('read')
        base_lines, _tax_lines = move._get_rounded_base_and_tax_lines()
        self.env['account.tax']._add_accounting_data_in_base_lines_tax_details(
            base_lines, company,
        )
        def money(value):
            return self._decimal(company.currency_id.round(float(value)))

        by_id = {base['record'].id: base for base in base_lines
                 if base['record']._name == 'account.move.line'
                 and base['record'].move_id == move
                 and base['record'].display_type == 'product'}
        if set(by_id) != set(source_lines.ids) or len(by_id) != len(source_lines):
            self._deny_incomplete_source()
        for line in source_lines:
            base = by_id[line.id]
            details = base.get('tax_details') or {}
            if 'total_excluded' not in details or 'taxes_data' not in details:
                self._deny_incomplete_source()
            if abs(money(details['total_excluded'])) != abs(money(line.balance)):
                self._deny_incomplete_source()
            source_tax = Decimal('0')
            for tax_data in details['taxes_data']:
                tax = tax_data.get('tax')
                if not tax:
                    self._deny_incomplete_source()
                tax.check_access('read')
                amount = money(tax_data.get('tax_amount'))
                if tax.amount < 0:
                    excluded['unsupported_negative_tax_lines'] += 1
                    source_tax = None
                    break
                reps = tax_data.get('tax_reps_data') or []
                rep_total = Decimal('0')
                for rep in reps:
                    rep_line = rep.get('tax_repartition_line')
                    if rep_line:
                        rep_line.check_access('read')
                    rep_account = rep.get('account')
                    if rep_account:
                        rep_account.check_access('read')
                    rep_total += money(rep.get('tax_amount'))
                if money(rep_total) != amount:
                    self._deny_incomplete_source()
                # Odoo's signed tax detail may reverse for credit notes. The
                # tax's magnitude is sourced here, then oriented by the actual
                # posted P&L base below; never infer it from a flat VAT rate.
                source_tax += abs(amount)
            if source_tax is None:
                continue
            account = line.account_id
            section = account.account_type
            if section not in SECTION_KEYS:
                excluded['non_pl_invoice_lines'] += 1
                continue
            # The rounded base is in company currency. The source tax is also
            # in company currency; invoice price_total may be foreign currency.
            net = (-self._decimal(line.balance) if section not in EXPENSE_KEYS
                   else self._decimal(line.balance))
            if not net and source_tax:
                excluded['tax_only_invoice_lines'] += 1
                continue
            signed_tax = source_tax.copy_sign(net) if source_tax else Decimal('0')
            self._record(sections, section, account, net + signed_tax, 'invoice')
        # Tax AML is accounting evidence, never an additional operation.
        move.line_ids.filtered('tax_line_id').check_access('read')
        excluded['nonrecoverable_tax_amls_not_readded'] += len(
            move.line_ids.filtered(
                lambda item: item.tax_line_id and
                item.account_id.account_type in SECTION_KEYS,
            ),
        )

    @api.model
    def _pos_amounts(self, order, company, sections, excluded):
        order.check_access('read')
        if order.company_id != company:
            self._deny_incomplete_source()
        session = order.session_id
        if not session or not session.config_id or not session.config_id.journal_id:
            self._deny_incomplete_source()
        session.check_access('read')
        session.config_id.check_access('read')
        session.config_id.journal_id.check_access('read')
        if session.company_id != company:
            self._deny_incomplete_source()
        if session.state == 'closed':
            if not session.move_id or session.move_id.state != 'posted':
                self._deny_incomplete_source()
            session.move_id.check_access('read')
        if order.currency_id != company.currency_id:
            excluded['foreign_pos_orders'] += 1
            return
        if order.source == 'baseer_summary':
            summary = order.baseer_summary_id
            if not summary or summary.state != 'approved' or summary.order_id != order:
                self._deny_incomplete_source()
            summary.check_access('read')
        if order.account_move:
            order.account_move.check_access('read')
            if order.account_move.state != 'posted' or order not in order.account_move.pos_order_ids:
                self._deny_incomplete_source()
            excluded['linked_pos_invoice_not_readded'] += 1
        order.reversed_move_ids.check_access('read')
        lines = self._pos_lines(order)
        if not lines:
            self._deny_incomplete_source()
        lines.mapped('product_id').check_access('read')
        lines.mapped('tax_ids').check_access('read')
        if order.fiscal_position_id:
            order.fiscal_position_id.check_access('read')
        sign = -1 if order.is_refund else 1
        gross = sum((self._decimal(line.price_subtotal_incl) for line in lines), Decimal('0'))
        net = sum((self._decimal(line.price_subtotal) for line in lines), Decimal('0'))
        if (sign * gross != self._decimal(order.amount_total)
                or sign * net + self._decimal(order.amount_tax) != self._decimal(order.amount_total)):
            self._deny_incomplete_source()
        for line in lines:
            account = line._prepare_base_line_for_taxes_computation().get('account_id')
            if not account or account._name != 'account.account':
                self._deny_incomplete_source()
            account.check_access('read')
            section = account.account_type
            if section not in SECTION_KEYS:
                excluded['non_pl_pos_lines'] += 1
                continue
            gross_amount = sign * self._decimal(line.price_subtotal_incl)
            amount = -gross_amount if section in EXPENSE_KEYS else gross_amount
            self._record(sections, section, account, amount, 'pos')

    @api.model
    def _direct_exclusions(self, company, start, end, journal_ids):
        domain = [
            ('company_id', '=', company.id), ('parent_state', '=', 'posted'),
            ('move_id.move_type', '=', 'entry'),
            ('date', '>=', start), ('date', '<=', end),
            ('account_id.account_type', 'in', SECTION_KEYS),
        ]
        if journal_ids:
            domain.append(('journal_id', 'in', journal_ids))
        lines = self.env['account.move.line'].search(domain)
        sql = (
            'aml.company_id=%s AND aml.parent_state=%s AND m.move_type=%s '
            'AND aml.date >= %s AND aml.date <= %s AND a.account_type IN %s'
        )
        params = [company.id, 'posted', 'entry', start, end, SECTION_KEYS]
        if journal_ids:
            sql += ' AND aml.journal_id = ANY(%s)'
            params.append(journal_ids)
        self.env['account.move.line'].flush_model([
            'company_id', 'parent_state', 'date', 'journal_id', 'move_id', 'account_id',
        ])
        self.env['account.move'].flush_model(['move_type'])
        self.env['account.account'].flush_model(['account_type'])
        self.env.cr.execute(
            'SELECT aml.id FROM account_move_line aml '
            'JOIN account_move m ON m.id=aml.move_id '
            'JOIN account_account a ON a.id=aml.account_id WHERE ' + sql,
            params,
        )
        if set(row[0] for row in self.env.cr.fetchall()) != set(lines.ids):
            self._deny_incomplete_source()
        lines.check_access('read')
        # Source count only, not a VAT allocation or a subtotal.
        return len(lines)

    @api.model
    def _purchase_outflows(self, company, start, end, journal_ids, sections, excluded):
        """Limited proof: one-line company-currency bill paid by a bank statement.

        Neither a posted bill nor a registered payment on an outstanding
        account is a cash event.  The statement is the unique dated source.
        Unsupported purchase patterns remain outside this incomplete report.
        """
        domain = [
            ('company_id', '=', company.id), ('date', '>=', start),
            ('date', '<=', end), ('amount', '<', 0),
        ]
        statements = self.env['account.bank.statement.line'].search(domain, order='id')
        self.env['account.bank.statement.line'].flush_model([
            'company_id', 'date', 'amount',
        ])
        self._assert_visible(
            'account_bank_statement_line',
            'company_id=%s AND date >= %s AND date <= %s AND amount < 0',
            [company.id, start, end], statements,
        )
        seen = set()
        for statement in statements:
            if journal_ids:
                excluded['purchase_journal_filter_unproven'] += 1
                continue
            statement.check_access('read')
            journal = statement.journal_id
            journal.check_access('read')
            move = statement.move_id
            move.check_access('read')
            if (statement.id in seen or move.state != 'posted'
                    or move.company_id != company or journal.type != 'bank'
                    or not journal.default_account_id):
                self._deny_incomplete_source()
            seen.add(statement.id)
            lines = move.line_ids
            self.env['account.move.line'].flush_model(['move_id'])
            self._assert_visible(
                'account_move_line', 'move_id=%s', [move.id], lines,
            )
            bank = lines.filtered(
                lambda line: line.account_id == journal.default_account_id,
            )
            counterpart = lines - bank
            amount = -self._decimal(statement.amount)
            if (len(bank) != 1 or len(counterpart) != 1
                    or self._decimal(bank.balance) != -amount
                    or self._decimal(counterpart.balance) != amount):
                excluded['unproven_bank_outflow'] += 1
                continue
            if counterpart.account_id.account_type == 'liability_payable':
                payable_debit = counterpart
            elif (counterpart.account_id.account_type == 'asset_current'
                  and counterpart.account_id.reconcile):
                # The bank has cleared an outstanding payment.  That payment
                # must already be matched to exactly one bill for this slice.
                clearing = counterpart.matched_credit_ids
                self._assert_visible(
                    'account_partial_reconcile', 'debit_move_id=%s',
                    [counterpart.id], clearing,
                )
                if len(clearing) != 1 or self._decimal(clearing.amount) != amount:
                    excluded['unproven_outstanding_allocation'] += 1
                    continue
                payment_credit = clearing.credit_move_id
                payment_move = payment_credit.move_id
                payment_move.check_access('read')
                payment_lines = payment_move.line_ids
                self._assert_visible(
                    'account_move_line', 'move_id=%s',
                    [payment_move.id], payment_lines,
                )
                payables = payment_lines.filtered(
                    lambda line: line.account_id.account_type == 'liability_payable',
                )
                if (len(payables) != 1 or payment_credit.account_id != counterpart.account_id
                        or self._decimal(payment_credit.balance) != -amount
                        or self._decimal(payables.balance) != amount):
                    excluded['unproven_outstanding_allocation'] += 1
                    continue
                payable_debit = payables
            else:
                # Internal liquidity transfers and unclassified cash events
                # never become a purchase by inference.
                excluded['non_purchase_bank_outflow'] += 1
                continue
            allocations = payable_debit.matched_credit_ids
            self._assert_visible(
                'account_partial_reconcile', 'debit_move_id=%s',
                [payable_debit.id], allocations,
            )
            if len(allocations) != 1 or self._decimal(allocations.amount) != amount:
                excluded['unproven_bill_allocation'] += 1
                continue
            bill_line = allocations.credit_move_id
            bill = bill_line.move_id
            bill.check_access('read')
            bill_lines = bill.line_ids
            self._assert_visible(
                'account_move_line', 'move_id=%s', [bill.id], bill_lines,
            )
            if (bill.state != 'posted' or bill.move_type != 'in_invoice'
                    or bill.company_id != company or bill.currency_id != company.currency_id
                    or not bill.invoice_date or bill.invoice_date > statement.date
                    or bill_line.account_id != payable_debit.account_id
                    or len(bill.invoice_line_ids.filtered(
                        lambda line: line.display_type == 'product')) != 1):
                excluded['unsupported_purchase_bill'] += 1
                continue
            bill_sections = {key: {} for key in SECTION_KEYS}
            bill_excluded = Counter()
            self._invoice_amounts(bill, company, bill_sections, bill_excluded)
            entries = [(kind, entry) for kind in EXPENSE_KEYS
                       for entry in bill_sections[kind].values()]
            if (len(entries) != 1 or bill_excluded.get('non_pl_invoice_lines')
                    or bill_excluded.get('unsupported_negative_tax_lines')
                    or bill_excluded.get('tax_only_invoice_lines')
                    or entries[0][1]['raw'] != self._decimal(bill.amount_total)):
                excluded['unsupported_purchase_bill'] += 1
                continue
            section, entry = entries[0]
            self._record(sections, section, entry['account'], amount, 'bank_statement')

    @api.model
    def _rows(self, sections, company):
        raw = {key: sum((entry['raw'] for entry in sections[key].values()), Decimal('0'))
               for key in SECTION_KEYS}
        result = {
            'income': raw['income'],
            'cost_of_sales': raw['expense_direct_cost'],
            'expense': raw['expense'] + raw['expense_depreciation'],
            'other_income': raw['income_other'],
            'other_expense': raw['expense_other'],
        }
        result['gross_profit'] = result['income'] - result['cost_of_sales']
        result['net_operating_income'] = result['gross_profit'] - result['expense']
        result['net_other_income'] = result['other_income'] - result['other_expense']
        result['net_income'] = result['net_operating_income'] + result['net_other_income']
        pl = self.env['baseer.profit.loss.report']
        rows = [{'key': key, 'amount': pl._format_money(result[key], company.currency_id),
                 'negative': result[key] < 0} for key in ROW_KEYS]
        leaf = {}
        for key, account_types in (
            ('income', ('income',)), ('cost_of_sales', ('expense_direct_cost',)),
            ('expense', SECTION_GROUPS['expense']),
            ('other_income', ('income_other',)), ('other_expense', ('expense_other',)),
        ):
            accounts = [entry for kind in account_types for entry in sections[kind].values()]
            accounts.sort(key=lambda entry: (entry['account'].code or '', entry['account'].id))
            leaf[key] = [
                {'account_id': entry['account'].id,
                 'account_code': entry['account'].code,
                 'account_name': entry['account'].name,
                 'amount': pl._format_money(entry['raw'], company.currency_id),
                 'negative': entry['raw'] < 0,
                 'source_count': entry['count']}
                for entry in accounts
            ]
        return rows, leaf

    @api.model
    def get_source_snapshot(self, filters):
        """Internal source evidence only. Never expose it as a complete report."""
        company, journal_ids, periods, period_control, comparison_control = self._scope(filters)
        payload_periods = []
        for period in periods:
            start = fields.Date.to_date(period['date_from'])
            end = fields.Date.to_date(period['date_to'])
            sections = {key: {} for key in SECTION_KEYS}
            excluded = Counter()
            for move in self._invoice_records(company, start, end, journal_ids):
                self._invoice_amounts(move, company, sections, excluded)
            for order in self._pos_records(company, start, end, journal_ids):
                self._pos_amounts(order, company, sections, excluded)
            self._purchase_outflows(
                company, start, end, journal_ids, sections, excluded,
            )
            excluded['direct_aml_unproven'] = self._direct_exclusions(
                company, start, end, journal_ids,
            )
            rows, accounts = self._rows(sections, company)
            payload_periods.append({
                'key': period['key'], 'date_from': period['date_from'],
                'date_to': period['date_to'], 'label': period['label'],
                'rows': rows, 'accounts': accounts,
                'excluded': dict(excluded),
            })
        return {
            'complete': False,
            'scope': 'proven_invoice_and_original_pos_only',
            'not_accounting_profit': True,
            'company_id': company.id,
            'currency_code': company.currency_id.name,
            'period_controls': period_control,
            'comparison_controls': comparison_control,
            'periods': payload_periods,
        }
