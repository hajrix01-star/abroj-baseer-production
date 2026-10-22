"""Read-only native POS accounting witnesses; never a second sale event."""
from collections import Counter
from decimal import Decimal

from odoo import api, fields, models

from odoo.addons.baseer_profit_loss_report.models.profit_loss import SECTION_KEYS


class OperationsPosEvidence(models.AbstractModel):
    _inherit = 'baseer.operations.report'

    def _pos_evidence_money(self, value, company):
        return Decimal(self.env['baseer.profit.loss.report']._format_money(
            self._decimal(value), company.currency_id).replace(',', ''))

    def _pos_evidence_taxes(self, records):
        """Prove the raw M2M membership and every native group child first."""
        records.check_access('read')
        records.flush_recordset(['tax_ids'])
        relation = records._fields['tax_ids']
        self.env.cr.execute('SELECT "%s", "%s" FROM "%s" WHERE "%s"=ANY(%%s)' % (
            relation.column1, relation.column2, relation.relation, relation.column1), [records.ids])
        pairs = set(self.env.cr.fetchall())
        if pairs != {(row.id, tax.id) for row in records for tax in row.tax_ids}:
            self._deny_incomplete_source()
        tax_model = self.env['account.tax']
        return self._pos_evidence_tax_graph(tax_model.browse(sorted({tax for _, tax in pairs})))

    def _pos_evidence_tax_graph(self, taxes):
        """Normal-user proof also used for fiscal-position mapped base taxes."""
        tax_model = self.env['account.tax']
        pending = tax_model.browse(taxes.ids)
        child_field = tax_model._fields['children_tax_ids']
        tax_model.flush_model(['children_tax_ids'])
        checked = set()
        while pending:
            pending.check_access('read')
            checked.update(pending.ids)
            if len(checked) > 100000:
                self._deny_incomplete_source()
            groups = pending.filtered(lambda tax: tax.amount_type == 'group')
            self.env.cr.execute('SELECT "%s" FROM "%s" WHERE "%s"=ANY(%%s)' % (
                child_field.column2, child_field.relation, child_field.column1), [groups.ids])
            children = {row[0] for row in self.env.cr.fetchall()}
            pending = tax_model.browse(sorted(children - checked))
        return tax_model.browse(sorted(checked))

    def _pos_evidence_repartition(self, taxes, refund):
        """A hidden repartition must fail before native allocation uses it."""
        taxes.check_access('read')
        if not taxes:
            return
        name = 'refund_repartition_line_ids' if refund else 'invoice_repartition_line_ids'
        inverse = taxes._fields[name].inverse_name
        records = taxes[name]
        records.check_access('read')
        # Odoo 19 shares tax_id for both One2many fields; their document_type
        # domain is part of membership, not an ACL filter to omit here.
        self.env['account.tax.repartition.line'].flush_model([inverse, 'document_type'])
        self.env.cr.execute(
            ('SELECT "%s", id FROM account_tax_repartition_line '
             'WHERE "%s"=ANY(%%s) AND document_type=%%s') % (inverse, inverse),
            [taxes.ids, 'refund' if refund else 'invoice'],
        )
        if set(self.env.cr.fetchall()) != {(record[inverse].id, record.id) for record in records}:
            self._deny_incomplete_source()

    def _pos_evidence_partials(self, line):
        partials = line.matched_debit_ids | line.matched_credit_ids
        self._assert_visible('account_partial_reconcile',
                             'debit_move_id=%s OR credit_move_id=%s',
                             [line.id, line.id], partials)
        return partials

    def _pos_evidence_lines(self, move, company):
        move.check_access('read')
        lines = move.line_ids
        self.env['account.move.line'].flush_model(['move_id'])
        self._assert_visible('account_move_line', 'move_id=%s', [move.id], lines)
        if len(lines) > 100000:
            self._deny_incomplete_source()
        lines.account_id.check_access('read')
        lines.tax_ids.check_access('read')
        lines.tax_line_id.check_access('read')
        lines.tax_repartition_line_id.check_access('read')
        lines.tax_tag_ids.check_access('read')
        self._pos_evidence_taxes(lines)
        if (move.company_id != company or move.state != 'posted'
                or move.currency_id != company.currency_id
                or any(line.company_id != company or line.move_id != move
                       or line.journal_id != move.journal_id
                       or line.currency_id != company.currency_id
                       or self._decimal(line.amount_currency) != self._decimal(line.balance)
                       for line in lines)
                or sum((self._decimal(line.balance) for line in lines), Decimal(0))):
            self._deny_incomplete_source()
        return lines

    @staticmethod
    def _pos_evidence_key(account, tax_ids, tags, product, repartition, tax, balance):
        if repartition:
            return ('tax', account, repartition, tax, tuple(sorted(tags)))
        return ('base', account, tuple(sorted(tax_ids)), tuple(sorted(tags)),
                product or False, 1 if balance > 0 else -1)

    def _pos_posted_vector(self, move, company):
        vector = {}
        for line in self._pos_evidence_lines(move, company):
            if not line.tax_line_id and line.account_id.account_type not in SECTION_KEYS:
                continue
            balance = self._decimal(line.balance)
            key = self._pos_evidence_key(
                line.account_id.id, line.tax_ids.ids, line.tax_tag_ids.ids,
                line.product_id.id, line.tax_repartition_line_id.id,
                line.tax_line_id.id, balance)
            # Native closing has one row per accounting group. Do not accept
            # an extra opposite pair merely because its net is zero.
            if key in vector:
                return None
            vector[key] = (balance, self._pos_evidence_money(line.tax_base_amount, company)
                           if line.tax_line_id else Decimal(0))
        return {key: value for key, value in vector.items() if value != (0, 0)}

    def _pos_expected_vector(self, session, company):
        orders = session.order_ids
        self.env['pos.order'].flush_model(['session_id'])
        self._assert_visible('pos_order', 'session_id=%s', [session.id], orders)
        eligible = orders.filtered(lambda order: order.state in ('paid', 'done', 'invoiced'))
        if len(eligible) > 100000:
            self._deny_incomplete_source()
        vector = {}
        source_values = []
        tax_model = self.env['account.tax']
        for order in eligible:
            if (order.company_id != company or order.session_id != session
                    or order.config_id != session.config_id
                    or order.currency_id != company.currency_id
                    or order.source not in ('pos', 'baseer_summary')
                    or (order.source == 'pos' and not order.date_order)):
                return None
        # Prove the complete eligible set (including sources outside the
        # display period) in one read batch, retaining native per-order math.
        self._pos_amounts(eligible, company, {key: {} for key in SECTION_KEYS}, Counter())
        order_bases = []
        for order in eligible:
            if order.is_invoiced:
                # A later invoice reverses a sale already posted by closing.
                # The current invoice flag alone cannot reconstruct that
                # historical native subset. Require its real reversal graph.
                reversals = order.reversed_move_ids
                inverse = order._fields['reversed_move_ids'].inverse_name
                self.env['account.move'].flush_model([inverse])
                self._assert_visible('account_move', inverse+'=%s', [order.id], reversals)
                if not reversals:
                    continue
                reversal_lines = self.env['account.move.line']
                for reversal in reversals:
                    reversal_lines |= self._pos_evidence_lines(reversal, company)
                if self._proven_pos_invoice_reversal_lines(company, reversal_lines) != set(reversal_lines.ids):
                    return None
            if not order.lines:
                continue
            bases = order.with_context(linked_to_pos=True)._prepare_tax_base_line_values()
            order_bases.append(bases)
        # Fiscal positions may substitute taxes absent from the display
        # line's M2M. Prove the actual native bases, including group children,
        # before native accounting can filter a hidden repartition to empty.
        for refund in (False, True):
            actual_taxes = tax_model.browse(sorted({
                tax.id for bases in order_bases for base in bases
                if bool(base['is_refund']) == refund for tax in base['tax_ids']
            }))
            self._pos_evidence_repartition(self._pos_evidence_tax_graph(actual_taxes), refund)
        for bases in order_bases:
            tax_model._add_tax_details_in_base_lines(bases, company)
            tax_model._round_base_lines_tax_details(bases, company)
            tax_model._add_accounting_data_in_base_lines_tax_details(
                bases, company, include_caba_tags=True)
            prepared = tax_model._prepare_tax_lines(bases, company)
            values = []
            for base, update in prepared['base_lines_to_update']:
                values.append(session._get_sale_vals(session._get_sale_key(base), {
                    'amount': update['amount_currency'],
                    'amount_converted': update['balance'], 'quantity': base['quantity'],
                }))
            for tax in prepared['tax_lines_to_add']:
                key = (tax['account_id'], tax['tax_repartition_line_id'],
                       tuple(tax['tax_tag_ids'][0][2]))
                values.append(session._get_tax_vals(
                    key, tax['amount_currency'], tax['balance'], tax['tax_base_amount']))
            source_values.extend(values)
        # Prove all native accounting targets in the caller's environment
        # before reading their classification. Keep every row and its order;
        # tax calculations/rounding above are still independent per order.
        accounts = self.env['account.account'].browse(sorted({
            value['account_id'] for value in source_values
        }))
        reps = self.env['account.tax.repartition.line'].browse(sorted({
            value['tax_repartition_line_id'] for value in source_values
            if value.get('tax_repartition_line_id')
        }))
        accounts.check_access('read')
        reps.check_access('read')
        reps.tax_id.check_access('read')
        account_map = {account.id: account for account in accounts}
        rep_map = {rep.id: rep for rep in reps}
        for value in source_values:
            account = account_map[value['account_id']]
            rep = rep_map.get(value.get('tax_repartition_line_id'))
            if not rep and account.account_type not in SECTION_KEYS:
                return None
            balance = self._pos_evidence_money(value['balance'], company)
            key = self._pos_evidence_key(
                account.id, value.get('tax_ids', [(6, 0, [])])[0][2],
                value.get('tax_tag_ids', [(6, 0, [])])[0][2],
                value.get('product_id'), rep.id if rep else False,
                rep.tax_id.id if rep else False, balance)
            amount, base_amount = vector.get(key, (Decimal(0), Decimal(0)))
            vector[key] = (amount + balance, base_amount + (
                self._pos_evidence_money(value['tax_base_amount'], company)
                if rep else Decimal(0)))
        return {key: value for key, value in vector.items() if value != (0, 0)}

    def _pos_adjustment_link(self, move, company):
        """An exact FK accounting witness, not an amount/reference heuristic."""
        if (move.company_id != company or move.state != 'posted'
                or move.move_type != 'entry' or move.journal_id.type != 'general'):
            return None
        self._assert_visible('account_move', 'reversed_entry_id=%s', [move.id], move.reversal_move_ids)
        self._assert_visible('pos_order', 'account_move=%s', [move.id], move.pos_order_ids)
        if (move.origin_payment_id or move.statement_line_id or move.pos_order_ids
                or move.reversed_entry_id or move.reversal_move_ids):
            return None
        lines = self._pos_evidence_lines(move, company)
        counter = lines.filtered(lambda line: line.account_id.account_type == 'asset_receivable')
        if (len(counter) != 1 or counter.balance <= 0 or not counter.reconciled
                or not counter.full_reconcile_id or counter.tax_ids
                or counter.tax_line_id or counter.tax_tag_ids
                or any(line.account_id.account_type == 'asset_cash' for line in lines)
                or any(line != counter and not line.tax_line_id
                       and line.account_id.account_type not in SECTION_KEYS for line in lines)):
            return None
        partials = counter.matched_debit_ids | counter.matched_credit_ids
        self._assert_visible('account_partial_reconcile',
                             'debit_move_id=%s OR credit_move_id=%s',
                             [counter.id, counter.id], partials)
        if len(partials) != 1 or partials.debit_move_id != counter:
            return None
        original = partials.credit_move_id
        original.check_access('read')
        original.move_id.check_access('read')
        full = counter.full_reconcile_id
        full.check_access('read')
        linked = full.reconciled_line_ids
        self._assert_visible('account_move_line', 'full_reconcile_id=%s', [full.id], linked)
        other_partials = original.matched_debit_ids | original.matched_credit_ids
        self._assert_visible('account_partial_reconcile',
                             'debit_move_id=%s OR credit_move_id=%s',
                             [original.id, original.id], other_partials)
        if (linked != (counter | original) or partials != other_partials
                or original.company_id != company or original.account_id != counter.account_id
                or original.partner_id != counter.partner_id
                or original.full_reconcile_id != full or not original.reconciled
                or original.tax_ids or original.tax_line_id or original.tax_tag_ids
                or self._decimal(original.balance) != -self._decimal(counter.balance)
                or self._decimal(partials.amount) != self._decimal(counter.balance)
                or original.amount_residual or counter.amount_residual
                or move.journal_id != original.move_id.journal_id):
            return None
        sessions = self.env['pos.session'].search([
            ('company_id', '=', company.id), ('move_id', '=', original.move_id.id)])
        self._assert_visible('pos_session', 'config_id IN (SELECT id FROM pos_config WHERE company_id=%s) AND move_id=%s',
                             [company.id, original.move_id.id], sessions)
        return sessions if len(sessions) == 1 else None

    @api.model
    def _proven_pos_secondary_lines(self, company, candidate_lines):
        moves = candidate_lines.move_id
        if not moves:
            return set()
        sessions = self.env['pos.session'].search([
            ('company_id', '=', company.id), ('move_id', 'in', moves.ids)])
        self._assert_visible('pos_session', 'config_id IN (SELECT id FROM pos_config WHERE company_id=%s) AND move_id = ANY(%s)',
                             [company.id, moves.ids], sessions)
        for move in moves:
            linked = self._pos_adjustment_link(move, company)
            if linked:
                sessions |= linked
        proven = set()
        for session in sessions:
            session.check_access('read')
            session.config_id.check_access('read')
            if (session.state != 'closed' or session.company_id != company
                    or session.move_id.state != 'posted'
                    or session.config_id.journal_id != session.move_id.journal_id
                    or session.currency_id != company.currency_id
                    or session.config_id.cash_rounding):
                continue
            expected = self._pos_expected_vector(session, company)
            original = self._pos_posted_vector(session.move_id, company)
            if expected is None or original is None or not expected:
                continue
            approved = session.move_id
            if original != expected:
                adjustments = self.env['account.move']
                for counter in session.move_id.line_ids.filtered(
                        lambda line: line.account_id.account_type == 'asset_receivable'
                        and line.balance < 0 and line.full_reconcile_id):
                    full = counter.full_reconcile_id
                    full.check_access('read')
                    linked = full.reconciled_line_ids
                    self._assert_visible('account_move_line', 'full_reconcile_id=%s', [full.id], linked)
                    for move in linked.move_id - session.move_id:
                        if self._pos_adjustment_link(move, company) == session:
                            adjustments |= move
                if len(adjustments) != 1:
                    continue
                extra = self._pos_posted_vector(adjustments, company)
                if extra is None:
                    continue
                combined = dict(original)
                for key, (amount, base) in extra.items():
                    old_amount, old_base = combined.get(key, (Decimal(0), Decimal(0)))
                    combined[key] = (old_amount + amount, old_base + base)
                combined = {key: value for key, value in combined.items() if value != (0, 0)}
                if combined != expected:
                    continue
                approved |= adjustments
            proven.update((candidate_lines & approved.line_ids).ids)
        return proven

    def _pos_variance_session(self, session, company):
        session.check_access('read')
        if (not session or session.company_id != company or session.state != 'closed'
                or session.currency_id != company.currency_id or not session.move_id
                or session.move_id.state != 'posted'):
            return False
        session.move_id.check_access('read')
        return True

    @api.model
    def _native_pos_variance_inflows(self, company, start, end, journal_ids,
                                     sections, excluded):
        """Proven native counting/receipt differences, not new POS sales.

        Only posted company-currency asset_cash inflows without tax lines are
        supported. An inbound payment remains unconfirmed bank settlement.
        """
        domain = [('company_id', '=', company.id), ('parent_state', '=', 'posted'),
                  ('move_id.move_type', '=', 'entry'), ('date', '>=', start),
                  ('date', '<=', end), ('account_id.account_type', '=', 'income_other')]
        if journal_ids:
            domain.append(('journal_id', 'in', journal_ids))
        candidates = self.env['account.move.line'].search(domain, limit=100001)
        if len(candidates) > 100000:
            self._deny_incomplete_source()
        sql = ("aml.company_id=%s AND aml.parent_state='posted' AND m.move_type='entry' "
               "AND aml.date >= %s AND aml.date <= %s AND a.account_type='income_other'")
        args = [company.id, start, end]
        if journal_ids:
            sql += ' AND aml.journal_id = ANY(%s)'
            args.append(journal_ids)
        self.env['account.move.line'].flush_model(['move_id', 'date', 'company_id', 'account_id', 'parent_state'])
        self.env.cr.execute('SELECT aml.id FROM account_move_line aml JOIN account_move m '
                            'ON m.id=aml.move_id JOIN account_account a ON a.id=aml.account_id WHERE '+sql, args)
        if {row[0] for row in self.env.cr.fetchall()} != set(candidates.ids):
            self._deny_incomplete_source()
        candidates.check_access('read')
        recognized = set()
        for profit in candidates:
            move, journal = profit.move_id, profit.journal_id
            journal.check_access('read')
            journal.profit_account_id.check_access('read')
            if (profit.balance >= 0 or journal.type not in ('cash', 'bank')
                    or journal.company_id != company or journal.profit_account_id != profit.account_id
                    or (journal.currency_id and journal.currency_id != company.currency_id)
                    or move.reversed_entry_id or move.reversal_move_ids):
                continue
            self._assert_visible('account_move', 'reversed_entry_id=%s',
                                 [move.id], move.reversal_move_ids)
            lines = self._pos_evidence_lines(move, company)
            if (any(line.tax_ids or line.tax_line_id or line.tax_tag_ids for line in lines)
                    or profit.account_id.reconcile
                    or self._pos_evidence_partials(profit)):
                continue
            liquidity = lines.filtered(lambda line: line.account_id.account_type == 'asset_cash')
            if (len(liquidity) != 1 or liquidity.balance <= 0
                    or self._pos_evidence_partials(liquidity)):
                continue
            amount = -self._decimal(profit.balance)
            statement, payment = move.statement_line_id, move.origin_payment_id
            statement.check_access('read')
            payment.check_access('read')
            if statement and not payment:
                session = statement.pos_session_id
                if (not self._pos_variance_session(session, company)
                        or journal.type != 'cash' or session.cash_journal_id != journal
                        or statement.move_id != move or statement.journal_id != journal
                        or statement.date != move.date or statement.company_id != company
                        or statement.foreign_currency_id or statement.payment_ids
                        or len(lines) != 2 or liquidity.account_id != journal.default_account_id
                        or self._decimal(statement.amount) != amount
                        or self._decimal(liquidity.balance) != amount
                        or self._pos_evidence_money(session.cash_register_difference, company) != amount):
                    continue
                self._assert_visible('account_bank_statement_line', 'move_id=%s', [move.id], statement)
                all_statements = session.statement_line_ids
                self._assert_visible('account_bank_statement_line', 'pos_session_id=%s',
                                     [session.id], all_statements)
                for peer in all_statements.filtered(lambda row: row.move_id.state == 'posted'
                                                    and row.journal_id == journal):
                    self._pos_evidence_lines(peer.move_id, company)
                peers = all_statements.filtered(lambda row: row.move_id.state == 'posted'
                    and row.journal_id == journal and row.move_id.line_ids.filtered(
                        lambda line: line.account_id == journal.profit_account_id))
                peers.move_id.line_ids.check_access('read')
                if peers != statement:
                    continue
                source_model, source_id, source = 'account.bank.statement.line', statement.id, 'native_pos_cash_variance'
                link_status = 'counted'
            elif payment and not statement:
                session, method = payment.pos_session_id, payment.pos_payment_method_id
                method.check_access('read')
                if (not self._pos_variance_session(session, company) or not method
                        or method.company_id != company or method not in session.payment_method_ids
                        or payment.company_id != company or payment.currency_id != company.currency_id
                        or payment.state not in ('in_process', 'paid')
                        or payment.payment_type != 'inbound' or payment.partner_type != 'customer'
                        or payment.move_id != move or payment.date != move.date
                        or payment.journal_id != journal or method.journal_id != journal
                        or method.type != 'bank' or method.split_transactions or len(lines) != 3
                        or payment.outstanding_account_id != liquidity.account_id
                        or self._decimal(payment.amount) != self._decimal(liquidity.balance)):
                    continue
                bank_payments = session.bank_payment_ids.filtered(lambda row: row.pos_payment_method_id == method)
                self._assert_visible('account_payment', 'pos_session_id=%s AND pos_payment_method_id=%s',
                                     [session.id, method.id], bank_payments)
                if bank_payments != payment:
                    continue
                orders = session.order_ids.filtered(lambda order: order.state in ('paid', 'done', 'invoiced'))
                self._assert_visible('pos_order', 'session_id=%s AND state IN %s',
                                     [session.id, ('paid', 'done', 'invoiced')], orders)
                sources = orders.payment_ids.filtered(lambda row: row.payment_method_id == method)
                self._assert_visible('pos_payment', 'pos_order_id=ANY(%s) AND payment_method_id=%s',
                                     [orders.ids, method.id], sources)
                if (any(order.company_id != company or order.session_id != session
                        or order.config_id != session.config_id
                        or order.currency_id != company.currency_id for order in orders)
                        or any(row.pos_order_id not in orders or row.payment_method_id != method
                               or row.currency_id != company.currency_id for row in sources)):
                    continue
                self._pos_evidence_lines(session.move_id, company)
                if self._pos_expected_vector(session, company) is None:
                    continue
                source_amount = sum((self._decimal(row.amount) for row in sources), Decimal(0))
                receivable = lines.filtered(lambda row: row.account_id.account_type == 'asset_receivable')
                if (not sources or len(receivable) != 1 or source_amount <= 0
                        or self._decimal(receivable.balance) != -source_amount
                        or self._decimal(liquidity.balance) != source_amount + amount
                        or not receivable.reconciled or not receivable.full_reconcile_id):
                    continue
                partials = receivable.matched_debit_ids | receivable.matched_credit_ids
                self._assert_visible('account_partial_reconcile',
                                     'credit_move_id=%s OR debit_move_id=%s',
                                     [receivable.id, receivable.id], partials)
                if len(partials) != 1 or partials.credit_move_id != receivable:
                    continue
                original = partials.debit_move_id
                original.check_access('read')
                full = receivable.full_reconcile_id
                full.check_access('read')
                linked = full.reconciled_line_ids
                self._assert_visible('account_move_line', 'full_reconcile_id=%s', [full.id], linked)
                original_partials = self._pos_evidence_partials(original)
                if (linked != (receivable | original) or original.move_id != session.move_id
                        or original.account_id != receivable.account_id
                        or original.company_id != company or original.full_reconcile_id != full
                        or original.currency_id != company.currency_id
                        or self._decimal(original.amount_currency) != self._decimal(original.balance)
                        or original_partials != partials or not original.reconciled
                        or original.amount_residual or receivable.amount_residual
                        or self._decimal(original.balance) != source_amount
                        or self._decimal(partials.amount) != source_amount):
                    continue
                native = session._get_diff_vals(method.id, float(amount), payment.outstanding_account_id)
                if (not native or native[0]['account_id'] != liquidity.account_id.id
                        or native[1]['account_id'] != profit.account_id.id
                        or self._pos_evidence_money(native[0]['balance'] if 'balance' in native[0]
                            else native[0].get('debit', 0)-native[0].get('credit', 0), company) != amount
                        or self._pos_evidence_money(native[1]['balance'] if 'balance' in native[1]
                            else native[1].get('debit', 0)-native[1].get('credit', 0), company) != -amount):
                    continue
                source_model, source_id, source = 'account.payment', payment.id, 'native_pos_bank_variance'
                link_status = 'unconfirmed'
                excluded['unconfirmed_payment_link'] += 1
            else:
                continue
            self._record(sections, 'income_other', profit.account_id, amount, source, {
                'source_model': source_model, 'source_id': source_id,
                'line_model': 'account.move.line', 'line_id': profit.id,
                'date': fields.Date.to_string(move.date), 'payment_move_id': move.id,
                'liquidity_line_id': liquidity.id, 'pos_session_id': session.id,
                'link_status': link_status,
            })
            recognized.add(profit.id)
        return recognized
