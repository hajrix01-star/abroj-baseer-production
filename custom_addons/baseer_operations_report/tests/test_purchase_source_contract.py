"""Characterize purchase-payment evidence; this is not a report calculator.

The gross-operations policy recognizes a vendor bill only when funds leave a
real company cash/bank account.  In Odoo an invoice/payment reconciliation can
precede the bank movement when an outstanding account is configured.
"""

from decimal import Decimal

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOperationsPurchaseSourceContract(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.accounts = self.env['account.account'].with_company(self.company)

        def account(code, kind, reconcile=False):
            return self.accounts.create({
                'code': code, 'name': 'Gross payment source ' + code,
                'account_type': kind, 'reconcile': reconcile,
                'company_ids': [Command.set(self.company.ids)],
            })

        self.payable = account('958121', 'liability_payable', True)
        self.expense = account('958122', 'expense')
        self.vat_account = account('958123', 'asset_current')
        self.outstanding = account('958124', 'asset_current', True)
        self.cash = account('958125', 'asset_cash')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Gross payment source supplier',
            'property_account_payable_id': self.payable.id,
        })
        self.purchase = self.env['account.journal'].with_company(self.company).create({
            'name': 'Gross payment source purchases', 'code': 'GPS',
            'type': 'purchase', 'company_id': self.company.id,
        })
        self.general = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        self.bank = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.assertTrue(self.general and self.bank and self.bank.default_account_id)
        self.assertEqual(self.bank.default_account_id.account_type, 'asset_cash')
        self.method = self.bank.outbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id.code == 'manual',
        )[:1]
        self.assertTrue(self.method)
        self.method.payment_account_id = self.outstanding
        self.tax = self.env['account.tax'].with_company(self.company).create({
            'name': 'Gross payment source VAT', 'amount_type': 'percent',
            'amount': 15, 'type_tax_use': 'purchase',
            'company_id': self.company.id,
        })
        self.tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).write({'account_id': self.vat_account.id})

    def _bill(self):
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice', 'partner_id': self.partner.id,
            'journal_id': self.purchase.id, 'invoice_date': '2026-06-10',
            'invoice_line_ids': [Command.create({
                'name': 'Purchase 100 plus recorded VAT 15',
                'quantity': 1, 'price_unit': 100,
                'account_id': self.expense.id,
                'tax_ids': [Command.set(self.tax.ids)],
            })],
        })
        bill.action_post()
        self.assertEqual(Decimal(str(bill.amount_total)), Decimal('115.00'))
        return bill

    def _entry(self, day, debit_account, credit_account, amount):
        move = self.env['account.move'].with_company(self.company).create({
            'date': day, 'journal_id': self.general.id, 'move_type': 'entry',
            'line_ids': [
                Command.create({
                    'name': 'Gross payment source debit', 'partner_id': self.partner.id,
                    'account_id': debit_account.id, 'debit': amount,
                }),
                Command.create({
                    'name': 'Gross payment source credit', 'partner_id': self.partner.id,
                    'account_id': credit_account.id, 'credit': amount,
                }),
            ],
        })
        move._post(soft=False)
        return move

    def _bank_statement(self, day, counterpart, amount):
        statement_line = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': self.bank.id,
            'date': day,
            'payment_ref': 'Gross payment source bank debit',
            'partner_id': self.partner.id,
            'amount': -amount,
            'counterpart_account_id': counterpart.id,
        })
        self.assertEqual(statement_line.move_id.state, 'posted')
        self.assertEqual(Decimal(str(statement_line.amount)), -Decimal(str(amount)))
        return statement_line

    def _purchase_amount(self, start, end, report=None):
        report = report or self.env['baseer.operations.report']
        snapshot = report.get_source_snapshot({
            'company_id': self.company.id,
            'date_from': start, 'date_to': end, 'journal_ids': [],
        })
        self.assertFalse(snapshot['complete'])
        rows = snapshot['periods'][0]['rows']
        return Decimal(next(row['amount'].replace(',', '') for row in rows
                            if row['key'] == 'expense'))

    def test_bill_waits_for_real_outflow_and_partial_50_then_65(self):
        bill = self._bill()
        bill_payable = bill.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        self.assertEqual(len(bill_payable), 1)
        self.assertFalse(bill_payable.matched_debit_ids)
        self.assertEqual(Decimal(str(bill.amount_residual)), Decimal('115.00'))
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 0)

        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id,
            'payment_method_line_id': self.method.id,
            'amount': 50,
            'payment_date': '2026-06-12',
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })
        payment = wizard._create_payments()
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.payment_type, 'outbound')
        self.assertEqual(payment.partner_type, 'supplier')
        self.assertEqual(payment.outstanding_account_id, self.outstanding)
        self.assertEqual(payment.move_id.state, 'posted')
        payment_payable = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        outstanding_credit = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.outstanding,
        )
        self.assertEqual(len(payment_payable), 1)
        self.assertEqual(len(outstanding_credit), 1)
        self.assertEqual(Decimal(str(outstanding_credit.balance)), Decimal('-50.00'))
        self.assertFalse(payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        ))
        first_partial = self.env['account.partial.reconcile'].search([
            ('debit_move_id', '=', payment_payable.id),
            ('credit_move_id', '=', bill_payable.id),
        ])
        self.assertEqual(len(first_partial), 1)
        self.assertEqual(Decimal(str(first_partial.amount)), Decimal('50.00'))
        # Reconciliation is not proof of bank outflow: this payment still sits
        # in outstanding, and the bill has 65 due.
        self.assertEqual(Decimal(str(bill.amount_residual)), Decimal('65.00'))
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 0)

        bank_50 = self._bank_statement('2026-06-15', self.outstanding, 50)
        outstanding_debit = bank_50.move_id.line_ids.filtered(
            lambda line: line.account_id == self.outstanding,
        )
        (outstanding_credit + outstanding_debit).reconcile()
        bank_50_line = bank_50.move_id.line_ids.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        )
        self.assertEqual(Decimal(str(bank_50_line.balance)), Decimal('-50.00'))
        self.assertEqual(str(bank_50_line.date), '2026-06-15')
        self.assertEqual(first_partial.max_date, max(bill_payable.date, payment_payable.date))
        self.assertNotEqual(first_partial.max_date, bank_50_line.date)
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 50)

        bank_65 = self._bank_statement('2026-07-05', self.payable, 65)
        payable_65 = bank_65.move_id.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        (bill_payable + payable_65).reconcile()
        second_partial = self.env['account.partial.reconcile'].search([
            ('debit_move_id', '=', payable_65.id),
            ('credit_move_id', '=', bill_payable.id),
        ])
        self.assertEqual(len(second_partial), 1)
        self.assertEqual(Decimal(str(second_partial.amount)), Decimal('65.00'))
        self.assertEqual(Decimal(str(bill.amount_residual)), Decimal('0.00'))
        bank_65_line = bank_65.move_id.line_ids.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        )
        self.assertEqual(Decimal(str(bank_65_line.balance)), Decimal('-65.00'))
        self.assertEqual(str(bank_65_line.date), '2026-07-05')
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 50)
        self.assertEqual(self._purchase_amount('2026-07-01', '2026-07-31'), 65)
        # One bill, two unique real outflow lines; payment posting and both
        # reconciliations must not introduce a third recognized event.
        self.assertEqual(len(bank_50_line | bank_65_line), 2)
        self.assertEqual(
            -sum((Decimal(str(line.balance)) for line in bank_50_line | bank_65_line),
                 Decimal('0')),
            Decimal('115.00'),
        )

    def test_advance_and_internal_transfer_have_no_bill_allocation(self):
        self._bill()
        advance = self._entry(
            '2026-06-16', self.payable, self.bank.default_account_id, 30,
        )
        transfer = self._entry(
            '2026-06-17', self.cash, self.bank.default_account_id, 40,
        )
        advance_payable = advance.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        self.assertFalse(advance_payable.matched_credit_ids)
        self.assertFalse(advance_payable.matched_debit_ids)
        self.assertFalse(transfer.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        ))
        self.assertEqual(Decimal(str(advance.line_ids.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        ).balance)), Decimal('-30.00'))
        self.assertEqual(Decimal(str(transfer.line_ids.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        ).balance)), Decimal('-40.00'))
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 0)
        # Neither bank decrease is a classified purchase source: the first is
        # an unapplied vendor advance; the second only changes liquidity.

    def test_hidden_outflow_and_other_company_require_fail_closed_reader(self):
        bill = self._bill()
        outflow = self._entry(
            '2026-06-15', self.payable, self.bank.default_account_id, 50,
        )
        bill_payable = bill.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        payment_payable = outflow.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        (bill_payable + payment_payable).reconcile()
        partial = self.env['account.partial.reconcile'].search([
            ('debit_move_id', '=', payment_payable.id),
            ('credit_move_id', '=', bill_payable.id),
        ])
        self.assertEqual(len(partial), 1)
        reader = self.env['res.users'].create({
            'name': 'Gross payment source readonly',
            'login': 'gross_payment_source_readonly',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured_move = self.env['account.move'].with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(secured_move.search([('id', '=', outflow.id)]).ids,
                         outflow.ids)
        partial.with_user(reader).check_access('read')
        rule = self.env['ir.rule'].create({
            'name': 'Gross payment source hide bank outflow',
            'model_id': self.env['ir.model']._get('account.move').id,
            'domain_force': f"[('id', '!=', {outflow.id})]",
        })
        try:
            rule.flush_recordset()
            self.assertFalse(secured_move.search([('id', '=', outflow.id)]))
            self.env.cr.execute('SELECT id FROM account_move WHERE id=%s', [outflow.id])
            self.assertEqual(self.env.cr.fetchone()[0], outflow.id)
        finally:
            rule.unlink()

        other = self.env['res.company'].create({
            'name': 'Gross payment source other company',
        })
        other_accounts = self.env['account.account'].with_company(other)
        other_payable = other_accounts.create({
            'code': '958121', 'name': 'Other gross payment payable',
            'account_type': 'liability_payable', 'reconcile': True,
            'company_ids': [Command.set(other.ids)],
        })
        other_cash = other_accounts.create({
            'code': '958125', 'name': 'Other gross payment cash',
            'account_type': 'asset_cash',
            'company_ids': [Command.set(other.ids)],
        })
        other_journal = self.env['account.journal'].with_company(other).create({
            'name': 'Other gross payment general', 'code': 'GPO',
            'type': 'general', 'company_id': other.id,
        })
        other_move = self.env['account.move'].with_company(other).create({
            'date': '2026-06-15', 'journal_id': other_journal.id,
            'move_type': 'entry',
            'line_ids': [
                Command.create({'name': 'Other payable',
                                'account_id': other_payable.id, 'debit': 50}),
                Command.create({'name': 'Other cash',
                                'account_id': other_cash.id, 'credit': 50}),
            ],
        })
        other_move._post(soft=False)
        self.assertFalse(secured_move.search([('id', '=', other_move.id)]))
        self.assertNotEqual(other_move.company_id, self.company)
