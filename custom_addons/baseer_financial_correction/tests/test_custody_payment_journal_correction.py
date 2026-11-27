"""Custody-journal acceptance and PO-linked payment-journal corrections."""
from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCustodyPaymentJournalCorrection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.baseer_financial_correction.models.dispatcher import can_correct
        # Assigning Baseer groups through group_ids is rejected by the role
        # validator. Use the official role selector when the test user cannot
        # already correct financial operations.
        if not can_correct(cls.env):
            cls.env.user.write({'baseer_access_role': 'owner'})
        sar = cls.env['res.currency'].with_context(active_test=False).search([('name', '=', 'SAR')], limit=1)
        if not sar:
            sar = cls.env['res.currency'].create({'name': 'SAR', 'symbol': '﷼', 'active': True})
        sar.active = True
        if sar.decimal_places != 2:
            sar.decimal_places = 2
        cls.company = cls.env['res.company'].create({
            'name': 'Correction custody SAR company',
            'currency_id': sar.id,
        })
        cls.env.user.company_ids |= cls.company
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=cls.company.ids))
        cls.env.user.company_id = cls.company

        Account = cls.env['account.account']
        cls.payable = Account.create({
            'name': 'Correction test payable', 'code': 'CJT201',
            'account_type': 'liability_payable', 'reconcile': True,
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.expense = Account.create({
            'name': 'Correction test expense', 'code': 'CJT601',
            'account_type': 'expense',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.cash_account = Account.create({
            'name': 'Correction test cash', 'code': 'CJT105',
            'account_type': 'asset_cash',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.custody_account = Account.create({
            'name': 'Representative Petty Cash | عهدة مندوبي المشتريات', 'code': 'CJT108',
            'account_type': 'asset_current', 'reconcile': True,
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.other_current = Account.create({
            'name': 'Correction unflagged current asset', 'code': 'CJT109',
            'account_type': 'asset_current',
            'company_ids': [Command.set(cls.company.ids)],
        })

        cls.company.baseer_procurement_representative_petty_cash_account_id = cls.custody_account

        Journal = cls.env['account.journal']
        cls.purchase_journal = Journal.create({
            'name': 'Correction purchases', 'code': 'CJTP', 'type': 'purchase',
            'company_id': cls.company.id, 'default_account_id': cls.expense.id,
        })
        cls.cash_journal = Journal.create({
            'name': 'النقد ARZ', 'code': 'CJTC', 'type': 'cash',
            'company_id': cls.company.id, 'default_account_id': cls.cash_account.id,
        })
        cls._bind_outbound_method(cls.cash_journal)

        cls.representative = cls.env['res.partner'].create({
            'name': 'Osama custody representative', 'company_id': cls.company.id,
        })
        cls.representative.with_company(cls.company).write({'is_purchase_representative': True})

        cls.custody_journal = Journal.create({
            'name': 'عهدة أسامة', 'code': 'CJTO', 'type': 'cash',
            'company_id': cls.company.id, 'default_account_id': cls.custody_account.id,
            'baseer_custody_representative_id': cls.representative.id,
        })
        cls._bind_outbound_method(cls.custody_journal)

        cls.unflagged_journal = Journal.create({
            'name': 'Unflagged current-asset cash', 'code': 'CJTU', 'type': 'cash',
            'company_id': cls.company.id, 'default_account_id': cls.other_current.id,
        })
        cls._bind_outbound_method(cls.unflagged_journal)

        cls.vendor = cls.env['res.partner'].create({
            'name': 'Correction test vendor', 'supplier_rank': 1,
            'company_id': cls.company.id,
            'property_account_payable_id': cls.payable.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Correction test product', 'type': 'service',
            'purchase_ok': True, 'sale_ok': False,
            'list_price': 100, 'standard_price': 100,
            'categ_id': cls.env['product.category'].create({'name': 'Correction test category'}).id,
            'property_account_expense_id': cls.expense.id,
            'supplier_taxes_id': [Command.clear()],
        })

    @classmethod
    def _bind_outbound_method(cls, journal):
        methods = journal.outbound_payment_method_line_ids.filtered(lambda method: method.code == 'manual')
        methods.write({'payment_account_id': journal.default_account_id.id})

    def _outbound_method(self, journal):
        methods = journal.outbound_payment_method_line_ids.filtered(
            lambda method: method.code == 'manual' and method.payment_account_id == journal.default_account_id
        )
        self.assertTrue(methods, 'Expected a bound manual outbound method on %s' % journal.name)
        return methods[:1]

    def _post_bill(self, amount=120, purchase_order=False):
        today = fields.Date.context_today(self.env.user)
        if purchase_order:
            order = self.env['purchase.order'].create({
                'partner_id': self.vendor.id,
                'company_id': self.company.id,
                'currency_id': self.company.currency_id.id,
                'order_line': [Command.create({
                    'product_id': self.product.id,
                    'name': self.product.display_name,
                    'product_qty': 1,
                    'price_unit': amount,
                    'tax_ids': [Command.clear()],
                })],
            })
            order.button_confirm()
            order.action_create_invoice()
            bill = order.invoice_ids
            self.assertEqual(len(bill), 1)
            bill.invoice_date = today
            if not bill.journal_id or bill.journal_id.company_id != self.company:
                bill.journal_id = self.purchase_journal
            bill.invoice_line_ids.account_id = self.expense
        else:
            order = self.env['purchase.order']
            bill = self.env['account.move'].create({
                'company_id': self.company.id,
                'move_type': 'in_invoice',
                'partner_id': self.vendor.id,
                'journal_id': self.purchase_journal.id,
                'invoice_date': today,
                'invoice_line_ids': [Command.create({
                    'name': 'Independent vendor bill',
                    'account_id': self.expense.id,
                    'quantity': 1,
                    'price_unit': amount,
                    'tax_ids': [Command.clear()],
                })],
            })
        bill.action_post()
        return bill, order

    def _pay_bill(self, bill, journal, amount=None):
        amount = amount if amount is not None else bill.amount_total
        payment = self.env['account.payment'].create({
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': bill.partner_id.id,
            'amount': amount,
            'date': bill.invoice_date,
            'journal_id': journal.id,
            'payment_method_line_id': self._outbound_method(journal).id,
            'destination_account_id': self.payable.id,
        })
        payment.action_post()
        terms = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        counterpart = payment._seek_for_lines()[1]
        (terms | counterpart).reconcile()
        self.assertTrue(payment.is_reconciled)
        self.assertEqual(bill.payment_state, 'paid')
        return payment

    def _open_and_confirm_journal_change(self, source, journal):
        action = source.action_baseer_correct_operation()
        self.assertEqual(action.get('res_model'), 'baseer.financial.correction')
        wizard = self.env['baseer.financial.correction'].browse(action['res_id'])
        wizard.write({
            'reason': 'AGENT: مساعد البرمجة — move custody payment to cash journal',
            'correct_payment': True,
            'payment_journal_id': journal.id,
            'payment_method_line_id': self._outbound_method(journal).id,
        })
        wizard.action_confirm()
        return wizard

    def test_custody_journal_is_accepted_and_unflagged_current_asset_is_rejected(self):
        self.assertTrue(self.custody_journal._baseer_is_custody_liquidity_journal())
        self.assertTrue(self.custody_journal._baseer_is_correction_liquidity_journal())
        self.assertTrue(self.cash_journal._baseer_is_correction_liquidity_journal())
        self.assertFalse(self.unflagged_journal._baseer_is_custody_liquidity_journal())
        self.assertFalse(self.unflagged_journal._baseer_is_correction_liquidity_journal())

        Correction = self.env['baseer.financial.correction']
        Correction._validate_method(
            self._outbound_method(self.custody_journal), self.company, 'outbound',
        )
        Correction._validate_method(
            self._outbound_method(self.cash_journal), self.company, 'outbound',
        )
        with self.assertRaises(UserError):
            Correction._validate_method(
                self._outbound_method(self.unflagged_journal), self.company, 'outbound',
            )

    def test_po_linked_bill_allows_payment_journal_correction_and_restores_reconciliation(self):
        bill, order = self._post_bill(amount=119.99, purchase_order=True)
        payment = self._pay_bill(bill, self.custody_journal)
        bill_state = (bill.id, bill.state, bill.amount_total, bill.partner_id.id, bill.invoice_date)
        po_lines = bill.invoice_line_ids.purchase_line_id
        self.assertTrue(po_lines)
        po_snapshot = (order.id, order.state, po_lines.ids, po_lines.mapped('price_unit'))

        wizard = self._open_and_confirm_journal_change(payment, self.cash_journal)

        bill.invalidate_recordset()
        payment.invalidate_recordset()
        order.invalidate_recordset()
        self.assertTrue(wizard.completed)
        self.assertEqual(payment.journal_id, self.cash_journal)
        self.assertEqual(payment.payment_method_line_id, self._outbound_method(self.cash_journal))
        self.assertEqual(payment.state, 'paid')
        self.assertTrue(payment.is_reconciled)
        self.assertAlmostEqual(payment.amount, 119.99, places=2)
        self.assertEqual((bill.id, bill.state, bill.amount_total, bill.partner_id.id, bill.invoice_date), bill_state)
        self.assertEqual(bill.payment_state, 'paid')
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(bill.invoice_line_ids.purchase_line_id.ids, po_snapshot[2])
        self.assertEqual((order.id, order.state, order.order_line.mapped('price_unit')), (po_snapshot[0], po_snapshot[1], po_snapshot[3]))
        counterpart = payment._seek_for_lines()[1]
        partials = counterpart.matched_debit_ids | counterpart.matched_credit_ids
        reconciled_moves = (partials.debit_move_id.move_id | partials.credit_move_id.move_id) - payment.move_id
        self.assertEqual(reconciled_moves, bill)

    def test_po_linked_bill_action_opens_payment_journal_wizard(self):
        bill, _order = self._post_bill(amount=240.01, purchase_order=True)
        self._pay_bill(bill, self.custody_journal)
        action = bill.action_baseer_correct_operation()
        self.assertEqual(action.get('res_model'), 'baseer.financial.correction')
        wizard = self.env['baseer.financial.correction'].browse(action['res_id'])
        self.assertTrue(wizard.purchase_source_locked)
        self.assertTrue(wizard.correct_payment)
        self.assertEqual(wizard.payment_id.journal_id, self.custody_journal)

    def test_po_linked_bill_change_is_still_routed_to_the_purchase_order(self):
        bill, order = self._post_bill(amount=100, purchase_order=True)
        payment = self._pay_bill(bill, self.custody_journal)
        action = payment.action_baseer_correct_operation()
        wizard = self.env['baseer.financial.correction'].browse(action['res_id'])
        wizard.write({
            'reason': 'AGENT: مساعد البرمجة — attempt to change the bill',
            'correct_payment': True,
            'payment_journal_id': self.cash_journal.id,
            'payment_method_line_id': self._outbound_method(self.cash_journal).id,
        })
        wizard.line_ids[:1].write({'price_unit_input': '150.00'})
        with self.assertRaises(UserError) as error:
            wizard.action_confirm()
        self.assertIn('another workflow', str(error.exception))
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.amount_total, 100)
        self.assertEqual(payment.journal_id, self.custody_journal)
        self.assertEqual(order.order_line.price_unit, 100)

    def test_po_linked_cancel_remains_blocked(self):
        bill, _order = self._post_bill(amount=80, purchase_order=True)
        payment = self._pay_bill(bill, self.custody_journal)
        with self.assertRaises(UserError):
            bill.action_baseer_cancel_operation()
        with self.assertRaises(UserError):
            payment.action_baseer_cancel_operation()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(payment.state, 'paid')

    def test_non_po_custody_payment_can_change_journal(self):
        bill, order = self._post_bill(amount=79.99, purchase_order=False)
        self.assertFalse(order)
        self.assertFalse(bill.invoice_line_ids.purchase_line_id)
        payment = self._pay_bill(bill, self.custody_journal)
        self._open_and_confirm_journal_change(payment, self.cash_journal)
        self.assertEqual(payment.journal_id, self.cash_journal)
        self.assertEqual(payment.state, 'paid')
        self.assertTrue(payment.is_reconciled)
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.payment_state, 'paid')
        self.assertEqual(bill.amount_residual, 0)
        self.assertAlmostEqual(bill.amount_total, 79.99, places=2)
