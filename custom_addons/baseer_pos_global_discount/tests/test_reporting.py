"""Owned allowances change product economics, never merchandise quantities or native history."""
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.point_of_sale.report.pos_order_report import ReportPosOrder as NativeReport
from odoo.addons.baseer_pos_print_bridge.models.job import BaseerPrintJob as NativePrintJob

from ..models.discount_reporting import _replace_once
from . import test_global_discount as fixtures


@tagged('post_install', '-at_install')
class TestDiscountReporting(TransactionCase):
    _order = fixtures.TestGlobalDiscount._order
    _apply = fixtures.TestGlobalDiscount._apply
    _paid = fixtures.TestGlobalDiscount._paid
    _refund = fixtures.TestGlobalDiscount._refund
    _prepare = fixtures.TestGlobalDiscount._prepare
    _combo_order = fixtures.TestGlobalDiscount._combo_order
    _combo_refund = fixtures.TestGlobalDiscount._combo_refund

    def setUp(self):
        super().setUp()
        self.account = self.env['account.account'].create({
            'name': 'Reporting fixture income', 'code': 'GDRPT001', 'account_type': 'income',
            'company_ids': [Command.set(self.env.company.ids)],
        })
        self.env.company.currency_id.rounding = .01
        self.tax = self.env['account.tax'].create({
            'name': 'Reporting VAT15', 'amount_type': 'percent', 'amount': 15,
            'type_tax_use': 'sale', 'company_id': self.env.company.id,
        })
        self.root_category = self.env['pos.category'].create({'name': 'Reporting main category'})
        self.category = self.env['pos.category'].create({'name': 'Reporting child category', 'parent_id': self.root_category.id})
        self.product = self.env['product.product'].create({
            'name': 'Reporting actual merchandise', 'type': 'service', 'available_in_pos': True,
            'list_price': 100, 'standard_price': 20,
            'property_account_income_id': self.account.id,
            'taxes_id': [Command.set(self.tax.ids)], 'pos_categ_ids': [Command.set(self.category.ids)],
        })
        self.config = self.env['pos.config'].create({
            'name': 'Reporting fixture POS', 'baseer_global_discount_account_id': self.account.id,
        })
        self.config.action_baseer_setup_global_discount()
        self.config.open_ui()
        self.config.current_session_id.state = 'opened'
        self.report = self.env['report.pos.order']

    def _cost(self, order):
        order.lines._compute_total_cost(self.env['stock.move'])
        self.env.flush_all()

    def _other_product(self, name, cost=0, category=None):
        return self.env['product.product'].create({
            'name': name, 'type': 'service', 'available_in_pos': True,
            'list_price': 0, 'standard_price': cost,
            'property_account_income_id': self.account.id,
            'taxes_id': [Command.set(self.tax.ids)],
            'pos_categ_ids': [Command.set((category or self.category).ids)],
        })

    def _rows(self, order):
        self.env.flush_all()
        self.report.invalidate_model()
        return self.report.search([('order_id', '=', order.id)], order='id')

    def _assert_totals(self, order):
        self._cost(order)
        rows = self._rows(order)
        self.assertAlmostEqual(sum(rows.mapped('price_total')), order.amount_total, places=2)
        self.assertAlmostEqual(sum(rows.mapped('price_subtotal_excl')), order.amount_total - order.amount_tax, places=2)
        self.assertAlmostEqual(sum(rows.mapped('margin')), order.margin, places=2)
        sign = -1 if order.is_refund else 1
        native_margin_sum = sum(line.price_subtotal * sign - line.total_cost
                                for line in order.lines if line.product_id.type != 'combo')
        self.assertAlmostEqual(order.margin, native_margin_sum, places=2)
        self.assertTrue(all(line.margin == 0 and line.margin_percent == 0
                            for line in order.lines.filtered('baseer_global_discount_line')))
        return rows

    def test_original_products_categories_net_revenue_margin_and_counts(self):
        order = self._order()
        other_category = self.env['pos.category'].create({'name': 'Reporting second category'})
        other = self._other_product('Reporting second merchandise', cost=10, category=other_category)
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': other.id, 'uuid': str(uuid4()), 'qty': 2,
            'price_unit': 50, 'discount': 0, 'price_subtotal': 100, 'price_subtotal_incl': 115,
            'tax_ids': [Command.set(self.tax.ids)],
        })
        original = [(line.id, line.price_unit, line.discount) for line in order.lines]
        self._apply(order, '23', 'fixed')
        rows = self._assert_totals(order)
        self.assertEqual(rows.ids, [item[0] for item in original])
        self.assertEqual(set(rows.product_id.ids), {self.product.id, other.id})
        self.assertAlmostEqual(sum(rows.mapped('product_qty')), 3)
        self.assertEqual(sum(rows.mapped('nbr_lines')), 2)
        self.assertAlmostEqual(sum(rows.mapped('baseer_invoice_discount')), 20, places=2)
        self.assertAlmostEqual(sum(rows.mapped('total_discount')), 0, places=2)
        self.assertAlmostEqual(order.margin, 140, places=2)
        for row in rows:
            self.assertAlmostEqual(row.price_subtotal_excl, 90, places=2)
            self.assertAlmostEqual(row.margin, 70, places=2)
        first = rows.filtered(lambda row: row.product_id == self.product)
        self.assertEqual(first.pos_categ_id, self.category)
        if 'baseer_root_pos_categ_id' in self.report._fields:
            self.assertEqual(first.baseer_root_pos_categ_id, self.root_category)
        self.assertEqual(original, [(line.id, line.price_unit, line.discount) for line in order.lines
                                    if not line.baseer_global_discount_line])

    def test_line_discount_unit_price_measure_stays_separate_from_pre_vat_allowance(self):
        self.tax.price_include_override = 'tax_included'
        order = self._order(price=115)
        source = order.lines
        source.discount = 10
        self._apply(order, '11.50', 'fixed')
        row = self._assert_totals(order).ensure_one()
        self.assertAlmostEqual(row.total_discount, 11.50, places=2)
        self.assertAlmostEqual(row.baseer_invoice_discount, 10, places=2)
        self.assertAlmostEqual(row.price_subtotal_excl, 80, places=2)
        self.assertAlmostEqual(row.margin, 60, places=2)
        self.assertAlmostEqual(source.margin, 60, places=2)
        self.assertAlmostEqual(source.margin_percent, .75, places=4)
        self.assertEqual((source.price_unit, source.discount), (115, 10))

    def test_current_refund_source_and_cumulative_discount_margin_cents(self):
        self.product.standard_price = .10
        order = self._order(price=1, qty=3)
        self._apply(order, '0.97', 'fixed')
        sale = self._assert_totals(order).ensure_one()
        sale_values = {key: sale[key] for key in ('baseer_invoice_discount', 'price_total', 'price_subtotal_excl', 'margin')}
        self._paid(order)
        totals = dict.fromkeys(sale_values, 0)
        for _ in range(3):
            refund = self._refund(order, 1)
            self._prepare(refund)
            row = self._assert_totals(refund).ensure_one()
            self.assertEqual(row.product_id, self.product)
            self.assertLess(row.baseer_invoice_discount, 0)
            self.assertEqual(set(refund.lines.filtered('baseer_global_discount_line').baseer_global_discount_source_id.ids), {row.id})
            for key in totals:
                totals[key] += row[key]
            self._paid(refund)
        for key, value in sale_values.items():
            self.assertAlmostEqual(totals[key], -value, places=2, msg=key)

    def test_managed_combo_parent_hidden_but_free_component_and_source_quantities_retained(self):
        order, parent = self._combo_order(ordinary=True)
        free_product = self._other_product('Reporting free component')
        free_choice = self.env['product.combo'].create({
            'name': 'Reporting free choice', 'company_id': order.company_id.id,
            'combo_item_ids': [Command.create({'product_id': free_product.id})],
        })
        parent.product_id.combo_ids = [Command.link(free_choice.id)]
        free = self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': free_product.id, 'qty': 1, 'price_unit': 0,
            'price_subtotal': 0, 'price_subtotal_incl': 0, 'tax_ids': [Command.set(self.tax.ids)],
            'combo_parent_id': parent.id, 'combo_item_id': free_choice.combo_item_ids.id,
        })
        self._apply(order, '20', 'fixed')
        rows = self._assert_totals(order)
        self.assertNotIn(parent.id, rows.ids)
        self.assertIn(free.id, rows.ids)
        self.assertEqual(sum(rows.mapped('nbr_lines')), 4)
        self.assertAlmostEqual(sum(rows.mapped('product_qty')), 5)
        self.assertEqual(rows.filtered(lambda row: row.id == free.id).price_total, 0)
        self.assertAlmostEqual(sum(rows.mapped('baseer_invoice_discount')),
                               -sum(line.price_subtotal for line in order.lines.filtered('baseer_global_discount_line')), places=2)

    def test_global_rounding_sale_and_full_combo_refund_reporting_totals(self):
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        order, parent = self._combo_order(parent_qty=3, ordinary=True)
        self._apply(order, '0.97', 'fixed')
        sale = self._assert_totals(order)
        original_totals = {key: sum(sale.mapped(key)) for key in ('baseer_invoice_discount', 'price_total', 'price_subtotal_excl', 'margin')}
        self._paid(order)
        refund = self._combo_refund(order, parent, 3, ordinary=True)
        self._prepare(refund)
        rows = self._assert_totals(refund)
        self.assertEqual(sum(rows.mapped('nbr_lines')), 3)
        for key, value in original_totals.items():
            self.assertAlmostEqual(sum(rows.mapped(key)), -value, places=2, msg=key)

    def test_native_legacy_global_discount_and_combo_rows_remain_exactly_unchanged(self):
        order, _parent = self._combo_order(ordinary=True)
        normal = order.lines.filtered(lambda line: not line.combo_parent_id and line.product_id.type != 'combo')
        normal.discount = 5
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.config.discount_product_id.id, 'qty': 1,
            'price_unit': -10, 'price_subtotal': -10, 'price_subtotal_incl': -11.5,
            'tax_ids': [Command.set(self.tax.ids)],
        })
        self._cost(order)
        query = NativeReport._select(self.report) + NativeReport._from(self.report)
        self.env.cr.execute('SELECT * FROM (' + query + ') native WHERE order_id=%s ORDER BY id', [order.id])
        expected = self.env.cr.dictfetchall()
        self.assertTrue(expected)
        columns = list(expected[0])
        self.env.cr.execute('SELECT ' + ', '.join('"' + name + '"' for name in columns)
                            + ' FROM report_pos_order WHERE order_id=%s ORDER BY id', [order.id])
        self.assertEqual(self.env.cr.dictfetchall(), expected)
        self.assertEqual(sum(self._rows(order).mapped('baseer_invoice_discount')), 0)

    def test_inverse_allocation_write_is_denied_and_native_sql_drift_fails_closed(self):
        order = self._order()
        self._apply(order)
        source = order.lines.filtered(lambda line: not line.baseer_global_discount_line)
        allocations = source.baseer_global_discount_allocation_ids
        with self.assertRaises(AccessError):
            source.write({'baseer_global_discount_allocation_ids': [Command.clear()]})
        self.assertEqual(source.baseer_global_discount_allocation_ids, allocations)
        with self.assertRaises(ValidationError):
            _replace_once('native query without the expected alias', r'AS margin', 'AS net_margin')
        with self.assertRaises(ValidationError):
            _replace_once('AS margin AS margin', r'AS margin', 'AS net_margin')

    def test_historical_managed_refund_negative_subtotals_are_projected_without_rewriting(self):
        order = self._order(qty=2)
        self._apply(order, '23', 'fixed')
        self._cost(order)
        self._paid(order)
        refund = self._refund(order, 1)
        self._prepare(refund)
        rows = self._assert_totals(refund)
        expected_margin = refund.margin
        expected_report = rows.read(['price_total', 'price_subtotal_excl', 'margin', 'baseer_invoice_discount'])
        self._paid(refund)
        # Reproduce the earlier managed-refund storage orientation in this
        # isolated fixture only. Product/quantity/price/discount/GL are unchanged.
        for line in refund._gd_internal().lines:
            line.write({'price_subtotal': -line.price_subtotal,
                        'price_subtotal_incl': -line.price_subtotal_incl})
        historical = [(line.id, line.price_subtotal, line.price_subtotal_incl) for line in refund.lines]
        self.assertAlmostEqual(refund.margin, expected_margin, places=2)
        self.assertEqual(self._rows(refund).read(['price_total', 'price_subtotal_excl', 'margin', 'baseer_invoice_discount']), expected_report)
        self.assertEqual(historical, [(line.id, line.price_subtotal, line.price_subtotal_incl) for line in refund.lines])

    def test_session_closing_counters_ignore_allowances_and_financial_summary_remains_native(self):
        order = self._order(qty=2)
        session = self.config.current_session_id
        jobs = self.env['baseer.print.job']
        now = fields.Datetime.now()
        # The native paid-order guard must remain intact. Build the baseline in
        # a rolled-back fixture savepoint rather than moving a paid sale to draft.
        with self.cr.savepoint() as baseline:
            self._paid(order)
            before = jobs._session_close_payload(session, as_of=now)
            baseline.close()
        self.assertEqual(before['summary']['units_sold'], '2.00')
        self.assertEqual(before['summary']['products_sold'], 1)
        self._apply(order, '23', 'fixed')
        self._paid(order)
        after = jobs._session_close_payload(session, as_of=now)
        self.assertEqual(after['summary']['units_sold'], '2.00')
        self.assertEqual(after['summary']['products_sold'], 1)
        self.assertEqual(after['summary']['total_amount'], '207.00')
        refund = self._refund(order, 2)
        self._prepare(refund)
        self._paid(refund)
        returned = jobs._session_close_payload(session, as_of=now)
        self.assertEqual(returned['summary']['units_sold'], '2.00')
        self.assertEqual(returned['summary']['products_sold'], 1)
        self.assertEqual(returned['summary']['total_amount'], '0.00')
        self.assertEqual(returned['summary']['refund_count'], 1)
        native = NativePrintJob._session_close_payload(jobs, session, as_of=now)
        for key in returned['summary']:
            if key not in ('units_sold', 'products_sold'):
                self.assertEqual(returned['summary'][key], native['summary'][key], key)
