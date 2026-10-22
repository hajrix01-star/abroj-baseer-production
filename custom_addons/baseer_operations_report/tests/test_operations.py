"""Narrow G5 evidence for the incomplete gross-operations source slice."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from pytz import UTC, timezone

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOperationsGrossCalculator(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.partner_id.tz = 'UTC'
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
        selected_report = report if report is not None else self.report
        return selected_report._build_source_snapshot(self._filters(journal_ids))

    @staticmethod
    def _row(snapshot, key):
        return next(row for row in snapshot['periods'][0]['rows'] if row['key'] == key)

    def _empty_native_pos_order(self, session=None):
        if session is None:
            bank = self.env['account.journal'].search([
                ('company_id', '=', self.company.id), ('type', '=', 'bank'),
            ], limit=1)
            self.assertTrue(bank)
            clearing = self._account('958141', 'asset_current', True)
            method = self.env['pos.payment.method'].with_company(self.company).create({
                'name': 'Empty native source payment guard',
                'company_id': self.company.id, 'journal_id': bank.id,
                'receivable_account_id': self.receivable.id,
                'outstanding_account_id': clearing.id,
            })
            config = self.env['pos.config'].with_company(self.company).create({
                'name': 'Gross operations empty native order',
                'company_id': self.company.id,
                'journal_id': self.sale_journal.id,
                'invoice_journal_id': self.sale_journal.id,
                'payment_method_ids': [Command.set(method.ids)],
            })
            session = self.env['pos.session'].create({'config_id': config.id})
            session.set_opening_control(0, 'Empty native source regression')
        return self.env['pos.order'].with_company(self.company).create({
            'session_id': session.id, 'company_id': self.company.id,
            'partner_id': self.partner.id, 'state': 'paid', 'source': 'pos',
            'date_order': '2041-06-10 12:00:00',
            'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0,
            'amount_return': 0, 'lines': [], 'payment_ids': [],
        })

    def test_empty_zero_native_pos_has_no_financial_event(self):
        order = self._empty_native_pos_order()
        snapshot = self.report.get_source_snapshot(self._filters())
        self.assertTrue(snapshot['complete'])
        self.assertEqual(self._row(snapshot, 'income')['amount'], '0.00')
        self.assertTrue(all(not items for items in snapshot['periods'][0]['accounts'].values()))
        self.assertEqual(snapshot['periods'][0]['excluded']['empty_zero_native_pos_orders'], 1)
        self.assertEqual(snapshot['periods'][0]['excluded']['census_pos_orders'], 1)
        self.assertFalse(order.lines)

    def test_empty_native_pos_rejects_each_nonzero_header(self):
        order = self._empty_native_pos_order()
        for field in ('amount_total', 'amount_tax', 'amount_paid', 'amount_return'):
            with self.subTest(field=field):
                order[field] = 1
                with self.assertRaises(AccessError):
                    self.report.get_source_snapshot(self._filters())
                order[field] = 0

    def _empty_order_payment(self, order):
        method = order.session_id.config_id.payment_method_ids[:1]
        return self.env['pos.payment'].create({
            'pos_order_id': order.id, 'payment_method_id': method.id, 'amount': 0,
        })

    def test_empty_native_pos_rejects_even_a_zero_payment(self):
        order = self._empty_native_pos_order()
        self._empty_order_payment(order)
        with self.assertRaises(AccessError):
            self.report.get_source_snapshot(self._filters())

    def test_empty_native_pos_proof_rejects_wrong_source_refund_currency_and_invoice(self):
        order = self._empty_native_pos_order()
        prove = self.report._is_proven_empty_native_pos_order
        self.assertTrue(prove(order, self.company, order.lines))
        with patch.object(type(order), 'source', 'baseer_summary'):
            self.assertFalse(prove(order, self.company, order.lines))
        with patch.object(type(order), 'is_refund', True):
            self.assertFalse(prove(order, self.company, order.lines))
        other_currency = self.env['res.currency'].with_context(active_test=False).search([
            ('id', '!=', self.company.currency_id.id),
        ], limit=1)
        self.assertTrue(other_currency)
        with patch.object(type(order), 'currency_id', other_currency):
            self.assertFalse(prove(order, self.company, order.lines))
        order.account_move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'journal_id': self.sale_journal.id,
            'partner_id': self.partner.id, 'invoice_date': fields.Date.today(),
        })
        self.assertFalse(prove(order, self.company, order.lines))
        with self.assertRaises(AccessError):
            self.report.get_source_snapshot(self._filters())

    def test_empty_native_pos_rejects_reversal_link(self):
        order = self._empty_native_pos_order()
        reversal = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.sale_journal.id,
            'date': '2041-06-10',
        })
        reversal[order._fields['reversed_move_ids'].inverse_name] = order.id
        self.assertFalse(self.report._is_proven_empty_native_pos_order(
            order, self.company, order.lines,
        ))
        with self.assertRaises(AccessError):
            self.report.get_source_snapshot(self._filters())

    def _native_global_rounding_order(self, session=None):
        self.company.tax_calculation_rounding_method = 'round_globally'
        order = self._empty_native_pos_order(session)
        product = self.env['product.product'].create({
            'name': 'Global rounding source service', 'type': 'service',
            'available_in_pos': True, 'property_account_income_id': self.income.id,
            'taxes_id': [Command.set(self.tax.ids)],
        })
        order.write({
            'amount_total': .09, 'amount_tax': .01, 'amount_paid': .09,
            'lines': [Command.create({
                'product_id': product.id, 'uuid': str(uuid4()), 'qty': 1,
                'price_unit': .02, 'price_subtotal': .02,
                'price_subtotal_incl': .02, 'full_product_name': product.display_name,
                'tax_ids': [Command.set(self.tax.ids)],
            }) for _ in range(4)],
        })
        return order

    def test_native_global_rounding_uses_proven_order_allocations(self):
        order = self._native_global_rounding_order()
        self.assertEqual(sum(Decimal(str(line.price_subtotal_incl)) for line in order.lines),
                         Decimal('.08'))
        snapshot = self.report.get_source_snapshot(self._filters())
        self.assertTrue(snapshot['complete'])
        self.assertEqual(self._row(snapshot, 'income')['amount'], '0.09')
        sections, _excluded = self.report._period_sources(
            self.company, fields.Date.to_date('2041-06-01'),
            fields.Date.to_date('2041-06-30'), [],
        )
        events = sections['income'][self.income.id]['events']
        self.assertEqual(len(events), 4)
        self.assertEqual(sum(event['amount'] for event in events), Decimal('.09'))

    def test_native_global_rounding_rejects_changed_header_or_tax(self):
        order = self._native_global_rounding_order()
        for field, correct in (('amount_total', .09), ('amount_tax', .01)):
            with self.subTest(field=field):
                order[field] = correct + .01
                with self.assertRaises(AccessError):
                    self.report.get_source_snapshot(self._filters())
                order[field] = correct

    def test_native_global_rounding_refund_reverses_exact_allocations(self):
        order = self._native_global_rounding_order()
        refund = order._refund()
        refund.write({'state': 'paid', 'date_order': order.date_order})
        self.assertTrue(refund.is_refund)
        self.assertEqual(Decimal(str(refund.amount_total)), Decimal('-.09'))
        snapshot = self.report.get_source_snapshot(self._filters())
        self.assertTrue(snapshot['complete'])
        self.assertEqual(self._row(snapshot, 'income')['amount'], '0.00')
        self.assertEqual(snapshot['periods'][0]['excluded']['native_pos_tax_rounding'], 2)

    def test_native_global_rounding_rejects_changed_or_compensated_line_cache(self):
        order = self._native_global_rounding_order()
        first, second = order.lines[:2]
        first.price_subtotal_incl = .03
        # Matching the order header is not enough to prove individual lines.
        with self.assertRaises(AccessError):
            self.report.get_source_snapshot(self._filters())
        second.price_subtotal_incl = .01
        with self.assertRaises(AccessError):
            self.report.get_source_snapshot(self._filters())

    def _empty_native_reader(self):
        user = self.env['res.users'].create({
            'name': 'Native source guarded reader',
            'login': 'native_source_guarded_reader',
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_manager').id,
                self.env.ref('point_of_sale.group_pos_manager').id,
            ])],
        })
        return self.report.with_user(user).with_context(allowed_company_ids=self.company.ids)

    def test_empty_native_pos_rejects_hidden_payment_and_reversal(self):
        order = self._empty_native_pos_order()
        payment = self._empty_order_payment(order)
        reversal = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.sale_journal.id,
            'date': '2041-06-10',
        })
        inverse = order._fields['reversed_move_ids'].inverse_name
        secured = self._empty_native_reader()
        for model, record in (('pos.payment', payment), ('account.move', reversal)):
            if model == 'account.move':
                payment.unlink()
                reversal[inverse] = order.id
            rule = self.env['ir.rule'].create({
                'name': 'Hide empty native source link',
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {record.id})]",
            })
            try:
                secured.env.invalidate_all()
                self.assertFalse(secured.env[model].search([('id', '=', record.id)]))
                with self.assertRaises(AccessError):
                    secured.get_source_snapshot(self._filters())
            finally:
                rule.unlink()

    def test_native_global_rounding_rejects_hidden_line_and_tax(self):
        order = self._native_global_rounding_order()
        secured = self._empty_native_reader()
        for model, record in (('pos.order.line', order.lines[:1]), ('account.tax', self.tax)):
            rule = self.env['ir.rule'].create({
                'name': 'Hide native global-rounding source',
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {record.id})]",
            })
            try:
                secured.env.invalidate_all()
                with self.assertRaises(AccessError):
                    secured.get_source_snapshot(self._filters())
            finally:
                rule.unlink()

    def test_empty_native_pos_and_real_sale_share_a_closed_session(self):
        empty = self._empty_native_pos_order()
        order = self._native_global_rounding_order(empty.session_id)
        now = fields.Datetime.now()
        empty.date_order = order.date_order = now
        payment = self._empty_order_payment(order)
        payment.amount = .09
        order.session_id.action_pos_session_closing_control()
        self.assertEqual(order.session_id.state, 'closed')
        self.assertEqual(order.session_id.move_id.state, 'posted')
        day = fields.Date.to_string(fields.Date.today())
        filters = {**self._filters(), 'date_from': day, 'date_to': day}
        snapshot = self.report.get_source_snapshot(filters)
        self.assertTrue(snapshot['complete'])
        self.assertEqual(self._row(snapshot, 'income')['amount'], '0.09')
        self.assertEqual(snapshot['periods'][0]['excluded']['empty_zero_native_pos_orders'], 1)
        self.assertEqual(snapshot['periods'][0]['excluded']['direct_aml_unproven'], 0)

    def test_pos_tax_rounding_accepts_only_bounded_multiline_difference(self):
        consistent = self.report._pos_totals_consistent
        gross, net, tax, total = map(
            Decimal, ('53.00', '46.08', '6.91', '53.00'),
        )
        cent = Decimal('0.01')
        self.assertTrue(consistent(gross, net, tax, total, 1, 2, cent))
        self.assertTrue(consistent(gross, net, -tax, -total, -1, 2, cent))
        self.assertFalse(consistent(gross, net, tax, total, 1, 1, cent))
        self.assertFalse(consistent(gross, Decimal('46.07'), tax, total,
                                    1, 2, cent))
        self.assertFalse(consistent(gross, Decimal('46.07'), tax, total,
                                    1, 100, cent))
        self.assertFalse(consistent(gross, net, tax, Decimal('53.01'),
                                    1, 2, cent))

    def test_unknown_asset_funding_remains_unproven(self):
        asset = self._account('958121', 'asset_current')
        journal = self._journal('general', 'GOA')
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': journal.id,
            'date': '2041-06-10',
            'line_ids': [Command.create({'account_id': asset.id, 'debit': 1}),
                         Command.create({'account_id': self.cash.id, 'credit': 1})],
        })
        move.action_post()
        excluded = self.report._liquidity_outflow_exclusions(
            self.company, fields.Date.to_date('2041-06-01'),
            fields.Date.to_date('2041-06-30'), [journal.id], {},
        )
        self.assertEqual(excluded['unproven_liquidity_outflow'], 1)
        self.assertFalse(self.report._coverage_complete(excluded))

    def test_native_representative_advance_excluded_without_hiding_amount_mismatch(self):
        model = 'baseer.procurement.representative.advance'
        if model not in self.env:
            self.skipTest('Optional procurement source is not installed in this test database')
        asset = self._account('958122', 'asset_current', True)
        bank = self._journal('bank', 'GOF')
        bank.default_account_id = self.cash
        self.company.write({
            'baseer_procurement_representative_petty_cash_account_id': asset.id,
            'baseer_procurement_representative_petty_cash_payment_journal_ids':
                [Command.link(bank.id)],
        })
        representative = self.env['res.partner'].with_company(self.company).create({
            'name': 'Gross operations source representative',
            'company_id': self.company.id, 'is_purchase_representative': True,
        })
        product = self.env['product.product'].create({
            'name': 'Source funding material', 'company_id': self.company.id,
        })
        option = self.env['baseer.procurement.purchase.option'].create({
            'name': 'Source funding unit', 'company_id': self.company.id,
            'product_id': product.id, 'uom_id': product.uom_id.id,
        })
        request = self.env['baseer.procurement.request'].create({
            'company_id': self.company.id,
            'warehouse_id': self.env['stock.warehouse'].search([
                ('company_id', '=', self.company.id),
            ], limit=1).id,
            'representative_partner_id': representative.id,
            'line_ids': [Command.create({
                'option_id': option.id, 'requested_qty': 1, 'requested_price': 1,
            })],
        })
        # Exercise the real transition with an authorized synthetic requester.
        requester = self.env['res.users'].create({
            'name': 'Source funding requester', 'login': 'source_funding_requester',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('baseer_procurement_requests.group_procurement_user').id,
            ])],
        })
        request.with_user(requester).with_context(
            allowed_company_ids=self.company.ids,
        ).action_mark_sent()
        for documented_amount, expected in ((1, True), (2, False)):
            move = self.env['account.move'].create({
                'move_type': 'entry', 'journal_id': self.sale_journal.id,
                'date': '2041-06-10',
                'line_ids': [Command.create({'account_id': asset.id, 'debit': 1}),
                             Command.create({'account_id': self.cash.id, 'credit': 1})],
            })
            move.action_post()
            self.env[model].sudo().with_context(
                baseer_representative_petty_cash_internal=True,
            ).create({
                'company_id': self.company.id, 'movement_type': 'funding',
                'representative_partner_id': representative.id,
                'procurement_request_id': request.id,
                'payment_journal_id': bank.id, 'movement_date': '2041-06-10',
                'amount': documented_amount, 'move_id': move.id,
                'client_token': str(uuid4()),
            })
            liquidity = move.line_ids.filtered(lambda line: line.account_id == self.cash)
            self.assertEqual(self.report._is_proven_representative_advance(
                self.company, liquidity, move.line_ids), expected)

    def test_month_caption_uses_server_period_label(self):
        snapshot = self.report._build_source_snapshot({
            'company_id': self.company.id,
            'period': {'kind': 'month', 'anchor_date': '2041-06-15',
                       'direction': 0},
            'comparison': {'kind': 'none', 'order': 'descending'},
            'journal_ids': [],
        })
        self.assertEqual(
            snapshot['periods'][0]['display_label'],
            snapshot['period_controls']['options'][0]['display_label'],
        )

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
        # Posting an unpaid vendor bill is no longer a purchase cash event.
        self.assertEqual(self._row(snapshot, 'cost_of_sales')['amount'], '0.00')
        self.assertEqual(self._row(snapshot, 'expense')['amount'], '0.00')
        self.assertEqual(self._row(snapshot, 'other_income')['amount'], '80.00')
        self.assertEqual(self._row(snapshot, 'gross_profit')['amount'], '51.75')
        self.assertEqual(self._row(snapshot, 'net_income')['amount'], '131.75')
        income_accounts = snapshot['periods'][0]['accounts']['income']
        self.assertEqual(len(income_accounts), 1)
        self.assertEqual(income_accounts[0]['account_id'], self.income.id)
        self.assertEqual(income_accounts[0]['amount'], '51.75')
        details = self.report._build_account_events(
            self._filters(), 'income', self.income.id,
            snapshot['periods'][0]['key'], income_accounts[0]['fingerprint'],
        )
        self.assertEqual(details['amount'], '51.75')
        self.assertEqual(details['total_count'], 3)
        self.assertEqual(sum((Decimal(event['amount'].replace(',', ''))
                              for event in details['events']), Decimal('0')),
                         Decimal('51.75'))
        self.assertEqual({event['date'] for event in details['events']},
                         {'2041-06-10'})
        with self.assertRaises(ValidationError):
            self.report._build_account_events(
                self._filters(), 'expense', self.income.id,
                snapshot['periods'][0]['key'], income_accounts[0]['fingerprint'],
            )
        with self.assertRaises(ValidationError):
            self.report._build_account_events(
                self._filters([self.sale_journal.id]), 'income', self.income.id,
                snapshot['periods'][0]['key'], income_accounts[0]['fingerprint'],
            )
        self._invoice('out_invoice', self.sale_journal, [
            ('New sale after snapshot', self.income, 10, 0, False),
        ])
        with self.assertRaises(ValidationError):
            self.report._build_account_events(
                self._filters(), 'income', self.income.id,
                snapshot['periods'][0]['key'], income_accounts[0]['fingerprint'],
            )

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
        self.assertEqual(self._row(snapshot, 'cost_of_sales')['amount'], '0.00')
        self.assertEqual(self._row(snapshot, 'expense')['amount'], '0.00')
        self.assertFalse(snapshot['periods'][0]['accounts']['cost_of_sales'])
        self.assertFalse(snapshot['periods'][0]['accounts']['expense'])
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
        self.assertFalse(snapshot['periods'][0]['coverage_complete'])

    def test_customer_invoice_issue_and_accounting_dates_are_distinct_sources(self):
        invoice = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id,
            'journal_id': self.sale_journal.id,
            'invoice_date': '2041-06-10', 'date': '2041-07-02',
            'invoice_line_ids': [Command.create({
                'name': 'Issued before accounting date', 'quantity': 1,
                'price_unit': 100, 'account_id': self.income.id,
                'tax_ids': [Command.set(self.tax.ids)],
            })],
        })
        invoice.action_post()
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(str(invoice.invoice_date), '2041-06-10')
        self.assertEqual(str(invoice.date), '2041-07-02')
        june_by_issue = self.env['account.move'].search([
            ('id', '=', invoice.id), ('state', '=', 'posted'),
            ('invoice_date', '>=', '2041-06-01'),
            ('invoice_date', '<=', '2041-06-30'),
        ])
        june_by_entry = self.env['account.move'].search([
            ('id', '=', invoice.id), ('state', '=', 'posted'),
            ('date', '>=', '2041-06-01'), ('date', '<=', '2041-06-30'),
        ])
        self.assertEqual(june_by_issue, invoice)
        self.assertFalse(june_by_entry)
        invoice.flush_recordset(['invoice_date', 'date'])
        self.env.cr.execute(
            'SELECT invoice_date, date FROM account_move WHERE id = %s',
            [invoice.id],
        )
        issue_day, entry_day = self.env.cr.fetchone()
        self.assertEqual(str(issue_day), '2041-06-10')
        self.assertEqual(str(entry_day), '2041-07-02')
        june = self.report._build_source_snapshot(self._filters())
        july_filters = self._filters()
        july_filters.update({'date_from': '2041-07-01', 'date_to': '2041-07-31'})
        july = self.report._build_source_snapshot(july_filters)
        self.assertEqual(self._row(june, 'income')['amount'], '115.00')
        self.assertEqual(self._row(july, 'income')['amount'], '0.00')
        sections, _excluded = self.report._period_sources(
            self.company, fields.Date.to_date('2041-06-01'),
            fields.Date.to_date('2041-06-30'), [],
        )
        event = sections['income'][self.income.id]['events'][0]
        self.assertEqual((event['source_model'], event['source_id']),
                         ('account.move', invoice.id))
        self.assertEqual((event['line_model'], event['line_id']),
                         ('account.move.line', invoice.invoice_line_ids.id))
        self.assertEqual(event['date'], '2041-06-10')
        self.assertEqual(event['amount'], Decimal('115.00'))

    def test_sales_receipt_source_shape_before_reusing_invoice_calculator(self):
        """Prove Odoo's posted receipt uses the same 100 + recorded VAT 15 evidence."""
        receipt = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_receipt', 'partner_id': self.partner.id,
            'journal_id': self.sale_journal.id,
            'invoice_date': '2041-06-10', 'date': '2041-07-02',
            'invoice_line_ids': [Command.create({
                'name': 'Issued sales receipt', 'quantity': 1,
                'price_unit': 100, 'account_id': self.income.id,
                'tax_ids': [Command.set(self.tax.ids)],
            })],
        })
        receipt.action_post()
        self.assertEqual(receipt.state, 'posted')
        self.assertEqual(str(receipt.invoice_date), '2041-06-10')
        self.assertEqual(str(receipt.date), '2041-07-02')
        self.assertEqual(Decimal(str(receipt.amount_total)), Decimal('115.00'))
        line = receipt.invoice_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(Decimal(str(line.balance)), Decimal('-100.00'))
        base_lines, _tax_lines = receipt._get_rounded_base_and_tax_lines()
        self.env['account.tax']._add_accounting_data_in_base_lines_tax_details(
            base_lines, self.company,
        )
        base = next(item for item in base_lines if item['record'] == line)
        details = base['tax_details']
        self.assertEqual(Decimal(str(details['total_excluded'])), Decimal('100.00'))
        self.assertEqual(sum((Decimal(str(item['tax_amount']))
                              for item in details['taxes_data']), Decimal('0')),
                         Decimal('15.00'))
        tax_lines = receipt.line_ids.filtered('tax_line_id')
        self.assertEqual(sum((Decimal(str(item.credit - item.debit))
                              for item in tax_lines), Decimal('0')),
                         Decimal('15.00'))

    def test_approved_app_summary_uses_business_day_not_synthetic_utc_time(self):
        company = self.env['res.company'].create({
            'name': 'Gross operations app timing company',
        })
        wizard_action = company.action_baseer_open_onboarding()
        wizard = self.env[wizard_action['res_model']].browse(wizard_action['res_id'])
        wizard.write({'sales_mode': 'summary', 'setup_summary_jahez': True})
        wizard.action_apply_selected()
        company.partner_id.tz = 'Pacific/Honolulu'
        scoped = self.env['baseer.pos.summary'].with_context(
            allowed_company_ids=[company.id],
        ).with_company(company)
        config = scoped.env['pos.config'].search([
            ('company_id', '=', company.id),
            ('baseer_summary_only', '=', True),
        ], limit=1)
        platform = config.payment_method_ids.filtered(
            lambda method: method.baseer_category_id.kind == 'platform',
        )
        self.assertEqual(len(platform), 1)
        business_day = fields.Date.today() - timedelta(days=1)
        summary = scoped.create({
            'company_id': company.id, 'config_id': config.id,
            'business_date': business_day, 'period_scope': 'all',
            'day_schedule': 'all', 'customer_count': 1,
            'allocation_ids': [Command.create({
                'payment_method_id': platform.id, 'amount': 115,
            })],
        })
        summary.action_approve()
        self.assertEqual(summary.state, 'approved')
        self.assertEqual(summary.order_id.source, 'baseer_summary')
        local_synthetic_day = fields.Datetime.context_timestamp(
            summary.order_id.with_context(tz='Pacific/Honolulu'),
            summary.order_id.date_order,
        ).date()
        self.assertEqual(local_synthetic_day, business_day - timedelta(days=1))
        zero_day = scoped.create({
            'company_id': company.id, 'config_id': config.id,
            'business_date': local_synthetic_day, 'period_scope': 'all',
            'day_schedule': 'all', 'zero_sales': True,
            'customer_count': 0, 'allocation_ids': [],
        })
        zero_day.action_approve()
        self.assertEqual(zero_day.state, 'approved')
        self.assertFalse(zero_day.order_id)
        report = self.report.with_context(
            allowed_company_ids=[company.id],
        ).with_company(company)
        def at_day(day):
            return report._build_source_snapshot({
                'company_id': company.id,
                'date_from': fields.Date.to_string(day),
                'date_to': fields.Date.to_string(day),
                'journal_ids': [],
            })

        original = at_day(business_day)
        synthetic = at_day(local_synthetic_day)
        self.assertEqual(self._row(original, 'income')['amount'], '115.00')
        self.assertEqual(self._row(synthetic, 'income')['amount'], '0.00')
        summary_account = original['periods'][0]['accounts']['income'][0]
        summary_details = report._build_account_events(
            {'company_id': company.id,
             'date_from': fields.Date.to_string(business_day),
             'date_to': fields.Date.to_string(business_day),
             'journal_ids': []},
            'income', summary_account['account_id'],
            original['periods'][0]['key'], summary_account['fingerprint'],
        )
        self.assertEqual(summary_details['events'][0]['source_id'], summary.id)
        self.assertEqual(summary_details['events'][0]['date'],
                         fields.Date.to_string(business_day))
        sections, _excluded = report._period_sources(
            company, business_day, business_day, [],
        )
        events = [event for entry in sections['income'].values()
                  for event in entry['events']]
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]['source_model'], events[0]['source_id']),
                         ('baseer.pos.summary', summary.id))
        self.assertEqual(events[0]['line_id'], summary.order_id.lines.id)
        self.assertEqual(events[0]['date'], fields.Date.to_string(business_day))
        self.assertEqual(events[0]['amount'], Decimal('115.00'))
        other_company = self.report._build_source_snapshot({
            'company_id': self.company.id,
            'date_from': fields.Date.to_string(business_day),
            'date_to': fields.Date.to_string(business_day),
            'journal_ids': [],
        })
        self.assertEqual(self._row(other_company, 'income')['amount'], '0.00')
        self.assertNotEqual(
            report._local_utc_bounds(company, business_day, business_day),
            self.report._local_utc_bounds(
                self.company, business_day, business_day,
            ),
        )
        reader = self.env['res.users'].create({
            'name': 'Gross operations summary reader',
            'login': 'gross_operations_summary_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_manager').id,
                self.env.ref('point_of_sale.group_pos_manager').id,
            ])],
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
        })
        secured = report.with_user(reader)
        self.assertEqual(
            self._row(secured._build_source_snapshot({
                'company_id': company.id,
                'date_from': fields.Date.to_string(business_day),
                'date_to': fields.Date.to_string(business_day),
                'journal_ids': [],
            }), 'income')['amount'], '115.00',
        )
        for model in ('baseer.pos.summary', 'pos.order'):
            rule = self.env['ir.rule'].create({
                'name': 'Gross operations hide ' + model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {summary.id if model == 'baseer.pos.summary' else summary.order_id.id})]",
            })
            try:
                rule.flush_recordset()
                with self.assertRaises(AccessError):
                    secured._build_source_snapshot({
                        'company_id': company.id,
                        'date_from': fields.Date.to_string(business_day),
                        'date_to': fields.Date.to_string(business_day),
                        'journal_ids': [],
                    })
            finally:
                rule.unlink()

    def test_company_timezone_prefers_partner_then_calendar(self):
        calendar = self.company.resource_calendar_id
        if not calendar:
            calendar = self.env['resource.calendar'].with_company(self.company).create({
                'name': 'Gross operations company calendar',
                'company_id': self.company.id, 'tz': 'Asia/Riyadh',
            })
            self.company.resource_calendar_id = calendar
        calendar.tz = 'Asia/Riyadh'
        self.company.partner_id.tz = False
        lower, _upper = self.report._local_utc_bounds(
            self.company, fields.Date.to_date('2041-07-01'),
            fields.Date.to_date('2041-07-01'),
        )
        self.assertEqual(str(lower), '2041-06-30 21:00:00')
        self.company.partner_id.tz = 'Pacific/Honolulu'
        lower, _upper = self.report._local_utc_bounds(
            self.company, fields.Date.to_date('2041-07-01'),
            fields.Date.to_date('2041-07-01'),
        )
        self.assertEqual(str(lower), '2041-07-01 10:00:00')
        self.company.partner_id.tz = False
        self.company.resource_calendar_id = False
        with self.assertRaises(AccessError):
            self.report._local_utc_bounds(
                self.company, fields.Date.to_date('2041-07-01'),
                fields.Date.to_date('2041-07-01'),
            )
        self.company.resource_calendar_id = calendar
        self.env.cr.execute(
            'UPDATE res_partner SET tz=%s WHERE id=%s',
            ['Not/A_Timezone', self.company.partner_id.id],
        )
        self.company.partner_id.invalidate_recordset(['tz'])
        with self.assertRaises(AccessError):
            self.report._local_utc_bounds(
                self.company, fields.Date.to_date('2041-07-01'),
                fields.Date.to_date('2041-07-01'),
            )

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
        visible = self._snapshot(report=secured)
        self.assertEqual(self._row(visible, 'income')['amount'], '115.00')
        fingerprint = visible['periods'][0]['accounts']['income'][0]['fingerprint']
        self.assertEqual(secured._build_account_events(
            self._filters(), 'income', self.income.id,
            visible['periods'][0]['key'], fingerprint,
        )['amount'], '115.00')
        rule = self.env['ir.rule'].create({
            'name': 'Gross operations hide source invoice',
            'model_id': self.env['ir.model']._get('account.move').id,
            'domain_force': f"[('id', '!=', {invoice.id})]",
        })
        try:
            rule.flush_recordset()
            self.assertFalse(secured.env['account.move'].search([('id', '=', invoice.id)]))
            self.env['account.move'].flush_model([
                'company_id', 'state', 'move_type', 'date',
            ])
            self.env.cr.execute(
                "SELECT id FROM account_move WHERE id=%s AND company_id=%s "
                "AND state='posted' AND move_type='out_invoice' "
                'AND date >= %s AND date <= %s',
                [invoice.id, self.company.id, '2041-06-01', '2041-06-30'],
            )
            self.assertEqual(self.env.cr.fetchone()[0], invoice.id)
            with self.assertRaises(AccessError):
                self._snapshot(report=secured)
            with self.assertRaises(AccessError):
                secured._build_account_events(
                    self._filters(), 'income', self.income.id,
                    visible['periods'][0]['key'], fingerprint,
                )
        finally:
            rule.unlink()
        other = self.env['res.company'].create({'name': 'Other gross operations company'})
        with self.assertRaises(AccessError):
            self.report._build_source_snapshot({**self._filters(), 'company_id': other.id})
        with self.assertRaises(AccessError):
            self.report._build_account_events(
                {**self._filters(), 'company_id': other.id},
                'income', self.income.id, visible['periods'][0]['key'], fingerprint,
            )

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
            return self.report._build_source_snapshot(current_filters)

        first = current_snapshot()
        self.assertEqual(self._row(first, 'income')['amount'], '115.00')
        self.assertEqual(first['periods'][0]['accounts']['income'][0]['account_id'],
                         mapped_income.id)
        session.action_pos_session_closing_control()
        order.with_context(generate_pdf=False).action_pos_order_invoice()
        after_invoice = current_snapshot()
        self.assertEqual(self._row(after_invoice, 'income')['amount'], '115.00')
        self.assertEqual(after_invoice['periods'][0]['excluded'].get('direct_aml_unproven', 0), 0)
        reversal_income = order.reversed_move_ids.line_ids.filtered(
            lambda line: line.account_id == mapped_income)
        self.assertTrue(reversal_income)
        self.assertEqual(self.report._proven_pos_invoice_reversal_lines(
            self.company, reversal_income), set(reversal_income.ids))
        # Merely attaching an unrelated balanced entry must not prove it.
        malformed = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.sale_journal.id,
            'date': today,
            'line_ids': [Command.create({
                'account_id': self.other_income.id, 'debit': 115,
            }), Command.create({
                'account_id': self.receivable.id, 'partner_id': self.partner.id,
                'credit': 115,
            })],
        })
        malformed.action_post()
        reversal_inverse = order._fields['reversed_move_ids'].inverse_name
        malformed.write({reversal_inverse: order.id})
        self.assertEqual(self.report._proven_pos_invoice_reversal_lines(
            self.company, malformed.line_ids), set())
        malformed.write({reversal_inverse: False})
        malformed.button_draft()
        malformed.unlink()
        self.assertEqual(after_invoice['periods'][0]['excluded']['linked_pos_invoice'], 1)
        self.assertGreater(
            after_invoice['periods'][0]['excluded']['pos_session_income_not_readded'], 0,
        )
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
        pos_account = after_refund['periods'][0]['accounts']['income'][0]
        pos_details = self.report._build_account_events(
            current_filters, 'income', mapped_income.id,
            after_refund['periods'][0]['key'], pos_account['fingerprint'],
        )
        self.assertEqual(pos_details['total_count'], 2)
        self.assertEqual({event['source_id'] for event in pos_details['events']},
                         {order.id, refund.id})
        sections, _excluded = self.report._period_sources(
            self.company, today, today, [self.sale_journal.id],
        )
        events = sections['income'][mapped_income.id]['events']
        self.assertEqual({event['source_id'] for event in events},
                         {order.id, refund.id})
        self.assertEqual({event['source_model'] for event in events}, {'pos.order'})
        self.assertEqual({event['date'] for event in events},
                         {fields.Date.to_string(today)})
        self.assertEqual(sum((event['amount'] for event in events), Decimal('0')),
                         Decimal('0'))

        # The invoices remain in today's period, but their original POS
        # operations have moved outside it. Hiding one old order must fail
        # closed rather than allowing its invoice to become a second sale.
        older = fields.Datetime.now() - timedelta(days=1)
        (order | refund).write({'date_order': older})
        invoice_only = current_snapshot()
        self.assertEqual(self._row(invoice_only, 'income')['amount'], '0.00')
        self.assertEqual(invoice_only['periods'][0]['excluded']['linked_pos_invoice'], 2)
        # The linked invoice must not hide an older POS order whose current
        # source classification would produce a different gross event sum.
        original_income_account = product.property_account_income_id
        product.property_account_income_id = self.expense
        try:
            with self.assertRaises(AccessError):
                current_snapshot()
        finally:
            product.property_account_income_id = original_income_account
        self.assertEqual(self._row(current_snapshot(), 'income')['amount'], '0.00')
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
            self._row(secured._build_source_snapshot(current_filters), 'income')['amount'],
            '0.00',
        )
        hidden_config = self.env['ir.rule'].create({
            'name': 'Gross operations hide POS configuration after source day',
            'model_id': self.env['ir.model']._get('pos.config').id,
            'domain_force': f"[('id', '!=', {config.id})]",
        })
        try:
            hidden_config.flush_recordset()
            self.assertFalse(secured.env['pos.config'].search([('id', '=', config.id)]))
            with self.assertRaises(AccessError):
                secured._direct_exclusions(
                    self.company, today, today, [self.sale_journal.id],
                )
        finally:
            hidden_config.unlink()
        rule = self.env['ir.rule'].create({
            'name': 'Gross operations hide older linked POS order',
            'model_id': self.env['ir.model']._get('pos.order').id,
            'domain_force': f"[('id', '!=', {order.id})]",
        })
        try:
            rule.flush_recordset()
            self.assertFalse(secured.env['pos.order'].search([('id', '=', order.id)]))
            with self.assertRaises(AccessError):
                secured._build_source_snapshot(current_filters)
        finally:
            rule.unlink()
        # The UTC date is still June 30, but the company's Riyadh business
        # date is July 1.  This is source characterization, not calculator GO.
        self.company.partner_id.tz = 'Asia/Riyadh'
        order.date_order = '2041-06-30 21:30:00'
        local_day = fields.Datetime.context_timestamp(
            order.with_context(tz='Asia/Riyadh'), order.date_order,
        ).date()
        self.assertEqual(str(order.date_order.date()), '2041-06-30')
        self.assertEqual(str(local_day), '2041-07-01')
        local_tz = timezone('Asia/Riyadh')
        july_start_utc = local_tz.localize(
            datetime(2041, 7, 1), is_dst=None,
        ).astimezone(UTC).replace(tzinfo=None)
        august_start_utc = local_tz.localize(
            datetime(2041, 8, 1), is_dst=None,
        ).astimezone(UTC).replace(tzinfo=None)
        self.assertEqual(str(july_start_utc), '2041-06-30 21:00:00')
        native_july = self.env['pos.order'].search([
            ('id', '=', order.id), ('source', '=', 'pos'),
            ('date_order', '>=', july_start_utc),
            ('date_order', '<', august_start_utc),
        ])
        self.assertEqual(native_july, order)
        order.flush_recordset(['date_order'])
        self.env.cr.execute(
            'SELECT id FROM pos_order WHERE id = %s AND source = %s '
            'AND date_order >= %s AND date_order < %s',
            [order.id, 'pos', july_start_utc, august_start_utc],
        )
        self.assertEqual([row[0] for row in self.env.cr.fetchall()], [order.id])
        july_filters = self._filters([self.sale_journal.id])
        july_filters.update({'date_from': '2041-07-01', 'date_to': '2041-07-31'})
        july = self.report._build_source_snapshot(july_filters)
        self.assertEqual(self._row(july, 'income')['amount'], '115.00')
        july_sections, _excluded = self.report._period_sources(
            self.company, fields.Date.to_date('2041-07-01'),
            fields.Date.to_date('2041-07-31'), [self.sale_journal.id],
        )
        july_event = july_sections['income'][mapped_income.id]['events'][0]
        self.assertEqual((july_event['source_id'], july_event['date']),
                         (order.id, '2041-07-01'))
        june_filters = self._filters([self.sale_journal.id])
        june = self.report._build_source_snapshot(june_filters)
        self.assertEqual(self._row(june, 'income')['amount'], '0.00')
