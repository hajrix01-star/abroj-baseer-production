"""Characterize purchase-payment evidence; this is not a report calculator.

The gross-operations policy recognizes a vendor bill only when funds leave a
real company cash/bank account.  In Odoo an invoice/payment reconciliation can
precede the bank movement when an outstanding account is configured.
"""

from decimal import Decimal

from odoo import Command
from odoo.exceptions import AccessError
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

    def _purchase_amount(self, start, end, report=None, journal_ids=None):
        report = report if report is not None else self.env['baseer.operations.report']
        snapshot = report.get_source_snapshot({
            'company_id': self.company.id,
            'date_from': start, 'date_to': end,
            'journal_ids': journal_ids or [],
        })
        self.assertFalse(snapshot['complete'])
        rows = snapshot['periods'][0]['rows']
        return Decimal(next(row['amount'].replace(',', '') for row in rows
                            if row['key'] == 'expense'))

    def test_native_bank_entry_generates_recorded_purchase_vat(self):
        """Describe Odoo's source before admitting taxed direct outflow to report."""
        statement = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': self.bank.id,
            'date': '2026-06-22',
            'payment_ref': 'Actual taxed bank outflow',
            'partner_id': self.partner.id,
            'amount': -115,
            'line_ids': [
                Command.create({
                    'name': 'Actual bank decrease',
                    'partner_id': self.partner.id,
                    'account_id': self.bank.default_account_id.id,
                    'credit': 115,
                }),
                Command.create({
                    'name': 'Expense base with native purchase VAT',
                    'partner_id': self.partner.id,
                    'account_id': self.expense.id,
                    'debit': 100,
                    'tax_ids': [Command.set(self.tax.ids)],
                }),
            ],
        })
        move = statement.move_id
        lines = move.line_ids
        bank_lines = lines.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        )
        base_lines = lines.filtered(lambda line: line.account_id == self.expense)
        tax_lines = lines.filtered(lambda line: line.tax_line_id)
        self.assertEqual(statement.company_id, self.company)
        self.assertEqual(statement.currency_id, self.company.currency_id)
        self.assertEqual(str(statement.date), '2026-06-22')
        self.assertEqual(Decimal(str(statement.amount)), Decimal('-115.00'))
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.company_id, self.company)
        self.assertEqual(move.journal_id, self.bank)
        self.assertEqual(move.statement_line_id, statement)
        self.assertFalse(move.origin_payment_id)
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(bank_lines), 1)
        self.assertEqual(len(base_lines), 1)
        self.assertEqual(len(tax_lines), 1)
        self.assertEqual(Decimal(str(bank_lines.balance)), Decimal('-115.00'))
        self.assertEqual(Decimal(str(base_lines.balance)), Decimal('100.00'))
        self.assertEqual(base_lines.tax_ids, self.tax)
        self.assertEqual(Decimal(str(tax_lines.balance)), Decimal('15.00'))
        self.assertEqual(tax_lines.account_id, self.vat_account)
        self.assertEqual(tax_lines.tax_line_id, self.tax)
        self.assertIn(
            tax_lines.tax_repartition_line_id,
            self.tax.invoice_repartition_line_ids,
        )
        self.assertEqual(sum(Decimal(str(line.balance)) for line in lines), 0)
        self.assertFalse(lines.filtered(lambda line:
                                        line.matched_credit_ids or line.matched_debit_ids))
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 115)
        self.assertEqual(self._purchase_amount('2026-07-01', '2026-07-31'), 0)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=self.bank.ids,
        ), 115)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=self.general.ids,
        ), 0)
        snapshot = self.env['baseer.operations.report'].get_source_snapshot({
            'company_id': self.company.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30',
            'journal_ids': [],
        })
        self.assertEqual(snapshot['periods'][0]['excluded']['direct_aml_unproven'], 0)
        self.assertEqual(snapshot['periods'][0]['accounts']['expense'], [{
            'account_id': self.expense.id,
            'account_code': self.expense.code,
            'account_name': self.expense.name,
            'amount': '115.00',
            'negative': False,
            'source_count': 1,
        }])

        reader = self.env['res.users'].create({
            'name': 'Gross taxed bank outflow reader',
            'login': 'gross_taxed_bank_outflow_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured = self.env['baseer.operations.report'].with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', report=secured,
        ), 115)
        for model, hidden in (
                ('account.bank.statement.line', statement),
                ('account.move.line', tax_lines),
                ('account.tax', self.tax),
                ('account.tax.repartition.line', tax_lines.tax_repartition_line_id),
                ('account.account', self.vat_account)):
            rule = self.env['ir.rule'].create({
                'name': 'Gross taxed bank hide ' + model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {hidden.id})]",
            })
            try:
                rule.flush_recordset()
                with self.assertRaises(AccessError):
                    self._purchase_amount(
                        '2026-06-01', '2026-06-30', report=secured,
                    )
            finally:
                rule.unlink()

    def test_direct_taxed_bank_rejects_unlinked_vat_and_fourth_line(self):
        # A VAT-looking AML without an Odoo tax repartition is not proof of
        # recorded VAT for the expense base.  This negative fixture is manual
        # deliberately; the positive fixture never creates its VAT AML.
        unlinked = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': self.bank.id, 'date': '2026-06-23',
            'payment_ref': 'Manual VAT-looking counterpart',
            'partner_id': self.partner.id, 'amount': -115,
            'line_ids': [
                Command.create({
                    'account_id': self.bank.default_account_id.id,
                    'name': 'Bank', 'credit': 115,
                }),
                Command.create({
                    'account_id': self.expense.id,
                    'name': 'Expense without tax configuration', 'debit': 100,
                }),
                Command.create({
                    'account_id': self.vat_account.id,
                    'name': 'Unlinked VAT-like amount', 'debit': 15,
                }),
            ],
        })
        self.assertEqual(len(unlinked.move_id.line_ids), 3)
        self.assertFalse(unlinked.move_id.line_ids.filtered('tax_line_id'))

        other = self.accounts.create({
            'code': '958126', 'name': 'Extra gross payment expense',
            'account_type': 'expense_other',
            'company_ids': [Command.set(self.company.ids)],
        })
        extra = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': self.bank.id, 'date': '2026-06-24',
            'payment_ref': 'Four AML direct expense',
            'partner_id': self.partner.id, 'amount': -116,
            'line_ids': [
                Command.create({
                    'account_id': self.bank.default_account_id.id,
                    'name': 'Bank', 'credit': 116,
                }),
                Command.create({
                    'account_id': self.expense.id,
                    'name': 'Taxed expense base', 'debit': 100,
                    'tax_ids': [Command.set(self.tax.ids)],
                }),
                Command.create({
                    'account_id': other.id,
                    'name': 'Another expense not in narrow contract', 'debit': 1,
                }),
            ],
        })
        self.assertEqual(len(extra.move_id.line_ids), 4)
        self.assertEqual(Decimal(str(extra.amount)), Decimal('-116.00'))
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 0)

    def test_cash_statement_is_real_outflow_source_not_internal_transfer(self):
        self.assertNotEqual(self.cash, self.bank.default_account_id)
        cash_journal = self.env['account.journal'].with_company(self.company).create({
            'name': 'Gross cash source', 'code': 'GCA', 'type': 'cash',
            'company_id': self.company.id,
            'default_account_id': self.cash.id,
        })
        cash_out = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': cash_journal.id, 'date': '2026-06-25',
            'payment_ref': 'Cash paid for expense',
            'partner_id': self.partner.id, 'amount': -40,
            'counterpart_account_id': self.expense.id,
        })
        cash_lines = cash_out.move_id.line_ids
        liquidity = cash_lines.filtered(lambda line: line.account_id == self.cash)
        expense = cash_lines - liquidity
        self.assertEqual(cash_journal.type, 'cash')
        self.assertEqual(cash_journal.default_account_id, self.cash)
        self.assertEqual(cash_out.company_id, self.company)
        self.assertEqual(cash_out.currency_id, self.company.currency_id)
        self.assertEqual(str(cash_out.date), '2026-06-25')
        self.assertEqual(Decimal(str(cash_out.amount)), Decimal('-40.00'))
        self.assertEqual(cash_out.move_id.state, 'posted')
        self.assertEqual(cash_out.move_id.statement_line_id, cash_out)
        self.assertEqual(cash_out.move_id.journal_id, cash_journal)
        self.assertEqual(len(cash_lines), 2)
        self.assertEqual(Decimal(str(liquidity.balance)), Decimal('-40.00'))
        self.assertEqual(expense.account_id, self.expense)
        self.assertEqual(Decimal(str(expense.balance)), Decimal('40.00'))

        transfer = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': cash_journal.id, 'date': '2026-06-26',
            'payment_ref': 'Cash moved to bank',
            'partner_id': self.partner.id, 'amount': -30,
            'counterpart_account_id': self.bank.default_account_id.id,
        })
        transfer_lines = transfer.move_id.line_ids
        transfer_cash = transfer_lines.filtered(
            lambda line: line.account_id == self.cash,
        )
        transfer_bank = transfer_lines - transfer_cash
        self.assertEqual(transfer.move_id.state, 'posted')
        self.assertEqual(len(transfer_lines), 2)
        self.assertEqual(Decimal(str(transfer_cash.balance)), Decimal('-30.00'))
        self.assertEqual(transfer_bank.account_id, self.bank.default_account_id)
        self.assertEqual(Decimal(str(transfer_bank.balance)), Decimal('30.00'))
        self.assertEqual(transfer_bank.account_id.account_type, 'asset_cash')
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 40)
        self.assertEqual(self._purchase_amount('2026-07-01', '2026-07-31'), 0)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=cash_journal.ids,
        ), 40)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=self.bank.ids,
        ), 0)
        snapshot = self.env['baseer.operations.report'].get_source_snapshot({
            'company_id': self.company.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30',
            'journal_ids': [],
        })
        rows = {row['key']: row['amount'] for row in snapshot['periods'][0]['rows']}
        self.assertEqual(rows['net_income'], '-40.00')
        self.assertEqual(snapshot['periods'][0]['excluded']['direct_aml_unproven'], 0)

        # The tax AML is generated by Odoo, not created by this fixture.
        cash_taxed = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': cash_journal.id, 'date': '2026-06-27',
            'payment_ref': 'Actual taxed cash outflow',
            'partner_id': self.partner.id, 'amount': -115,
            'line_ids': [
                Command.create({
                    'account_id': self.cash.id, 'name': 'Cash', 'credit': 115,
                }),
                Command.create({
                    'account_id': self.expense.id, 'name': 'Expense base',
                    'debit': 100, 'tax_ids': [Command.set(self.tax.ids)],
                }),
            ],
        })
        cash_tax_lines = cash_taxed.move_id.line_ids
        cash_liquidity = cash_tax_lines.filtered(
            lambda line: line.account_id == self.cash,
        )
        cash_base = cash_tax_lines.filtered(
            lambda line: line.account_id == self.expense,
        )
        cash_vat = cash_tax_lines.filtered(lambda line: line.tax_line_id)
        self.assertEqual(cash_taxed.move_id.state, 'posted')
        self.assertEqual(cash_taxed.move_id.statement_line_id, cash_taxed)
        self.assertEqual(cash_taxed.move_id.journal_id, cash_journal)
        self.assertEqual(cash_taxed.company_id, self.company)
        self.assertEqual(cash_taxed.currency_id, self.company.currency_id)
        self.assertEqual(str(cash_taxed.date), '2026-06-27')
        self.assertEqual(Decimal(str(cash_taxed.amount)), Decimal('-115.00'))
        self.assertFalse(cash_taxed.move_id.origin_payment_id)
        self.assertEqual(len(cash_tax_lines), 3)
        self.assertEqual(len(cash_liquidity), 1)
        self.assertEqual(len(cash_base), 1)
        self.assertEqual(len(cash_vat), 1)
        self.assertEqual(Decimal(str(cash_liquidity.balance)), Decimal('-115.00'))
        self.assertEqual(Decimal(str(cash_base.balance)), Decimal('100.00'))
        self.assertEqual(cash_base.tax_ids, self.tax)
        self.assertEqual(Decimal(str(cash_vat.balance)), Decimal('15.00'))
        self.assertEqual(cash_vat.account_id, self.vat_account)
        self.assertEqual(cash_vat.tax_line_id, self.tax)
        self.assertIn(
            cash_vat.tax_repartition_line_id,
            self.tax.invoice_repartition_line_ids,
        )
        self.assertEqual(
            sum((Decimal(str(line.balance)) for line in cash_tax_lines), Decimal('0')),
            Decimal('0'),
        )
        self.assertFalse(cash_tax_lines.filtered(
            lambda line: line.matched_credit_ids or line.matched_debit_ids,
        ))
        cash_outstanding = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': cash_journal.id, 'date': '2026-06-28',
            'payment_ref': 'Cash outstanding allocation not yet proven',
            'partner_id': self.partner.id, 'amount': -20,
            'counterpart_account_id': self.outstanding.id,
        })
        self.assertEqual(cash_outstanding.move_id.state, 'posted')
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 155)

        reader = self.env['res.users'].create({
            'name': 'Gross cash outflow reader',
            'login': 'gross_cash_outflow_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured = self.env['baseer.operations.report'].with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', report=secured,
        ), 155)
        for model, hidden in (
                ('account.bank.statement.line', cash_out),
                ('account.move', cash_out.move_id),
                ('account.move.line', expense),
                ('account.account', self.cash)):
            rule = self.env['ir.rule'].create({
                'name': 'Gross cash hide ' + model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {hidden.id})]",
            })
            try:
                rule.flush_recordset()
                with self.assertRaises(AccessError):
                    self._purchase_amount(
                        '2026-06-01', '2026-06-30', report=secured,
                    )
            finally:
                rule.unlink()

    def test_direct_taxed_cash_counts_only_recorded_vat_once(self):
        cash_journal = self.env['account.journal'].with_company(self.company).create({
            'name': 'Gross taxed cash', 'code': 'GCT', 'type': 'cash',
            'company_id': self.company.id,
            'default_account_id': self.cash.id,
        })
        taxed = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': cash_journal.id, 'date': '2026-06-27',
            'payment_ref': 'Taxed cash expense',
            'partner_id': self.partner.id, 'amount': -115,
            'line_ids': [
                Command.create({
                    'account_id': self.cash.id, 'name': 'Cash', 'credit': 115,
                }),
                Command.create({
                    'account_id': self.expense.id, 'name': 'Expense base',
                    'debit': 100, 'tax_ids': [Command.set(self.tax.ids)],
                }),
            ],
        })
        vat_line = taxed.move_id.line_ids.filtered('tax_line_id')
        self.assertEqual(len(vat_line), 1)
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 115)
        self.assertEqual(self._purchase_amount('2026-07-01', '2026-07-31'), 0)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=cash_journal.ids,
        ), 115)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=self.bank.ids,
        ), 0)
        snapshot = self.env['baseer.operations.report'].get_source_snapshot({
            'company_id': self.company.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30',
            'journal_ids': [],
        })
        rows = {row['key']: row['amount'] for row in snapshot['periods'][0]['rows']}
        self.assertEqual(rows['net_income'], '-115.00')
        self.assertEqual(snapshot['periods'][0]['accounts']['expense'][0][
            'source_count'], 1)
        self.assertEqual(snapshot['periods'][0]['excluded']['direct_aml_unproven'], 0)

        # Neither a VAT-looking manual AML nor a fourth counterpart can
        # qualify for the narrow three-line Odoo-tax source.
        fake_vat = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': cash_journal.id, 'date': '2026-06-28',
            'payment_ref': 'Unlinked cash VAT', 'partner_id': self.partner.id,
            'amount': -115,
            'line_ids': [
                Command.create({
                    'account_id': self.cash.id, 'name': 'Cash', 'credit': 115,
                }),
                Command.create({
                    'account_id': self.expense.id, 'name': 'Expense base',
                    'debit': 100,
                }),
                Command.create({
                    'account_id': self.vat_account.id, 'name': 'Unlinked VAT',
                    'debit': 15,
                }),
            ],
        })
        self.assertFalse(fake_vat.move_id.line_ids.filtered('tax_line_id'))
        extra_account = self.accounts.create({
            'code': '958126', 'name': 'Extra cash expense',
            'account_type': 'expense_other',
            'company_ids': [Command.set(self.company.ids)],
        })
        extra = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': cash_journal.id, 'date': '2026-06-29',
            'payment_ref': 'Four-line cash expense',
            'partner_id': self.partner.id, 'amount': -116,
            'line_ids': [
                Command.create({
                    'account_id': self.cash.id, 'name': 'Cash', 'credit': 116,
                }),
                Command.create({
                    'account_id': self.expense.id, 'name': 'Expense base',
                    'debit': 100,
                    'tax_ids': [Command.set(self.tax.ids)],
                }),
                Command.create({
                    'account_id': extra_account.id, 'name': 'Extra counterpart',
                    'debit': 1,
                }),
            ],
        })
        self.assertEqual(len(extra.move_id.line_ids), 4)
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 115)

        reader = self.env['res.users'].create({
            'name': 'Gross taxed cash reader',
            'login': 'gross_taxed_cash_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured = self.env['baseer.operations.report'].with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', report=secured,
        ), 115)
        for model, hidden in (
                ('account.bank.statement.line', taxed),
                ('account.move.line', vat_line),
                ('account.tax', self.tax),
                ('account.tax.repartition.line', vat_line.tax_repartition_line_id),
                ('account.account', self.vat_account)):
            rule = self.env['ir.rule'].create({
                'name': 'Gross taxed cash hide ' + model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {hidden.id})]",
            })
            try:
                rule.flush_recordset()
                with self.assertRaises(AccessError):
                    self._purchase_amount(
                        '2026-06-01', '2026-06-30', report=secured,
                    )
            finally:
                rule.unlink()

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

        second_wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id,
            'payment_method_line_id': self.method.id,
            'amount': 65,
            'payment_date': '2026-07-03',
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })
        second_payment = second_wizard._create_payments()
        payable_65 = second_payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        second_partial = self.env['account.partial.reconcile'].search([
            ('debit_move_id', '=', payable_65.id),
            ('credit_move_id', '=', bill_payable.id),
        ])
        self.assertEqual(len(second_partial), 1)
        self.assertEqual(Decimal(str(second_partial.amount)), Decimal('65.00'))
        self.assertEqual(Decimal(str(bill.amount_residual)), Decimal('0.00'))
        self.assertEqual(self._purchase_amount('2026-07-01', '2026-07-31'), 0)
        bank_65 = self._bank_statement('2026-07-05', self.outstanding, 65)
        outstanding_65_credit = second_payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.outstanding,
        )
        outstanding_65_debit = bank_65.move_id.line_ids.filtered(
            lambda line: line.account_id == self.outstanding,
        )
        (outstanding_65_credit + outstanding_65_debit).reconcile()
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

    def test_approved_batch_direct_cash_payment_counts_its_bill_once(self):
        self.purchase.write({
            'default_account_id': self.expense.id, 'sequence': -100,
        })
        cash_journal = self.env['account.journal'].with_company(self.company).create({
            'name': 'Gross batch cash', 'code': 'GBC', 'type': 'cash',
            'company_id': self.company.id,
            'default_account_id': self.cash.id,
        })
        method = cash_journal.outbound_payment_method_line_ids.filtered(
            lambda item: item.code == 'manual',
        )[:1]
        self.assertTrue(method)
        method.payment_account_id = self.cash
        batch = self.env['baseer.purchase.batch'].with_company(self.company).create({
            'line_ids': [Command.create({
                'partner_id': self.partner.id,
                'supplier_ref': 'GROSS-DIRECT-CASH-115',
                'gross_amount': 115, 'tax_id': self.tax.id,
                'is_credit': False,
                'payment_method_line_id': method.id,
                'invoice_date': '2026-06-27',
            })],
        })
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 0)
        batch.action_approve()
        line = batch.line_ids
        bill = line.move_id
        payment = line.payment_id
        self.assertEqual(batch.state, 'approved')
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(str(payment.move_id.date), '2026-06-27')
        self.assertEqual(Decimal(str(bill.amount_total)), Decimal('115.00'))
        cash_line = payment.move_id.line_ids.filtered(
            lambda item: item.account_id == self.cash,
        )
        self.assertEqual(len(cash_line), 1)
        self.assertEqual(Decimal(str(cash_line.balance)), Decimal('-115.00'))
        payable_payment = payment.move_id.line_ids.filtered(
            lambda item: item.account_id == self.payable,
        )
        payable_bill = bill.line_ids.filtered(
            lambda item: item.account_id == self.payable,
        )
        partial = payable_payment.matched_credit_ids
        self.assertEqual(len(partial), 1)
        self.assertEqual(partial.credit_move_id, payable_bill)
        self.assertEqual(Decimal(str(partial.amount)), Decimal('115.00'))
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 115)
        self.assertEqual(self._purchase_amount('2026-07-01', '2026-07-31'), 0)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=cash_journal.ids,
        ), 115)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=self.bank.ids,
        ), 0)
        snapshot = self.env['baseer.operations.report'].get_source_snapshot({
            'company_id': self.company.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30',
            'journal_ids': [],
        })
        rows = {row['key']: row['amount'] for row in snapshot['periods'][0]['rows']}
        self.assertEqual(rows['net_income'], '-115.00')
        self.assertEqual(snapshot['periods'][0]['accounts']['expense'][0][
            'source_count'], 1)
        bill_ids, payment_ids = bill.ids, payment.ids
        batch.action_approve()
        self.assertEqual(batch.line_ids.move_id.ids, bill_ids)
        self.assertEqual(batch.line_ids.payment_id.ids, payment_ids)
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 115)

        credit = self.env['baseer.purchase.batch'].with_company(self.company).create({
            'line_ids': [Command.create({
                'partner_id': self.partner.id,
                'supplier_ref': 'GROSS-CREDIT-115',
                'gross_amount': 115, 'tax_id': self.tax.id,
                'is_credit': True, 'invoice_date': '2026-06-28',
            })],
        })
        credit.action_approve()
        self.assertFalse(credit.line_ids.payment_id)
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 115)

        # A generic Odoo payment is not a Baseer batch source even when its
        # journal directly credits bank liquidity; advances share this shape.
        generic_bill = self._bill()
        self.method.payment_account_id = self.bank.default_account_id
        generic_wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=generic_bill.ids,
        ).create({
            'journal_id': self.bank.id,
            'payment_method_line_id': self.method.id,
            'amount': 30, 'payment_date': '2026-06-29',
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })
        generic_payment = generic_wizard._create_payments()
        generic_liquidity = generic_payment.move_id.line_ids.filtered(
            lambda item: item.account_id == self.bank.default_account_id,
        )
        self.assertEqual(Decimal(str(generic_liquidity.balance)), Decimal('-30.00'))
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 115)

        reader = self.env['res.users'].create({
            'name': 'Gross batch direct cash reader',
            'login': 'gross_batch_direct_cash_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_invoice').id,
                self.env.ref('account.group_account_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured = self.env['baseer.operations.report'].with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', report=secured,
        ), 115)
        for model, hidden in (
                ('baseer.purchase.batch.line', line),
                ('baseer.purchase.batch', batch),
                ('account.move', bill),
                ('account.payment', payment),
                ('account.move.line', cash_line),
                ('account.partial.reconcile', partial),
                ('account.tax', self.tax),
                ('account.tax.repartition.line',
                 self.tax.invoice_repartition_line_ids.filtered(
                     lambda item: item.repartition_type == 'tax',
                 ))):
            rule = self.env['ir.rule'].create({
                'name': 'Gross batch hide ' + model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {hidden.id})]",
            })
            try:
                rule.flush_recordset()
                with self.assertRaises(AccessError):
                    self._purchase_amount(
                        '2026-06-01', '2026-06-30', report=secured,
                    )
            finally:
                rule.unlink()

    def test_advance_and_internal_transfer_have_no_bill_allocation(self):
        bill = self._bill()
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
        # A direct bank debit booked before the bill stays an excluded
        # advance even if someone matches it to a backdated bill later.
        bank_advance = self._bank_statement('2026-05-16', self.payable, 30)
        advance_debit = bank_advance.move_id.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        bill_payable = bill.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        (advance_debit + bill_payable).reconcile()
        self.assertEqual(self._purchase_amount('2026-05-01', '2026-05-31'), 0)
        # Neither bank decrease is a classified purchase source: the first is
        # an unapplied vendor advance; the second only changes liquidity.

    def test_direct_untaxed_bank_expense_has_a_distinct_cash_source(self):
        direct = self._bank_statement('2026-06-18', self.expense, 40)
        move = direct.move_id
        lines = move.line_ids
        bank_line = lines.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        )
        expense_line = lines - bank_line
        self.assertEqual(len(bank_line), 1)
        self.assertEqual(len(expense_line), 1)
        self.assertEqual(expense_line.account_id, self.expense)
        self.assertEqual(Decimal(str(bank_line.balance)), Decimal('-40.00'))
        self.assertEqual(Decimal(str(expense_line.balance)), Decimal('40.00'))
        self.assertEqual(str(direct.date), '2026-06-18')
        self.assertEqual(direct.company_id, self.company)
        self.assertEqual(direct.currency_id, self.company.currency_id)
        self.assertFalse(move.origin_payment_id)
        self.assertFalse(lines.filtered('tax_line_id'))
        self.assertFalse(expense_line.tax_ids)
        self.assertFalse(expense_line.matched_credit_ids | expense_line.matched_debit_ids)
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 40)
        self.assertEqual(self._purchase_amount('2026-07-01', '2026-07-31'), 0)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=self.bank.ids,
        ), 40)
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', journal_ids=self.general.ids,
        ), 0)
        snapshot = self.env['baseer.operations.report'].get_source_snapshot({
            'company_id': self.company.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30',
            'journal_ids': [],
        })
        rows = {row['key']: row['amount'] for row in snapshot['periods'][0]['rows']}
        self.assertEqual(rows['expense'], '40.00')
        self.assertEqual(rows['net_income'], '-40.00')
        self.assertEqual(snapshot['periods'][0]['excluded']['direct_aml_unproven'], 0)

        transfer = self._bank_statement('2026-06-19', self.cash, 30)
        advance = self._bank_statement('2026-06-20', self.payable, 20)
        outstanding = self._bank_statement('2026-06-21', self.outstanding, 10)
        for statement in (transfer, advance, outstanding):
            counterpart = statement.move_id.line_ids.filtered(
                lambda line: line.account_id != self.bank.default_account_id,
            )
            self.assertEqual(len(counterpart), 1)
            self.assertNotIn(counterpart.account_id.account_type,
                             ('expense', 'expense_direct_cost',
                              'expense_depreciation', 'expense_other'))
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 40)

        reader = self.env['res.users'].create({
            'name': 'Gross direct expense reader',
            'login': 'gross_direct_expense_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured = self.env['baseer.operations.report'].with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(self._purchase_amount(
            '2026-06-01', '2026-06-30', report=secured,
        ), 40)
        for model, hidden in (
                ('account.bank.statement.line', direct),
                ('account.move', move),
                ('account.move.line', expense_line),
                ('account.account', self.expense)):
            rule = self.env['ir.rule'].create({
                'name': 'Gross direct hide ' + model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {hidden.id})]",
            })
            try:
                rule.flush_recordset()
                with self.assertRaises(AccessError):
                    self._purchase_amount(
                        '2026-06-01', '2026-06-30', report=secured,
                    )
            finally:
                rule.unlink()
        tax_tag = self.env['account.account.tag']._get_tax_tags(
            '7(B)', self.env.ref('base.sa').id,
        )
        expense_line.write({'tax_tag_ids': [Command.set(tax_tag.ids)]})
        self.assertTrue(expense_line.tax_tag_ids)
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 0)

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
            'name': 'Gross payment source accountant',
            'login': 'gross_payment_source_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
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

        hidden_bank = self._bank_statement('2026-06-15', self.outstanding, 10)
        secured_report = self.env['baseer.operations.report'].with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(
            Decimal(next(row['amount'].replace(',', '') for row in
                         secured_report.get_source_snapshot({
                             'company_id': self.company.id,
                             'date_from': '2026-06-01', 'date_to': '2026-06-30',
                             'journal_ids': [],
                         })['periods'][0]['rows'] if row['key'] == 'expense')),
            0,
        )
        bank_rule = self.env['ir.rule'].create({
            'name': 'Gross payment source hide bank statement',
            'model_id': self.env['ir.model']._get('account.bank.statement.line').id,
            'domain_force': f"[('id', '!=', {hidden_bank.id})]",
        })
        try:
            bank_rule.flush_recordset()
            with self.assertRaises(AccessError):
                secured_report.get_source_snapshot({
                    'company_id': self.company.id,
                    'date_from': '2026-06-01', 'date_to': '2026-06-30',
                    'journal_ids': [],
                })
        finally:
            bank_rule.unlink()

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

    def test_foreign_currency_bank_statement_is_not_company_currency_purchase(self):
        foreign = self.env.ref('base.EUR' if self.company.currency_id.name != 'EUR'
                               else 'base.USD')
        foreign.active = True
        self.env['res.currency.rate'].create({
            'name': '2026-06-01', 'company_id': self.company.id,
            'currency_id': foreign.id, 'rate': 2,
        })
        foreign_bank = self.env['account.journal'].with_company(self.company).create({
            'name': 'Gross payment foreign bank', 'code': 'GPF',
            'type': 'bank', 'company_id': self.company.id,
            'currency_id': foreign.id, 'default_account_id': self.cash.id,
        })
        statement = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': foreign_bank.id, 'date': '2026-06-22',
            'payment_ref': 'Foreign currency outflow',
            'partner_id': self.partner.id, 'amount': -10,
            'counterpart_account_id': self.outstanding.id,
        })
        self.assertEqual(statement.currency_id, foreign)
        foreign_direct = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': foreign_bank.id, 'date': '2026-06-23',
            'payment_ref': 'Foreign direct expense',
            'partner_id': self.partner.id, 'amount': -12,
            'counterpart_account_id': self.expense.id,
        })
        self.assertEqual(foreign_direct.currency_id, foreign)
        snapshot = self.env['baseer.operations.report'].get_source_snapshot({
            'company_id': self.company.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30',
            'journal_ids': [],
        })
        self.assertFalse(snapshot['complete'])
        self.assertEqual(snapshot['periods'][0]['excluded'][
            'foreign_currency_bank_outflow'], 2)
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 0)

    def test_multi_line_bill_source_and_cumulative_50_105_allocation(self):
        cost = self.accounts.create({
            'code': '958126', 'name': 'Gross payment source direct cost',
            'account_type': 'expense_direct_cost',
            'company_ids': [Command.set(self.company.ids)],
        })
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice', 'partner_id': self.partner.id,
            'journal_id': self.purchase.id, 'invoice_date': '2026-06-10',
            'invoice_line_ids': [
                Command.create({
                    'name': 'Cost with actual VAT', 'quantity': 1,
                    'price_unit': 100, 'account_id': cost.id,
                    'tax_ids': [Command.set(self.tax.ids)],
                }),
                Command.create({
                    'name': 'Exempt expense', 'quantity': 1,
                    'price_unit': 40, 'account_id': self.expense.id,
                    'tax_ids': [Command.clear()],
                }),
            ],
        })
        bill.action_post()
        self.assertEqual(bill.currency_id, self.company.currency_id)
        self.assertEqual(Decimal(str(bill.amount_total)), 155)
        base_lines, _tax_lines = bill._get_rounded_base_and_tax_lines()
        self.env['account.tax']._add_accounting_data_in_base_lines_tax_details(
            base_lines, self.company,
        )
        source_gross = {}
        for base in base_lines:
            line = base['record']
            if line not in bill.invoice_line_ids:
                continue
            details = base['tax_details']
            gross = Decimal(str(details['total_excluded'])) + sum((
                Decimal(str(tax['tax_amount'])) for tax in details['taxes_data']
            ), Decimal('0'))
            source_gross[line.account_id.id] = gross
        self.assertEqual(source_gross[cost.id], 115)
        self.assertEqual(source_gross[self.expense.id], 40)
        self.assertEqual(sum(source_gross.values()), Decimal(str(bill.amount_total)))
        self.assertEqual(self._purchase_amount('2026-06-01', '2026-06-30'), 0)

        bill_payable = bill.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        self.assertEqual(len(bill_payable), 1)
        events = []
        for amount, payment_day, bank_day in (
            (50, '2026-06-12', '2026-06-15'),
            (105, '2026-07-03', '2026-07-05'),
        ):
            wizard = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=bill.ids,
            ).create({
                'journal_id': self.bank.id,
                'payment_method_line_id': self.method.id,
                'amount': amount, 'payment_date': payment_day,
                'installments_mode': 'full',
                'payment_difference_handling': 'open',
            })
            payment = wizard._create_payments()
            payment_payable = payment.move_id.line_ids.filtered(
                lambda line: line.account_id == self.payable,
            )
            bill_partial = self.env['account.partial.reconcile'].search([
                ('debit_move_id', '=', payment_payable.id),
                ('credit_move_id', '=', bill_payable.id),
            ])
            self.assertEqual(len(bill_partial), 1)
            self.assertEqual(Decimal(str(bill_partial.amount)), amount)
            statement = self._bank_statement(bank_day, self.outstanding, amount)
            outstanding_credit = payment.move_id.line_ids.filtered(
                lambda line: line.account_id == self.outstanding,
            )
            outstanding_debit = statement.move_id.line_ids.filtered(
                lambda line: line.account_id == self.outstanding,
            )
            (outstanding_credit + outstanding_debit).reconcile()
            events.append((statement.id, Decimal(str(statement.amount)), statement.date))
        self.assertEqual(len({event[0] for event in events}), 2)
        self.assertEqual(events[0][1], Decimal('-50'))
        self.assertEqual(str(events[0][2]), '2026-06-15')
        self.assertEqual(events[1][1], Decimal('-105'))
        self.assertEqual(str(events[1][2]), '2026-07-05')
        self.assertEqual(Decimal(str(bill.amount_residual)), 0)
        # Odoo reconciles each payment against the bill's payable term, not
        # against either product line. Allocation by account is a report rule.
        self.assertEqual(len(bill_payable.matched_debit_ids), 2)
        report = self.env['baseer.operations.report']
        def row_amount(start, end, key):
            snapshot = report.get_source_snapshot({
                'company_id': self.company.id,
                'date_from': start, 'date_to': end, 'journal_ids': [],
            })
            self.assertFalse(snapshot['complete'])
            return Decimal(next(row['amount'].replace(',', '') for row in
                                snapshot['periods'][0]['rows'] if row['key'] == key))

        self.assertEqual(row_amount('2026-06-01', '2026-06-30', 'cost_of_sales'),
                         Decimal('37.10'))
        self.assertEqual(row_amount('2026-06-01', '2026-06-30', 'expense'),
                         Decimal('12.90'))
        self.assertEqual(row_amount('2026-07-01', '2026-07-31', 'cost_of_sales'),
                         Decimal('77.90'))
        self.assertEqual(row_amount('2026-07-01', '2026-07-31', 'expense'),
                         Decimal('27.10'))
        reader = self.env['res.users'].create({
            'name': 'Gross multi-line accountant',
            'login': 'gross_multiline_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured = report.with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        july = {
            'company_id': self.company.id,
            'date_from': '2026-07-01', 'date_to': '2026-07-31',
            'journal_ids': [],
        }
        baseline = secured.get_source_snapshot(july)
        self.assertEqual(Decimal(next(
            row['amount'].replace(',', '') for row in baseline['periods'][0]['rows']
            if row['key'] == 'expense'
        )), Decimal('27.10'))
        prior_bank_rule = self.env['ir.rule'].create({
            'name': 'Gross multi-line hide prior June bank',
            'model_id': self.env['ir.model']._get('account.bank.statement.line').id,
            'domain_force': f"[('id', '!=', {events[0][0]})]",
        })
        try:
            prior_bank_rule.flush_recordset()
            with self.assertRaises(AccessError):
                secured.get_source_snapshot(july)
        finally:
            prior_bank_rule.unlink()

    def test_cumulative_allocation_of_many_small_outflows_has_no_drift(self):
        report = self.env['baseer.operations.report']
        gross = [Decimal('115.00'), Decimal('40.00')]
        totals = [Decimal('0'), Decimal('0')]
        for paid_before in range(155):
            allocation = report._allocate_purchase_event(
                gross, Decimal(paid_before), Decimal('1'),
                self.company.currency_id,
            )
            self.assertEqual(sum(allocation), Decimal('1'))
            for index, value in enumerate(allocation):
                totals[index] += value
        self.assertEqual(totals, gross)
        tiny_gross = [Decimal('0.01')] * 3
        tiny_totals = [Decimal('0')] * 3
        for step in range(3):
            allocation = report._allocate_purchase_event(
                tiny_gross, Decimal(step) / 100, Decimal('0.01'),
                self.company.currency_id,
            )
            self.assertEqual(sum(allocation), Decimal('0.01'))
            self.assertTrue(all(value >= 0 for value in allocation))
            tiny_totals = [old + new for old, new in zip(
                tiny_totals, allocation, strict=True,
            )]
        self.assertEqual(tiny_totals, tiny_gross)

    def test_two_bill_lines_on_same_pl_account_aggregate_after_allocation(self):
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice', 'partner_id': self.partner.id,
            'journal_id': self.purchase.id, 'invoice_date': '2026-06-10',
            'invoice_line_ids': [
                Command.create({
                    'name': 'Taxed expense', 'quantity': 1,
                    'price_unit': 100, 'account_id': self.expense.id,
                    'tax_ids': [Command.set(self.tax.ids)],
                }),
                Command.create({
                    'name': 'Exempt expense', 'quantity': 1,
                    'price_unit': 40, 'account_id': self.expense.id,
                    'tax_ids': [Command.clear()],
                }),
            ],
        })
        bill.action_post()
        self.assertEqual(Decimal(str(bill.amount_total)), 155)
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id,
            'payment_method_line_id': self.method.id,
            'amount': 155, 'payment_date': '2026-06-12',
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })
        payment = wizard._create_payments()
        statement = self._bank_statement('2026-06-15', self.outstanding, 155)
        outstanding_credit = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.outstanding,
        )
        outstanding_debit = statement.move_id.line_ids.filtered(
            lambda line: line.account_id == self.outstanding,
        )
        (outstanding_credit + outstanding_debit).reconcile()
        snapshot = self.env['baseer.operations.report'].get_source_snapshot({
            'company_id': self.company.id,
            'date_from': '2026-06-01', 'date_to': '2026-06-30',
            'journal_ids': [],
        })
        self.assertFalse(snapshot['complete'])
        self.assertEqual(snapshot['periods'][0]['accounts']['expense'], [{
            'account_id': self.expense.id,
            'account_code': self.expense.code,
            'account_name': self.expense.name,
            'amount': '155.00', 'negative': False, 'source_count': 2,
        }])
