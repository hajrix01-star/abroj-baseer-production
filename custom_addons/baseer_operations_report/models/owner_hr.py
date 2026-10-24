"""Private HR cash facts, proved from stored native accounting links.

Salary accruals, deductions, outstanding payments and correction totals are not
cash. Claims are invocation-local and are emitted only after the whole source
has passed normal-user visibility and exact conservation checks.
"""

from collections import Counter
from decimal import Decimal, localcontext

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


OWNER_HR_CENSUS_BATCH_SIZE = 1000


class OperationsOwnerHr(models.AbstractModel):
    _inherit = 'baseer.operations.report'

    @staticmethod
    def _owner_hr_id_chunks(ids):
        """Keep inverse-link census parameters bounded without changing scope."""
        for offset in range(0, len(ids), OWNER_HR_CENSUS_BATCH_SIZE):
            yield ids[offset:offset + OWNER_HR_CENSUS_BATCH_SIZE]

    def _owner_hr_candidate_moves(self, liquidity, *, loans_available, salary_available):
        """Census HR inverse links once, without accepting any financial fact.

        The three native validators below deliberately prove both the declared
        relation and its raw inverse for one cash move.  Repeating their empty
        inverse probes for every ordinary cash move made imported history
        scale with the number of unrelated liquidity lines.  This helper is
        only a request-local gate: a move is merely selected for the existing
        validator when either side of a native link exists.  Validators retain
        all cardinality, ACL, company, amount, and reversal checks.
        """
        moves = liquidity.move_id
        if not moves:
            return set(), set(), set()
        move_ids = moves.ids

        def inverse_moves(model_name, table):
            model = self.env[model_name]
            model.flush_model(['move_id'])
            result = set()
            for batch in self._owner_hr_id_chunks(move_ids):
                self.env.cr.execute(
                    'SELECT move_id FROM %s WHERE move_id=ANY(%%s)' % table,
                    [batch],
                )
                result.update(row[0] for row in self.env.cr.fetchall())
            return result

        loan_moves = set()
        if loans_available:
            loan_moves = inverse_moves('baseer.hr.loan', 'baseer_hr_loan')
            loan_moves.update(move.id for move in moves if move.baseer_loan_id)

        statement_moves = payment_moves = set()
        if salary_available:
            statement_moves = inverse_moves(
                'account.bank.statement.line', 'account_bank_statement_line')
            statement_moves.update(move.id for move in moves if move.statement_line_id)
            payment_moves = inverse_moves('account.payment', 'account_payment')
            payment_moves.update(move.id for move in moves if move.origin_payment_id)
        return loan_moves, statement_moves, payment_moves

    def _owner_hr_reversed(self, moves):
        """A visible reversal is unsupported; a hidden inverse is denied."""
        moves.check_access('read')
        moves.reversed_entry_id.check_access('read')
        reversals = self._owner_sales_pairs(
            moves, 'reversal_move_ids', 'account.move', 'reversed_entry_id')
        return bool(reversals or moves.reversed_entry_id)

    def _owner_hr_move_lines(self, move, company):
        move.check_access('read')
        move.journal_id.check_access('read')
        move.currency_id.check_access('read')
        if (move.company_id != company or move.state != 'posted'
                or move.currency_id != company.currency_id
                or move.journal_id.company_id != company):
            self._deny_incomplete_source()
        lines = self._owner_sales_pairs(move, 'line_ids', 'account.move.line', 'move_id')
        lines.account_id.check_access('read')
        lines.partner_id.check_access('read')
        total = Decimal(0)
        for line in lines:
            if (line.company_id != company or line.journal_id != move.journal_id
                    or line.date != move.date or line.currency_id != company.currency_id
                    or company not in line.account_id.company_ids):
                self._deny_incomplete_source()
            amount = self._owner_sales_money(line.balance, company.currency_id)
            debit = self._owner_sales_money(line.debit, company.currency_id)
            credit = self._owner_sales_money(line.credit, company.currency_id)
            if (debit < 0 or credit < 0 or debit - credit != amount
                    or self._owner_sales_money(line.amount_currency, company.currency_id) != amount):
                self._deny_incomplete_source()
            total += amount
        if not lines or total:
            self._deny_incomplete_source()
        return lines

    def _owner_hr_contact(self, source, company):
        source.check_access('read')
        employee = source.employee_id
        employee.check_access('read')
        contact = employee.work_contact_id
        contact.check_access('read')
        if (source.company_id != company or not employee or employee.company_id != company
                or not contact or contact.company_id not in (company, self.env['res.company'])):
            self._deny_incomplete_source()
        return contact

    def _owner_hr_advance(self, liquidity, company):
        move = liquidity.move_id
        declared = move.baseer_loan_id
        model = self.env['baseer.hr.loan']
        model.flush_model(['move_id'])
        self.env.cr.execute('SELECT id FROM baseer_hr_loan WHERE move_id=%s', [move.id])
        source_ids = {row[0] for row in self.env.cr.fetchall()}
        if not source_ids and not declared:
            return None, False
        loans = model.search([('move_id', '=', move.id)])
        if set(loans.ids) != source_ids:
            self._deny_incomplete_source()
        loans.check_access('read')
        declared.check_access('read')
        if not loans:
            # Repayments and reviewed reversals also carry baseer_loan_id.
            # They are not the original advance disbursement.
            return None, bool(declared)
        if len(loans) != 1 or declared != loans:
            self._deny_incomplete_source()
        loan = loans
        contact = self._owner_hr_contact(loan, company)
        loan.journal_id.check_access('read')
        loan.currency_id.check_access('read')
        lines = self._owner_hr_move_lines(move, company)
        principal = lines - liquidity
        amount = self._owner_sales_money(loan.amount, company.currency_id)
        if (len(lines) != 2 or len(principal) != 1 or move.move_type != 'entry'
                or move.origin_payment_id or move.statement_line_id or move.reversed_entry_id
                or loan.move_id != move or loan.currency_id != company.currency_id
                or loan.date != move.date or loan.journal_id != move.journal_id
                or loan.journal_id.type not in ('bank', 'cash')
                or loan.journal_id.default_account_id != liquidity.account_id
                or (loan.journal_id.currency_id and loan.journal_id.currency_id != company.currency_id)
                or liquidity.account_id.account_type != 'asset_cash'
                or principal.account_id.account_type not in ('asset_receivable', 'asset_current', 'asset_non_current')
                or not principal.account_id.reconcile
                or principal.partner_id != contact or liquidity.partner_id != contact
                or amount <= 0
                or self._owner_sales_money(principal.balance, company.currency_id) != amount
                or self._owner_sales_money(liquidity.balance, company.currency_id) != -amount):
            self._deny_incomplete_source()
        # Current loan state/recoveries do not erase its historical cash issue.
        return {
            'company_id': company.id, 'direction': 'outgoing',
            'classification': 'employee_advance',
            'source_model': 'baseer.hr.loan', 'source_id': loan.id,
            'line_model': 'account.move.line', 'line_id': principal.id,
            'payment_move_id': move.id, 'payment_line_id': liquidity.id,
            'amount': amount, 'date': fields.Date.to_string(liquidity.date),
            'employee_id': loan.employee_id.id, 'loan_id': loan.id,
        }, True

    def _owner_hr_salary_source(self, source, company, contact):
        """Return a proved slip, or False for a visible unsupported correction."""
        source.check_access('read')
        slip = source.baseer_payslip_id
        slip.check_access('read')
        if not slip:
            return False
        employee_contact = self._owner_hr_contact(slip, company)
        original = slip.move_id
        original.check_access('read')
        if (slip.state != 'done' or not original or original.state != 'posted'
                or original.company_id != company or original.baseer_payslip_id != slip
                or employee_contact != contact or source.move_type != 'entry'):
            self._deny_incomplete_source()
        originals = self.env['hr.payslip'].search([('move_id', '=', original.id)])
        originals.flush_model(['move_id'])
        self._assert_visible('hr_payslip', 'move_id=%s', [original.id], originals)
        if originals != slip:
            self._deny_incomplete_source()
        self._owner_hr_move_lines(original, company)
        if self._owner_hr_reversed(source | original):
            return False
        if source == original:
            if (source.baseer_correction_payslip_id or source.baseer_correction_source_id
                    or source.baseer_correction_kind):
                self._deny_incomplete_source()
            return slip
        corrections = self._owner_sales_pairs(
            slip, 'baseer_correction_ids', 'account.move', 'baseer_correction_payslip_id')
        if (source not in corrections or source.baseer_correction_payslip_id != slip
                or source.baseer_correction_source_id != original):
            self._deny_incomplete_source()
        if source.baseer_correction_kind != 'wage':
            return False
        return slip

    def _owner_hr_salary(self, liquidity, company, *, statement=None, outstanding_credit=None):
        """Share salary-source proof between direct cash and whole bank clearing."""
        funding_credit = outstanding_credit if statement else liquidity
        move = funding_credit.move_id
        payments = self.env['account.payment'].search([('move_id', '=', move.id)])
        payments.flush_model(['move_id'])
        self._assert_visible('account_payment', 'move_id=%s', [move.id], payments)
        declared = move.origin_payment_id
        declared.check_access('read')
        if not payments and not declared:
            return [], False, None
        if len(payments) != 1 or declared != payments:
            self._deny_incomplete_source()
        payment = payments
        lines = self._owner_hr_move_lines(move, company)
        payable = lines.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        partials = self._owner_sales_pairs(
            payable, 'matched_credit_ids', 'account.partial.reconcile', 'debit_move_id')
        credits = partials.credit_move_id
        credits.check_access('read')
        credits.move_id.check_access('read')
        slips = credits.move_id.baseer_payslip_id
        if not slips:
            return [], False, None
        slips.check_access('read')
        if self._owner_hr_reversed(move):
            return [], True, None
        contact = payment.partner_id
        contact.check_access('read')
        method = payment.payment_method_line_id
        method.check_access('read')
        payment.journal_id.check_access('read')
        payment.currency_id.check_access('read')
        # Visible unsupported shapes retain the global cash census gap.
        amount = self._owner_sales_money(payment.amount, company.currency_id)
        if (payment.company_id != company or payment.move_id != move
                or payment.date != move.date
                or payment.date > liquidity.date
                or payment.payment_type != 'outbound' or payment.partner_type != 'supplier'
                or payment.state not in ('in_process', 'paid')
                or payment.currency_id != company.currency_id
                or payment.journal_id != move.journal_id
                or payment.journal_id.type not in ('bank', 'cash')
                or payment.journal_id.default_account_id != liquidity.account_id
                or (payment.journal_id.currency_id and payment.journal_id.currency_id != company.currency_id)
                or not method or method.journal_id != payment.journal_id
                or method.company_id != company or method.payment_type != 'outbound'
                or method.payment_account_id != funding_credit.account_id
                or payment.outstanding_account_id != funding_credit.account_id
                or move.statement_line_id or move.reversed_entry_id
                or len(lines) != 2 or len(payable) != 1
                or funding_credit not in lines or funding_credit.partner_id != contact
                or payable.partner_id != contact or not contact
                or (statement and (statement.partner_id != contact
                                   or statement.journal_id != payment.journal_id))
                or not payable.account_id.reconcile or amount <= 0
                or self._owner_sales_money(liquidity.balance, company.currency_id) != -amount
                or self._owner_sales_money(funding_credit.balance, company.currency_id) != -amount
                or self._owner_sales_money(payable.balance, company.currency_id) != amount):
            return [], True, None
        grouped = {}
        for partial in partials:
            credit = partial.credit_move_id
            source = credit.move_id
            credit.account_id.check_access('read')
            credit.partner_id.check_access('read')
            if (partial.company_id != company or partial.debit_move_id != payable
                    or credit.company_id != company or credit.account_id != payable.account_id
                    or credit.partner_id != contact or source.date > move.date
                    or self._owner_sales_money(credit.balance, company.currency_id) >= 0):
                self._deny_incomplete_source()
            self._owner_hr_move_lines(source, company)
            reverse = self._owner_sales_pairs(
                credit, 'matched_debit_ids', 'account.partial.reconcile', 'credit_move_id')
            if partial not in reverse:
                self._deny_incomplete_source()
            slip = self._owner_hr_salary_source(source, company, contact)
            if not slip:
                return [], True, None
            allocated = self._owner_sales_money(partial.amount, company.currency_id)
            if allocated <= 0:
                self._deny_incomplete_source()
            event = grouped.setdefault(credit.id, {
                'company_id': company.id, 'direction': 'outgoing', 'classification': 'payroll',
                'source_model': 'account.bank.statement.line' if statement else 'account.payment',
                'source_id': statement.id if statement else payment.id,
                'line_model': 'account.move.line', 'line_id': credit.id,
                'payment_move_id': liquidity.move_id.id, 'payment_line_id': liquidity.id,
                'amount': Decimal(0), 'date': fields.Date.to_string(liquidity.date),
                'employee_id': slip.employee_id.id, 'payslip_id': slip.id,
            })
            if statement:
                event['origin_payment_id'] = payment.id
            event['amount'] += allocated
        events = list(grouped.values())
        if not events or sum((event['amount'] for event in events), Decimal(0)) != amount:
            return [], True, None
        return events, True, payment.id

    def _owner_hr_statement(self, liquidity, company):
        """Only a whole payment cleared by one whole statement is supported."""
        move = liquidity.move_id
        model = self.env['account.bank.statement.line']
        model.flush_model(['move_id'])
        self.env.cr.execute('SELECT id FROM account_bank_statement_line WHERE move_id=%s', [move.id])
        source_ids = {row[0] for row in self.env.cr.fetchall()}
        declared = move.statement_line_id
        if not source_ids and not declared:
            return [], False, None
        statements = model.search([('move_id', '=', move.id)])
        statements.check_access('read')
        declared.check_access('read')
        if set(statements.ids) != source_ids or len(statements) != 1 or statements != declared:
            self._deny_incomplete_source()
        statement = statements
        statement.journal_id.check_access('read')
        statement.currency_id.check_access('read')
        statement.partner_id.check_access('read')
        lines = self._owner_hr_move_lines(move, company)
        counterpart = lines - liquidity
        amount = -self._owner_sales_money(liquidity.balance, company.currency_id)
        if (len(lines) != 2 or len(counterpart) != 1
                or move.move_type != 'entry' or move.origin_payment_id
                or statement.company_id != company or statement.move_id != move
                or statement.date != liquidity.date or statement.journal_id != move.journal_id
                or statement.journal_id.type != 'bank'
                or statement.journal_id.default_account_id != liquidity.account_id
                or (statement.journal_id.currency_id
                    and statement.journal_id.currency_id != company.currency_id)
                or statement.currency_id != company.currency_id
                or amount <= 0 or self._owner_sales_money(statement.amount, company.currency_id) != -amount
                or counterpart.account_id.account_type != 'asset_current'
                or not counterpart.account_id.reconcile
                or self._owner_sales_money(counterpart.balance, company.currency_id) != amount):
            return [], False, None
        clearing = self._owner_sales_pairs(
            counterpart, 'matched_credit_ids', 'account.partial.reconcile', 'debit_move_id')
        debit_matches = self._owner_sales_pairs(
            counterpart, 'matched_debit_ids', 'account.partial.reconcile', 'credit_move_id')
        credits = clearing.credit_move_id
        credits.check_access('read')
        credits.move_id.check_access('read')
        credits.account_id.check_access('read')
        credits.partner_id.check_access('read')
        reverse = self._owner_sales_pairs(
            credits, 'matched_debit_ids', 'account.partial.reconcile', 'credit_move_id')
        credit_matches = self._owner_sales_pairs(
            credits, 'matched_credit_ids', 'account.partial.reconcile', 'debit_move_id')
        if (len(clearing) != 1 or len(credits) != 1 or reverse != clearing
                or debit_matches or credit_matches
                or clearing.company_id != company or clearing.debit_move_id != counterpart
                or credits.company_id != company or credits.account_id != counterpart.account_id
                or counterpart.partner_id != statement.partner_id
                or credits.partner_id != statement.partner_id
                or self._owner_sales_money(clearing.amount, company.currency_id) != amount
                or self._owner_sales_money(credits.balance, company.currency_id) != -amount):
            return [], False, None
        # Check both sides before salary proof, including hidden reversals.
        if self._owner_hr_reversed(move):
            return [], False, None
        events, hr_source, _payment_id = self._owner_hr_salary(
            liquidity, company, statement=statement, outstanding_credit=credits)
        return events, hr_source, statement.id if events else None

    @api.model
    def _owner_hr_cash(self, company, start, end, journal_ids):
        company.ensure_one()
        if (company.id != self.env.company.id or company.id not in {1, 2, 3, 56}
                or company.id not in self.env.user.company_ids.ids):
            raise AccessError(_('Only an authorized active company may be reported.'))
        company = self.env['res.company'].browse(company.id)
        company.check_access('read')
        company.currency_id.check_access('read')
        start, end = fields.Date.to_date(start), fields.Date.to_date(end)
        if not start or not end or start > end:
            self._deny_incomplete_source()
        if (not isinstance(journal_ids, (list, tuple))
                or any(type(value) is not int or value <= 0 for value in journal_ids)):
            self._deny_incomplete_source()
        journals = self.env['account.journal'].browse(journal_ids).exists()
        journals.check_access('read')
        if set(journals.ids) != set(journal_ids) or any(row.company_id != company for row in journals):
            self._deny_incomplete_source()
        move_fields = self.env['account.move']._fields
        loans_available = ('baseer.hr.loan' in self.env and 'baseer_loan_id' in move_fields)
        salary_available = ('hr.payslip' in self.env and all(name in move_fields for name in (
            'baseer_payslip_id', 'baseer_correction_payslip_id',
            'baseer_correction_source_id', 'baseer_correction_kind'))
            and all(name in self.env['hr.payslip']._fields for name in (
                'move_id', 'employee_id', 'baseer_correction_ids')))
        result = {'events': [], 'claimed_payment_ids': set(), 'claimed_statement_ids': set(),
                  'claimed_liquidity_ids': set(), 'excluded': {}}
        if not loans_available and not salary_available:
            return result
        domain = [('company_id', '=', company.id), ('parent_state', '=', 'posted'),
                  ('date', '>=', start), ('date', '<=', end),
                  ('account_id.account_type', '=', 'asset_cash'), ('balance', '<', 0)]
        sql = ('l.company_id=%s AND l.parent_state=%s AND l.date >= %s AND l.date <= %s '
               'AND a.account_type=%s AND l.balance < 0')
        params = [company.id, 'posted', start, end, 'asset_cash']
        if journal_ids:
            domain.append(('journal_id', 'in', list(journal_ids)))
            sql += ' AND l.journal_id=ANY(%s)'
            params.append(list(journal_ids))
        liquidity = self.env['account.move.line'].search(domain, order='id')
        liquidity.flush_model(['company_id', 'parent_state', 'date', 'account_id', 'balance', 'journal_id'])
        self.env['account.account'].flush_model(['account_type'])
        self.env.cr.execute('SELECT l.id FROM account_move_line l JOIN account_account a '
                            'ON a.id=l.account_id WHERE ' + sql, params)
        if {row[0] for row in self.env.cr.fetchall()} != set(liquidity.ids):
            self._deny_incomplete_source()
        liquidity.check_access('read')
        liquidity.move_id.check_access('read')
        liquidity.account_id.check_access('read')
        loan_moves, statement_moves, payment_moves = self._owner_hr_candidate_moves(
            liquidity, loans_available=loans_available, salary_available=salary_available,
        )
        excluded = Counter()
        with localcontext() as context:
            context.prec = 60
            for line in liquidity:
                move_id = line.move_id.id
                advance, hr_source = (self._owner_hr_advance(line, company)
                                      if move_id in loan_moves else (None, False))
                if advance:
                    result['events'].append(advance)
                    result['claimed_liquidity_ids'].add(line.id)
                    continue
                if hr_source:
                    excluded['unsupported_hr_cash'] += 1
                    continue
                events, hr_source, statement_id = (self._owner_hr_statement(line, company)
                                                   if move_id in statement_moves else ([], False, None))
                if events:
                    result['events'].extend(events)
                    result['claimed_statement_ids'].add(statement_id)
                    result['claimed_liquidity_ids'].add(line.id)
                    continue
                if hr_source:
                    excluded['unsupported_hr_cash'] += 1
                    continue
                events, hr_source, payment_id = (self._owner_hr_salary(line, company)
                                                 if move_id in payment_moves else ([], False, None))
                if events:
                    result['events'].extend(events)
                    result['claimed_payment_ids'].add(payment_id)
                    result['claimed_liquidity_ids'].add(line.id)
                elif hr_source:
                    excluded['unsupported_hr_cash'] += 1
        result['excluded'] = dict(excluded)
        return result
