"""Stored header collection: signed amounts, source census and reader rules."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from . import test_native_preparation, test_operations


@tagged('post_install', '-at_install', 'operations_owner_sales')
class TestOperationsOwnerSales(TransactionCase):
    # Compose only fixture builders; never inherit another test suite.
    _account = test_native_preparation.TestOperationsNativePreparation._account
    _journal = test_native_preparation.TestOperationsNativePreparation._journal
    _tax = test_native_preparation.TestOperationsNativePreparation._tax
    _empty_native_reader = test_native_preparation.TestOperationsNativePreparation._empty_native_reader
    _empty_native_pos_order = test_native_preparation.TestOperationsNativePreparation._empty_native_pos_order
    _native_global_rounding_order = test_native_preparation.TestOperationsNativePreparation._native_global_rounding_order
    _empty_order_payment = test_native_preparation.TestOperationsNativePreparation._empty_order_payment
    _order = test_native_preparation.TestOperationsNativePreparation._order
    _invoice = test_operations.TestOperationsGrossCalculator._invoice

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.partner_id.tz = 'UTC'
        self.report = self.env['baseer.operations.report']
        self.receivable = self._account('953101', 'asset_receivable', True)
        self.payable = self._account('953102', 'liability_payable', True)
        self.income = self._account('953103', 'income')
        self.tax_account = self._account('953104', 'liability_current')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Stored owner sales synthetic partner',
            'property_account_receivable_id': self.receivable.id,
            'property_account_payable_id': self.payable.id,
        })
        self.sale_journal = self._journal('sale', 'OSH')
        self.tax = self._tax('sale', self.tax_account)
        self.tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax').account_id = self.tax_account
        self.day = fields.Date.to_date('2041-06-10')

    def _sale(self, session=None):
        order = self._order(session, taxed=True)
        order.date_order = '2041-06-10 12:00:00'
        return order

    def _read(self, report=None, journal_ids=None):
        selected = self.report if report is None else report
        return selected._owner_sales(self.company, self.day, self.day, journal_ids or [])

    def _customer_invoice(self, move_type='out_invoice', currency=None):
        return self._invoice(move_type, self.sale_journal, [
            ('Stored sales', self.income, 100, 0, self.tax),
        ], currency=currency)

    def _invoice_sale(self, sale):
        sale.with_context(generate_pdf=False).action_pos_order_invoice()
        invoice = sale.account_move
        # Native POS soft-post schedules future-dated invoices. This fixture
        # needs an actually posted invoice, not a scheduled draft.
        self.assertEqual(invoice.state, 'draft')
        invoice.write({'auto_post': 'no', 'invoice_date': self.day, 'date': self.day})
        invoice.action_post()
        self.assertEqual(invoice.state, 'posted')
        self.assertIn(invoice, self.report._invoice_records(self.company, self.day, self.day, []))
        self.assertIn(sale, invoice.pos_order_ids)
        return invoice

    def test_header_global_rounding_and_refund_without_tax_pipeline(self):
        sale = self._native_global_rounding_order()
        self._empty_order_payment(sale).amount = .09
        refund = sale._refund()
        refund.write({'state': 'paid', 'date_order': sale.date_order})
        self._empty_order_payment(refund).amount = -.09
        self.assertEqual(Decimal(str(refund.amount_total)), Decimal('-.09'))
        self.env.flush_all()
        with patch.object(type(self.env['pos.order.line']), '_prepare_tax_base_line_values',
                          side_effect=AssertionError('No tax preparation in header reader')), \
                patch.object(type(self.env['account.tax']), '_get_tax_totals_summary',
                             side_effect=AssertionError('No tax recalculation in header reader')):
            events = self._read()
        self.assertEqual({row['source_id']: row['amount'] for row in events},
                         {sale.id: Decimal('.09'), refund.id: Decimal('-.09')})
        self.assertEqual({row['line_model'] for row in events}, {'pos.order'})
        self.assertTrue(all(not row['ledger_confirmed'] for row in events))
        self.assertEqual(sum((row['amount'] for row in events), Decimal(0)), Decimal(0))

    def test_empty_native_order_has_no_sale_event(self):
        self._empty_native_pos_order()
        self.assertEqual(self._read(), [])

    def test_nonempty_zero_order_retains_header(self):
        sale = self._sale()
        sale.write({'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0})
        sale.payment_ids.amount = 0
        self.assertEqual(self._read()[0]['amount'], Decimal('0.00'))

    def test_unpaid_and_tender_mismatch_are_unallocated(self):
        sale = self._sale()
        payment = sale.payment_ids
        payment.amount = 114
        self.assertEqual(self._read()[0]['channels'][0][0], 'unallocated')
        payment.unlink()
        event = self._read()[0]
        self.assertEqual(event['amount'], Decimal('115'))
        self.assertEqual(event['channels'][0][0], 'unallocated')
        self.assertFalse(event['ledger_confirmed'])

    def test_exact_mixed_tender_and_mixed_sign_fallback(self):
        empty = self._empty_native_pos_order()
        first_method = empty.config_id.payment_method_ids[:1]
        second_method = first_method.copy({'name': 'Second header tender'})
        config = empty.config_id.copy({
            'name': 'Stored mixed tender source',
            'payment_method_ids': [Command.set((first_method | second_method).ids)],
        })
        session = self.env['pos.session'].create({'config_id': config.id})
        session.set_opening_control(0, 'Stored header mixed tender fixture')
        sale = self._sale(session)
        first = sale.payment_ids
        second = self.env['pos.payment'].create({
            'pos_order_id': sale.id, 'payment_method_id': second_method.id,
            'amount': 75, 'payment_date': sale.date_order,
        })
        first.amount = 40
        event = self._read()[0]
        self.assertEqual({key: amount for key, _name, amount in event['channels']}, {
            'payment_%s' % first.payment_method_id.id: Decimal('40'),
            'payment_%s' % second_method.id: Decimal('75'),
        })
        first.amount, second.amount = -5, 120
        self.assertEqual(self._read()[0]['channels'][0][0], 'unallocated')

    def test_posted_unpaid_invoice_and_refund_are_sales_not_cash(self):
        invoice = self._customer_invoice()
        refund = self._customer_invoice('out_refund')
        events = self._read()
        self.assertEqual({row['source_id']: row['amount'] for row in events}, {
            invoice.id: Decimal('115'), refund.id: Decimal('-115'),
        })
        self.assertTrue(all(row['sales_posted'] and not row['ledger_confirmed'] for row in events))
        self.assertTrue(all(row['channels'][0][0] == 'unallocated' for row in events))

    def test_linked_pos_invoice_is_not_added_twice(self):
        sale = self._sale()
        self._invoice_sale(sale)
        events = self._read()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['source_model'], 'pos.order')
        self.assertEqual(events[0]['linked_invoice_id'], sale.account_move.id)
        self.assertIs(events[0]['invoice_not_readded'], True)
        self.assertEqual(events[0]['amount'], Decimal('115'))

    def test_out_of_period_linked_order_proves_invoice_exclusion(self):
        sale = self._sale()
        self._invoice_sale(sale)
        sale.date_order = '2041-06-09 12:00:00'
        self.assertEqual(self._read(), [])
        sale.amount_total = 116
        with self.assertRaises(AccessError):
            self._read()

    def test_relation_dedup_uses_all_linked_order_headers(self):
        first = self._sale()
        second = self._sale(first.session_id)
        invoice = self._invoice('out_invoice', self.sale_journal, [
            ('Two stored orders', self.income, 200, 0, self.tax),
        ])
        (first | second).write({'account_move': invoice.id})
        events = self._read()
        self.assertEqual({row['source_id'] for row in events}, {first.id, second.id})
        second.date_order = '2041-06-09 12:00:00'
        self.assertEqual(len(self._read()), 1)
        second.amount_total = 114
        with self.assertRaises(AccessError):
            self._read()

    def test_foreign_currency_invoice_fails_explicitly(self):
        currency = self.env.ref('base.EUR')
        if currency == self.company.currency_id:
            currency = self.env.ref('base.USD')
        currency.active = True
        self._customer_invoice(currency=currency)
        with self.assertRaises(AccessError):
            self._read()

    def test_fresh_calls_read_header_changes_and_ignore_injected_proof(self):
        sale = self._sale()
        self.assertEqual(self._read()[0]['amount'], Decimal('115'))
        sale.write({'amount_total': 230, 'amount_paid': 230})
        sale.payment_ids.amount = 230
        injected = self.report.with_context(
            baseer_operations_batch_verified=True,
            baseer_operations_pos_lines_by_order={str(sale.id): []},
        )
        self.assertEqual(self._read(report=injected)[0]['amount'], Decimal('230'))

    def test_normal_user_hidden_sources_and_links_fail_closed(self):
        sale = self._sale()
        invoice = self._customer_invoice()
        secured = self._empty_native_reader()
        self.assertEqual(len(self._read(report=secured)), 2)
        for model, hidden in (
                ('pos.order', sale), ('pos.order.line', sale.lines[:1]),
                ('pos.session', sale.session_id), ('pos.config', sale.config_id),
                ('pos.payment', sale.payment_ids[:1]),
                ('pos.payment.method', sale.payment_ids.payment_method_id[:1]),
                ('account.move', invoice), ('account.move.line', invoice.line_ids[:1]),
                ('account.account', self.receivable), ('account.journal', self.sale_journal)):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide stored header witness %s' % model,
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': "[('id', '!=', %s)]" % hidden.id,
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', hidden.id)]))
                    with self.assertRaises(AccessError):
                        self._read(report=secured)
                finally:
                    rule.unlink()

    def test_hidden_out_of_period_pos_link_fails_closed(self):
        sale = self._sale()
        self._invoice_sale(sale)
        sale.date_order = '2041-06-09 12:00:00'
        secured = self._empty_native_reader()
        self.assertEqual(self._read(report=secured), [])
        rule = self.env['ir.rule'].create({
            'name': 'Hide old linked stored source',
            'model_id': self.env['ir.model']._get('pos.order').id,
            'domain_force': "[('id', '!=', %s)]" % sale.id,
        })
        try:
            secured.env.invalidate_all()
            with self.assertRaises(AccessError):
                self._read(report=secured)
        finally:
            rule.unlink()

    def test_cross_company_and_context_expansion_are_rejected(self):
        other = self.env['res.company'].create({'name': 'Other stored sales company'})
        secured = self._empty_native_reader()
        with self.assertRaises(AccessError):
            secured._owner_sales(other, self.day, self.day, [])
        with self.assertRaises(AccessError):
            secured.with_context(allowed_company_ids=other.ids)._owner_sales(
                other, self.day, self.day, [])

    def test_hidden_unused_product_and_tax_do_not_change_stored_header(self):
        sale = self._sale()
        secured = self._empty_native_reader()
        expected = self._read(report=secured)
        for model, hidden in (('product.product', sale.lines.product_id), ('account.tax', self.tax)):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide unused header graph %s' % model,
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': "[('id', '!=', %s)]" % hidden.id,
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', hidden.id)]))
                    self.assertEqual(self._read(report=secured), expected)
                finally:
                    rule.unlink()

    def test_posted_header_must_equal_receivable_witness(self):
        invoice = self._customer_invoice()
        self.assertEqual(self._read()[0]['amount'], Decimal('115'))
        # Synthetic transaction-only corruption exercises the stored-header guard.
        invoice.flush_recordset(['amount_total'])
        self.env.cr.execute('UPDATE account_move SET amount_total=%s WHERE id=%s', [116, invoice.id])
        invoice.invalidate_recordset(['amount_total'])
        with self.assertRaises(AccessError):
            self._read()

    def test_closed_session_requires_visible_posted_linked_move(self):
        sale = self._sale()
        sale.session_id.action_pos_session_closing_control()
        session, move = sale.session_id, sale.session_id.move_id
        if move.state == 'draft':
            move.action_post()
        self.assertEqual(session.state, 'closed')
        self.assertEqual(move.state, 'posted')
        secured = self._empty_native_reader()
        self.assertEqual(self._read(report=secured)[0]['amount'], Decimal('115'))
        rule = self.env['ir.rule'].create({
            'name': 'Hide closed header journal entry',
            'model_id': self.env['ir.model']._get('account.move').id,
            'domain_force': "[('id', '!=', %s)]" % move.id,
        })
        try:
            secured.env.invalidate_all()
            with self.assertRaises(AccessError):
                self._read(report=secured)
        finally:
            rule.unlink()
        move.flush_recordset(['state'])
        self.env.cr.execute("UPDATE account_move SET state='draft' WHERE id=%s", [move.id])
        move.invalidate_recordset(['state'])
        with self.assertRaises(AccessError):
            self._read()

    def test_selected_journal_cannot_be_hidden(self):
        self._sale()
        secured = self._empty_native_reader()
        self.assertEqual(len(self._read(report=secured, journal_ids=self.sale_journal.ids)), 1)
        rule = self.env['ir.rule'].create({
            'name': 'Hide selected header journal',
            'model_id': self.env['ir.model']._get('account.journal').id,
            'domain_force': "[('id', '!=', %s)]" % self.sale_journal.id,
        })
        try:
            secured.env.invalidate_all()
            with self.assertRaises(AccessError):
                self._read(report=secured, journal_ids=self.sale_journal.ids)
        finally:
            rule.unlink()

    def test_closing_move_rejects_misconfigured_session_outside_selected_orders(self):
        sale = self._sale()
        sale.session_id.action_pos_session_closing_control()
        move = sale.session_id.move_id
        self.assertEqual(move.state, 'posted')
        secured = self._empty_native_reader()
        self.assertEqual(self._read(report=secured)[0]['amount'], Decimal('115'))
        other_journal = self._journal('sale', 'OSC')
        config = sale.config_id.copy({
            'name': 'Unselected closing witness', 'journal_id': other_journal.id,
            'invoice_journal_id': other_journal.id,
        })
        extra = self.env['pos.session'].create({'config_id': config.id})
        # ORM fixture links an otherwise unselected session to the same entry.
        # No SQL corruption or report guard bypass is involved.
        extra.write({'state': 'closed', 'move_id': move.id})
        self.assertFalse(extra.order_ids)
        self.assertIn(extra, move.pos_session_ids)
        self.assertNotEqual(extra.config_id.journal_id, move.journal_id)
        with self.assertRaises(AccessError):
            self._read(report=secured)

    def test_approved_summary_keeps_business_day_and_rejects_hidden_or_changed_header(self):
        # Real approval in the authorized active company, never a test allowlist.
        sar = self.env.ref('base.SAR')
        sar.active = True
        self.company.currency_id = sar
        product = self.env['product.product'].create({
            'name': 'Stored summary service', 'type': 'service', 'available_in_pos': True,
            'property_account_income_id': self.income.id,
            'taxes_id': [Command.set(self.tax.ids)],
        })
        bank = self._journal('bank', 'OSB')
        clearing = self._account('953111', 'asset_current', True)
        category = self.env['baseer.pos.payment.category'].create({
            'name': 'Stored summary platform', 'company_id': self.company.id, 'kind': 'platform',
        })
        method = self.env['pos.payment.method'].create({
            'name': 'Stored summary platform', 'company_id': self.company.id,
            'journal_id': bank.id, 'baseer_category_id': category.id,
            'receivable_account_id': self.receivable.id, 'outstanding_account_id': clearing.id,
        })
        config = self.env['pos.config'].create({
            'name': 'Stored summary source', 'company_id': self.company.id,
            'journal_id': self.sale_journal.id, 'invoice_journal_id': self.sale_journal.id,
            'payment_method_ids': [Command.set(method.ids)],
            'baseer_summary_only': True, 'baseer_summary_product_id': product.id,
            'baseer_summary_tax_id': self.tax.id,
        })
        self.company.partner_id.tz = 'Pacific/Honolulu'
        self.day = fields.Date.today() - timedelta(days=1)
        summary = self.env['baseer.pos.summary'].create({
            'company_id': self.company.id, 'config_id': config.id, 'business_date': self.day,
            'period_scope': 'all', 'day_schedule': 'all', 'customer_count': 1,
            'allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': 115})],
        })
        summary.action_approve()
        self.assertEqual(summary.state, 'approved')
        secured = self._empty_native_reader()
        event, = self._read(report=secured)
        self.assertEqual((event['date'], event['amount'], event['source_id']),
                         (self.day, Decimal('115'), summary.order_id.id))
        rule = self.env['ir.rule'].create({
            'name': 'Hide approved stored summary',
            'model_id': self.env['ir.model']._get('baseer.pos.summary').id,
            'domain_force': "[('id', '!=', %s)]" % summary.id,
        })
        try:
            secured.env.invalidate_all()
            with self.assertRaises(AccessError):
                self._read(report=secured)
        finally:
            rule.unlink()
        summary.order_id.flush_recordset(['amount_total'])
        self.env.cr.execute('UPDATE pos_order SET amount_total=%s WHERE id=%s', [116, summary.order_id.id])
        summary.order_id.invalidate_recordset(['amount_total'])
        with self.assertRaises(AccessError):
            self._read()

    def test_company_timezone_boundaries_and_explicit_journal_scope(self):
        self.company.partner_id.tz = 'Asia/Riyadh'
        first = self._sale()
        second = self._sale(first.session_id)
        third = self._sale(first.session_id)
        fourth = self._sale(first.session_id)
        first.date_order = '2041-06-09 20:59:59'
        second.date_order = '2041-06-09 21:00:00'
        third.date_order = '2041-06-10 20:59:59'
        fourth.date_order = '2041-06-10 21:00:00'
        self.assertEqual({event['source_id'] for event in self._read()}, {second.id, third.id})
        other_journal = self._journal('sale', 'OSX')
        self.assertEqual(self._read(journal_ids=other_journal.ids), [])
