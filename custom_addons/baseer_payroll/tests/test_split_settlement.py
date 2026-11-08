from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
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
        cls.third = journal('Split test reserve', 'STR', 'bank', account('978207', 'asset_cash'))
        cls.same_treasury = journal('Split test bank alias', 'STA', 'bank', cls.primary.default_account_id)
        manual = cls.env.ref('account.account_payment_method_manual_out')
        for field in ('primary', 'secondary', 'third', 'same_treasury'):
            source = getattr(cls, field)
            method = source.outbound_payment_method_line_ids.filtered(
                lambda line: line.payment_method_id == manual
            ).ensure_one()
            method.payment_account_id = method.journal_id.default_account_id
            setattr(cls, field + '_method', method)

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
    def _wizard(self, run):
        action = run.action_pay()
        wizard = run.env[action['res_model']].browse(action['res_id'])
        wizard.write({
            'journal_id': self.primary.id,
            'payment_method_line_id': self.primary_method.id,
        })
        return wizard

    @staticmethod
    def _funding(journal, method, amount):
        return Command.create({
            'journal_id': journal.id,
            'payment_method_line_id': method.id,
            'amount': amount,
        })

    def test_split_posts_native_payments_and_keeps_remaining_salary(self):
        run = self._run()
        wizard = self._wizard(run)
        stale = self._wizard(run)
        line = wizard.line_ids.filtered(lambda row: row.employee_id == self.employees[0])
        wizard.write({
            'line_ids': [Command.update(line.id, {'amount': 1500.23})],
            'funding_line_ids': [
                self._funding(self.secondary, self.secondary_method, 600.11),
                self._funding(self.third, self.third_method, 500.10),
            ],
        })
        self.assertEqual(wizard.amount_primary, 1400.02)
        result = wizard.action_confirm()
        self.assertEqual((result['res_model'], result['res_id']), (run._name, run.id))
        self.assertEqual(len(wizard.payment_ids), 4)
        self.assertEqual(run.baseer_residual, 499.77)
        self.assertEqual(run.baseer_payment_state, 'partial')
        expected = {
            (self.employees[0].work_contact_id.id, self.primary.id): money('1400.02'),
            (self.employees[0].work_contact_id.id, self.secondary.id): money('100.21'),
            (self.employees[1].work_contact_id.id, self.secondary.id): money('499.90'),
            (self.employees[1].work_contact_id.id, self.third.id): money('500.10'),
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

        remainder = self._wizard(run)
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
            with self.subTest(amount=invalid), self.assertRaises(ValidationError), self.cr.savepoint():
                wizard.write({'funding_line_ids': [self._funding(self.secondary, self.secondary_method, invalid)]})
        for case, lines in {
            'zero': [self._funding(self.secondary, self.secondary_method, 0)],
            'total exhausted': [self._funding(self.secondary, self.secondary_method, 3000)],
            'total exceeded': [
                self._funding(self.secondary, self.secondary_method, 1600),
                self._funding(self.third, self.third_method, 1500),
            ],
            'method from another journal': [self._funding(self.secondary, self.primary_method, 100)],
            'duplicate journal': [
                self._funding(self.secondary, self.secondary_method, 100),
                self._funding(self.secondary, self.secondary_method, 200),
            ],
            'duplicate liquidity account': [self._funding(self.same_treasury, self.same_treasury_method, 100)],
        }.items():
            with self.subTest(case=case), self.assertRaises(ValidationError), self.cr.savepoint():
                wizard.write({'funding_line_ids': lines})
                wizard.action_confirm()
        self.assertEqual(self.env['account.payment'].search_count([]), payment_count)
        self.assertEqual(run.baseer_residual, 3000)
        self.assertEqual(wizard.state, 'draft')

    def test_funding_journal_cannot_belong_to_another_allowed_company(self):
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
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.write({'funding_line_ids': [
                self._funding(foreign_journal, foreign_journal.outbound_payment_method_line_ids[:1], 100),
            ]})
            wizard.action_confirm()
        self.assertFalse(run._baseer_payment_rows())

    def test_same_company_manager_cannot_access_another_users_payment_draft(self):
        run = self._run()
        owner_wizard = self._wizard(run)
        owner_wizard.write({'funding_line_ids': [
            self._funding(self.secondary, self.secondary_method, 100),
        ]})
        owner_row = owner_wizard.funding_line_ids.ensure_one()
        company = run.company_id
        other = self.env['res.users'].create({
            'name': 'Another payroll manager',
            'login': 'another.split.payroll.manager',
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([
                self.env.ref(xmlid).id for xmlid in (
                    'base.group_user',
                    'account.group_account_user',
                    'account.group_account_manager',
                    'hr.group_hr_manager',
                    'om_hr_payroll.group_hr_payroll_manager',
                )
            ])],
        })
        own_wizard = self._wizard(run.with_user(other))
        self.assertFalse(owner_wizard.env.su)
        self.assertFalse(own_wizard.env.su)
        own_wizard.write({'funding_line_ids': [self._funding(self.third, self.third_method, 200)]})
        self.assertEqual(own_wizard.funding_line_ids.amount, 200)

        foreign_wizard = owner_wizard.with_user(other)
        foreign_row = owner_row.with_user(other)
        add_source = self._funding(self.third, self.third_method, 300)
        operations = {
            'attach through the wizard': lambda: foreign_wizard.write({'funding_line_ids': [add_source]}),
            'attach directly': lambda: foreign_row.env[foreign_row._name].create({
                **add_source[2], 'settlement_id': foreign_wizard.id,
            }),
            'read source': lambda: foreign_row.read(['amount']),
            'edit source': lambda: foreign_row.write({'amount': 400}),
            'delete source': foreign_row.unlink,
            'confirm draft': foreign_wizard.action_confirm,
        }
        for name, action in operations.items():
            with self.subTest(operation=name), self.assertRaises(AccessError), self.cr.savepoint():
                action()

        self.assertEqual(owner_wizard.funding_line_ids, owner_row)
        self.assertEqual(owner_row.amount, 100)
        self.assertEqual(owner_wizard.state, 'draft')
        self.assertFalse(run._baseer_payment_rows())

    def test_locked_accounting_period_blocks_split_payment(self):
        run = self._run()
        wizard = self._wizard(run)
        wizard.write({'funding_line_ids': [self._funding(self.secondary, self.secondary_method, 100)]})
        run.company_id.sudo().fiscalyear_lock_date = wizard.payment_date
        with self.assertRaisesRegex(ValidationError, 'locked accounting period'):
            wizard.action_confirm()
        self.assertFalse(run._baseer_payment_rows())

    def test_last_funding_journal_failure_rolls_back_all_postings(self):
        run = self._run()
        wizard = self._wizard(run)
        wizard.write({'funding_line_ids': [
            self._funding(self.secondary, self.secondary_method, 400),
            self._funding(self.third, self.third_method, 600),
        ]})
        payments_before = self.env['account.payment'].search_count([])
        moves_before = self.env['account.move'].search_count([])
        record_allocation = type(wizard)._record_allocation
        posted = []

        def fail_last(record, slip, amount, remaining, journal, method):
            if journal == self.third:
                self.assertEqual(posted, [self.primary.id, self.secondary.id])
                raise UserError('Injected last journal posting failure')
            result = record_allocation(record, slip, amount, remaining, journal, method)
            posted.append(journal.id)
            return result

        with patch.object(type(wizard), '_record_allocation', fail_last):
            with self.assertRaisesRegex(UserError, 'Injected last journal'):
                wizard.action_confirm()

        self.assertEqual(self.env['account.payment'].search_count([]), payments_before)
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)
        self.assertFalse(run._baseer_payment_rows())
        self.assertEqual(run.baseer_residual, 3000)
        self.assertEqual(wizard.state, 'draft')
        self.assertFalse(wizard.payment_ids)
        wizard.action_confirm()
        self.assertEqual(run.baseer_payment_state, 'paid')
