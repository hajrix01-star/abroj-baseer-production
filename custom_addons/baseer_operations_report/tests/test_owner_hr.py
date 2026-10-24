"""Native HR workflows feed direct cash facts without salary/advance duplication."""

from decimal import Decimal
import re
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'operations_owner_hr', 'operations_owner_hr_perf')
class TestOwnerHrCash(TransactionCase):
    def setUp(self):
        super().setUp()
        if ('baseer.hr.loan' not in self.env or 'hr.payslip' not in self.env
                or 'baseer_managed' not in self.env['hr.payslip']._fields):
            self.skipTest('Optional native Baseer payroll module is not installed')
        # Native payroll actions explicitly check group membership even for
        # the test administrator. Grant ordinary roles, never internal tokens.
        self.env.user.write({'group_ids': [Command.link(self.env.ref(xmlid).id) for xmlid in (
            'account.group_account_user', 'account.group_account_manager',
            'hr.group_hr_manager', 'om_hr_payroll.group_hr_payroll_manager',
        )]})
        self.company = self.env.company
        self.report = self.env['baseer.operations.report']

        def account(code, kind, reconcile=False):
            return self.env['account.account'].create({
                'code': code, 'name': 'Owner HR ' + code, 'account_type': kind,
                'reconcile': reconcile, 'company_ids': [Command.set(self.company.ids)],
            })

        self.expense = account('952101', 'expense')
        self.payable = account('952102', 'liability_payable', True)
        self.advance = account('952103', 'asset_receivable', True)
        self.deduction = account('952104', 'income_other')
        self.cash = account('952105', 'asset_cash')
        self.outstanding = account('952106', 'asset_current', True)
        self.journal = self.env['account.journal'].create({
            'name': 'Owner HR payroll', 'code': 'OHR', 'type': 'general', 'company_id': self.company.id,
        })
        self.bank = self.env['account.journal'].create({
            'name': 'Owner HR direct bank', 'code': 'OHB', 'type': 'bank',
            'company_id': self.company.id, 'default_account_id': self.cash.id,
        })
        self.method = self.bank.outbound_payment_method_line_ids.filtered(
            lambda row: row.payment_method_id.code == 'manual')[:1]
        self.assertTrue(self.method)
        self.method.payment_account_id = self.cash
        # Match the native PayrollAnalyticsCase setup: a real company-owned
        # leaf under the reviewed payroll root plan, enabled before posting.
        self.payroll_analytic = self.env['account.analytic.account'].create({
            'name': 'Owner HR native payroll cost',
            'plan_id': self.env.ref('baseer_payroll.payroll_cost_plan').id,
            'company_id': self.company.id,
        })
        self.company.write({
            'baseer_salary_expense_id': self.expense.id,
            'baseer_salary_payable_id': self.payable.id,
            'baseer_loan_account_id': self.advance.id,
            'baseer_deduction_account_id': self.deduction.id,
            'baseer_payroll_journal_id': self.journal.id,
            'baseer_payroll_analytic_account_id': self.payroll_analytic.id,
            'baseer_payroll_analytic_enabled': True,
            'baseer_structure_id': False,
        })
        self.contact = self.env['res.partner'].create({
            'name': 'Owner HR employee contact', 'company_id': self.company.id,
            'property_account_payable_id': self.payable.id,
            'property_account_receivable_id': self.advance.id,
        })
        self.employee = self.env['hr.employee'].create({
            'name': 'Owner HR native employee', 'company_id': self.company.id,
            'work_contact_id': self.contact.id, 'baseer_payroll_enabled': True,
        })
        self.employee.version_id.write({
            'date_version': '2026-01-01', 'contract_date_start': '2026-01-01',
            'wage': 2000, 'baseer_salary_mode': 'fixed',
        })

    def _read(self, report=None, start='2026-06-01', end='2026-07-31'):
        return (self.report if report is None else report)._owner_hr_cash(
            self.company, start, end, self.bank.ids)

    def _loan(self):
        loan = self.env['baseer.hr.loan'].create({
            'name': 'Owner HR native advance', 'company_id': self.company.id,
            'employee_id': self.employee.id, 'amount': 500,
            'date': '2026-06-01', 'first_due_date': '2026-06-30',
            'installment_count': 1, 'journal_id': self.bank.id,
        })
        loan.action_disburse()
        self.assertEqual(loan.move_id.state, 'posted')
        self.assertEqual(loan.move_id.baseer_loan_id, loan)
        return loan

    def _payroll(self):
        run = self.env['hr.payslip.run'].create({
            'baseer_managed': True, 'baseer_month': '2026-06-01', 'company_id': self.company.id,
        })
        # The real loader may include unrelated demo employees. Keep only the
        # fixture's generated draft before native approval, without FK tokens.
        run.slip_ids.filtered(lambda row: row.employee_id != self.employee).unlink()
        slip = run.slip_ids
        self.assertEqual(slip.employee_id, self.employee)
        self.assertEqual(slip.baseer_gross, 2000)
        run.action_approve()
        self.assertEqual((slip.state, slip.move_id.state), ('done', 'posted'))
        self.assertEqual(slip.move_id.baseer_payslip_id, slip)
        expense = slip.move_id.line_ids.filtered(lambda row: row.account_id == self.expense)
        self.assertTrue(expense)
        self.assertTrue(all(row.analytic_distribution == {str(self.payroll_analytic.id): 100}
                            for row in expense))
        return slip

    def _pay(self, slip, amount, day='2026-07-01'):
        action = slip.action_pay()
        wizard = self.env['account.payment.register'].with_context(action['context']).create({
            'journal_id': self.bank.id, 'payment_method_line_id': self.method.id,
            'payment_date': day, 'amount': amount,
            'group_payment': True, 'payment_difference_handling': 'open',
        })
        payments = wizard._create_payments()
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments.move_id.state, 'posted')
        return payments

    def _clear_outstanding(self, payment, day, amount=None):
        amount = payment.amount if amount is None else amount
        statement = self.env['account.bank.statement.line'].create({
            'journal_id': self.bank.id, 'date': day,
            'payment_ref': 'Native payroll bank clearing',
            'partner_id': self.contact.id, 'amount': -amount,
            'counterpart_account_id': self.outstanding.id,
        })
        credit = payment.move_id.line_ids.filtered(lambda row: row.account_id == self.outstanding)
        debit = statement.move_id.line_ids.filtered(lambda row: row.account_id == self.outstanding)
        self.assertEqual((len(credit), len(debit)), (1, 1))
        (credit | debit).reconcile()
        self.assertEqual(statement.move_id.state, 'posted')
        return statement

    def _unrelated_cash_moves(self, count, day='2026-06-18'):
        """Real posted liquidity, deliberately without an HR native relation."""
        moves = self.env['account.move'].create([{
            'move_type': 'entry', 'journal_id': self.bank.id, 'date': day,
            'line_ids': [
                Command.create({
                    'name': 'Owner HR ordinary cash %s' % index,
                    'account_id': self.expense.id, 'debit': 1,
                }),
                Command.create({
                    'name': 'Owner HR ordinary cash %s' % index,
                    'account_id': self.cash.id, 'credit': 1,
                }),
            ],
        } for index in range(count)])
        moves.action_post()
        self.assertTrue(all(not move.baseer_loan_id and not move.statement_line_id
                            and not move.origin_payment_id for move in moves))
        return moves

    def _reader(self):
        user = self.env['res.users'].create({
            'name': 'Owner HR normal reader', 'login': 'owner_hr_normal_reader',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_manager').id,
                self.env.ref('hr.group_hr_manager').id,
                self.env.ref('om_hr_payroll.group_hr_payroll_manager').id,
            ])],
        })
        return self.report.with_user(user).with_context(allowed_company_ids=self.company.ids)

    def test_native_loan_and_net_salary_partial_cash_count_once(self):
        loan = self._loan()
        slip = self._payroll()
        self.assertEqual(slip.baseer_loan_amount, 500)
        self.assertEqual(slip.baseer_net, 1500)
        self.assertEqual(loan.state, 'closed')
        unpaid = self._read()
        self.assertEqual([row['amount'] for row in unpaid['events']], [Decimal('500')])
        first = self._pay(slip, 600)
        second = self._pay(slip, 900, '2026-07-02')
        result = self._read()
        self.assertEqual(result['excluded'], {})
        self.assertEqual(result['claimed_payment_ids'], {first.id, second.id})
        self.assertEqual(len(result['claimed_liquidity_ids']), 3)
        totals = {}
        for event in result['events']:
            totals[event['classification']] = totals.get(event['classification'], Decimal(0)) + event['amount']
        self.assertEqual(totals, {'employee_advance': Decimal('500'), 'payroll': Decimal('1500')})
        self.assertEqual(self._read(), result)
        integrated = self.report._owner_cash(
            self.company, '2026-06-01', '2026-07-31', self.bank.ids)
        self.assertTrue(integrated['coverage_complete'], integrated['excluded'])
        self.assertEqual(integrated['excluded'], {})
        self.assertEqual(len(integrated['events']), 3)
        self.assertEqual({row['classification'] for row in integrated['events']},
                         {'employee_advance', 'payroll'})
        from ..models.owner_summary import build_owner_summary
        summary = build_owner_summary(integrated['events'], integrated['liquidity_totals'],
                                      company_id=self.company.id)
        self.assertEqual(summary['cash_total'], Decimal('2000'))
        self.assertEqual(summary['cash_event_count'], 3)

    def test_hr_batch_census_preserves_native_candidates_amid_ordinary_cash(self):
        loan = self._loan()
        slip = self._payroll()
        payment = self._pay(slip, 600)
        self._unrelated_cash_moves(120)

        result = self._read()
        self.assertEqual(result['excluded'], {})
        self.assertEqual(result['claimed_payment_ids'], {payment.id})
        self.assertEqual(result['claimed_liquidity_ids'], {
            loan.move_id.line_ids.filtered(lambda row: row.account_id == self.cash).id,
            payment.move_id.line_ids.filtered(lambda row: row.account_id == self.cash).id,
        })
        self.assertEqual({row['classification'] for row in result['events']},
                         {'employee_advance', 'payroll'})
        self.assertEqual(sum(row['amount'] for row in result['events']), Decimal('1100'))

    def test_direct_salary_facts_batch_two_eligible_payments_and_keep_cash_parity(self):
        slip = self._payroll()
        first = self._pay(slip, 600)
        second = self._pay(slip, 900, '2026-07-02')
        moves = first.move_id | second.move_id

        facts = self.report._owner_hr_direct_salary_facts(moves)

        self.assertEqual(set(facts['payments_by_move']), set(moves.ids))
        self.assertEqual({rows.id for rows in facts['payments_by_move'].values()},
                         {first.id, second.id})
        self.assertEqual(set(facts['lines_by_move']), set(moves.ids))
        self.assertTrue(all(facts['credits_by_payable'].values()))
        result = self._read()
        self.assertEqual(result['claimed_payment_ids'], {first.id, second.id})
        self.assertEqual(sum(row['amount'] for row in result['events']), Decimal('1500'))

    def test_direct_salary_facts_hide_one_partial_fails_closed_for_all_candidates(self):
        slip = self._payroll()
        first = self._pay(slip, 600)
        second = self._pay(slip, 900, '2026-07-02')
        payable = first.move_id.line_ids.filtered(lambda row: row.account_id == self.payable)
        partial = payable.matched_credit_ids
        secured = self._reader()
        rule = self.env['ir.rule'].create({
            'name': 'Hide one batched direct-salary partial',
            'model_id': self.env['ir.model']._get('account.partial.reconcile').id,
            'domain_force': "[('id', '!=', %s)]" % partial.id,
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['account.partial.reconcile'].search([
                ('id', '=', partial.id),
            ]))
            with self.assertRaises(AccessError):
                secured._owner_hr_direct_salary_facts(
                    secured.env['account.move'].browse((first.move_id | second.move_id).ids))
        finally:
            rule.unlink()

    def test_direct_salary_facts_uses_one_payment_inverse_probe_for_many_moves(self):
        slip = self._payroll()
        first = self._pay(slip, 600)
        second = self._pay(slip, 900, '2026-07-02')
        self.env.invalidate_all()
        cursor_type = type(self.env.cr)
        original_execute = cursor_type.execute
        probes = []

        def counted_execute(cursor, query, *args, **kwargs):
            sql = re.sub(r'\s+', ' ', str(getattr(query, 'code', query))).lower()
            if 'from account_payment where move_id=any' in sql:
                probes.append(sql)
            return original_execute(cursor, query, *args, **kwargs)

        with patch.object(cursor_type, 'execute', new=counted_execute):
            self.report._owner_hr_direct_salary_facts(first.move_id | second.move_id)
        self.assertEqual(len(probes), 1, probes)

    def test_hr_batch_census_uses_constant_inverse_probes_for_ordinary_cash(self):
        self._unrelated_cash_moves(120)
        self.env.invalidate_all()
        cursor_type = type(self.env.cr)
        original_execute = cursor_type.execute
        queries = []

        def counted_execute(cursor, query, *args, **kwargs):
            sql = re.sub(r'\s+', ' ', str(getattr(query, 'code', query))).lower()
            if any(table in sql for table in (
                    'baseer_hr_loan', 'account_bank_statement_line', 'account_payment')):
                queries.append(sql)
            return original_execute(cursor, query, *args, **kwargs)

        with patch.object(cursor_type, 'execute', new=counted_execute):
            result = self._read()
        self.assertEqual(result, {
            'events': [], 'claimed_payment_ids': set(), 'claimed_statement_ids': set(),
            'claimed_liquidity_ids': set(), 'excluded': {},
        })
        for table in ('baseer_hr_loan', 'account_bank_statement_line', 'account_payment'):
            with self.subTest(table=table):
                matching = [sql for sql in queries if 'from %s where move_id=any' % table in sql]
                self.assertEqual(len(matching), 1, queries)
                self.assertFalse(any('from %s where move_id=%%s' % table in sql
                                     for sql in queries), queries)

    def test_hr_candidate_census_id_chunks_bound_parameters(self):
        chunks = list(self.report._owner_hr_id_chunks(list(range(1, 1002))))

        self.assertEqual([len(chunk) for chunk in chunks], [1000, 1])
        self.assertEqual(chunks[0][0], 1)
        self.assertEqual(chunks[-1], [1001])

    def test_hr_batch_census_hidden_raw_inverse_still_fails_closed(self):
        loan = self._loan()
        secured = self._reader()
        rule = self.env['ir.rule'].create({
            'name': 'Hide batched owner HR loan inverse',
            'model_id': self.env['ir.model']._get('baseer.hr.loan').id,
            'domain_force': "[('id', '!=', %s)]" % loan.id,
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['baseer.hr.loan'].search([('id', '=', loan.id)]))
            with self.assertRaises(AccessError):
                self._read(report=secured)
        finally:
            rule.unlink()

    def test_hr_batch_census_selects_each_enabled_native_family(self):
        loan = self._loan()
        slip = self._payroll()
        direct = self._pay(slip, 600)
        self.method.payment_account_id = self.outstanding
        outstanding = self._pay(slip, 900, '2026-07-02')
        statement = self._clear_outstanding(outstanding, '2026-07-05')
        liquidity = loan.move_id.line_ids.filtered(lambda row: row.account_id == self.cash)
        liquidity |= direct.move_id.line_ids.filtered(lambda row: row.account_id == self.cash)
        liquidity |= statement.move_id.line_ids.filtered(lambda row: row.account_id == self.cash)

        loan_moves, statement_moves, payment_moves = self.report._owner_hr_candidate_moves(
            liquidity, loans_available=True, salary_available=True)
        self.assertEqual(loan_moves, {loan.move_id.id})
        self.assertEqual(statement_moves, {statement.move_id.id})
        self.assertEqual(payment_moves, {direct.move_id.id})

    def test_hr_batch_census_hidden_statement_and_payment_inverses_fail_closed(self):
        slip = self._payroll()
        direct = self._pay(slip, 600)
        self.method.payment_account_id = self.outstanding
        outstanding = self._pay(slip, 900, '2026-07-02')
        statement = self._clear_outstanding(outstanding, '2026-07-05')
        secured = self._reader()
        for model, record in (
                ('account.payment', direct),
                ('account.bank.statement.line', statement)):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide batched owner HR %s inverse' % model,
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': "[('id', '!=', %s)]" % record.id,
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', record.id)]))
                    with self.assertRaises(AccessError):
                        self._read(report=secured)
                finally:
                    rule.unlink()

    def test_unpaid_payroll_and_outstanding_payment_have_no_cash_claim(self):
        slip = self._payroll()
        self.assertEqual(self._read()['events'], [])
        self.method.payment_account_id = self.outstanding
        self._pay(slip, 600)
        result = self._read()
        self.assertEqual(result, {'events': [], 'claimed_payment_ids': set(),
                                  'claimed_statement_ids': set(),
                                  'claimed_liquidity_ids': set(), 'excluded': {}})

    def test_generic_direct_payment_keeps_account_acl_before_no_payslip_skip(self):
        payment = self.env['account.payment'].create({
            'date': '2026-07-04', 'amount': 20,
            'payment_type': 'outbound', 'partner_type': 'supplier',
            'partner_id': self.contact.id, 'journal_id': self.bank.id,
            'company_id': self.company.id, 'currency_id': self.company.currency_id.id,
            'payment_method_line_id': self.method.id,
        })
        payment.action_post()
        secured = self._reader()
        self.assertEqual(self._read(report=secured)['events'], [])
        rule = self.env['ir.rule'].create({
            'name': 'Hide generic direct-payment cash account',
            'model_id': self.env['ir.model']._get('account.account').id,
            'domain_force': "[('id', '!=', %s)]" % self.cash.id,
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['account.account'].search([('id', '=', self.cash.id)]))
            with self.assertRaises(AccessError):
                self._read(report=secured)
        finally:
            rule.unlink()

    def test_wage_correction_counts_only_its_actual_payment(self):
        slip = self._payroll()
        self._pay(slip, 2000)
        correction = self.env['baseer.payroll.correction'].create({
            'company_id': self.company.id, 'slip_id': slip.id, 'kind': 'wage',
            'amount': 100, 'date': '2026-07-02', 'reason': 'Native wage correction fixture',
            'reviewed': True,
        })
        correction.action_confirm()
        move = correction.move_id
        self.assertEqual(move.baseer_payslip_id, slip)
        self.assertEqual(move.baseer_correction_payslip_id, slip)
        self.assertEqual(move.baseer_correction_source_id, slip.move_id)
        self.assertEqual(sum(row['amount'] for row in self._read()['events']), Decimal('2000'))
        payment = self._pay(slip, 100, '2026-07-03')
        result = self._read()
        events = [row for row in result['events'] if row['source_id'] == payment.id]
        self.assertEqual(sum(row['amount'] for row in events), Decimal('100'))
        self.assertEqual({row['line_id'] for row in events}, set(move.line_ids.filtered(
            lambda row: row.account_id == self.payable and row.credit > 0).ids))

    def test_payroll_recovery_correction_is_not_supported_cash(self):
        self._loan()
        slip = self._payroll()
        self._pay(slip, 1500)
        correction = self.env['baseer.payroll.correction'].create({
            'company_id': self.company.id, 'slip_id': slip.id, 'kind': 'payroll_recovery',
            'date': '2026-07-02', 'reason': 'Native recovery reversal fixture', 'reviewed': True,
        })
        correction.action_confirm()
        payment = self._pay(slip, 500, '2026-07-03')
        result = self._read()
        self.assertNotIn(payment.id, result['claimed_payment_ids'])
        self.assertEqual(result['excluded'], {'unsupported_hr_cash': 1})

    def test_reversed_advance_keeps_original_historical_cash(self):
        loan = self._loan()
        correction = self.env['baseer.payroll.correction'].create({
            'company_id': self.company.id, 'loan_id': loan.id, 'kind': 'advance',
            'date': '2026-06-02', 'reason': 'Native advance reversal fixture', 'reviewed': True,
        })
        correction.action_confirm()
        self.assertEqual(loan.state, 'cancel')
        result = self._read()
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['amount'], Decimal('500'))
        self.assertEqual(result['events'][0]['source_id'], loan.id)

    def test_normal_user_hidden_hr_sources_fail_closed(self):
        loan = self._loan()
        slip = self._payroll()
        payment = self._pay(slip, 600)
        secured = self._reader()
        self.assertEqual(len(self._read(report=secured)['events']), 2)
        payable = payment.move_id.line_ids.filtered(lambda row: row.account_id == self.payable)
        partial = payable.matched_credit_ids[:1]
        for model, record in (
                ('baseer.hr.loan', loan), ('hr.payslip', slip),
                ('hr.employee', self.employee), ('res.partner', self.contact),
                ('account.move', slip.move_id), ('account.move.line', loan.move_id.line_ids[:1]),
                ('account.partial.reconcile', partial), ('account.payment', payment)):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide owner HR proof %s' % model,
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': "[('id', '!=', %s)]" % record.id,
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', record.id)]))
                    with self.assertRaises(AccessError):
                        self._read(report=secured)
                finally:
                    rule.unlink()

    def test_cross_company_and_context_claims_cannot_expand_scope(self):
        self._loan()
        other = self.env['res.company'].create({'name': 'Owner HR other company'})
        secured = self._reader()
        with self.assertRaises(AccessError):
            secured._owner_hr_cash(other, '2026-06-01', '2026-07-31', [])
        with self.assertRaises(AccessError):
            secured.with_context(allowed_company_ids=other.ids)._owner_hr_cash(
                other, '2026-06-01', '2026-07-31', [])
        injected = secured.with_context(
            claimed_payment_ids=[999], claimed_liquidity_ids=[999],
            baseer_operations_batch_verified=True)
        self.assertEqual(self._read(report=injected), self._read(report=secured))

    def test_actual_cash_date_controls_period_not_salary_month(self):
        slip = self._payroll()
        payment = self._pay(slip, 600, '2026-07-01')
        self.assertEqual(self._read(start='2026-06-01', end='2026-06-30')['events'], [])
        result = self._read(start='2026-07-01', end='2026-07-01')
        self.assertEqual(result['claimed_payment_ids'], {payment.id})
        self.assertEqual(sum(row['amount'] for row in result['events']), Decimal('600'))

    def test_unrelated_statement_and_vendor_cash_do_not_require_hr_access(self):
        statement = self.env['account.bank.statement.line'].create({
            'journal_id': self.bank.id, 'date': '2026-06-18',
            'payment_ref': 'Unrelated operating cash', 'amount': -40,
            'partner_id': self.contact.id, 'counterpart_account_id': self.expense.id,
        })
        purchase = self.env['account.journal'].create({
            'name': 'Owner HR unrelated purchases', 'code': 'OHV',
            'type': 'purchase', 'company_id': self.company.id,
        })
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'journal_id': purchase.id,
            'partner_id': self.contact.id, 'invoice_date': '2026-06-18',
            'invoice_line_ids': [Command.create({
                'name': 'Unrelated vendor expense', 'quantity': 1,
                'price_unit': 20, 'account_id': self.expense.id,
                'tax_ids': [Command.clear()],
            })],
        })
        bill.action_post()
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id, 'payment_method_line_id': self.method.id,
            'amount': 20, 'payment_date': '2026-06-20',
            'installments_mode': 'full', 'payment_difference_handling': 'open',
        })._create_payments()
        user = self.env['res.users'].create({
            'name': 'Owner HR unrelated accounting reader', 'login': 'owner_hr_non_hr_reader',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref(xmlid).id for xmlid in (
                'base.group_user', 'account.group_account_user', 'point_of_sale.group_pos_user',
            )])],
        })
        secured = self.report.with_user(user).with_context(allowed_company_ids=self.company.ids)
        self.assertFalse(user.has_group('om_hr_payroll.group_hr_payroll_manager'))
        with self.assertRaises(AccessError):
            secured.env['baseer.hr.loan'].check_access('read')
        self.assertEqual(self._read(report=secured), {
            'events': [], 'claimed_payment_ids': set(),
            'claimed_statement_ids': set(),
            'claimed_liquidity_ids': set(), 'excluded': {},
        })
        integrated = secured._owner_cash(self.company, '2026-06-01', '2026-07-31', self.bank.ids)
        self.assertTrue(integrated['coverage_complete'], integrated['excluded'])
        self.assertEqual(sum(integrated['liquidity_totals'].values()), Decimal('60'))
        self.assertEqual({(row['source_model'], row['source_id']) for row in integrated['events']},
                         {('account.bank.statement.line', statement.id), ('account.payment', payment.id)})

    def test_hr_batch_census_keeps_native_invoice_payment_relation(self):
        purchase = self.env['account.journal'].create({
            'name': 'Owner HR guarded payment purchases', 'code': 'OHP',
            'type': 'purchase', 'company_id': self.company.id,
        })
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'journal_id': purchase.id,
            'partner_id': self.contact.id, 'invoice_date': '2026-06-18',
            'invoice_line_ids': [Command.create({
                'name': 'Owner HR guarded payment expense', 'quantity': 1,
                'price_unit': 20, 'account_id': self.expense.id,
                'tax_ids': [Command.clear()],
            })],
        })
        bill.action_post()
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id, 'payment_method_line_id': self.method.id,
            'amount': 20, 'payment_date': '2026-06-20',
            'installments_mode': 'full', 'payment_difference_handling': 'open',
        })._create_payments()
        move = payment.move_id
        liquidity = move.line_ids.filtered(lambda row: row.account_id == self.cash)
        _loans, _statements, payments = self.report._owner_hr_candidate_moves(
            liquidity, loans_available=True, salary_available=True)
        self.assertEqual(payments, {move.id})

        # This laboratory does not necessarily install the optional lifecycle
        # guard module.  Prove the native relation that the census consumes,
        # then re-read it through a fresh environment cache.
        self.assertEqual(move.origin_payment_id, payment)
        self.env.invalidate_all()
        move = self.env['account.move'].browse(move.id)
        self.assertEqual(move.origin_payment_id, payment)
        liquidity = move.line_ids.filtered(lambda row: row.account_id == self.cash)
        _loans, _statements, payments = self.report._owner_hr_candidate_moves(
            liquidity, loans_available=True, salary_available=True)
        self.assertEqual(payments, {move.id})

        integrated = self.report._owner_cash(
            self.company, '2026-06-01', '2026-07-31', self.bank.ids)
        events = [row for row in integrated['events']
                  if row['source_model'] == 'account.payment' and row['source_id'] == payment.id]
        self.assertEqual([row['amount'] for row in events], [Decimal('20')])

    def _assert_reversed_cash_unclaimed(self, payment, reversal):
        result = self._read()
        self.assertNotIn(payment.id, result['claimed_payment_ids'])
        self.assertFalse(result['events'])
        self.assertEqual(result['excluded'], {'unsupported_hr_cash': 1})
        integrated = self.report._owner_cash(
            self.company, '2026-06-01', '2026-07-31', self.bank.ids)
        self.assertFalse(integrated['coverage_complete'])
        self.assertFalse(integrated['events'])
        secured = self._reader()
        rule = self.env['ir.rule'].create({
            'name': 'Hide owner HR reversal evidence',
            'model_id': self.env['ir.model']._get('account.move').id,
            'domain_force': "[('id', '!=', %s)]" % reversal.id,
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['account.move'].search([('id', '=', reversal.id)]))
            with self.assertRaises(AccessError):
                self._read(report=secured)
        finally:
            rule.unlink()

    def test_native_payment_reversal_is_unclaimed_and_hidden_reverse_denied(self):
        slip = self._payroll()
        payment = self._pay(slip, 600)
        reverse = payment.move_id._reverse_moves(
            default_values_list=[{'date': '2026-07-02'}], cancel=False)
        if reverse.state == 'draft':
            reverse.action_post()
        self.assertEqual(reverse.reversed_entry_id, payment.move_id)
        self._assert_reversed_cash_unclaimed(payment, reverse)

    def test_source_reverse_import_boundary_and_hidden_reverse_denied(self):
        slip = self._payroll()
        payment = self._pay(slip, 600)
        # Payroll protects its own reversal action. An ordinary native journal
        # entry can still reference the standard reversal relation (e.g. an
        # imported correction); no protected HR link, token or SQL is used.
        source = slip.move_id
        reverse = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': source.journal_id.id,
            'date': '2026-07-02', 'reversed_entry_id': source.id,
            'line_ids': [Command.create({
                'name': 'Native imported source reversal', 'account_id': line.account_id.id,
                'partner_id': line.partner_id.id, 'debit': line.credit, 'credit': line.debit,
            }) for line in source.line_ids],
        })
        reverse.action_post()
        self.assertEqual(reverse.reversed_entry_id, source)
        self._assert_reversed_cash_unclaimed(payment, reverse)

    def test_outstanding_salary_full_bank_clearings_use_actual_cash_dates_once(self):
        self._loan()
        slip = self._payroll()
        self.method.payment_account_id = self.outstanding
        first = self._pay(slip, 600, '2026-07-01')
        second = self._pay(slip, 900, '2026-07-02')
        self.assertEqual(self._read(start='2026-07-01', end='2026-07-04')['events'], [])
        statement_one = self._clear_outstanding(first, '2026-07-05')
        statement_two = self._clear_outstanding(second, '2026-07-06')
        result = self._read()
        self.assertEqual(result['excluded'], {})
        self.assertEqual(result['claimed_payment_ids'], set())
        self.assertEqual(result['claimed_statement_ids'], {statement_one.id, statement_two.id})
        self.assertEqual(len(result['claimed_liquidity_ids']), 3)
        salaries = [row for row in result['events'] if row['classification'] == 'payroll']
        self.assertEqual({row['source_model'] for row in salaries}, {'account.bank.statement.line'})
        self.assertEqual({row['origin_payment_id'] for row in salaries}, {first.id, second.id})
        self.assertEqual({row['date'] for row in salaries}, {'2026-07-05', '2026-07-06'})
        self.assertEqual(sum(row['amount'] for row in salaries), Decimal('1500'))
        self.assertEqual(self._read(start='2026-07-01', end='2026-07-04')['events'], [])
        on_first_bank_day = self._read(start='2026-07-05', end='2026-07-05')
        self.assertEqual(sum(row['amount'] for row in on_first_bank_day['events']), Decimal('600'))
        integrated = self.report._owner_cash(
            self.company, '2026-06-01', '2026-07-31', self.bank.ids)
        self.assertTrue(integrated['coverage_complete'], integrated['excluded'])
        self.assertEqual(integrated['excluded'], {})
        self.assertEqual(sum(integrated['liquidity_totals'].values()), Decimal('2000'))
        self.assertEqual(len(integrated['events']), 3)
        self.assertEqual(self._read(), result)

    def test_outstanding_wage_correction_and_hidden_clearing_chain(self):
        slip = self._payroll()
        self._pay(slip, 2000)
        correction = self.env['baseer.payroll.correction'].create({
            'company_id': self.company.id, 'slip_id': slip.id, 'kind': 'wage',
            'amount': 100, 'date': '2026-07-02',
            'reason': 'Native outstanding wage correction', 'reviewed': True,
        })
        correction.action_confirm()
        self.method.payment_account_id = self.outstanding
        payment = self._pay(slip, 100, '2026-07-03')
        self.assertEqual(self._read(start='2026-07-02')['events'], [])
        statement = self._clear_outstanding(payment, '2026-07-05')
        secured = self._reader()
        result = self._read(report=secured, start='2026-07-02')
        self.assertEqual(result['claimed_statement_ids'], {statement.id})
        self.assertEqual([row['amount'] for row in result['events']], [Decimal('100')])
        credit = payment.move_id.line_ids.filtered(lambda row: row.account_id == self.outstanding)
        clearing = credit.matched_debit_ids
        for model, record in (
                ('account.bank.statement.line', statement),
                ('account.partial.reconcile', clearing), ('account.payment', payment),
                ('account.move.line', credit), ('account.move', correction.move_id),
                ('hr.payslip', slip)):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide salary bank chain %s' % model,
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': "[('id', '!=', %s)]" % record.id,
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', record.id)]))
                    with self.assertRaises(AccessError):
                        self._read(report=secured, start='2026-07-02')
                finally:
                    rule.unlink()

    def test_partial_or_split_bank_clearing_cannot_claim_whole_salary_payment(self):
        slip = self._payroll()
        self.method.payment_account_id = self.outstanding
        payment = self._pay(slip, 600)
        self._clear_outstanding(payment, '2026-07-05', amount=300)
        for stage in ('partial', 'split'):
            with self.subTest(stage=stage):
                if stage == 'split':
                    self._clear_outstanding(payment, '2026-07-06', amount=300)
                result = self._read()
                self.assertEqual(result['events'], [])
                self.assertEqual(result['claimed_statement_ids'], set())
                self.assertEqual(result['claimed_payment_ids'], set())
                self.assertEqual(result['claimed_liquidity_ids'], set())
                integrated = self.report._owner_cash(
                    self.company, '2026-06-01', '2026-07-31', self.bank.ids)
                self.assertFalse(integrated['coverage_complete'])
                self.assertEqual(integrated['events'], [])
