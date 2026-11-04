from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.abroj_contracting.models.contracting import FrozenDocument
from odoo.addons.abroj_project_dashboard.models.voucher_workflow import Payment, RecognitionMove


@tagged('post_install', '-at_install', 'abroj_voucher_workflow')
class AbrojVoucherWorkflowCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.company = cls.env.company
        cls.accounts = {}
        for index, kind in enumerate(('expense', 'income', 'liability_payable',
                                      'asset_receivable', 'asset_cash', 'asset_current')):
            cls.accounts[kind] = cls.env['account.account'].create({
                'name': 'Voucher flow ' + kind, 'code': 'VFLOW%s' % index,
                'account_type': kind, 'reconcile': kind in ('liability_payable', 'asset_receivable'),
            })
        cls.partner = cls.env['res.partner'].create({'name': 'Voucher native party'})
        cls.partner.property_account_payable_id = cls.accounts['liability_payable']
        cls.partner.property_account_receivable_id = cls.accounts['asset_receivable']
        cls.cash = cls.env['account.journal'].create({
            'name': 'Voucher flow cash', 'code': 'VFC', 'type': 'cash',
            'company_id': cls.company.id, 'default_account_id': cls.accounts['asset_cash'].id,
        })
        (cls.cash.inbound_payment_method_line_ids | cls.cash.outbound_payment_method_line_ids).payment_account_id = cls.accounts['asset_cash']
        cls.purchase = cls.env['account.journal'].create({
            'name': 'Voucher flow purchases', 'code': 'VFP', 'type': 'purchase', 'company_id': cls.company.id,
        })
        cls.sale = cls.env['account.journal'].create({
            'name': 'Voucher flow sales', 'code': 'VFS', 'type': 'sale', 'company_id': cls.company.id,
        })
        cls.tax = cls.env['account.tax'].create({
            'name': 'Voucher purchase VAT15', 'amount': 15, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': cls.company.id,
            'invoice_repartition_line_ids': [
                Command.create({'repartition_type': 'base'}),
                Command.create({'repartition_type': 'tax', 'account_id': cls.accounts['asset_current'].id}),
            ],
            'refund_repartition_line_ids': [
                Command.create({'repartition_type': 'base'}),
                Command.create({'repartition_type': 'tax', 'account_id': cls.accounts['asset_current'].id}),
            ],
        })
        cls.project = cls.env['project.project'].create({
            'name': 'Voucher workflow fixture', 'company_id': cls.company.id,
            'partner_id': cls.partner.id, 'contract_value': 10000, 'abroj_budget': 1000,
        })
        plan = cls.env['project.project']._abroj_project_analytic_plan()
        cls.project.account_id = cls.env['account.analytic.account'].create({
            'name': 'Voucher native project column', 'plan_id': plan.id, 'company_id': cls.company.id,
        })
        cls.budget = cls.env['abroj.project.budget.line'].create({
            'project_id': cls.project.id, 'name': 'Voucher budget allocation', 'budget': 1000,
        })
        cls.sub = cls.env['abroj.contracting.subcontractor'].create({
            'project_id': cls.project.id, 'partner_id': cls.partner.id, 'agreed_amount': 1000,
        })
        groups = [cls.env.ref('base.group_user').id, cls.env.ref('project.group_project_manager').id]
        cls.reader = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Voucher workflow reader', 'login': 'voucher_workflow_reader',
            'group_ids': [Command.set(groups)],
        })
        cls.agent = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Voucher workflow extraction accountant', 'login': 'voucher_workflow_agent',
            'group_ids': [Command.set(groups + [cls.env.ref('account.group_account_invoice').id,
                                               cls.env.ref('abroj_contracting.group_extraction_agent').id])],
        })

    def voucher(self, kind='payment', purpose='advance', amount=100, issued=True, **extra):
        values = {
            'project_id': self.project.id, 'partner_id': self.partner.id, 'kind': kind,
            'amount': amount, 'method': 'cash', 'date': self.today,
            'payment_purpose': purpose,
            'vendor_contract_reference': 'VFLOW/SOURCE', 'vendor_contract_value': 1000,
        }
        if purpose == 'supplier_refund':
            values['subcontractor_id'] = self.sub.id
        values.update(extra)
        record = self.env['abroj.contracting.voucher'].create(values)
        if issued:
            record.action_issue()
        return record

    def review(self, voucher, purpose=None, **extra):
        purpose = purpose or voucher.payment_purpose
        values = {
            'voucher_id': voucher.id, 'purpose': purpose, 'partner_id': self.partner.id,
            'journal_id': self.cash.id,
            'invoice_journal_id': self.purchase.id if voucher.kind == 'payment' else self.sale.id,
            'name': 'Voucher supporting recognition', 'document_reference': 'VFLOW/%s' % voucher.id,
            'evidence_note': 'Synthetic supporting invoice and receipt evidence',
            'account_id': self.accounts['expense' if voucher.kind == 'payment' else 'income'].id,
            'invoice_date': self.today, 'date': self.today, 'tax_ids': [Command.clear()],
        }
        if voucher.kind == 'payment' and purpose == 'direct':
            values['budget_line_id'] = self.budget.id
        values.update(extra)
        return self.env['abroj.project.voucher.review'].create(values)

    def bill(self, amount=100, move_type='in_invoice', posted=True, project=None, partner=None, currency=None, budget=None):
        project, partner = project or self.project, partner or self.partner
        supplier = move_type in ('in_invoice', 'in_refund')
        if budget is None:
            budget = self.budget if project == self.project else self.env['abroj.project.budget.line'].search([
                ('project_id', '=', project.id),
            ], limit=1)
        bill = self.env['account.move'].create({
            'move_type': move_type, 'partner_id': partner.id,
            'currency_id': (currency or self.company.currency_id).id,
            'journal_id': self.purchase.id if supplier else self.sale.id,
            'invoice_date': self.today, 'date': self.today,
            'abroj_project_id': project.id, 'ref': 'VFLOW/EXISTING',
            'invoice_line_ids': [Command.create({
                'name': 'Existing native recognition', 'quantity': 1, 'price_unit': amount,
                'account_id': self.accounts['expense' if supplier else 'income'].id,
                'tax_ids': [Command.clear()],
                'analytic_distribution': {str(project.account_id.id): 100},
                'abroj_budget_line_id': budget.id if supplier and budget else False,
            })],
        })
        if posted:
            bill.action_post()
        return bill

    def legacy_payment(self, voucher, partner=True):
        """Synthetic already-posted history; never call a new workflow to seed it."""
        native_partner = self.partner if partner else self.env['res.partner']
        supplier = voucher.kind == 'payment' or voucher.payment_purpose == 'supplier_refund'
        direction = 'outbound' if voucher.kind == 'payment' else 'inbound'
        methods = self.cash.outbound_payment_method_line_ids if direction == 'outbound' else self.cash.inbound_payment_method_line_ids
        payment = self.env['account.payment'].create({
            'payment_type': direction, 'partner_type': 'supplier' if supplier else 'customer',
            'partner_id': native_partner.id or False, 'amount': voucher.amount,
            'date': voucher.date, 'currency_id': voucher.currency_id.id,
            'journal_id': self.cash.id, 'payment_method_line_id': methods[0].id,
            'company_id': voucher.company_id.id,
            'destination_account_id': self.accounts['liability_payable' if supplier else 'asset_receivable'].id,
            'memo': voucher.name,
        })
        payment._generate_journal_entry()
        payment.move_id.abroj_project_id = self.project
        counterpart = payment.move_id.line_ids.filtered(lambda line: line.account_id == payment.destination_account_id)
        counterpart.analytic_distribution = {str(self.project.account_id.id): 100}
        payment.action_post()
        # Explicit private seeding models existing posted history; the public
        # API must never allow callers to manufacture these canonical links.
        super(Payment, payment).write({'abroj_voucher_id': voucher.id})
        super(RecognitionMove, payment.move_id).write({
            'abroj_voucher_id': voucher.id,
        })
        super(FrozenDocument, voucher).write({'payment_id': payment.id})
        voucher.invalidate_recordset()
        return payment

    def signature(self, payment):
        return (payment.id, payment.amount, payment.date, payment.journal_id.id, payment.partner_id.id,
                tuple((line.id, line.account_id.id, line.debit, line.credit, line.partner_id.id)
                      for line in payment.move_id.line_ids.sorted('id')))

    def actual(self):
        return self.project._abroj_data()['actual']

    def test_purpose_is_required_before_voucher_issue(self):
        voucher = self.voucher(issued=False, purpose=False)
        with self.assertRaises(UserError), self.cr.savepoint():
            voucher.action_issue()
        self.assertEqual(voucher.state, 'draft')

    def test_direct_expense_recognizes_once_and_allocates_budget(self):
        voucher = self.voucher(purpose='direct')
        wizard = self.review(voucher)
        wizard.action_apply()
        invoice, payment = voucher.recognition_move_id, voucher.payment_id
        self.assertEqual((invoice.move_type, invoice.state, invoice.amount_total), ('in_invoice', 'posted', 100))
        self.assertEqual(invoice.amount_residual, 0)
        self.assertTrue(voucher.workflow_reviewed)
        self.assertEqual(voucher.workflow_status, 'reviewed')
        self.assertEqual(voucher.abroj_budget_line_id, self.budget)
        self.assertEqual(self.actual(), 100)
        data = self.project._abroj_data()
        self.assertEqual((data['recognized_revenue'], data['recognized_profit']), (0, -100))
        self.assertEqual(self.budget.actual, 100)
        self.assertEqual(self.budget.manual_actual, 0)
        count = self.env['account.move'].search_count([])
        wizard.action_apply()
        self.assertEqual((voucher.recognition_move_id, voucher.payment_id), (invoice, payment))
        self.assertEqual(self.env['account.move'].search_count([]), count)
        self.assertEqual(self.actual(), 100)

    def test_direct_income_is_revenue_not_project_expense(self):
        voucher = self.voucher(kind='receipt', purpose='direct')
        self.review(voucher).action_apply()
        invoice = voucher.recognition_move_id
        self.assertEqual((invoice.move_type, invoice.amount_total, invoice.amount_residual), ('out_invoice', 100, 0))
        self.assertEqual(sum(invoice.line_ids.filtered(lambda l: l.account_id == self.accounts['income']).mapped('credit')), 100)
        self.assertEqual(self.actual(), 0)
        data = self.project._abroj_data()
        self.assertEqual((data['recognized_revenue'], data['recognized_profit']), (100, 100))

    def test_advances_create_no_recognition_for_both_directions(self):
        for kind in ('payment', 'receipt'):
            voucher = self.voucher(kind=kind, purpose='advance')
            self.review(voucher).action_apply()
            self.assertTrue(voucher.payment_id)
            self.assertFalse(voucher.recognition_move_id)
            self.assertEqual(self.actual(), 0)

    def test_supplier_advance_later_settles_existing_bill_with_same_payment(self):
        voucher = self.voucher(purpose='advance')
        self.review(voucher).action_apply()
        payment = voucher.payment_id
        self.assertEqual(voucher.action_open_voucher_review()['res_model'], 'abroj.project.voucher.review')
        invoice = self.bill()
        before = self.env['account.payment'].search_count([])
        self.review(voucher, purpose='settlement', invoice_id=invoice.id).action_apply()
        self.assertEqual(voucher.payment_id, payment)
        self.assertEqual(voucher.recognition_move_id, invoice)
        self.assertEqual(invoice.amount_residual, 0)
        self.assertEqual(self.env['account.payment'].search_count([]), before)
        self.assertEqual(self.actual(), 100)

    def test_partial_and_full_settlements_do_not_duplicate_expense(self):
        invoice = self.bill(150)
        first = self.voucher(purpose='settlement', amount=100)
        self.review(first, invoice_id=invoice.id).action_apply()
        self.assertEqual(invoice.amount_residual, 50)
        second = self.voucher(purpose='settlement', amount=50)
        self.review(second, invoice_id=invoice.id).action_apply()
        self.assertEqual(invoice.amount_residual, 0)
        self.assertEqual(first.recognition_move_id, second.recognition_move_id)
        self.assertNotEqual(first.payment_id, second.payment_id)
        self.assertEqual(self.actual(), 150)
        self.assertEqual(self.project.total_paid, 150)

    def test_existing_posted_payment_is_reconciled_without_financial_rewrite(self):
        voucher = self.voucher(purpose='settlement')
        payment = self.legacy_payment(voucher)
        original = self.signature(payment)
        invoice = self.bill()
        count = self.env['account.move'].search_count([])
        wizard = self.review(voucher, invoice_id=invoice.id)
        wizard.action_apply()
        wizard.action_apply()
        self.assertEqual(self.signature(payment), original)
        self.assertEqual(self.env['account.move'].search_count([]), count)
        self.assertEqual(voucher.payment_id, payment)
        self.assertEqual(invoice.amount_residual, 0)
        self.assertEqual(self.actual(), 100)

    def test_legacy_direct_expense_adds_only_missing_recognition(self):
        voucher = self.voucher(purpose='direct')
        payment = self.legacy_payment(voucher)
        original = self.signature(payment)
        payments = self.env['account.payment'].search_count([])
        self.assertEqual(self.actual(), 0)
        self.review(voucher).action_apply()
        self.assertEqual(self.signature(payment), original)
        self.assertEqual(self.env['account.payment'].search_count([]), payments)
        self.assertEqual(voucher.recognition_move_id.amount_residual, 0)
        self.assertEqual(self.actual(), 100)

    def test_supplier_refund_uses_payable_and_existing_credit_note(self):
        refund = self.bill(move_type='in_refund')
        voucher = self.voucher(kind='receipt', purpose='supplier_refund')
        self.review(voucher, invoice_id=refund.id).action_apply()
        self.assertEqual((voucher.payment_id.partner_type, voucher.payment_id.payment_type), ('supplier', 'inbound'))
        self.assertEqual(voucher.payment_id.destination_account_id, self.accounts['liability_payable'])
        self.assertEqual(voucher.recognition_move_id, refund)
        self.assertEqual(refund.amount_residual, 0)
        self.assertEqual(self.actual(), -100)

    def test_settlement_rejects_overpayment_and_unposted_invoice(self):
        invoice = self.bill(90)
        voucher = self.voucher(purpose='settlement', amount=100)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.review(voucher, invoice_id=invoice.id).action_apply()
        draft = self.bill(posted=False)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.review(voucher, invoice_id=draft.id).action_apply()
        self.assertFalse(voucher.payment_id)

    def test_settlement_rejects_wrong_partner_project_and_invoice_direction(self):
        other = self.env['res.partner'].create({'name': 'Unrelated voucher supplier'})
        other.property_account_payable_id = self.accounts['liability_payable']
        other.property_account_receivable_id = self.accounts['asset_receivable']
        other_project = self.env['project.project'].create({'name': 'Unrelated voucher project'})
        invoices = (self.bill(partner=other), self.bill(project=other_project), self.bill(move_type='out_invoice'))
        voucher = self.voucher(purpose='settlement')
        for invoice in invoices:
            with self.assertRaises(UserError), self.cr.savepoint():
                self.review(voucher, invoice_id=invoice.id).action_apply()
        self.assertFalse(voucher.payment_id)

    def test_review_rejects_foreign_company_journal(self):
        company = self.env['res.company'].create({'name': 'Foreign voucher company'})
        journal = self.env['account.journal'].with_company(company).create({
            'name': 'Foreign voucher journal', 'code': 'VFJ', 'type': 'cash', 'company_id': company.id,
        })
        voucher = self.voucher(purpose='direct')
        with self.assertRaises(UserError), self.cr.savepoint():
            self.review(voucher, journal_id=journal.id).action_apply()

    def test_partnerless_historical_payment_requires_manual_resolution(self):
        party = self.env['abroj.contracting.party'].create({'name': 'Independent historical supplier', 'party_type': 'supplier'})
        voucher = self.voucher(purpose='settlement', partner_id=False, party_id=party.id)
        payment = self.legacy_payment(voucher, partner=False)
        original = self.signature(payment)
        invoice = self.bill()
        with self.assertRaises(UserError), self.cr.savepoint():
            self.review(voucher, invoice_id=invoice.id).action_apply()
        self.assertEqual(self.signature(payment), original)
        self.assertFalse(voucher.workflow_reviewed)
        self.assertEqual(invoice.amount_residual, 100)

    def test_nonaccountants_and_extraction_agents_cannot_review(self):
        voucher = self.voucher(purpose='direct')
        for user in (self.reader, self.agent):
            with self.assertRaises(AccessError):
                voucher.with_user(user).action_open_voucher_review()
            wizard = self.review(voucher)
            with self.assertRaises(AccessError):
                wizard.with_user(user).action_apply()
        self.assertFalse(voucher.workflow_reviewed)
        self.assertFalse(voucher.payment_id)

    def test_workflow_links_cannot_be_forged_by_rpc_or_context(self):
        voucher = self.voucher()
        invoice = self.bill()
        for values in ({'workflow_reviewed': True}, {'recognition_move_id': invoice.id},
                       {'abroj_budget_line_id': self.budget.id}):
            with self.assertRaises(AccessError), self.cr.savepoint():
                voucher.write(values)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.voucher(issued=False, workflow_reviewed=True)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['abroj.contracting.voucher'].with_context(default_workflow_reviewed=True).create({
                'project_id': self.project.id, 'partner_id': self.partner.id,
                'kind': 'payment', 'payment_purpose': 'advance', 'amount': 100,
                'vendor_contract_reference': 'VFLOW/FORGE', 'vendor_contract_value': 1000,
            })

    def test_reconciliation_failure_rolls_back_recognition_and_payment(self):
        voucher = self.voucher(purpose='direct')
        wizard = self.review(voucher)
        moves, payments = self.env['account.move'].search_count([]), self.env['account.payment'].search_count([])
        with patch.object(type(self.env['account.move.line']), 'reconcile', side_effect=UserError('Reconcile refused')):
            with self.assertRaises(UserError), self.cr.savepoint():
                wizard.action_apply()
        voucher.invalidate_recordset()
        self.assertFalse(voucher.payment_id)
        self.assertFalse(voucher.recognition_move_id)
        self.assertFalse(voucher.workflow_reviewed)
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertEqual(self.env['account.payment'].search_count([]), payments)

    def test_direct_expense_reuses_existing_confirmed_cost_document(self):
        baseline_commitment = self.project.total_costs
        cost = self.env['abroj.contracting.cost'].create({
            'project_id': self.project.id, 'name': 'Already accounted source cost',
            'partner_id': self.partner.id, 'amount': 100, 'date': self.today,
        })
        cost.action_confirm()
        cost_count = self.env['abroj.contracting.cost'].search_count([('project_id', '=', self.project.id)])
        moves = self.env['account.move'].search_count([])
        voucher = self.voucher(purpose='direct')
        wizard = self.review(voucher, expense_id=cost.id)
        wizard.action_apply()
        invoice = cost.account_move_id
        self.assertEqual(voucher.recognition_move_id, invoice)
        self.assertEqual(self.env['account.move'].search_count([]), moves + 2)
        self.assertEqual(self.project.total_costs, baseline_commitment + 100)
        self.assertEqual(self.env['abroj.contracting.cost'].search_count([('project_id', '=', self.project.id)]), cost_count)
        self.assertEqual(self.actual(), 100)
        self.assertEqual(self.budget.actual, 100)
        wizard.action_apply()
        self.assertEqual(self.env['account.move'].search_count([]), moves + 2)
        self.assertEqual(self.env['abroj.contracting.cost'].search_count([('project_id', '=', self.project.id)]), cost_count)

    def test_review_defaults_journal_and_evidence(self):
        self.cash.sequence = -10000
        voucher = self.voucher(purpose='advance')
        wizard_model = self.env['abroj.project.voucher.review'].with_context(default_voucher_id=voucher.id)
        values = wizard_model.default_get(['voucher_id', 'journal_id', 'evidence_note'])
        self.assertEqual(values['journal_id'], self.cash.id)
        self.assertIn(voucher.name, values['evidence_note'])
        values = wizard_model.with_context(default_evidence_note='Reviewed evidence').default_get(
            ['voucher_id', 'journal_id', 'evidence_note'])
        self.assertEqual(values['evidence_note'], 'Reviewed evidence')

    def test_legacy_accounting_entrypoints_cannot_bypass_purpose_review(self):
        voucher = self.voucher(purpose='direct')
        action = voucher.action_accounting_approve()
        self.assertEqual(action['res_model'], 'abroj.project.voucher.review')
        self.assertEqual(action['context']['default_voucher_id'], voucher.id)
        old = self.env['abroj.contracting.accounting.issue'].create({
            'voucher_id': voucher.id, 'partner_id': self.partner.id,
            'journal_id': self.cash.id, 'date': self.today,
        })
        try:
            action = old.action_issue()
        except UserError:
            pass
        else:
            self.assertEqual(action['res_model'], 'abroj.project.voucher.review')
        self.assertFalse(voucher.payment_id)

    def test_original_payment_is_frozen_but_native_reversal_remains_available(self):
        voucher = self.voucher(purpose='direct')
        self.review(voucher).action_apply()
        payment, move = voucher.payment_id, voucher.payment_id.move_id
        original = self.signature(payment)
        line = move.line_ids[:1]
        for operation in (
            lambda: payment.write({'amount': payment.amount + 1}),
            lambda: line.write({'debit': line.debit + 1}),
            move.button_draft, move.button_cancel, move.unlink, payment.unlink,
        ):
            with self.assertRaises(UserError), self.cr.savepoint():
                operation()
        reversal = move._reverse_moves([{'date': self.today, 'ref': 'Voucher payment correction'}], cancel=False)
        reversal.action_post()
        self.assertFalse(reversal.abroj_voucher_id)
        self.assertEqual(voucher.payment_id, payment)
        self.assertEqual(self.signature(payment), original)
        self.assertEqual(self.actual(), 100)
        credit = voucher.recognition_move_id._reverse_moves([{
            'date': self.today, 'invoice_date': self.today, 'ref': 'Voucher recognition credit',
        }], cancel=False)
        credit.action_post()
        self.assertFalse(credit.abroj_recognition_voucher_id)
        self.assertEqual(self.actual(), 0)

    def test_detailed_budget_approval_requires_project_manager(self):
        self.budget.budget = 170780
        viewer = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Budget nonapprover', 'login': 'voucher_budget_nonapprover',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('project.group_project_user').id])],
        })
        with self.assertRaises(AccessError):
            self.project.with_user(viewer).action_approve_detailed_budget()
        self.assertEqual(self.project.abroj_budget, 1000)
        self.project.action_approve_detailed_budget()
        self.assertEqual(self.project.abroj_budget, 170780)
        self.assertEqual(self.project._abroj_data()['expected_profit'], -160780)

    def test_project_user_can_create_and_issue_unreviewed_advance(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Voucher operational user', 'login': 'voucher_operational_user',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('project.group_project_user').id])],
        })
        self.project.message_subscribe(partner_ids=user.partner_id.ids)
        voucher = self.env['abroj.contracting.voucher'].with_user(user).create({
            'project_id': self.project.id, 'partner_id': self.partner.id, 'kind': 'payment',
            'payment_purpose': 'advance', 'amount': 100, 'method': 'cash',
            'vendor_contract_reference': 'VFLOW/USER', 'vendor_contract_value': 1000,
        })
        self.assertEqual(voucher.workflow_status, 'pending')
        voucher.action_issue()
        self.assertEqual(voucher.state, 'issued')
        self.assertEqual(voucher.workflow_status, 'pending')
        self.assertFalse(voucher.payment_id)

    def test_accountant_cannot_review_their_own_new_payment(self):
        accountant = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Self-issuing accountant', 'login': 'voucher_self_issuer',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('project.group_project_manager').id,
                                       self.env.ref('account.group_account_invoice').id])],
        })
        voucher = self.voucher(issued=False)
        voucher.with_user(accountant).action_issue()
        wizard = self.env['abroj.project.voucher.review'].with_user(accountant).create({
            'voucher_id': voucher.id, 'purpose': 'advance', 'partner_id': self.partner.id,
            'journal_id': self.cash.id, 'name': 'Issuer advance',
            'evidence_note': 'Self-approval must be rejected',
        })
        with self.assertRaises(AccessError), self.cr.savepoint():
            wizard.action_apply()
        self.assertFalse(voucher.payment_id)
        self.assertFalse(voucher.workflow_reviewed)

    def test_advance_rejects_hidden_recognition_fields(self):
        voucher = self.voucher(purpose='advance')
        invoice = self.bill()
        cost = self.env['abroj.contracting.cost'].create({
            'project_id': self.project.id, 'partner_id': self.partner.id,
            'name': 'Advance unrelated cost', 'amount': 100,
        })
        cost.action_confirm()
        moves, payments = self.env['account.move'].search_count([]), self.env['account.payment'].search_count([])
        for values in ({'invoice_id': invoice.id}, {'expense_id': cost.id},
                       {'budget_line_id': self.budget.id}, {'tax_ids': [Command.set(self.tax.ids)]}):
            with self.assertRaises(UserError), self.cr.savepoint():
                self.review(voucher, **values).action_apply()
        self.assertFalse(voucher.payment_id)
        self.assertFalse(voucher.recognition_move_id)
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertEqual(self.env['account.payment'].search_count([]), payments)

    def test_direct_vat_separates_gross_cash_and_net_expense(self):
        voucher = self.voucher(purpose='direct', amount=115)
        self.review(voucher, tax_ids=[Command.set(self.tax.ids)]).action_apply()
        invoice = voucher.recognition_move_id
        self.assertEqual((invoice.amount_untaxed, invoice.amount_tax, invoice.amount_total), (100, 15, 115))
        self.assertEqual(voucher.payment_id.amount, 115)
        self.assertEqual(invoice.amount_residual, 0)
        self.assertEqual(self.actual(), 100)
        self.assertEqual(self.budget.actual, 100)

    def test_settlement_rejects_foreign_currency_invoice(self):
        currency = self.env['res.currency'].create({'name': 'VFT', 'symbol': 'VFT', 'rounding': 0.01})
        self.env['res.currency.rate'].create({
            'currency_id': currency.id, 'company_id': self.company.id, 'name': self.today, 'rate': 2,
        })
        invoice = self.bill(currency=currency)
        voucher = self.voucher(purpose='settlement')
        with self.assertRaises(UserError), self.cr.savepoint():
            self.review(voucher, invoice_id=invoice.id).action_apply()
        self.assertFalse(voucher.payment_id)

    def test_period_lock_rolls_back_recognition_and_payment(self):
        voucher = self.voucher(purpose='direct')
        wizard = self.review(voucher)
        moves, payments = self.env['account.move'].search_count([]), self.env['account.payment'].search_count([])
        self.company.write({'fiscalyear_lock_date': self.today})
        try:
            with self.assertRaises(UserError), self.cr.savepoint():
                wizard.action_apply()
        finally:
            self.company.write({'fiscalyear_lock_date': False})
        self.assertFalse(voucher.payment_id)
        self.assertFalse(voucher.recognition_move_id)
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertEqual(self.env['account.payment'].search_count([]), payments)

    def test_independent_supplier_refund_does_not_reduce_customer_remaining(self):
        refund = self.bill(move_type='in_refund')
        voucher = self.voucher(kind='receipt', purpose='supplier_refund', subcontractor_id=False)
        self.review(voucher, invoice_id=refund.id).action_apply()
        self.assertEqual(voucher.payment_id.partner_type, 'supplier')
        self.assertEqual(self.project.total_received, 100)
        self.assertEqual(self.project.abroj_customer_received, 0)
        self.assertEqual(self.project.remaining, 10000)
        self.assertEqual(self.project._abroj_data()['remaining'], 10000)

    def test_unclassified_invoice_blocks_payment_and_split_categories_settle(self):
        invoice = self.bill(budget=False)
        voucher = self.voucher(purpose='settlement')
        payments = self.env['account.payment'].search_count([])
        original = [(line.id, line.abroj_budget_line_id.id, dict(line.analytic_distribution or {}))
                    for line in invoice.invoice_line_ids]
        with self.assertRaises(UserError), self.cr.savepoint():
            self.review(voucher, invoice_id=invoice.id).action_apply()
        self.assertFalse(voucher.payment_id)
        self.assertEqual(self.env['account.payment'].search_count([]), payments)
        self.assertEqual([(line.id, line.abroj_budget_line_id.id, dict(line.analytic_distribution or {}))
                          for line in invoice.invoice_line_ids], original)
        self.assertFalse(invoice.invoice_line_ids.mapped('abroj_budget_line_id'))
        self.assertEqual(invoice.amount_residual, 100)
        # Correct the first synthetic fact natively; do not rewrite its posted
        # accounting or analytic classification to make the review pass.
        credit = invoice._reverse_moves([{
            'date': self.today, 'invoice_date': self.today, 'ref': 'Unclassified source correction',
        }], cancel=False)
        credit.action_post()
        self.assertEqual(self.actual(), 0)
        second_budget = self.env['abroj.project.budget.line'].create({
            'project_id': self.project.id, 'name': 'Second valid split category', 'budget': 500,
        })
        split = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.partner.id,
            'journal_id': self.purchase.id, 'invoice_date': self.today, 'date': self.today,
            'abroj_project_id': self.project.id, 'ref': 'VFLOW/SPLIT',
            'invoice_line_ids': [Command.create({
                'name': 'Classified half', 'quantity': 1, 'price_unit': 50,
                'account_id': self.accounts['expense'].id, 'tax_ids': [Command.clear()],
                'analytic_distribution': {str(self.project.account_id.id): 100},
                'abroj_budget_line_id': category.id,
            }) for category in (self.budget, second_budget)],
        })
        split.action_post()
        self.review(voucher, invoice_id=split.id).action_apply()
        self.assertEqual(split.amount_residual, 0)
        self.assertEqual(voucher.recognition_move_id, split)
        self.assertEqual(voucher.payment_id.amount, 100)
        self.assertEqual(self.env['account.payment'].search_count([]), payments + 1)
        self.assertEqual((self.budget.actual, second_budget.actual), (50, 50))
        self.assertEqual(self.actual(), self.budget.actual + second_budget.actual)
        self.assertEqual(self.actual(), 100)

    def _mandatory_spend_fixture(self):
        """Activate the real independent addon's guard in this test only."""
        plan = self.env.ref('baseer_native_spend.spend_plan')
        self.assertFalse(plan.parent_id)
        self.assertEqual(plan.default_applicability, 'unavailable')
        child = self.env['account.analytic.plan'].create({
            'name': 'Voucher integration spend child', 'parent_id': plan.id,
        })
        account = self.env['account.analytic.account'].create({
            'name': 'Voucher integration spend classification', 'plan_id': child.id,
            'company_id': False,
        })
        applicability = self.env['account.analytic.applicability'].search([
            ('analytic_plan_id', '=', plan.id), ('company_id', '=', self.company.id),
            ('business_domain', '=', 'bill'), ('account_prefix', '=', False),
            ('product_categ_id', '=', False),
        ])
        if applicability:
            applicability.write({'applicability': 'mandatory'})
        else:
            self.env['account.analytic.applicability'].create({
                'analytic_plan_id': plan.id, 'company_id': self.company.id,
                'business_domain': 'bill', 'applicability': 'mandatory',
            })
        return plan, child, account

    def test_mandatory_spend_missing_rolls_back_invoice_and_payment(self):
        self._mandatory_spend_fixture()
        voucher = self.voucher(purpose='direct')
        moves, payments = self.env['account.move'].search_count([]), self.env['account.payment'].search_count([])
        with self.assertRaises(UserError), self.cr.savepoint():
            self.review(voucher, analytic_distribution={str(self.project.account_id.id): 100}).action_apply()
        voucher.invalidate_recordset()
        self.assertFalse(voucher.payment_id)
        self.assertFalse(voucher.recognition_move_id)
        self.assertFalse(voucher.workflow_reviewed)
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertEqual(self.env['account.payment'].search_count([]), payments)
        self.assertEqual((self.actual(), self.budget.actual), (0, 0))

    def test_combined_project_and_mandatory_spend_count_actual_once(self):
        plan, _child, spend = self._mandatory_spend_fixture()
        distribution = {'%s,%s' % (self.project.account_id.id, spend.id): 100}
        voucher = self.voucher(purpose='direct')
        self.review(voucher, analytic_distribution=distribution).action_apply()
        invoice = voucher.recognition_move_id
        self.assertEqual(invoice.invoice_line_ids.analytic_distribution, distribution)
        self.assertEqual((invoice.state, invoice.amount_total, invoice.amount_residual), ('posted', 100, 0))
        lines = self.env['account.analytic.line'].search([
            ('move_line_id', 'in', invoice.invoice_line_ids.ids),
            ('account_id', '=', self.project.account_id.id),
        ])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.amount, -100)
        self.assertNotEqual(plan._column_name(), 'account_id')
        self.assertEqual(lines[plan._column_name()], spend)
        self.assertEqual(lines.abroj_budget_line_id, self.budget)
        self.assertEqual((self.actual(), self.budget.actual), (100, 100))
        self.assertEqual(self.budget.manual_actual, 0)

    def test_review_rejects_invalid_or_foreign_native_distribution(self):
        _plan, child, spend = self._mandatory_spend_fixture()
        company = self.env['res.company'].create({'name': 'Foreign distribution company'})
        foreign = self.env['account.analytic.account'].with_company(company).create({
            'name': 'Foreign spend account', 'plan_id': child.id, 'company_id': company.id,
        })
        inactive = self.env['account.analytic.account'].create({
            'name': 'Inactive spend account', 'plan_id': child.id, 'company_id': False, 'active': False,
        })
        other_project = self.env['project.project'].create({'name': 'Wrong distribution project'})
        project = self.project.account_id.id
        bad = [
            {'%s,%s' % (project, foreign.id): 100},
            {'%s,%s' % (project, inactive.id): 100},
            {'%s,%s' % (other_project.account_id.id, spend.id): 100},
            {'not_an_account_id': 100},
            {'%s,%s,%s' % (project, project, spend.id): 100},
            {'%s,%s' % (project, spend.id): 100.001},
            {'%s,%s' % (project, spend.id): 'NaN'},
            [],
            0,
        ]
        voucher = self.voucher(purpose='direct')
        valid = {'%s,%s' % (project, spend.id): 100}
        wizard = self.review(voucher, analytic_distribution=valid)
        moves, payments = self.env['account.move'].search_count([]), self.env['account.payment'].search_count([])
        for distribution in bad:
            with self.subTest(distribution=distribution), self.assertRaises(UserError), self.cr.savepoint():
                self.review(voucher, analytic_distribution=distribution).action_apply()
            with self.subTest(write_distribution=distribution), self.assertRaises(UserError), self.cr.savepoint():
                wizard.write({'analytic_distribution': distribution})
            wizard.invalidate_recordset(['analytic_distribution'])
            self.assertEqual(wizard.analytic_distribution, valid)
        self.assertFalse(voucher.payment_id)
        self.assertFalse(voucher.recognition_move_id)
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertEqual(self.env['account.payment'].search_count([]), payments)

    def test_standalone_cost_wizard_supports_mandatory_spend_and_budget(self):
        plan, _child, spend = self._mandatory_spend_fixture()
        baseline = self.project.total_costs
        cost = self.env['abroj.contracting.cost'].create({
            'project_id': self.project.id, 'partner_id': self.partner.id,
            'name': 'Standalone classified expense', 'amount': 100, 'date': self.today,
        })
        cost.action_confirm()
        distribution = {'%s,%s' % (self.project.account_id.id, spend.id): 100}
        payments = self.env['account.payment'].search_count([])
        wizard = self.env['abroj.contracting.accounting.issue'].create({
            'cost_id': cost.id, 'mode': 'create', 'partner_id': self.partner.id,
            'journal_id': self.purchase.id, 'expense_account_id': self.accounts['expense'].id,
            'budget_line_id': self.budget.id, 'analytic_distribution': distribution,
            'invoice_date': self.today, 'date': self.today,
        })
        action = wizard.action_issue()
        invoice = cost.account_move_id
        self.assertEqual(action['res_id'], invoice.id)
        self.assertEqual((invoice.state, invoice.amount_total), ('posted', 100))
        self.assertEqual(invoice.invoice_line_ids.analytic_distribution, distribution)
        self.assertEqual(invoice.invoice_line_ids.abroj_budget_line_id, self.budget)
        lines = self.env['account.analytic.line'].search([
            ('move_line_id', 'in', invoice.invoice_line_ids.ids),
            ('account_id', '=', self.project.account_id.id),
        ])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[plan._column_name()], spend)
        self.assertEqual((self.actual(), self.budget.actual), (100, 100))
        self.assertEqual(self.project.total_costs, baseline + 100)
        self.assertEqual(self.env['account.payment'].search_count([]), payments)
