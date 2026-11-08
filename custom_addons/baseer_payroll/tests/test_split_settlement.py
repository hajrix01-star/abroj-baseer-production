from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.common import money


class SplitSettlementFixture:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        admin = cls.env.ref('base.user_admin')
        admin.write({
            'company_ids': [Command.link(company.id)],
            'group_ids': [Command.link(cls.env.ref(xmlid).id) for xmlid in (
                'account.group_account_user',
                'account.group_account_manager',
                'hr.group_hr_manager',
                'om_hr_payroll.group_hr_payroll_manager',
            )],
        })
        cls.payroll_env = cls.env(user=admin.id, context={
            'allowed_company_ids': company.ids,
            'tracking_disable': True,
        }, su=False)

        def account(code, kind, reconcile=False):
            return cls.env['account.account'].create({
                'name': 'Split payroll test ' + code,
                'code': code,
                'account_type': kind,
                'reconcile': reconcile,
                'company_ids': [Command.set(company.ids)],
            })

        def journal(name, code, kind, treasury=None):
            vals = {'name': name, 'code': code, 'type': kind, 'company_id': company.id}
            if treasury:
                vals['default_account_id'] = treasury.id
            return cls.env['account.journal'].create(vals)

        expense = account('978201', 'expense')
        payable = account('978202', 'liability_payable', True)
        advance = account('978203', 'asset_receivable', True)
        deduction = account('978204', 'income_other')
        payroll_journal = journal('Split test payroll', 'STP', 'general')
        cls.primary = journal('Split test bank', 'STB', 'bank', account('978205', 'asset_cash'))
        cls.secondary = journal('Split test cash', 'STC', 'cash', account('978206', 'asset_cash'))
        manual = cls.env.ref('account.account_payment_method_manual_out')
        cls.primary_method = cls.primary.outbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id == manual
        ).ensure_one()
        cls.secondary_method = cls.secondary.outbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id == manual
        ).ensure_one()
        for method in cls.primary_method | cls.secondary_method:
            method.payment_account_id = method.journal_id.default_account_id

        analytic = cls.env['account.analytic.account'].create({
            'name': 'Split payroll test cost center',
            'plan_id': cls.env.ref('baseer_payroll.payroll_cost_plan').id,
            'company_id': company.id,
        })
        company.write({
            'baseer_salary_expense_id': expense.id,
            'baseer_salary_payable_id': payable.id,
            'baseer_loan_account_id': advance.id,
            'baseer_deduction_account_id': deduction.id,
            'baseer_payroll_journal_id': payroll_journal.id,
            'baseer_payroll_analytic_account_id': analytic.id,
            'baseer_payroll_analytic_enabled': True,
            'baseer_structure_id': False,
        })
        cls.payable = payable
        cls.employees = cls.env['hr.employee']
        for name, wage in [('Split payroll employee A', 2000), ('Split payroll employee B', 1000)]:
            partner = cls.env['res.partner'].create({
                'name': name,
                'company_id': company.id,
                'property_account_payable_id': payable.id,
                'property_account_receivable_id': advance.id,
            })
            employee = cls.env['hr.employee'].create({
                'name': name,
                'company_id': company.id,
                'work_contact_id': partner.id,
                'baseer_payroll_enabled': True,
            })
            employee.version_id.write({
                'date_version': '2026-01-01',
                'contract_date_start': '2026-01-01',
                'wage': wage,
                'baseer_salary_mode': 'fixed',
            })
            cls.employees |= employee

    def _run(self):
        run = self.payroll_env['hr.payslip.run'].create({
            'baseer_managed': True,
            'baseer_month': '2026-06-01',
        })
        run.slip_ids.filtered(lambda slip: slip.employee_id not in self.employees).unlink()
        run.action_approve()
        self.assertEqual(run.baseer_residual, 3000)
        return run


@tagged('post_install', '-at_install')
class PayrollSplitSettlementCase(SplitSettlementFixture, TransactionCase):
    def _wizard(self, run, split=True):
        action = run.action_pay()
        wizard = run.env[action['res_model']].browse(action['res_id'])
        vals = {
            'journal_id': self.primary.id,
            'payment_method_line_id': self.primary_method.id,
        }
        if split:
            vals.update(second_journal_id=self.secondary.id,
                        second_payment_method_line_id=self.secondary_method.id)
        wizard.write(vals)
        return wizard

    def test_split_posts_native_payments_and_keeps_remaining_salary(self):
        run = self._run()
        wizard = self._wizard(run)
        stale = self._wizard(run, split=False)
        line = wizard.line_ids.filtered(lambda row: row.employee_id == self.employees[0])
        wizard.write({
            'line_ids': [Command.update(line.id, {'amount': 1500.23})],
            'second_amount': 600.11,
        })
        self.assertEqual((wizard.amount_primary, wizard.second_amount), (1900.12, 600.11))
        result = wizard.action_confirm()
        self.assertEqual((result['res_model'], result['res_id']), (run._name, run.id))
        self.assertEqual(len(wizard.payment_ids), 3)
        self.assertEqual(run.baseer_residual, 499.77)
        self.assertEqual(run.baseer_payment_state, 'partial')
        expected = {
            (self.employees[0].work_contact_id.id, self.primary.id): money('1500.23'),
            (self.employees[1].work_contact_id.id, self.primary.id): money('399.89'),
            (self.employees[1].work_contact_id.id, self.secondary.id): money('600.11'),
        }
        for payment in wizard.payment_ids:
            amount = expected.pop((payment.partner_id.id, payment.journal_id.id))
            self.assertEqual(payment.state, 'paid')
            self.assertEqual(payment.move_id.state, 'posted')
            self.assertEqual(payment.date, wizard.payment_date)
            self.assertEqual(payment.payment_type, 'outbound')
            self.assertEqual(payment.company_id, run.company_id)
            self.assertEqual(money(payment.amount), amount)
            cash_lines = payment.move_id.line_ids.filtered(
                lambda row: row.account_id == payment.journal_id.default_account_id)
            payable_lines = payment.move_id.line_ids.filtered(lambda row: row.account_id == self.payable)
            self.assertEqual(money(sum(cash_lines.mapped('balance'))), -amount)
            self.assertEqual(money(sum(payable_lines.mapped('balance'))), amount)
            self.assertEqual(money(sum(payment.move_id.line_ids.mapped('balance'))), 0)
        self.assertFalse(expected)
        ids = wizard.payment_ids.ids
        wizard.action_confirm()
        self.assertCountEqual(wizard.payment_ids.ids, ids)
        self.assertCountEqual([row['payment_id'] for row in run._baseer_payment_rows()], ids)
        self.assertEqual(run._baseer_payment_total(), 2500.23)
        with self.assertRaises(ValidationError):
            stale.action_confirm()

        remainder = self._wizard(run, split=False)
        remainder.action_confirm()
        self.assertEqual(len(remainder.payment_ids), 1)
        self.assertEqual(remainder.payment_ids.journal_id, self.primary)
        self.assertEqual(run.baseer_residual, 0)
        self.assertEqual(run.baseer_payment_state, 'paid')
        self.assertEqual(run._baseer_payment_total(), 3000)

    def test_invalid_allocation_and_method_are_rejected_before_posting(self):
        run = self._run()
        wizard = self._wizard(run)
        payment_count = self.env['account.payment'].search_count([])
        for invalid in (-1, 1.001):
            with self.assertRaises(ValidationError):
                wizard.second_amount = invalid
        with self.assertRaises(ValidationError):
            wizard.action_confirm()
        wizard.second_amount = 3000.01
        with self.assertRaises(ValidationError):
            wizard.action_confirm()
        wizard.second_amount = 100
        wizard.second_payment_method_line_id = self.primary_method
        with self.assertRaises(ValidationError):
            wizard.action_confirm()
        self.assertEqual(self.env['account.payment'].search_count([]), payment_count)
        self.assertEqual(run.baseer_residual, 3000)
        self.assertEqual(wizard.state, 'draft')

    def test_second_journal_cannot_belong_to_another_allowed_company(self):
        run = self._run()
        wizard = self._wizard(run)
        other = self.env['res.company'].create({
            'name': 'Split payroll other company',
            'currency_id': run.currency_id.id,
        })
        self.env.ref('base.user_admin').write({'company_ids': [Command.link(other.id)]})
        foreign_journal = self.env['account.journal'].with_company(other).create({
            'name': 'Split payroll other bank',
            'code': 'STO',
            'type': 'bank',
            'company_id': other.id,
        })
        wizard = wizard.with_context(allowed_company_ids=[run.company_id.id, other.id])
        wizard.write({
            'second_journal_id': foreign_journal.id,
            'second_payment_method_line_id': foreign_journal.outbound_payment_method_line_ids[:1].id,
            'second_amount': 100,
        })
        with self.assertRaisesRegex(ValidationError, 'belonging to this company'):
            wizard.action_confirm()
        self.assertFalse(run._baseer_payment_rows())

    def test_locked_accounting_period_blocks_split_payment(self):
        run = self._run()
        wizard = self._wizard(run)
        wizard.second_amount = 100
        run.company_id.sudo().fiscalyear_lock_date = wizard.payment_date
        with self.assertRaisesRegex(ValidationError, 'locked accounting period'):
            wizard.action_confirm()
        self.assertFalse(run._baseer_payment_rows())

    def test_second_journal_failure_rolls_back_first_native_posting(self):
        run = self._run()
        wizard = self._wizard(run)
        wizard.second_amount = 100
        payments_before = self.env['account.payment'].search_count([])
        moves_before = self.env['account.move'].search_count([])
        record_allocation = type(wizard)._record_allocation
        posted = []

        def fail_second(record, slip, amount, remaining, journal, method):
            if journal == self.secondary:
                self.assertTrue(posted)
                raise UserError('Injected second journal posting failure')
            result = record_allocation(record, slip, amount, remaining, journal, method)
            posted.append(result.ids)
            return result

        with patch.object(type(wizard), '_record_allocation', fail_second):
            with self.assertRaisesRegex(UserError, 'Injected second journal'):
                wizard.action_confirm()

        self.assertEqual(self.env['account.payment'].search_count([]), payments_before)
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)
        self.assertFalse(run._baseer_payment_rows())
        self.assertEqual(run.baseer_residual, 3000)
        self.assertEqual(wizard.state, 'draft')
        self.assertFalse(wizard.payment_ids)
        wizard.action_confirm()
        self.assertEqual(run.baseer_payment_state, 'paid')
