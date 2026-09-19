from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.common import INTERNAL


@tagged('post_install', '-at_install')
class PayrollAnalyticsCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.plan = cls.env.ref('baseer_payroll.payroll_cost_plan')
        Account = cls.env['account.account']
        cls.expense = Account.search([
            ('company_ids', 'in', cls.company.ids),
            ('account_type', 'in', ('expense', 'expense_direct_cost')),
        ], limit=1)
        cls.payable = Account.search([
            ('company_ids', 'in', cls.company.ids), ('account_type', '=', 'liability_payable'),
        ], limit=1)
        cls.advance = Account.search([
            ('company_ids', 'in', cls.company.ids), ('account_type', '=', 'asset_receivable'),
        ], limit=1)
        cls.journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'general'),
        ], limit=1)
        if not (cls.expense and cls.payable and cls.advance and cls.journal):
            raise AssertionError('The Odoo accounting test chart is incomplete.')
        cls.account = cls.env['account.analytic.account'].create({
            'name': 'Payroll analytic test',
            'plan_id': cls.plan.id,
            'company_id': cls.company.id,
        })
        cls.company.write({
            'baseer_salary_expense_id': cls.expense.id,
            'baseer_salary_payable_id': cls.payable.id,
            'baseer_loan_account_id': cls.advance.id,
            'baseer_payroll_journal_id': cls.journal.id,
            'baseer_payroll_analytic_account_id': cls.account.id,
            'baseer_payroll_analytic_enabled': True,
        })

    def _create_payroll_move(self):
        company = self.company
        move = self.env['account.move'].with_company(company).with_context(
            allowed_company_ids=[company.id],
            baseer_payroll_internal=INTERNAL,
            baseer_payroll_analytic_default=INTERNAL,
            baseer_payroll_analytic_company_id=company.id,
        ).create({
            'move_type': 'entry',
            'journal_id': company.baseer_payroll_journal_id.id,
            'date': fields.Date.today(),
            'line_ids': [
                (0, 0, {
                    'name': 'Salary expense',
                    'account_id': company.baseer_salary_expense_id.id,
                    'debit': 2000,
                    'credit': 0,
                    # Simulates the third-party provider's unsafe rule value.
                    'analytic_distribution': {'999999': 100},
                }),
                (0, 0, {
                    'name': 'Salary payable',
                    'account_id': company.baseer_salary_payable_id.id,
                    'debit': 0,
                    'credit': 1500,
                    'analytic_distribution': {'999999': 100},
                }),
                (0, 0, {
                    'name': 'Advance settlement',
                    'account_id': company.baseer_loan_account_id.id,
                    'debit': 0,
                    'credit': 500,
                    'analytic_distribution': {'999999': 100},
                }),
            ],
        })
        return move

    def test_payroll_creation_allocates_expense_only(self):
        move = self._create_payroll_move()
        expected = {str(self.account.id): 100}
        expense = move.line_ids.filtered(lambda line: line.account_id == self.company.baseer_salary_expense_id)
        self.assertEqual(expense.analytic_distribution, expected)
        self.assertFalse(any(line.analytic_distribution for line in (move.line_ids - expense)))
        self.assertEqual(sum(move.line_ids.mapped('balance')), 0)

    def test_disabled_payroll_analytics_clears_provider_values(self):
        self.company.baseer_payroll_analytic_enabled = False
        move = self._create_payroll_move()
        self.assertFalse(any(line.analytic_distribution for line in move.line_ids))

    def test_foreign_or_archived_account_cannot_enable_payroll_analytics(self):
        other = self.env['res.company'].create({'name': 'Foreign analytic company'})
        foreign = self.env['account.analytic.account'].create({
            'name': 'Foreign payroll analytic', 'plan_id': self.plan.id, 'company_id': other.id,
        })
        with self.assertRaises(ValidationError):
            self.company.write({'baseer_payroll_analytic_account_id': foreign.id})
        self.account.active = False
        with self.assertRaises(ValidationError):
            self.company.write({'baseer_payroll_analytic_enabled': True})
