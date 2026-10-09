"""Narrow G5 evidence for the incomplete gross-operations source slice."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOperationsGrossCalculator(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.report = self.env['baseer.operations.report']
        self.receivable = self._account('958101', 'asset_receivable', True)
        self.payable = self._account('958102', 'liability_payable', True)
        self.income = self._account('958103', 'income')
        self.other_income = self._account('958104', 'income_other')
        self.cost = self._account('958105', 'expense_direct_cost')
        self.expense = self._account('958106', 'expense')
        self.cash = self._account('958107', 'asset_cash')
        self.tax_account = self._account('958108', 'liability_current')
        self.input_tax_account = self._account('958109', 'asset_current')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Gross operations synthetic partner',
            'property_account_receivable_id': self.receivable.id,
            'property_account_payable_id': self.payable.id,
        })
        self.sale_journal = self._journal('sale', 'GOS')
        self.purchase_journal = self._journal('purchase', 'GOP')
        self.tax = self._tax('sale', self.tax_account)
        self.purchase_tax = self._tax('purchase', self.input_tax_account)

    def _account(self, code, kind, reconcile=False):
        return self.env['account.account'].with_company(self.company).create({
            'code': code, 'name': 'Gross operations ' + code,
            'account_type': kind, 'reconcile': reconcile,
            'company_ids': [Command.set(self.company.ids)],
        })

    def _journal(self, kind, code):
        return self.env['account.journal'].with_company(self.company).create({
            'name': 'Gross operations ' + kind, 'code': code,
            'type': kind, 'company_id': self.company.id,
        })

    def _tax(self, use, account):
        tax = self.env['account.tax'].with_company(self.company).create({
            'name': 'Gross operations VAT 15%', 'amount_type': 'percent',
            'amount': 15, 'type_tax_use': use, 'company_id': self.company.id,
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
        return move

    def _filters(self, journal_ids=None):
        return {
            'company_id': self.company.id,
            'date_from': '2041-06-01', 'date_to': '2041-06-30',
            'journal_ids': journal_ids or [],
        }

    def _snapshot(self, journal_ids=None, report=None):
        return (report or self.report).get_source_snapshot(self._filters(journal_ids))

    @staticmethod
    def _row(snapshot, key):
        return next(row for row in snapshot['periods'][0]['rows'] if row['key'] == key)

    def test_invoice_refund_and_nine_rows_include_attributed_vat(self):
        self._invoice('out_invoice', self.sale_journal, [
            ('VAT sale', self.income, 100, 0, self.tax),
            ('Exempt other income', self.other_income, 80, 0, False),
            ('Discounted sale', self.income, 50, 10, self.tax),
        ])
        self._invoice('out_refund', self.sale_journal, [
            ('VAT refund', self.income, 100, 0, self.tax),
        ])
        self._invoice('in_invoice', self.purchase_journal, [
            ('VAT cost', self.cost, 100, 0, self.purchase_tax),
            ('Expense', self.expense, 40, 0, False),
        ])
        snapshot = self._snapshot()
        self.assertFalse(snapshot['complete'])
        self.assertTrue(snapshot['not_accounting_profit'])
        self.assertEqual([row['key'] for row in snapshot['periods'][0]['rows']], [
            'income', 'cost_of_sales', 'gross_profit', 'expense',
            'net_operating_income', 'other_income', 'other_expense',
            'net_other_income', 'net_income',
        ])
        self.assertEqual(self._row(snapshot, 'income')['amount'], '51.75')
        self.assertEqual(self._row(snapshot, 'cost_of_sales')['amount'], '115.00')
        self.assertEqual(self._row(snapshot, 'expense')['amount'], '40.00')
        self.assertEqual(self._row(snapshot, 'other_income')['amount'], '80.00')
        self.assertEqual(self._row(snapshot, 'gross_profit')['amount'], '-63.25')
        self.assertEqual(self._row(snapshot, 'net_income')['amount'], '-23.25')
        income_accounts = snapshot['periods'][0]['accounts']['income']
        self.assertEqual(len(income_accounts), 1)
        self.assertEqual(income_accounts[0]['account_id'], self.income.id)
        self.assertEqual(income_accounts[0]['amount'], '51.75')

    def test_fx_partial_vat_uses_rounded_company_currency_and_no_tax_aml_double_count(self):
        foreign_xmlid = 'base.EUR' if self.company.currency_id.name != 'EUR' else 'base.USD'
        foreign = self.env.ref(foreign_xmlid)
        foreign.active = True
        self.env['res.currency.rate'].create({
            'name': '2041-06-01', 'company_id': self.company.id,
            'currency_id': foreign.id, 'rate': 2.3,
        })
        partial = self.env['account.tax'].with_company(self.company).create({
            'name': 'Gross operations partial VAT 15%',
            'amount_type': 'percent', 'amount': 15,
            'type_tax_use': 'purchase', 'company_id': self.company.id,
            'invoice_repartition_line_ids': [
                Command.create({'document_type': 'invoice',
                                'repartition_type': 'base', 'factor_percent': 100}),
                Command.create({'document_type': 'invoice',
                                'repartition_type': 'tax', 'factor_percent': 50,
                                'account_id': self.input_tax_account.id}),
                Command.create({'document_type': 'invoice',
                                'repartition_type': 'tax', 'factor_percent': 50}),
            ],
            'refund_repartition_line_ids': [
                Command.create({'document_type': 'refund',
                                'repartition_type': 'base', 'factor_percent': 100}),
                Command.create({'document_type': 'refund',
                                'repartition_type': 'tax', 'factor_percent': 50,
                                'account_id': self.input_tax_account.id}),
                Command.create({'document_type': 'refund',
                                'repartition_type': 'tax', 'factor_percent': 50}),
            ],
        })
        bill = self._invoice('in_invoice', self.purchase_journal, [
            ('Partial cost', self.cost, 33.33, 0, partial),
            ('Partial expense', self.expense, 66.67, 0, partial),
        ], currency=foreign)
        base_lines, _tax_lines = bill._get_rounded_base_and_tax_lines()
        self.env['account.tax']._add_accounting_data_in_base_lines_tax_details(
            base_lines, self.company,
        )
        expected = {}
        for base in base_lines:
            line = base['record']
            if line.id not in bill.invoice_line_ids.ids:
                continue
            net = Decimal(str(line.balance))
            vat = sum((Decimal(str(item['tax_amount']))
                       for item in base['tax_details']['taxes_data']), Decimal('0'))
            expected[line.account_id.id] = net + vat
        snapshot = self._snapshot([self.purchase_journal.id])
        for section, account in (('cost_of_sales', self.cost), ('expense', self.expense)):
            leaf = next(row for row in snapshot['periods'][0]['accounts'][section]
                        if row['account_id'] == account.id)
            self.assertEqual(leaf['amount'], f'{expected[account.id]:,.2f}')
        self.assertEqual(snapshot['periods'][0]['excluded'][
            'nonrecoverable_tax_amls_not_readded'], 2)
        self.assertEqual(
            sum((expected[account.id] for account in (self.cost, self.expense)), Decimal('0')),
            sum((Decimal(str(line.credit)) for line in bill.line_ids.filtered(
                lambda item: item.display_type == 'payment_term',
            )), Decimal('0')),
        )

    def test_direct_aml_is_counted_as_excluded_not_invented_tax(self):
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1) or self._journal('general', 'GOJ')
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2041-06-11', 'journal_id': journal.id,
            'move_type': 'entry',
            'line_ids': [
                Command.create({'account_id': self.cash.id, 'debit': 115}),
                Command.create({'account_id': self.income.id, 'credit': 100}),
                Command.create({'account_id': self.tax_account.id, 'credit': 15}),
            ],
        })
        move._post(soft=False)
        snapshot = self._snapshot([journal.id])
        self.assertEqual(self._row(snapshot, 'income')['amount'], '0.00')
        self.assertEqual(snapshot['periods'][0]['excluded']['direct_aml_unproven'], 1)

    def test_restricted_user_fails_closed_and_other_company_is_rejected(self):
        invoice = self._invoice('out_invoice', self.sale_journal, [
            ('Restricted VAT sale', self.income, 100, 0, self.tax),
        ])
        reader = self.env['res.users'].create({
            'name': 'Gross operations limited reader',
            'login': 'gross_operations_limited_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured = self.report.with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(self._row(self._snapshot(report=secured), 'income')['amount'], '115.00')
        rule = self.env['ir.rule'].create({
            'name': 'Gross operations hide source invoice',
            'model_id': self.env['ir.model']._get('account.move').id,
            'domain_force': f"[('id', '!=', {invoice.id})]",
        })
        try:
            rule.flush_recordset()
            self.assertFalse(secured.env['account.move'].search([('id', '=', invoice.id)]))
            with self.assertRaises(AccessError):
                self._snapshot(report=secured)
        finally:
            rule.unlink()
        other = self.env['res.company'].create({'name': 'Other gross operations company'})
        with self.assertRaises(AccessError):
            self.report.get_source_snapshot({**self._filters(), 'company_id': other.id})

    def test_native_pos_order_and_refund_are_once_only_after_invoice(self):
        """One original order each; invoice/session/reversal are never added."""
        mapped_income = self._account('958110', 'income')
        clearing = self._account('958111', 'asset_current')
        fiscal_position = self.env['account.fiscal.position'].with_company(self.company).create({
            'name': 'Gross operations mapped income', 'company_id': self.company.id,
            'account_ids': [Command.create({
                'account_src_id': self.income.id,
                'account_dest_id': mapped_income.id,
            })],
        })
        product = self.env['product.product'].with_company(self.company).create({
            'name': 'Gross operations POS service', 'type': 'service',
            'available_in_pos': True, 'list_price': 100,
            'property_account_income_id': self.income.id,
            'taxes_id': [Command.set(self.tax.ids)],
        })
        bank = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.assertTrue(bank)
        method = self.env['pos.payment.method'].with_company(self.company).create({
            'name': 'Gross operations POS bank', 'company_id': self.company.id,
            'journal_id': bank.id, 'receivable_account_id': self.receivable.id,
            'outstanding_account_id': clearing.id,
        })
        config = self.env['pos.config'].with_company(self.company).create({
            'name': 'Gross operations POS', 'company_id': self.company.id,
            'journal_id': self.sale_journal.id,
            'invoice_journal_id': self.sale_journal.id,
            'payment_method_ids': [Command.set(method.ids)],
        })
        config.open_ui()
        session = config.current_session_id
        session.set_opening_control(0, 'Gross operations POS test')
        payload = {
            'uuid': str(uuid4()), 'session_id': session.id,
            'company_id': self.company.id, 'partner_id': self.partner.id,
            'fiscal_position_id': fiscal_position.id,
            'state': 'paid', 'source': 'pos', 'to_invoice': False,
            'amount_total': 115, 'amount_tax': 15,
            'amount_paid': 115, 'amount_return': 0,
            'lines': [Command.create({
                'product_id': product.id, 'uuid': str(uuid4()),
                'qty': 1, 'price_unit': 100,
                'price_subtotal': 100, 'price_subtotal_incl': 115,
                'tax_ids': [Command.set(self.tax.ids)],
                'full_product_name': product.display_name,
            })],
            'payment_ids': [Command.create({
                'payment_method_id': method.id, 'amount': 115,
                'payment_date': fields.Datetime.now(),
            })],
        }
        order_id = self.env['pos.order'].with_company(self.company)._process_order(payload, False)
        order = self.env['pos.order'].browse(order_id)
        today = fields.Date.today()
        current_filters = self._filters([self.sale_journal.id])
        current_filters.update({
            'date_from': fields.Date.to_string(today),
            'date_to': fields.Date.to_string(today),
        })

        def current_snapshot():
            return self.report.get_source_snapshot(current_filters)

        first = current_snapshot()
        self.assertEqual(self._row(first, 'income')['amount'], '115.00')
        self.assertEqual(first['periods'][0]['accounts']['income'][0]['account_id'],
                         mapped_income.id)
        session.action_pos_session_closing_control()
        order.with_context(generate_pdf=False).action_pos_order_invoice()
        after_invoice = current_snapshot()
        self.assertEqual(self._row(after_invoice, 'income')['amount'], '115.00')
        self.assertEqual(after_invoice['periods'][0]['excluded']['linked_pos_invoice'], 1)
        config.open_ui()
        refund_session = config.current_session_id
        refund_session.set_opening_control(0, 'Gross operations refund test')
        refund = order._refund()
        self.env['pos.payment'].with_company(self.company).create({
            'pos_order_id': refund.id, 'payment_method_id': method.id,
            'amount': -115,
        })
        refund._compute_prices()
        refund.action_pos_order_paid()
        refund.with_context(generate_pdf=False).action_pos_order_invoice()
        after_refund = current_snapshot()
        self.assertEqual(self._row(after_refund, 'income')['amount'], '0.00')
        self.assertEqual(after_refund['periods'][0]['excluded']['linked_pos_invoice'], 2)
        self.assertEqual(after_refund['periods'][0]['accounts']['income'][0]['source_count'], 2)

        # The invoices remain in today's period, but their original POS
        # operations have moved outside it. Hiding one old order must fail
        # closed rather than allowing its invoice to become a second sale.
        older = fields.Datetime.now() - timedelta(days=1)
        (order | refund).write({'date_order': older})
        invoice_only = current_snapshot()
        self.assertEqual(self._row(invoice_only, 'income')['amount'], '0.00')
        self.assertEqual(invoice_only['periods'][0]['excluded']['linked_pos_invoice'], 2)
        reader = self.env['res.users'].create({
            'name': 'Gross operations POS link reader',
            'login': 'gross_operations_pos_link_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_manager').id,
                self.env.ref('point_of_sale.group_pos_manager').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured = self.report.with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(
            self._row(secured.get_source_snapshot(current_filters), 'income')['amount'],
            '0.00',
        )
        rule = self.env['ir.rule'].create({
            'name': 'Gross operations hide older linked POS order',
            'model_id': self.env['ir.model']._get('pos.order').id,
            'domain_force': f"[('id', '!=', {order.id})]",
        })
        try:
            rule.flush_recordset()
            self.assertFalse(secured.env['pos.order'].search([('id', '=', order.id)]))
            with self.assertRaises(AccessError):
                secured.get_source_snapshot(current_filters)
        finally:
            rule.unlink()
