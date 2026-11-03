from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'abroj_contracting')
class AbrojAccountingIssueCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.company = cls.env.company
        cls.expense = cls.env['account.account'].create({
            'name': 'Issue expense', 'code': 'AIXP01', 'account_type': 'expense',
        })
        cls.payable = cls.env['account.account'].create({
            'name': 'Issue payable', 'code': 'AIPY01',
            'account_type': 'liability_payable', 'reconcile': True,
        })
        cls.receivable = cls.env['account.account'].create({
            'name': 'Issue receivable', 'code': 'AIRC01',
            'account_type': 'asset_receivable', 'reconcile': True,
        })
        cls.vat_account = cls.env['account.account'].create({
            'name': 'Issue recoverable VAT', 'code': 'AIVA01', 'account_type': 'asset_current',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Issue native supplier'})
        cls.partner.property_account_payable_id = cls.payable
        cls.partner.property_account_receivable_id = cls.receivable
        cls.journal = cls.env['account.journal'].create({
            'name': 'Issue purchases', 'code': 'AIPU', 'type': 'purchase',
            'company_id': cls.company.id,
        })
        plan = cls.env['project.project']._abroj_project_analytic_plan()
        cls.project = cls.env['project.project'].create({
            'name': 'Accounting issue fixture', 'company_id': cls.company.id,
            'contract_value': 10000,
        })
        cls.project.account_id = cls.env['account.analytic.account'].create({
            'name': 'Issue project analytics', 'company_id': cls.company.id, 'plan_id': plan.id,
        })
        cls.tax = cls.env['account.tax'].create({
            'name': 'Issue VAT15', 'amount': 15, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': cls.company.id,
            'invoice_repartition_line_ids': [
                Command.create({'repartition_type': 'base'}),
                Command.create({'repartition_type': 'tax', 'account_id': cls.vat_account.id}),
            ],
            'refund_repartition_line_ids': [
                Command.create({'repartition_type': 'base'}),
                Command.create({'repartition_type': 'tax', 'account_id': cls.vat_account.id}),
            ],
        })
        groups = [cls.env.ref('base.group_user').id, cls.env.ref('project.group_project_manager').id]
        cls.reader = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Issue project reader', 'login': 'issue_project_reader',
            'group_ids': [Command.set(groups)],
        })
        cls.agent = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Issue extraction accountant', 'login': 'issue_extraction_accountant',
            'group_ids': [Command.set(groups + [
                cls.env.ref('account.group_account_invoice').id,
                cls.env.ref('abroj_contracting.group_extraction_agent').id,
            ])],
        })

    def cost(self, amount=100, confirmed=True, **extra):
        values = {'project_id': self.project.id, 'name': 'Confirmed issue cost',
                  'partner_id': self.partner.id, 'amount': amount, 'date': self.today}
        values.update(extra)
        cost = self.env['abroj.contracting.cost'].create(values)
        if confirmed:
            cost.action_confirm()
        return cost

    def wizard(self, cost, **extra):
        values = {
            'cost_id': cost.id, 'mode': 'create', 'partner_id': self.partner.id,
            'journal_id': self.journal.id, 'expense_account_id': self.expense.id,
            'invoice_date': self.today, 'date': self.today,
        }
        values.update(extra)
        return self.env['abroj.contracting.accounting.issue'].create(values)

    def issue(self, cost, **extra):
        action = self.wizard(cost, **extra).action_issue()
        self.assertEqual(action['res_model'], 'account.move')
        bill = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(bill, cost.account_move_id)
        return bill

    def existing_bill(self, amount=100, **extra):
        values = {
            'move_type': 'in_invoice', 'partner_id': self.partner.id,
            'company_id': self.company.id, 'currency_id': self.company.currency_id.id,
            'journal_id': self.journal.id, 'invoice_date': self.today, 'date': self.today,
            'abroj_project_id': self.project.id,
            'invoice_line_ids': [Command.create({
                'name': 'Previously recorded expense', 'account_id': self.expense.id,
                'quantity': 1, 'price_unit': amount, 'tax_ids': [Command.clear()],
                'analytic_distribution': {str(self.project.account_id.id): 100},
            })],
        }
        values.update(extra)
        bill = self.env['account.move'].create(values)
        bill.action_post()
        return bill

    def test_issue_native_bill_without_tax_and_balanced_entry(self):
        cost = self.cost()
        bill = self.issue(cost)
        self.assertEqual((bill.state, bill.move_type, bill.amount_total), ('posted', 'in_invoice', 100))
        self.assertEqual(bill.abroj_cost_id, cost)
        self.assertEqual(bill.abroj_project_id, self.project)
        self.assertEqual(bill.partner_id, self.partner)
        self.assertEqual(bill.invoice_line_ids.analytic_distribution, {str(self.project.account_id.id): 100})
        self.assertEqual(sum(bill.line_ids.mapped('balance')), 0)
        self.assertEqual(self.project.total_costs, 100)

    def test_gross_tax_uses_native_bill_and_preserves_source_total(self):
        cost = self.cost(115)
        bill = self.issue(cost, tax_ids=[Command.set(self.tax.ids)])
        self.assertEqual((bill.amount_untaxed, bill.amount_tax, bill.amount_total), (100, 15, 115))
        self.assertEqual(cost.amount, 115)
        self.assertEqual(self.project.total_costs, 115)
        lines = self.env['account.analytic.line'].search([
            ('move_line_id', 'in', bill.line_ids.ids), ('account_id', '=', self.project.account_id.id),
            ('general_account_id', '=', self.expense.id),
        ])
        self.assertEqual(-sum(lines.mapped('amount')), 100)

    def test_included_tax_and_currency_cents(self):
        self.tax.price_include_override = 'tax_included'
        bill = self.issue(self.cost(1.15), tax_ids=[Command.set(self.tax.ids)])
        self.assertEqual((bill.amount_untaxed, bill.amount_tax, bill.amount_total), (1, 0.15, 1.15))

    def test_excluded_tax_preserves_odd_gross_cents(self):
        bill = self.issue(self.cost(100.01), tax_ids=[Command.set(self.tax.ids)])
        self.assertEqual(bill.amount_total, 100.01)
        self.assertEqual(bill.currency_id.round(bill.amount_untaxed + bill.amount_tax), 100.01)

    def test_repeated_issue_returns_same_bill_once(self):
        cost = self.cost()
        first = self.issue(cost)
        second = self.issue(cost)
        self.assertEqual(first, second)
        self.assertEqual(self.env['account.move'].search_count([('abroj_cost_id', '=', cost.id)]), 1)
        self.assertEqual(cost.action_open_accounting_issue()['res_id'], first.id)
        self.assertEqual(self.project.total_costs, 100)

    def test_existing_posted_bill_adoption_creates_no_new_expense(self):
        cost = self.cost()
        bill = self.existing_bill()
        before = self.env['account.move'].search_count([])
        linked = self.issue(cost, mode='existing', existing_move_id=bill.id)
        self.assertEqual(linked, bill)
        self.assertEqual(self.env['account.move'].search_count([]), before)
        self.assertEqual(self.project.total_costs, 100)

    def test_existing_bill_cannot_be_claimed_by_second_cost(self):
        first, second = self.cost(), self.cost()
        bill = self.existing_bill()
        self.issue(first, mode='existing', existing_move_id=bill.id)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(second, mode='existing', existing_move_id=bill.id)
        self.assertFalse(second.account_move_id)

    def test_native_cost_link_has_database_uniqueness(self):
        cost = self.cost()
        first = self.issue(cost)
        second = self.existing_bill()
        first.flush_recordset(['abroj_cost_id'])
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            # Deliberately bypass ORM to prove the database also prevents a race.
            self.cr.execute('UPDATE account_move SET abroj_cost_id=%s WHERE id=%s',
                            (cost.id, second.id))
        self.assertEqual(self.env['account.move'].search_count([('abroj_cost_id', '=', cost.id)]), 1)

    def test_existing_bill_amount_partner_project_and_state_must_match(self):
        bill = self.existing_bill(90)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(self.cost(100), mode='existing', existing_move_id=bill.id)
        other = self.env['res.partner'].create({'name': 'Unrelated supplier'})
        other.property_account_payable_id = self.payable
        bill = self.existing_bill(partner_id=other.id)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(self.cost(), mode='existing', existing_move_id=bill.id)
        other_project = self.env['project.project'].create({'name': 'Different expense project'})
        bill = self.existing_bill(abroj_project_id=other_project.id)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(self.cost(), mode='existing', existing_move_id=bill.id)
        bill = self.existing_bill()
        bill.button_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(self.cost(), mode='existing', existing_move_id=bill.id)

    def test_unconfirmed_cost_cannot_issue(self):
        cost = self.cost(confirmed=False)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(cost)
        self.assertFalse(cost.account_move_id)

    def test_nonaccountant_and_extraction_agent_cannot_issue(self):
        cost = self.cost()
        for user in (self.reader, self.agent):
            with self.subTest(user=user.login):
                self.assertFalse(cost.with_user(user).abroj_can_accounting_issue)
                with self.assertRaises(AccessError):
                    cost.with_user(user).action_open_accounting_issue()
                wizard = self.wizard(cost)
                with self.assertRaises(AccessError):
                    wizard.with_user(user).action_issue()
        self.assertFalse(cost.account_move_id)

    def test_link_cannot_be_forged_via_create_write_or_cost_relations(self):
        cost = self.cost()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['account.move'].create({'journal_id': self.journal.id, 'abroj_cost_id': cost.id})
        bill = self.existing_bill()
        with self.assertRaises(AccessError):
            bill.write({'abroj_cost_id': cost.id})
        with self.assertRaises(AccessError):
            cost.write({'account_move_id': bill.id})
        with self.assertRaises(AccessError):
            cost.write({'account_move_ids': [Command.link(bill.id)]})

    def test_rpc_context_defaults_cannot_bypass_accounting_guards(self):
        unlinked = self.cost()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['account.move'].with_context(default_abroj_cost_id=unlinked.id).create({
                'move_type': 'in_invoice', 'journal_id': self.journal.id,
                'partner_id': self.partner.id, 'invoice_date': self.today,
            })
        self.assertFalse(unlinked.account_move_id)
        linked = self.issue(self.cost())
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['account.move.line'].with_context(
                default_move_id=linked.id, check_move_validity=False,
            ).create({'name': 'Injected through context', 'account_id': self.expense.id,
                      'debit': 1, 'credit': 0})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['abroj.contracting.voucher'].with_context(
                default_accounting_partner_id=self.partner.id,
            ).create({'project_id': self.project.id, 'partner_id': self.partner.id,
                      'kind': 'payment', 'amount': 100,
                      'vendor_contract_reference': 'CONTEXT/TEST', 'vendor_contract_value': 100})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['abroj.contracting.cost'].with_context(default_state='confirmed').create({
                'project_id': self.project.id, 'name': 'Forged confirmed expense',
                'partner_id': self.partner.id, 'amount': 100,
            })

    def test_original_bill_link_and_lifecycle_are_frozen(self):
        bill = self.issue(self.cost())
        with self.assertRaises(AccessError):
            bill.write({'abroj_cost_id': False})
        for operation in (
            lambda: bill.write({'invoice_line_ids': [Command.clear()]}),
            bill.button_draft, bill.button_cancel, bill.unlink,
        ):
            with self.assertRaises(UserError), self.cr.savepoint():
                operation()
        self.assertEqual(bill.state, 'posted')

    def test_foreign_journal_line_cannot_be_reparented_into_linked_bill(self):
        bill = self.issue(self.cost())
        foreign = self.existing_bill()
        source = foreign.invoice_line_ids[:1]
        with self.assertRaises(UserError), self.cr.savepoint():
            source.with_context(check_move_validity=False).write({'move_id': bill.id})
        self.assertEqual(source.move_id, foreign)

    def test_copy_and_credit_note_do_not_duplicate_cost_link(self):
        cost = self.cost()
        bill = self.issue(cost)
        copy = bill.copy()
        self.assertFalse(copy.abroj_cost_id)
        reversal = bill._reverse_moves([{
            'date': self.today, 'invoice_date': self.today, 'ref': 'Issue cost reversal',
        }], cancel=False)
        self.assertFalse(reversal.abroj_cost_id)
        reversal.action_post()
        self.assertEqual(cost.account_move_id, bill)
        original_amount = sum(self.env['account.analytic.line'].search([
            ('move_line_id', 'in', (bill | reversal).line_ids.ids),
            ('account_id', '=', self.project.account_id.id),
            ('general_account_id', '=', self.expense.id),
        ]).mapped('amount'))
        self.assertEqual(original_amount, 0)
        self.assertEqual(self.project.total_costs, 100)

    def test_posting_failure_rolls_back_document_and_link(self):
        cost = self.cost()
        wizard = self.wizard(cost)
        count = self.env['account.move'].search_count([])
        with patch.object(type(self.env['account.move']), 'action_post', side_effect=UserError('Posting rejected')):
            with self.assertRaises(UserError), self.cr.savepoint():
                wizard.action_issue()
        cost.invalidate_recordset()
        self.assertFalse(cost.account_move_id)
        self.assertEqual(self.env['account.move'].search_count([]), count)

    def test_sales_tax_and_nonexpense_account_are_rejected(self):
        sale_tax = self.tax.copy({'name': 'Wrong sale tax', 'type_tax_use': 'sale'})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(self.cost(115), tax_ids=[Command.set(sale_tax.ids)])
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(self.cost(), expense_account_id=self.vat_account.id)

    def test_cross_company_journal_is_rejected(self):
        company = self.env['res.company'].create({'name': 'Different issue company'})
        journal = self.env['account.journal'].with_company(company).create({
            'name': 'Other issue journal', 'code': 'AIOP', 'type': 'purchase', 'company_id': company.id,
        })
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(self.cost(), journal_id=journal.id)

    def test_expense_amount_precision_is_validated(self):
        with self.assertRaises(UserError), self.cr.savepoint():
            self.issue(self.cost(100.001))

    def test_payment_settlement_does_not_add_another_expense(self):
        cost = self.cost()
        bill = self.issue(cost)
        cash = self.env['account.account'].create({
            'name': 'Issue settlement cash', 'code': 'AICS01', 'account_type': 'asset_cash',
        })
        journal = self.env['account.journal'].create({
            'name': 'Issue settlement cash', 'code': 'AICS', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': cash.id,
        })
        journal.outbound_payment_method_line_ids.payment_account_id = cash
        voucher = self.env['abroj.contracting.voucher'].create({
            'project_id': self.project.id, 'partner_id': self.partner.id,
            'kind': 'payment', 'amount': 100, 'method': 'cash', 'journal_id': journal.id,
            'vendor_contract_reference': 'ISSUE/SETTLEMENT', 'vendor_contract_value': 100,
        })
        voucher.action_issue()
        voucher.action_accounting_approve()
        all_lines = self.env['account.analytic.line'].search([
            ('account_id', '=', self.project.account_id.id),
            ('move_line_id.account_id.account_type', 'in', ['expense', 'expense_direct_cost', 'expense_depreciation']),
            ('move_line_id.move_id.state', '=', 'posted'),
        ])
        self.assertEqual(-sum(all_lines.mapped('amount')), 100)
        self.assertEqual(self.project.total_costs, 100)
        self.assertEqual(self.project.total_paid, 100)
        self.assertEqual(cost.account_move_id, bill)
        if 'abroj_actual' in self.project._fields:
            self.assertEqual(self.project._abroj_data()['actual'], 100)
            self.assertEqual(self.project.abroj_actual, 100)

    def _voucher_review_fixture(self, kind='receipt'):
        self.project.partner_id = self.partner
        cash = self.env['account.account'].create({
            'name': 'Voucher reviewed cash', 'code': 'AIVC01', 'account_type': 'asset_cash',
        })
        journal = self.env['account.journal'].create({
            'name': 'Voucher review journal', 'code': 'AIVC', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': cash.id,
        })
        (journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids).payment_account_id = cash
        voucher = self.env['abroj.contracting.voucher'].create({
            'project_id': self.project.id, 'partner_id': self.partner.id,
            'kind': kind, 'amount': 100, 'method': 'cash',
        })
        voucher.action_issue()
        wizard = self.env['abroj.contracting.accounting.issue'].create({
            'voucher_id': voucher.id, 'partner_id': self.partner.id,
            'journal_id': journal.id, 'date': self.today,
        })
        return voucher, journal, wizard

    def test_voucher_review_issues_one_native_receipt_payment(self):
        voucher, journal, wizard = self._voucher_review_fixture()
        before = self.env['account.payment'].search_count([])
        action = wizard.action_issue()
        self.assertEqual(action['res_model'], 'account.move')
        self.assertEqual(action['res_id'], voucher.payment_id.move_id.id)
        self.assertEqual(voucher.accounting_partner_id, self.partner)
        self.assertEqual(voucher.payment_id.partner_id, self.partner)
        self.assertEqual(voucher.payment_id.payment_type, 'inbound')
        self.assertEqual(voucher.payment_id.journal_id, journal)
        self.assertEqual(voucher.payment_id.move_id.state, 'posted')
        second = wizard.action_issue()
        self.assertEqual(second['res_id'], action['res_id'])
        self.assertEqual(self.env['account.payment'].search_count([]), before + 1)
        self.assertEqual(voucher.action_open_accounting_issue()['res_id'], action['res_id'])

    def test_voucher_review_rejects_wrong_partner_and_bank_journal(self):
        voucher, journal, wizard = self._voucher_review_fixture()
        other = self.env['res.partner'].create({'name': 'Wrong accounting recipient'})
        wizard.partner_id = other
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.action_issue()
        wizard.partner_id = self.partner
        bank = self.env['account.journal'].create({
            'name': 'Wrong voucher journal', 'code': 'AIVB', 'type': 'bank',
            'company_id': self.company.id,
        })
        wizard.journal_id = bank
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.action_issue()
        self.assertFalse(voucher.payment_id)

    def test_source_native_partner_cannot_be_changed_for_create_or_adoption(self):
        cost = self.cost()
        other = self.env['res.partner'].create({'name': 'Different source supplier'})
        other.property_account_payable_id = self.payable
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.issue(cost, partner_id=other.id)
        existing = self.existing_bill(partner_id=other.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.issue(cost, mode='existing', existing_move_id=existing.id, partner_id=other.id)
        self.assertFalse(cost.account_move_id)

    def test_review_rejects_nonproject_plan_and_changed_voucher_date(self):
        original = self.project.account_id
        plan = self.env['account.analytic.plan'].create({'name': 'Incompatible review plan'})
        incompatible = self.env['account.analytic.account'].create({
            'name': 'Wrong project plan account', 'plan_id': plan.id,
            'company_id': self.company.id,
        })
        self.assertNotEqual(plan._column_name(), 'account_id')
        self.project.account_id = incompatible
        cost = self.cost()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.issue(cost)
        self.project.account_id = original
        voucher, _journal, wizard = self._voucher_review_fixture()
        wizard.date = fields.Date.add(voucher.date, days=1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.action_issue()
        self.assertFalse(voucher.payment_id)
