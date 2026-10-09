"""Native Odoo 19 source evidence for a proposed VAT-inclusive operations report.

No report calculator lives here.  Invoice-line totals are characterized beside
posted AML and account types; POS and Baseer summary semantics require their own
installed-module/QA evidence before G2 can approve an operations calculator.
"""

from decimal import Decimal

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOperationsGrossNativeSourceContract(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.receivable = self._account('956101', 'asset_receivable', reconcile=True)
        self.payable = self._account('956102', 'liability_payable', reconcile=True)
        self.income = self._account('956103', 'income')
        self.other_income = self._account('956104', 'income_other')
        self.cost = self._account('956105', 'expense_direct_cost')
        self.expense = self._account('956106', 'expense')
        self.cash = self._account('956107', 'asset_cash')
        self.vat_due = self._account('956108', 'liability_current')
        self.vat_paid = self._account('956109', 'asset_current')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Operations source synthetic partner',
            'property_account_receivable_id': self.receivable.id,
            'property_account_payable_id': self.payable.id,
        })
        self.sale_journal = self._journal('sale', 'OGS')
        self.purchase_journal = self._journal('purchase', 'OGP')
        self.sale_tax = self._tax('sale', self.vat_due)
        self.purchase_tax = self._tax('purchase', self.vat_paid)

    def _account(self, code, kind, reconcile=False):
        return self.env['account.account'].with_company(self.company).create({
            'code': code, 'name': f'Operations source {kind} {code}',
            'account_type': kind, 'reconcile': reconcile,
            'company_ids': [Command.set(self.company.ids)],
        })

    def _journal(self, kind, code):
        return self.env['account.journal'].with_company(self.company).create({
            'name': f'Operations source {kind}', 'code': code,
            'type': kind, 'company_id': self.company.id,
        })

    def _tax(self, use, account):
        tax = self.env['account.tax'].with_company(self.company).create({
            'name': f'Operations source {use} VAT 15%',
            'amount_type': 'percent', 'amount': 15,
            'type_tax_use': use, 'company_id': self.company.id,
        })
        tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).write({'account_id': account.id})
        return tax

    def _invoice(self, move_type, journal, rows, currency=None):
        values = {
            'move_type': move_type,
            'partner_id': self.partner.id,
            'journal_id': journal.id,
            'invoice_date': '2041-06-10',
            'invoice_line_ids': [Command.create({
                'name': name, 'quantity': 1, 'price_unit': price,
                'discount': discount, 'account_id': account.id,
                'tax_ids': [Command.set(tax.ids if tax else [])],
            }) for name, account, price, discount, tax in rows],
        }
        if currency:
            values['currency_id'] = currency.id
        move = self.env['account.move'].with_company(self.company).create(values)
        move.action_post()
        self.assertEqual(move.state, 'posted')
        return move

    @staticmethod
    def _money(value):
        return Decimal(str(value)).quantize(Decimal('0.01'))

    def _line(self, move, name):
        lines = move.invoice_line_ids.filtered(lambda line: line.name == name)
        self.assertEqual(len(lines), 1)
        return lines

    def test_posted_mixed_sales_invoice_maps_net_tax_gross_by_income_line(self):
        invoice = self._invoice('out_invoice', self.sale_journal, [
            ('Standard VAT', self.income, 100, 0, self.sale_tax),
            ('Exempt', self.other_income, 80, 0, False),
            ('Discounted VAT', self.income, 50, 10, self.sale_tax),
        ])
        expected = {
            'Standard VAT': (self.income, '100.00', '15.00', '115.00'),
            'Exempt': (self.other_income, '80.00', '0.00', '80.00'),
            'Discounted VAT': (self.income, '45.00', '6.75', '51.75'),
        }
        for name, (account, net, tax, gross) in expected.items():
            with self.subTest(line=name):
                line = self._line(invoice, name)
                self.assertEqual(line.account_id, account)
                self.assertEqual(line.account_id.account_type, account.account_type)
                self.assertEqual(self._money(line.price_subtotal), Decimal(net))
                self.assertEqual(self._money(line.price_total), Decimal(gross))
                self.assertEqual(self._money(line.price_total - line.price_subtotal),
                                 Decimal(tax))
                self.assertEqual(self._money(line.balance), -Decimal(net))
                self.assertEqual(line.tax_ids.ids, self.sale_tax.ids if tax != '0.00' else [])
                self.assertEqual(line.move_id.id, invoice.id)
        self.assertEqual(self._money(invoice.amount_untaxed), Decimal('225.00'))
        self.assertEqual(self._money(invoice.amount_tax), Decimal('21.75'))
        self.assertEqual(self._money(invoice.amount_total), Decimal('246.75'))
        posted_tax_lines = invoice.line_ids.filtered(lambda line: line.tax_line_id)
        self.assertEqual(sum((self._money(line.balance) for line in posted_tax_lines),
                             Decimal('0')), Decimal('-21.75'))
        self.assertEqual(sum((self._money(line.balance) for line in invoice.line_ids),
                             Decimal('0')), Decimal('0'))
        # A posted tax AML may cover several invoice lines.  Its tax ID alone
        # is not a one-to-one allocation of VAT to P&L leaf accounts.
        self.assertEqual(set(posted_tax_lines.mapped('tax_line_id').ids),
                         set(self.sale_tax.ids))

    def test_refund_and_purchase_cost_source_signs_are_not_sales_totals(self):
        sale_refund = self._invoice('out_refund', self.sale_journal, [
            ('Returned standard VAT', self.income, 100, 0, self.sale_tax),
        ])
        bill = self._invoice('in_invoice', self.purchase_journal, [
            ('Taxed cost', self.cost, 100, 0, self.purchase_tax),
            ('Untaxed expense', self.expense, 40, 0, False),
        ])
        vendor_refund = self._invoice('in_refund', self.purchase_journal, [
            ('Returned cost', self.cost, 20, 0, self.purchase_tax),
        ])
        for move, name, account, net, tax, gross, source_balance in (
            (sale_refund, 'Returned standard VAT', self.income,
             '100.00', '15.00', '115.00', '100.00'),
            (bill, 'Taxed cost', self.cost,
             '100.00', '15.00', '115.00', '100.00'),
            (bill, 'Untaxed expense', self.expense,
             '40.00', '0.00', '40.00', '40.00'),
            (vendor_refund, 'Returned cost', self.cost,
             '20.00', '3.00', '23.00', '-20.00'),
        ):
            with self.subTest(move_type=move.move_type, line=name):
                line = self._line(move, name)
                self.assertEqual(line.account_id, account)
                self.assertEqual(self._money(line.price_subtotal), Decimal(net))
                self.assertEqual(self._money(line.price_total - line.price_subtotal),
                                 Decimal(tax))
                self.assertEqual(self._money(line.price_total), Decimal(gross))
                self.assertEqual(self._money(line.balance), Decimal(source_balance))
        self.assertEqual(self._money(sale_refund.amount_total), Decimal('115.00'))
        self.assertEqual(self._money(bill.amount_total), Decimal('155.00'))
        self.assertEqual(self._money(vendor_refund.amount_total), Decimal('23.00'))
        for move in (sale_refund, bill, vendor_refund):
            self.assertEqual(sum((self._money(line.balance) for line in move.line_ids),
                                 Decimal('0')), Decimal('0'))

    def test_direct_journal_without_tax_metadata_cannot_prove_vat_origin(self):
        journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            journal = self._journal('general', 'OGJ')
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2041-06-11', 'journal_id': journal.id,
            'move_type': 'entry',
            'line_ids': [
                Command.create({'name': 'Unattributed receipt',
                                'account_id': self.cash.id, 'debit': 115}),
                Command.create({'name': 'Unattributed income',
                                'account_id': self.income.id, 'credit': 100}),
                Command.create({'name': 'Unattributed VAT-like balance',
                                'account_id': self.vat_due.id, 'credit': 15}),
            ],
        })
        move._post(soft=False)
        self.assertEqual(move.state, 'posted')
        income_line = move.line_ids.filtered(lambda line: line.account_id == self.income)
        vat_like_line = move.line_ids.filtered(lambda line: line.account_id == self.vat_due)
        self.assertFalse(income_line.tax_ids)
        self.assertFalse(vat_like_line.tax_line_id)
        self.assertEqual(self._money(income_line.balance), Decimal('-100.00'))
        self.assertEqual(self._money(vat_like_line.balance), Decimal('-15.00'))
        # A liability credit of 15 beside revenue 100 is not evidence that
        # this journal item originated as a 15% taxable sale.

    def test_foreign_invoice_line_total_is_not_a_company_currency_amount(self):
        foreign_xmlid = 'base.EUR' if self.company.currency_id.name != 'EUR' else 'base.USD'
        foreign = self.env.ref(foreign_xmlid)
        foreign.active = True
        self.env['res.currency.rate'].create({
            'name': '2041-06-01', 'company_id': self.company.id,
            'currency_id': foreign.id, 'rate': 2.0,
        })
        invoice = self._invoice('out_invoice', self.sale_journal, [
            ('Foreign taxable sale', self.income, 100, 0, self.sale_tax),
        ], currency=foreign)
        line = self._line(invoice, 'Foreign taxable sale')
        self.assertEqual(invoice.currency_id, foreign)
        self.assertEqual(line.currency_id, foreign)
        self.assertEqual(self._money(line.price_subtotal), Decimal('100.00'))
        self.assertEqual(self._money(line.price_total), Decimal('115.00'))
        self.assertEqual(self._money(line.amount_currency), Decimal('-100.00'))
        company_net = foreign._convert(100, self.company.currency_id,
                                       self.company, invoice.date)
        self.assertEqual(self._money(-line.balance), self._money(company_net))
        self.assertNotEqual(self._money(-line.balance), Decimal('100.00'))
        # price_total minus price_subtotal is transaction-currency VAT, not
        # an amount that can be added to company-currency P&L totals as-is.
        self.assertEqual(self._money(line.price_total - line.price_subtotal),
                         Decimal('15.00'))

    def test_foreign_bill_partial_vat_is_attributed_from_posted_tax_details(self):
        """VAT per P&L account comes from rounded source/repartition, not FX guesses."""
        foreign_xmlid = 'base.EUR' if self.company.currency_id.name != 'EUR' else 'base.USD'
        foreign = self.env.ref(foreign_xmlid)
        foreign.active = True
        self.env['res.currency.rate'].create({
            'name': '2041-06-01', 'company_id': self.company.id,
            'currency_id': foreign.id, 'rate': 2.3,
        })
        # Half the VAT is recoverable; the other half has no dedicated tax
        # account and Odoo books it to the originating expense account.
        partial_vat = self.env['account.tax'].with_company(self.company).create({
            'name': 'Operations source partly recoverable VAT 15%',
            'amount_type': 'percent', 'amount': 15,
            'type_tax_use': 'purchase', 'company_id': self.company.id,
            'invoice_repartition_line_ids': [
                Command.create({'document_type': 'invoice',
                                'repartition_type': 'base', 'factor_percent': 100}),
                Command.create({'document_type': 'invoice',
                                'repartition_type': 'tax', 'factor_percent': 50,
                                'account_id': self.vat_paid.id}),
                Command.create({'document_type': 'invoice',
                                'repartition_type': 'tax', 'factor_percent': 50}),
            ],
            'refund_repartition_line_ids': [
                Command.create({'document_type': 'refund',
                                'repartition_type': 'base', 'factor_percent': 100}),
                Command.create({'document_type': 'refund',
                                'repartition_type': 'tax', 'factor_percent': 50,
                                'account_id': self.vat_paid.id}),
                Command.create({'document_type': 'refund',
                                'repartition_type': 'tax', 'factor_percent': 50}),
            ],
        })
        bill = self._invoice('in_invoice', self.purchase_journal, [
            ('Partly recoverable cost', self.cost, 33.33, 0, partial_vat),
            ('Partly recoverable expense', self.expense, 66.67, 0, partial_vat),
        ], currency=foreign)
        self.assertEqual(bill.currency_id, foreign)
        self.assertEqual(self._money(bill.amount_total), Decimal('115.00'))
        posted_tax_amls = bill.line_ids.filtered(
            lambda line: line.tax_repartition_line_id.tax_id == partial_vat,
        )
        self.assertTrue(posted_tax_amls)
        self.assertEqual(set(posted_tax_amls.mapped('account_id').ids),
                         {self.vat_paid.id, self.cost.id, self.expense.id})
        self.assertEqual(set(posted_tax_amls.mapped('tax_line_id').ids),
                         {partial_vat.id})

        # Odoo 19 rebuilds per-source-line tax detail from the *posted* move
        # and distributes any document-level rounding delta against tax AMLs.
        # The tax AML alone can aggregate both invoice lines, so its tax ID is
        # not enough to allocate recoverable VAT between their P&L accounts.
        base_lines, tax_lines = bill._get_rounded_base_and_tax_lines()
        self.assertTrue(tax_lines)
        self.env['account.tax']._add_accounting_data_in_base_lines_tax_details(
            base_lines, self.company,
        )
        source_lines = {line.id: line for line in bill.invoice_line_ids}
        attributed = {}
        by_origin_account = {}
        tax_by_account = {}
        for base_line in base_lines:
            source = base_line['record']
            if source.id not in source_lines:
                continue
            self.assertEqual(source.move_id, bill)
            self.assertIn(source.account_id, self.cost | self.expense)
            net = self._money(source.balance)
            self.assertEqual(self._money(base_line['tax_details']['total_excluded']),
                             net)
            source_tax = Decimal('0.00')
            for tax_data in base_line['tax_details']['taxes_data']:
                self.assertEqual(tax_data['tax'], partial_vat)
                local_tax = self._money(tax_data['tax_amount'])
                source_tax += local_tax
                repartition_tax = Decimal('0.00')
                for repartition in tax_data['tax_reps_data']:
                    amount = self._money(repartition['tax_amount'])
                    tax_by_account[repartition['account'].id] = (
                        tax_by_account.get(repartition['account'].id, Decimal('0.00'))
                        + amount
                    )
                    repartition_tax += amount
                self.assertEqual(repartition_tax, local_tax)
            attributed[source.id] = (net, source_tax, net + source_tax)
            by_origin_account[source.account_id.id] = (net, source_tax, net + source_tax)
            # This is a company-currency value; the invoice's 33.33/66.67
            # price_total values are in the foreign document currency.
            self.assertNotEqual(net, self._money(source.price_subtotal))
        self.assertEqual(set(attributed), set(source_lines))
        self.assertEqual(set(by_origin_account), {self.cost.id, self.expense.id})
        self.assertEqual(set(tax_by_account),
                         {self.vat_paid.id, self.cost.id, self.expense.id})
        # The tax split names the destination accounts, but rounding in Odoo
        # is first aligned at tax-ID level. Never assume a rep share for one
        # source line equals a posted *grouped* tax AML for that account.
        posted_tax_by_account = {
            account.id: sum((self._money(line.balance) for line in posted_tax_amls
                             if line.account_id == account), Decimal('0.00'))
            for account in (self.vat_paid, self.cost, self.expense)
        }
        self.assertTrue(posted_tax_by_account[self.cost.id] > 0)
        self.assertTrue(posted_tax_by_account[self.expense.id] > 0)
        self.assertEqual(
            sum((values[1] for values in attributed.values()), Decimal('0.00')),
            sum((self._money(line.balance) for line in posted_tax_amls),
                Decimal('0.00')),
        )
        self.assertEqual(
            sum((values[2] for values in attributed.values()), Decimal('0.00')),
            self._money(sum(bill.line_ids.filtered(
                lambda line: line.display_type == 'payment_term',
            ).mapped('credit'))),
        )
        # The non-recoverable share is a posted P&L tax AML in cost/expense;
        # adding every tax AML to P&L net would count that share twice.
        self.assertEqual(
            sum(posted_tax_by_account.values(), Decimal('0.00')),
            sum(tax_by_account.values(), Decimal('0.00')),
        )

    def test_company_scoped_readonly_user_cannot_see_other_invoice_source(self):
        other = self.env['res.company'].create({
            'name': 'Operations source second company',
        })
        other_receivable = self.env['account.account'].with_company(other).create({
            'code': '956101', 'name': 'Other operations receivable',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [Command.set(other.ids)],
        })
        other_income = self.env['account.account'].with_company(other).create({
            'code': '956103', 'name': 'Other operations income',
            'account_type': 'income',
            'company_ids': [Command.set(other.ids)],
        })
        other_partner = self.env['res.partner'].with_company(other).create({
            'name': 'Other operations partner',
            'property_account_receivable_id': other_receivable.id,
        })
        other_journal = self.env['account.journal'].with_company(other).create({
            'name': 'Other operations sales', 'code': 'OGS',
            'type': 'sale', 'company_id': other.id,
        })
        other_invoice = self.env['account.move'].with_company(other).create({
            'move_type': 'out_invoice', 'partner_id': other_partner.id,
            'journal_id': other_journal.id, 'invoice_date': '2041-06-10',
            'invoice_line_ids': [Command.create({
                'name': 'Other operations source', 'quantity': 1,
                'price_unit': 20, 'account_id': other_income.id,
                'tax_ids': [Command.clear()],
            })],
        })
        other_invoice.action_post()
        source = other_invoice.invoice_line_ids
        self.assertEqual(other_invoice.state, 'posted')
        readonly = self.env['res.users'].create({
            'name': 'Operations source readonly',
            'login': 'operations_source_readonly',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        self.assertFalse(self.env['account.move'].with_user(readonly).search([
            ('id', '=', other_invoice.id),
        ]))
        self.assertFalse(self.env['account.move.line'].with_user(readonly).search([
            ('id', '=', source.id),
        ]))
        with self.assertRaises(AccessError):
            other_invoice.with_user(readonly).check_access('read')
        with self.assertRaises(AccessError):
            source.with_user(readonly).check_access('read')
