"""A deliberately incomplete, read-only gross-operations calculator.

Sales come from original invoice/POS sources. Purchases enter only through
the limited, proven cash/bank outflows below; posting a bill or an outstanding
payment alone never creates an operation.
"""

from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal

from pytz import UTC, timezone
from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError, UnknownTimeZoneError

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
            'baseer.pos.summary', 'res.partner',
            'product.product', 'account.fiscal.position',
            'account.bank.statement.line', 'account.partial.reconcile',
            'account.payment',
        ))
        return company, journal_ids, periods, period_control, comparison_control

    @api.model
    def _invoice_records(self, company, start, end, journal_ids):
        domain = [
            ('company_id', '=', company.id), ('state', '=', 'posted'),
            ('move_type', 'in', INVOICE_TYPES),
            ('invoice_date', '>=', start), ('invoice_date', '<=', end),
        ]
        sql = ("company_id=%s AND state='posted' AND move_type IN %s "
               "AND invoice_date >= %s AND invoice_date <= %s")
        params = [company.id, INVOICE_TYPES, start, end]
        if journal_ids:
            domain.append(('journal_id', 'in', journal_ids))
            sql += ' AND journal_id = ANY(%s)'
            params.append(journal_ids)
        moves = self.env['account.move'].search(domain, order='id')
        self.env['account.move'].flush_model([
            'company_id', 'state', 'move_type', 'invoice_date', 'journal_id',
        ])
        self._assert_visible('account_move', sql, params, moves)
        return moves

    @api.model
    def _company_timezone(self, company):
        company.partner_id.check_access('read')
        name = company.partner_id.tz
        if not name:
            calendar = company.resource_calendar_id
            if calendar:
                calendar.check_access('read')
                name = calendar.tz
        if not name:
            self._deny_incomplete_source()
        try:
            return timezone(name)
        except (UnknownTimeZoneError, AttributeError, TypeError):
            self._deny_incomplete_source()

    @api.model
    def _local_utc_bounds(self, company, start, end):
        zone = self._company_timezone(company)
        try:
            lower = zone.localize(datetime.combine(start, time.min), is_dst=None)
            upper = zone.localize(
                datetime.combine(end + timedelta(days=1), time.min),
                is_dst=None,
            )
        except (AmbiguousTimeError, NonExistentTimeError, OverflowError):
            self._deny_incomplete_source()
        return (
            lower.astimezone(UTC).replace(tzinfo=None),
            upper.astimezone(UTC).replace(tzinfo=None),
        )

    @api.model
    def _pos_records(self, company, start, end, journal_ids):
        # Native POS date_order is a real UTC timestamp; external-summary
        # date_order is synthetic and must never be used as its business day.
        lower, upper = self._local_utc_bounds(company, start, end)
        native_domain = [
            ('company_id', '=', company.id), ('source', '=', 'pos'),
            ('state', 'in', POS_STATES),
            ('date_order', '>=', lower), ('date_order', '<', upper),
        ]
        native = self.env['pos.order'].search(native_domain, order='id')
        self.env['pos.order'].flush_model([
            'company_id', 'source', 'state', 'date_order',
        ])
        self._assert_visible(
            'pos_order',
            'company_id=%s AND source=%s AND state IN %s '
            'AND date_order >= %s AND date_order < %s',
            [company.id, 'pos', POS_STATES, lower, upper], native,
        )
        summary_domain = [
            ('company_id', '=', company.id), ('state', '=', 'approved'),
            ('business_date', '>=', start), ('business_date', '<=', end),
        ]
        summaries = self.env['baseer.pos.summary'].search(summary_domain, order='id')
        self.env['baseer.pos.summary'].flush_model([
            'company_id', 'state', 'business_date', 'order_id',
        ])
        self._assert_visible(
            'baseer_pos_summary',
            'company_id=%s AND state=%s AND business_date >= %s '
            'AND business_date <= %s',
            [company.id, 'approved', start, end], summaries,
        )
        summary_ids = []
        for summary in summaries:
            order = summary.order_id
            if summary.zero_sales:
                if (order or summary.session_id or summary.amount_gross
                        or summary.amount_net or summary.amount_tax):
                    self._deny_incomplete_source()
                # An approved no-sales day has no POS order by design.
                continue
            if (not order or order.company_id != company
                    or order.source != 'baseer_summary'
                    or order.state not in POS_STATES
                    or order.baseer_summary_id != summary):
                self._deny_incomplete_source()
            summary_ids.append(order.id)
        if len(summary_ids) != len(set(summary_ids)):
            self._deny_incomplete_source()
        linked = self.env['pos.order'].search([
            ('id', 'in', summary_ids), ('company_id', '=', company.id),
            ('source', '=', 'baseer_summary'), ('state', 'in', POS_STATES),
        ], order='id')
        if set(linked.ids) != set(summary_ids):
            self._deny_incomplete_source()
        linked.check_access('read')
        orders = native | linked
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
    def _record(self, sections, section, account, amount, source, event=None):
        if section not in SECTION_KEYS:
            self._deny_incomplete_source()
        account.check_access('read')
        entry = sections[section].setdefault(account.id, {
            'account': account, 'raw': Decimal('0'), 'count': 0,
            'source_counts': Counter(), 'events': [],
        })
        entry['raw'] += amount
        entry['count'] += 1
        entry['source_counts'][source] += 1
        if event is not None:
            entry['events'].append({**event, 'amount': amount})

    @api.model
    def _invoice_amounts(self, move, company, sections, excluded, line_entries=None):
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
            if line_entries is not None:
                line_entries.append((line.id, section, account, net + signed_tax))
            self._record(
                sections, section, account, net + signed_tax, 'invoice',
                None if line_entries is not None else {
                    'source_model': 'account.move', 'source_id': move.id,
                    'line_model': 'account.move.line', 'line_id': line.id,
                    'date': fields.Date.to_string(move.invoice_date),
                },
            )
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
            event_date = (summary.business_date if order.source == 'baseer_summary'
                          else fields.Datetime.to_datetime(order.date_order).replace(
                              tzinfo=UTC,
                          ).astimezone(self._company_timezone(company)).date())
            self._record(
                sections, section, account, amount, 'pos', {
                    'source_model': ('baseer.pos.summary' if order.source == 'baseer_summary'
                                     else 'pos.order'),
                    'source_id': summary.id if order.source == 'baseer_summary' else order.id,
                    'line_model': 'pos.order.line', 'line_id': line.id,
                    'date': fields.Date.to_string(event_date),
                },
            )

    @api.model
    def _direct_exclusions(self, company, start, end, journal_ids,
                           recognized_direct_ids=()):
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
        recognized = set(recognized_direct_ids)
        if not recognized.issubset(set(lines.ids)):
            self._deny_incomplete_source()
        # Recognized direct bank expenses are not still called unproven AML.
        return len(lines) - len(recognized)

    @api.model
    def _allocate_purchase_event(self, gross_amounts, prior, amount, currency):
        """Allocate one cash event by the change in cumulative rounded targets."""
        total = sum(gross_amounts, Decimal('0'))
        after = prior + amount
        if (not gross_amounts or any(gross <= 0 for gross in gross_amounts)
                or prior < 0 or amount <= 0 or after > total):
            self._deny_incomplete_source()
        def targets(paid):
            remaining_paid = paid
            remaining_gross = total
            result = []
            for gross in gross_amounts[:-1]:
                target = self._decimal(currency.round(float(
                    remaining_paid * gross / remaining_gross,
                )))
                target = min(max(target, Decimal('0')), gross, remaining_paid)
                result.append(target)
                remaining_paid -= target
                remaining_gross -= gross
            result.append(remaining_paid)
            return result

        before_targets = targets(prior)
        after_targets = targets(after)
        allocated = [new - old for new, old in zip(
            after_targets, before_targets, strict=True,
        )]
        if (any(delta < 0 for delta in allocated)
                or any(target > gross for target, gross in zip(
                    after_targets, gross_amounts, strict=True,
                ))
                or sum(allocated, Decimal('0')) != amount):
            self._deny_incomplete_source()
        return allocated

    @api.model
    def _purchase_outflows(self, company, start, end, journal_ids, sections, excluded):
        """Limited proof: one-line company-currency bill paid by a bank statement.

        Neither a posted bill nor a registered payment on an outstanding
        account is a cash event.  The statement is the unique dated source.
        Unsupported purchase patterns remain outside this incomplete report.
        """
        domain = [
            ('company_id', '=', company.id),
            ('date', '<=', end), ('amount', '<', 0),
        ]
        statements = self.env['account.bank.statement.line'].search(domain, order='id')
        self.env['account.bank.statement.line'].flush_model([
            'company_id', 'move_id', 'amount',
        ])
        # statement.date is related to move.date, not a physical statement
        # table column in Odoo 19.  Compare the unruled joined source IDs.
        self.env['account.move'].flush_model(['date'])
        self.env.cr.execute(
            'SELECT s.id FROM account_bank_statement_line s '
            'JOIN account_move m ON m.id=s.move_id '
            'WHERE s.company_id=%s AND m.date <= %s '
            'AND s.amount < 0',
            [company.id, end],
        )
        if {row[0] for row in self.env.cr.fetchall()} != set(statements.ids):
            self._deny_incomplete_source()
        statements.check_access('read')
        seen = set()
        recognized_direct = set()
        cumulative = {}
        for statement in statements.sorted(lambda item: (item.date, item.id)):
            statement.check_access('read')
            journal = statement.journal_id
            journal.check_access('read')
            move = statement.move_id
            move.check_access('read')
            if (statement.id in seen or move.state != 'posted'
                    or move.company_id != company or journal.company_id != company
                    or move.journal_id != journal
                    or journal.type not in ('bank', 'cash')
                    or not journal.default_account_id
                    or journal.default_account_id.account_type != 'asset_cash'):
                self._deny_incomplete_source()
            seen.add(statement.id)
            if statement.currency_id != company.currency_id:
                excluded['foreign_currency_bank_outflow'] += 1
                continue
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
            if (len(bank) != 1 or self._decimal(bank.balance) != -amount
                    or move.statement_line_id != statement):
                excluded['unproven_bank_outflow'] += 1
                continue
            lines.mapped('account_id').check_access('read')
            if len(counterpart) == 2:
                bases = counterpart.filtered(
                    lambda line: line.account_id.account_type in EXPENSE_KEYS
                    and not line.tax_line_id,
                )
                taxes = counterpart.filtered(lambda line: line.tax_line_id)
                if len(bases) != 1 or len(taxes) != 1:
                    excluded['unsupported_direct_bank_expense'] += 1
                    continue
                base, tax_line = bases, taxes
                tax = tax_line.tax_line_id
                repartition = tax_line.tax_repartition_line_id
                tax.check_access('read')
                repartition.check_access('read')
                if (move.move_type != 'entry' or move.origin_payment_id
                        or statement.payment_ids
                        or any(line.move_id != move or line.company_id != company
                               or line.journal_id != journal
                               or line.currency_id != company.currency_id
                               or line.matched_credit_ids or line.matched_debit_ids
                               for line in lines)
                        or bank.tax_ids or bank.tax_line_id
                        or base.account_id.reconcile or base.tax_ids != tax
                        or tax_line.tax_ids or tax.company_id != company
                        or tax.type_tax_use != 'purchase'
                        or not repartition or repartition.tax_id != tax
                        or repartition.repartition_type != 'tax'
                        or repartition not in tax.invoice_repartition_line_ids
                        or repartition.account_id != tax_line.account_id
                        or tax_line.account_id.account_type in SECTION_KEYS
                        or tax_line.account_id.account_type == 'asset_cash'
                        or self._decimal(base.balance) <= 0
                        or self._decimal(tax_line.balance) <= 0
                        or self._decimal(base.balance)
                           + self._decimal(tax_line.balance) != amount):
                    excluded['unsupported_direct_bank_expense'] += 1
                    continue
                if journal_ids and journal.id not in journal_ids:
                    continue
                if start <= statement.date <= end:
                    self._record(
                        sections, base.account_id.account_type,
                        base.account_id, amount,
                        'cash_statement_direct_taxed' if journal.type == 'cash'
                        else 'bank_statement_direct_taxed',
                        {'source_model': 'account.bank.statement.line',
                         'source_id': statement.id,
                         'line_model': 'account.move.line', 'line_id': base.id,
                         'date': fields.Date.to_string(statement.date)},
                    )
                    recognized_direct.add(base.id)
                continue
            if (len(counterpart) != 1
                    or self._decimal(counterpart.balance) != amount):
                excluded['unproven_bank_outflow'] += 1
                continue
            if counterpart.account_id.account_type in EXPENSE_KEYS:
                if (move.move_type != 'entry' or move.origin_payment_id
                        or statement.payment_ids
                        or any(line.company_id != company or line.tax_line_id
                               or line.tax_ids or line.tax_tag_ids for line in lines)
                        or counterpart.account_id.reconcile
                        or counterpart.matched_credit_ids
                        or counterpart.matched_debit_ids):
                    excluded['unsupported_direct_bank_expense'] += 1
                    continue
                if journal_ids and journal.id not in journal_ids:
                    continue
                if start <= statement.date <= end:
                    self._record(
                        sections, counterpart.account_id.account_type,
                        counterpart.account_id, amount,
                        'cash_statement_direct' if journal.type == 'cash'
                        else 'bank_statement_direct',
                        {'source_model': 'account.bank.statement.line',
                         'source_id': statement.id,
                         'line_model': 'account.move.line',
                         'line_id': counterpart.id,
                         'date': fields.Date.to_string(statement.date)},
                    )
                    recognized_direct.add(counterpart.id)
                continue
            if journal.type != 'bank':
                excluded['non_purchase_cash_outflow'] += 1
                continue
            if journal_ids:
                excluded['purchase_journal_filter_unproven'] += 1
                continue
            if (counterpart.account_id.account_type == 'asset_current'
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
                payment = payment_move.origin_payment_id
                if not payment:
                    excluded['unproven_outstanding_allocation'] += 1
                    continue
                payment.check_access('read')
                payment_lines = payment_move.line_ids
                self._assert_visible(
                    'account_move_line', 'move_id=%s',
                    [payment_move.id], payment_lines,
                )
                payables = payment_lines.filtered(
                    lambda line: line.account_id.account_type == 'liability_payable',
                )
                payables.mapped('account_id').check_access('read')
                if (len(payables) != 1 or payment_credit.account_id != counterpart.account_id
                        or self._decimal(payment_credit.balance) != -amount
                        or self._decimal(payables.balance) != amount
                        or payment.move_id != payment_move
                        or payment.company_id != company
                        or payment_move.company_id != company
                        or payment.payment_type != 'outbound'
                        or payment.partner_type != 'supplier'
                        or payment.state not in ('in_process', 'paid')
                        or payment.currency_id != company.currency_id
                        or payment.date > statement.date
                        or statement.partner_id != payment.partner_id
                        or payment.outstanding_account_id != counterpart.account_id):
                    excluded['unproven_outstanding_allocation'] += 1
                    continue
                payable_debit = payables
            else:
                # A direct payable bank debit could be an advance reconciled
                # later. Without contemporaneous payment provenance it is not
                # supported by this narrow source slice.
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
            bill_line.account_id.check_access('read')
            bill_lines = bill.line_ids
            self._assert_visible(
                'account_move_line', 'move_id=%s', [bill.id], bill_lines,
            )
            if (bill.state != 'posted' or bill.move_type != 'in_invoice'
                    or bill.company_id != company or bill.currency_id != company.currency_id
                    or not bill.invoice_date or bill.invoice_date > statement.date
                    or bill_line.account_id != payable_debit.account_id
                    or payment.partner_id != bill.partner_id):
                excluded['unsupported_purchase_bill'] += 1
                continue
            bill_sections = {key: {} for key in SECTION_KEYS}
            bill_excluded = Counter()
            line_entries = []
            self._invoice_amounts(
                bill, company, bill_sections, bill_excluded, line_entries,
            )
            source_lines = bill.invoice_line_ids.filtered(
                lambda line: line.display_type == 'product',
            )
            if (not line_entries or len(line_entries) != len(source_lines)
                    or any(kind not in EXPENSE_KEYS or gross <= 0
                           for _line_id, kind, _account, gross in line_entries)
                    or bill_excluded.get('non_pl_invoice_lines')
                    or bill_excluded.get('unsupported_negative_tax_lines')
                    or bill_excluded.get('tax_only_invoice_lines')
                    or sum((item[3] for item in line_entries), Decimal('0'))
                    != self._decimal(bill.amount_total)):
                excluded['unsupported_purchase_bill'] += 1
                continue
            total = self._decimal(bill.amount_total)
            prior = cumulative.get(bill.id, Decimal('0'))
            after = prior + amount
            if after > total:
                self._deny_incomplete_source()
            cumulative[bill.id] = after
            line_entries.sort(key=lambda item: item[0])
            allocations = self._allocate_purchase_event(
                [item[3] for item in line_entries], prior, amount,
                company.currency_id,
            )
            if start <= statement.date <= end:
                for (invoice_line_id, section, account, _gross), allocated in zip(
                        line_entries, allocations, strict=True):
                    if allocated:
                        self._record(
                            sections, section, account, allocated,
                            'bank_statement',
                            {'source_model': 'account.bank.statement.line',
                             'source_id': statement.id,
                             'line_model': 'account.move.line',
                             'line_id': invoice_line_id,
                             'date': fields.Date.to_string(statement.date)},
                        )
        return recognized_direct

    @api.model
    def _batch_purchase_outflows(self, company, start, end, journal_ids,
                                 sections, excluded):
        """Count only an approved Baseer row that created its own cash payment."""
        domain = [
            ('company_id', '=', company.id),
            ('batch_id.state', '=', 'approved'),
            ('payment_id', '!=', False),
        ]
        self.env['baseer.purchase.batch.line'].flush_model([
            'company_id', 'batch_id', 'payment_id',
        ])
        self.env['baseer.purchase.batch'].flush_model(['state'])
        # Users without purchase-batch ACL may still read a report period
        # with no batch source. If a source exists, never silently omit it.
        self.env.cr.execute(
            'SELECT l.id FROM baseer_purchase_batch_line l '
            'JOIN baseer_purchase_batch b ON b.id=l.batch_id '
            'WHERE l.company_id=%s AND l.payment_id IS NOT NULL '
            'AND b.state=%s',
            [company.id, 'approved'],
        )
        source_ids = {row[0] for row in self.env.cr.fetchall()}
        if not source_ids:
            return
        self._require_read((
            'baseer.purchase.batch', 'baseer.purchase.batch.line',
            'account.payment.method.line',
        ))
        source = self.env['baseer.purchase.batch.line'].search(domain, order='id')
        if set(source.ids) != source_ids:
            self._deny_incomplete_source()
        source.check_access('read')
        seen_payments = set()
        seen_bills = set()
        for line in source:
            batch = line.batch_id
            batch.check_access('read')
            bill = line.move_id
            payment = line.payment_id
            bill.check_access('read')
            payment.check_access('read')
            line.partner_id.check_access('read')
            bill.partner_id.check_access('read')
            payment.partner_id.check_access('read')
            method = line.payment_method_line_id
            method.check_access('read')
            journal = method.journal_id
            journal.check_access('read')
            liquidity_account = journal.default_account_id
            liquidity_account.check_access('read')
            payment_move = payment.move_id
            payment_move.check_access('read')
            if bill.id in seen_bills or payment.id in seen_payments:
                self._deny_incomplete_source()
            seen_bills.add(bill.id)
            seen_payments.add(payment.id)
            if payment_move and payment_move.date != line.invoice_date:
                self._deny_incomplete_source()
            if bill and payment_move:
                self._assert_visible(
                    'account_move', 'reversed_entry_id=%s', [bill.id],
                    bill.reversal_move_ids,
                )
                self._assert_visible(
                    'account_move', 'reversed_entry_id=%s',
                    [payment_move.id], payment_move.reversal_move_ids,
                )
            if (batch.company_id != company
                    or line.company_id != company or batch.state != 'approved'
                    or line.batch_id != batch or line.is_credit
                    or not bill or not payment_move or not method
                    or bill.company_id != company or bill.state != 'posted'
                    or bill.move_type != 'in_invoice'
                    or bill.currency_id != company.currency_id
                    or not bill.invoice_date or bill.invoice_date != line.invoice_date
                    or bill.partner_id != line.partner_id
                    or payment.company_id != company
                    or payment.partner_id != line.partner_id
                    or payment.payment_type != 'outbound'
                    or payment.partner_type != 'supplier'
                    or payment.state != 'paid'
                    or payment.currency_id != company.currency_id
                    or payment.move_id != payment_move
                    or payment_move.state != 'posted'
                    or payment_move.company_id != company
                    or payment_move.origin_payment_id != payment
                    or payment_move.statement_line_id
                    or payment.journal_id != journal
                    or payment_move.journal_id != journal
                    or payment.payment_method_line_id != method
                    or method.company_id != company or method.code != 'manual'
                    or method.payment_type != 'outbound'
                    or journal.company_id != company
                    or journal.type not in ('bank', 'cash')
                    or (journal.currency_id
                        and journal.currency_id != company.currency_id)
                    or liquidity_account.account_type != 'asset_cash'
                    or method.payment_account_id != liquidity_account
                    or payment.outstanding_account_id != liquidity_account
                    or bill.reversed_entry_id or payment_move.reversed_entry_id
                    or bill.reversal_move_ids or payment_move.reversal_move_ids):
                excluded['unsupported_batch_cash_payment'] += 1
                continue
            bill_lines = bill.line_ids
            payment_lines = payment_move.line_ids
            self._assert_visible('account_move_line', 'move_id=%s',
                                 [bill.id], bill_lines)
            self._assert_visible('account_move_line', 'move_id=%s',
                                 [payment_move.id], payment_lines)
            bill_lines.mapped('account_id').check_access('read')
            payment_lines.mapped('account_id').check_access('read')
            if any(item.company_id != company or item.move_id != payment_move
                   or item.journal_id != journal
                   or item.currency_id != company.currency_id
                   for item in payment_lines):
                self._deny_incomplete_source()
            for tax_line in bill_lines.filtered('tax_line_id'):
                tax = tax_line.tax_line_id
                repartition = tax_line.tax_repartition_line_id
                tax.check_access('read')
                repartition.check_access('read')
                if (not repartition or repartition.tax_id != tax
                        or repartition not in tax.invoice_repartition_line_ids):
                    self._deny_incomplete_source()
            liquidity = payment_lines.filtered(
                lambda item: item.account_id == liquidity_account,
            )
            paid_payable = payment_lines.filtered(
                lambda item: item.account_id.account_type == 'liability_payable',
            )
            bill_payable = bill_lines.filtered(
                lambda item: item.account_id.account_type == 'liability_payable',
            )
            total = self._decimal(bill.amount_total)
            if (len(payment_lines) != 2 or len(liquidity) != 1
                    or len(paid_payable) != 1 or len(bill_payable) != 1
                    or self._decimal(liquidity.balance) != -total
                    or self._decimal(paid_payable.balance) != total
                    or self._decimal(bill_payable.balance) != -total
                    or paid_payable.account_id != bill_payable.account_id
                    or self._decimal(bill.amount_residual) != 0
                    or bill.payment_state != 'paid'):
                excluded['unsupported_batch_cash_payment'] += 1
                continue
            partials = paid_payable.matched_credit_ids
            self._assert_visible('account_partial_reconcile',
                                 'debit_move_id=%s', [paid_payable.id], partials)
            self._assert_visible('account_partial_reconcile',
                                 'credit_move_id=%s', [bill_payable.id],
                                 bill_payable.matched_debit_ids)
            if (len(partials) != 1 or partials != bill_payable.matched_debit_ids
                    or partials.credit_move_id != bill_payable
                    or self._decimal(partials.amount) != total):
                excluded['unsupported_batch_cash_payment'] += 1
                continue
            bill_sections = {key: {} for key in SECTION_KEYS}
            bill_excluded = Counter()
            line_entries = []
            self._invoice_amounts(
                bill, company, bill_sections, bill_excluded, line_entries,
            )
            if (len(line_entries) != 1 or line_entries[0][1] not in EXPENSE_KEYS
                    or line_entries[0][3] != total
                    or bill_excluded.get('non_pl_invoice_lines')
                    or bill_excluded.get('unsupported_negative_tax_lines')
                    or bill_excluded.get('tax_only_invoice_lines')):
                excluded['unsupported_batch_cash_payment'] += 1
                continue
            if journal_ids and journal.id not in journal_ids:
                continue
            if start <= payment_move.date <= end:
                invoice_line_id, section, account, amount = line_entries[0]
                self._record(
                    sections, section, account, amount,
                    'baseer_batch_direct_payment',
                    {'source_model': 'baseer.purchase.batch.line',
                     'source_id': line.id,
                     'line_model': 'account.move.line',
                     'line_id': invoice_line_id,
                     'payment_move_id': payment_move.id,
                     'payment_line_id': liquidity.id,
                     'date': fields.Date.to_string(payment_move.date)},
                )

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
    def _period_sources(self, company, start, end, journal_ids):
        """One calculation path for totals and non-public event evidence."""
        sections = {key: {} for key in SECTION_KEYS}
        excluded = Counter()
        for move in self._invoice_records(company, start, end, journal_ids):
            self._invoice_amounts(move, company, sections, excluded)
        for order in self._pos_records(company, start, end, journal_ids):
            self._pos_amounts(order, company, sections, excluded)
        recognized_direct = self._purchase_outflows(
            company, start, end, journal_ids, sections, excluded,
        )
        self._batch_purchase_outflows(
            company, start, end, journal_ids, sections, excluded,
        )
        excluded['direct_aml_unproven'] = self._direct_exclusions(
            company, start, end, journal_ids, recognized_direct,
        )
        for section in sections.values():
            for entry in section.values():
                if (entry['count'] != len(entry['events'])
                        or entry['raw'] != sum(
                            (event['amount'] for event in entry['events']),
                            Decimal('0'),
                        )):
                    self._deny_incomplete_source()
        return sections, excluded

    @api.model
    def get_source_snapshot(self, filters):
        """Internal source evidence only. Never expose it as a complete report."""
        company, journal_ids, periods, period_control, comparison_control = self._scope(filters)
        payload_periods = []
        for period in periods:
            start = fields.Date.to_date(period['date_from'])
            end = fields.Date.to_date(period['date_to'])
            sections, excluded = self._period_sources(
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
            'scope': 'limited_proven_sales_and_cash_outflows',
            'not_accounting_profit': True,
            'company_id': company.id,
            'currency_code': company.currency_id.name,
            'period_controls': period_control,
            'comparison_controls': comparison_control,
            'periods': payload_periods,
        }
