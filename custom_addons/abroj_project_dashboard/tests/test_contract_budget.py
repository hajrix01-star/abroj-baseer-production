from datetime import timedelta

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged
from odoo.addons.abroj_contracting.models.contracting import FrozenDocument


@tagged('post_install', '-at_install', 'abroj_contract_budget')
class AbrojContractBudgetCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Concrete supplier'})
        cls.project = cls.env['project.project'].create({'name': 'Budget link project'})
        cls.budget = cls.env['abroj.project.budget.line'].create({
            'project_id': cls.project.id, 'name': 'Concrete works', 'budget': 1000,
        })

    def _voucher(self, **values):
        return self.env['abroj.contracting.voucher'].create(dict({
            'project_id': self.project.id, 'partner_id': self.partner.id, 'amount': 10,
        }, **values))

    def test_dashboard_kpi_formulas(self):
        self.project.write({'abroj_contract_value': 2000, 'abroj_budget': 1000})
        self.budget.manual_actual = 950
        contract, journal, payable, expense = self._progress_setup()
        self._progress_payment(contract, journal, payable, 100, fields.Date.today())
        receipt = self._voucher(kind='receipt', payment_purpose='advance', amount=700)
        receipt.action_issue()
        refund = self._voucher(kind='receipt', payment_purpose='supplier_refund',
                               subcontractor_id=contract.id, amount=50)
        refund.action_issue()
        data = self.project._abroj_data()
        self.assertEqual((data['contract'], data['customer_received'], data['remaining']), (2000, 700, 1300))
        self.assertEqual((data['actual'], data['advance_paid'], data['total_spent']), (950, 100, 1050))
        self.assertEqual((data['budget_remaining'], data['budget_overrun']), (-50, 50))
        self.assertEqual((data['paid'], data['project_cash'], data['projected_profit']), (100, 600, 950))
        summary = self.env['project.project']._abroj_financial_summary([data])
        for key in ('contract', 'customer_received', 'remaining', 'total_spent', 'budget_remaining',
                    'budget_overrun', 'project_cash', 'projected_profit'):
            self.assertEqual(summary[key], data[key])
        self.project.abroj_budget = 1200
        data = self.project._abroj_data()
        self.assertEqual((data['budget_remaining'], data['budget_overrun'], data['projected_profit']), (150, 0, 800))
        self.project.abroj_budget = 0
        data = self.project._abroj_data()
        self.assertEqual((data['budget_remaining'], data['budget_overrun'], data['projected_profit']), (None, None, None))

    def test_contract_suggestion(self):
        contract = self.env['abroj.contracting.subcontractor'].create({
            'project_id': self.project.id, 'partner_id': self.partner.id, 'scope': 'Concrete works 123!',
        })
        self.assertEqual(contract.budget_line_id, self.budget)
        self.env['abroj.project.budget.line'].create({'project_id': self.project.id, 'name': 'Concrete works'})
        tied = self.env['abroj.contracting.subcontractor'].create({
            'project_id': self.project.id, 'partner_id': self.partner.id, 'scope': 'Concrete works',
        })
        self.assertFalse(tied.budget_line_id)

    def test_voucher_from_contract(self):
        contract = self.env['abroj.contracting.subcontractor'].create({
            'project_id': self.project.id, 'partner_id': self.partner.id, 'budget_line_id': self.budget.id,
        })
        voucher = self._voucher(subcontractor_id=contract.id)
        self.assertEqual(voucher.abroj_budget_line_id, self.budget)

    def test_voucher_from_last_partner_voucher(self):
        older = self._voucher(date=fields.Date.today() - timedelta(days=1))
        super(FrozenDocument, older).write({'abroj_budget_line_id': self.budget.id})
        voucher = self._voucher()
        self.assertEqual(voucher.abroj_budget_line_id, self.budget)

    def test_group_name(self):
        child = self.env['abroj.project.budget.line'].create({
            'project_id': self.project.id, 'name': 'Child', 'parent_id': self.budget.id,
        })
        self.assertEqual(self.budget.group_name, 'Concrete works')
        self.assertEqual(child.group_name, 'Concrete works')
        self.budget.name = 'Renamed'
        self.assertEqual(child.group_name, 'Renamed')
        child.parent_id = False
        self.assertEqual(child.group_name, 'Child')

    def test_advance_residual_after_settlement(self):
        payable = self.env['account.account'].create({
            'name': 'Budget payable', 'code': 'BUDPAY', 'account_type': 'liability_payable', 'reconcile': True,
        })
        cash = self.env['account.account'].create({
            'name': 'Budget cash', 'code': 'BUDCASH', 'account_type': 'asset_cash',
        })
        expense = self.env['account.account'].create({
            'name': 'Budget expense', 'code': 'BUDEXP', 'account_type': 'expense',
        })
        self.partner.property_account_payable_id = payable
        journal = self.env['account.journal'].create({
            'name': 'Budget cash', 'code': 'BGC', 'type': 'cash', 'default_account_id': cash.id,
        })
        journal.outbound_payment_method_line_ids.payment_account_id = cash
        voucher = self._voucher(kind='payment', payment_purpose='advance', amount=100,
                                method='cash', vendor_contract_reference='BUD', vendor_contract_value=1000)
        super(FrozenDocument, voucher).write({'abroj_budget_line_id': self.budget.id})
        voucher.action_issue()
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound', 'partner_type': 'supplier', 'partner_id': self.partner.id,
            'amount': 100, 'date': fields.Date.today(), 'journal_id': journal.id,
            'payment_method_line_id': journal.outbound_payment_method_line_ids[0].id,
            'destination_account_id': payable.id,
        })
        payment._generate_journal_entry()
        payment.action_post()
        super(FrozenDocument, voucher).write({'payment_id': payment.id})
        self.assertEqual(self.budget.advance_paid, 100)
        self.assertEqual(self.budget.total_spent, 100)
        purchase = self.env['account.journal'].create({'name': 'Budget purchase', 'code': 'BGP', 'type': 'purchase'})
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.partner.id, 'journal_id': purchase.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({'name': 'Bill', 'price_unit': 100,
                                                  'account_id': expense.id, 'tax_ids': [Command.clear()]})],
        })
        bill.action_post()
        (payment.move_id.line_ids | bill.line_ids).filtered(lambda l: l.account_id == payable).reconcile()
        self.assertEqual(self.budget.advance_paid, 0)

    def test_over_budget_does_not_block_write(self):
        self.budget.manual_actual = 1100
        self.assertTrue(self.budget.over_budget)
        self.assertEqual(self.budget.total_spent, 1100)
        self.assertEqual(self.budget.remaining_budget, -100)
        self.budget.manual_actual = 900
        self.assertFalse(self.budget.over_budget)

    def _progress_setup(self):
        payable = self.env['account.account'].create({'name': 'Progress payable', 'code': 'PRPAY', 'account_type': 'liability_payable', 'reconcile': True})
        cash = self.env['account.account'].create({'name': 'Progress cash', 'code': 'PRCASH', 'account_type': 'asset_cash'})
        expense = self.env['account.account'].create({'name': 'Progress expense', 'code': 'PREXP', 'account_type': 'expense'})
        self.partner.property_account_payable_id = payable
        self.budget.account_id = expense
        plan = self.env['project.project']._abroj_project_analytic_plan()
        self.project.account_id = self.env['account.analytic.account'].create({'name': 'Progress project', 'plan_id': plan.id})
        journal = self.env['account.journal'].create({'name': 'Progress cash', 'code': 'PRC', 'type': 'cash', 'default_account_id': cash.id})
        journal.outbound_payment_method_line_ids.payment_account_id = cash
        self.env['account.journal'].create({'name': 'Progress purchase', 'code': 'PRP', 'type': 'purchase'})
        contract = self.env['abroj.contracting.subcontractor'].create({'project_id': self.project.id, 'partner_id': self.partner.id, 'budget_line_id': self.budget.id})
        return contract, journal, payable, expense

    def _progress_payment(self, contract, journal, payable, amount, date):
        voucher = self._voucher(kind='payment', payment_purpose='advance', subcontractor_id=contract.id, amount=amount, date=date)
        voucher.action_issue()
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound', 'partner_type': 'supplier', 'partner_id': self.partner.id,
            'amount': amount, 'date': date, 'journal_id': journal.id,
            'payment_method_line_id': journal.outbound_payment_method_line_ids[0].id, 'destination_account_id': payable.id,
        })
        payment._generate_journal_entry()
        payment.action_post()
        super(FrozenDocument, voucher).write({'payment_id': payment.id})
        return payment

    def test_progress_bill_and_oldest_advances(self):
        contract, journal, payable, expense = self._progress_setup()
        today = fields.Date.today()
        old = self._progress_payment(contract, journal, payable, 60, today - timedelta(days=2))
        new = self._progress_payment(contract, journal, payable, 80, today - timedelta(days=1))
        self.assertEqual(contract.state, 'open')
        wizard = self.env['abroj.contract.progress.bill.wizard'].create({'contract_id': contract.id, 'amount': 100, 'mode': 'progress'})
        bill = self.env['account.move'].browse(wizard.action_confirm()['res_id'])
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.invoice_line_ids.account_id, expense)
        self.assertEqual(bill.abroj_budget_line_id, self.budget)
        self.assertIn(str(self.project.account_id.id), next(iter(bill.invoice_line_ids.analytic_distribution)))
        self.assertEqual(bill.ref, 'مستخلص %s' % contract.display_name)
        self.assertIn(bill, contract.progress_bill_ids)
        self.assertEqual(sum(old.move_id.line_ids.filtered(lambda l: l.account_id == payable).mapped('amount_residual')), 0)
        self.assertAlmostEqual(sum(new.move_id.line_ids.filtered(lambda l: l.account_id == payable).mapped('amount_residual')), 40)
        agent_bill = contract.action_create_progress_bill(10, by_agent=True)
        self.assertTrue(agent_bill.ref.endswith(' - AGENT: مساعد البرمجة'))

    def test_final_bill_defaults_and_closes(self):
        contract, journal, payable, expense = self._progress_setup()
        self._progress_payment(contract, journal, payable, 75, fields.Date.today())
        self.assertEqual(contract.state, 'open')
        defaults = self.env['abroj.contract.progress.bill.wizard'].with_context(default_contract_id=contract.id, default_mode='final').default_get(['contract_id', 'mode', 'amount'])
        self.assertEqual(defaults['amount'], 75)
        wizard = self.env['abroj.contract.progress.bill.wizard'].create(defaults)
        bill = self.env['account.move'].browse(wizard.action_confirm()['res_id'])
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(contract.state, 'closed')
        self.assertEqual(bill.amount_residual, 0)
