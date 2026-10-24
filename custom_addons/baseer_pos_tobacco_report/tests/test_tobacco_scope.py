"""Native tobacco-only screening parity; synthetic fixtures, no financial shortcuts."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from .test_tobacco_report import TestTobaccoReport


@tagged('post_install', '-at_install', 'tobacco_scope', 'reports_unified_export')
class TestTobaccoScope(TransactionCase):
    _pos_fixture = TestTobaccoReport._pos_fixture
    _real_order = TestTobaccoReport._real_order

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.currency_id = self.env.ref('base.SAR')
        self.report = self.env['report.baseer_pos_tobacco_report.report_pos_tobacco_fees']
        self.quantum = Decimal('.01')
        self.filters = {'company_id': self.company.id, 'period': 'month', 'month': 10, 'year': 2099,
                        'date_from': '2099-10-01', 'date_to': '2099-10-31', 'show_products': True}

    def _done(self, order):
        order._compute_prices()
        order.write({'state': 'done', 'date_order': '2099-10-03 10:00:00'})
        return order

    def _unrelated(self):
        order = self._real_order([1])
        order.lines.tax_ids = [Command.clear()]
        return self._done(order)

    def _build(self, report=None):
        report = self.report if report is None else report
        wizard = report.env['baseer.pos.tobacco.report.wizard'].new({
            'company_id': self.company.id, 'period': 'custom',
            'date_from': date(2099, 10, 1), 'date_to': date(2099, 10, 31), 'show_products': True})
        return report._build_report(wizard)

    def _assert_exhaustive_parity(self, orders):
        ordered = orders.sorted(lambda order: (order.date_order, order.id))
        # Exhaustive native calculator includes every line of every order and
        # does not call the candidate filter being tested.
        expected = self.report._collect_rows(ordered, self.company.currency_id, self.quantum)
        actual = self._build()
        self.assertEqual(actual['rows'], expected[0])
        self.assertEqual(actual['exceptions'], expected[1])
        for key, value in zip(('debit_total', 'credit_total', 'closing'), expected[2:]):
            self.assertEqual(Decimal(actual[key].replace(',', '')), value)
        return actual

    def _ordinary_account(self):
        return self.env['account.account'].create({'name': 'Scope unrelated tax account', 'code': '963311',
            'account_type': 'liability_current', 'company_ids': [Command.set(self.company.ids)]})

    def test_native_mixed_refund_global_cash_rounding_and_bounded_candidate_calls(self):
        self.company.tax_calculation_rounding_method = 'round_globally'
        mixed = self._real_order([4, -1])
        product, _tax, session = self._pos_fixture()
        mixed.write({'lines': [Command.create({'product_id': product.id, 'uuid': str(uuid4()),
            'qty': 1, 'price_unit': 7.03, 'price_subtotal': 7.03, 'price_subtotal_incl': 7.03,
            'full_product_name': 'Untaxed companion', 'tax_ids': [Command.clear()]})]})
        profit = self.env['account.account'].create({'name': 'Scope rounding profit', 'code': '963312',
            'account_type': 'income_other', 'company_ids': [Command.set(self.company.ids)]})
        loss = self.env['account.account'].create({'name': 'Scope rounding loss', 'code': '963313',
            'account_type': 'expense', 'company_ids': [Command.set(self.company.ids)]})
        rounding = self.env['account.cash.rounding'].create({'name': 'Scope five-halalas', 'rounding': .05,
            'strategy': 'add_invoice_line', 'rounding_method': 'HALF-UP',
            'profit_account_id': profit.id, 'loss_account_id': loss.id})
        session.config_id.write({'cash_rounding': True, 'only_round_cash_method': False,
                                 'rounding_method': rounding.id})
        mixed = self._done(mixed)
        refund = self._done(self._real_order([-2]))
        unrelated = self.env['pos.order']
        for _index in range(6):
            unrelated |= self._unrelated()
        unrelated[:1].amount_total += 1
        self.assertTrue(self.report._order_fee_data(unrelated[:1], self.quantum)[1])
        all_orders = mixed | refund | unrelated
        expected = self._assert_exhaustive_parity(all_orders)
        native = self.report._order_fee_data
        called = []

        def counted(order, quantum, lines=None):
            called.append(order.id)
            self.assertEqual(set(lines.ids), set(order.lines.ids), 'Mixed/global rounding lost companion lines')
            return native(order, quantum, lines=lines)

        with patch.object(type(self.report), '_order_fee_data', side_effect=counted):
            actual = self._build()
        self.assertEqual(called, [mixed.id, refund.id])
        self.assertEqual(actual['rows'], expected['rows'])
        self.assertTrue(any(row['_fee'] > 0 for row in actual['rows']))
        self.assertTrue(any(row['_fee'] < 0 for row in actual['rows']))
        self.assertFalse(any(row['_order_id'] in unrelated.ids for row in actual['exceptions']))

    def test_fiscal_mapped_and_group_tax_are_candidates(self):
        _product, tax, _session = self._pos_fixture()
        ordinary = tax.copy({'name': 'Ordinary source tax'})
        (ordinary.invoice_repartition_line_ids | ordinary.refund_repartition_line_ids).filtered(
            lambda row: row.repartition_type == 'tax').account_id = self._ordinary_account()
        mapped = tax.copy({'name': 'Mapped tobacco tax', 'original_tax_ids': [Command.set(ordinary.ids)]})
        position = self.env['account.fiscal.position'].create({'name': 'Scope tax mapping',
            'company_id': self.company.id, 'tax_ids': [Command.set(mapped.ids)]})
        mapped_order = self._real_order([1])
        mapped_order.lines.tax_ids = [Command.set(ordinary.ids)]
        mapped_order.fiscal_position_id = position
        self.assertEqual(mapped_order.lines.tax_ids_after_fiscal_position, mapped)
        self._done(mapped_order)
        group = self.env['account.tax'].create({'name': 'Scope grouped tobacco', 'amount_type': 'group',
            'type_tax_use': 'sale', 'company_id': self.company.id, 'children_tax_ids': [Command.set(tax.ids)]})
        # Native Odoo forbids a group inside another group. Preserve that rule
        # instead of manufacturing corrupt nested taxes through SQL for a test.
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['account.tax'].create({'name': 'Invalid nested scope group', 'amount_type': 'group',
                'type_tax_use': 'sale', 'company_id': self.company.id,
                'children_tax_ids': [Command.set(group.ids)]})
        grouped_order = self._real_order([1])
        grouped_order.lines.tax_ids = [Command.set(group.ids)]
        self._done(grouped_order)
        ordinary_order = self._real_order([1])
        ordinary_order.lines.tax_ids = [Command.set(ordinary.ids)]
        self._done(ordinary_order)
        orders = mapped_order | grouped_order | ordinary_order
        self.assertEqual(set(self.report._tobacco_candidates(orders, orders.lines, self.company).ids),
                         {mapped_order.id, grouped_order.id})
        result = self._assert_exhaustive_parity(orders)
        self.assertEqual({row['_order_id'] for row in result['rows']}, {mapped_order.id, grouped_order.id})

    def test_zero_actual_fee_retains_row_and_mismatch_but_nonfee_does_not(self):
        _product, tax, _session = self._pos_fixture()
        tax.amount = 0
        zero = self._done(self._real_order([1]))
        zero.amount_total += 1
        unrelated = self._unrelated()
        unrelated.amount_total += 1
        native_fee, mismatch, _computed, _saved = self.report._order_fee_data(zero, self.quantum)
        self.assertEqual([amount for _line, amount in native_fee], [Decimal('0.00')])
        self.assertTrue(mismatch)
        result = self._assert_exhaustive_parity(zero | unrelated)
        self.assertEqual([row['_order_id'] for row in result['rows']], [zero.id])
        self.assertEqual([row['_order_id'] for row in result['exceptions']], [zero.id])

    def test_blank_tax_target_is_conservative_and_native_base_account_can_be_tobacco(self):
        product, tax, _session = self._pos_fixture()
        target = tax.invoice_repartition_line_ids.filtered(lambda row: row.repartition_type == 'tax').account_id
        (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(
            lambda row: row.repartition_type == 'tax').account_id = False
        product.property_account_income_id = target
        order = self._done(self._real_order([1]))
        fees = self.report._order_fee_data(order, self.quantum)[0]
        self.assertTrue(fees, 'Native blank-account fallback must exercise account 201021')
        self.assertEqual(self.report._tobacco_candidates(order, order.lines, self.company), order)
        self._assert_exhaustive_parity(order)

    def test_hidden_line_tax_repartition_account_fail_closed_for_normal_reader(self):
        order = self._done(self._real_order([1]))
        _product, tax, _session = self._pos_fixture()
        reps = tax.invoice_repartition_line_ids.filtered(lambda row: row.repartition_type == 'tax')
        user = self.env['res.users'].create({'name': 'Tobacco scope reader', 'login': 'tobacco_scope_reader',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id, self.env.ref('point_of_sale.group_pos_user').id])]})
        report = self.report.with_user(user).sudo(False).with_context(allowed_company_ids=self.company.ids)
        self.assertTrue(self._build(report)['rows'])
        for model, record in (('pos.order.line', order.lines), ('account.tax', tax),
                              ('account.tax.repartition.line', reps), ('account.account', reps.account_id)):
            rule = self.env['ir.rule'].create({'name': 'Scope hidden ' + model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {record.id})]"})
            try:
                report.env.invalidate_all()
                with self.assertRaises(AccessError):
                    self._build(report)
            finally:
                rule.unlink()

        # Mapping metadata itself is security evidence, including original taxes
        # not directly present on this POS line. Hiding one cannot silently turn
        # the mapped tobacco tax into an unrelated/noncandidate order.
        extra_original = tax.copy({'name': 'Scope mapping extra original'})
        mapped = tax.copy({'name': 'Scope protected mapped tobacco',
                           'original_tax_ids': [Command.set((tax | extra_original).ids)]})
        position = self.env['account.fiscal.position'].create({'name': 'Scope protected position',
            'company_id': self.company.id, 'tax_ids': [Command.set(mapped.ids)]})
        order.fiscal_position_id = position
        order._compute_prices()
        report.env.invalidate_all()
        self.assertTrue(self._build(report)['rows'])
        for model, record in (('account.tax', mapped), ('account.tax', extra_original),
                              ('account.fiscal.position', position)):
            rule = self.env['ir.rule'].create({'name': 'Scope hidden mapping ' + model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {record.id})]"})
            try:
                report.env.invalidate_all()
                with self.assertRaises(AccessError):
                    self._build(report)
            finally:
                rule.unlink()

        # The legal group-to-child relation and the child's repartitions must
        # remain visible even though the POS line references only the group.
        group = self.env['account.tax'].create({'name': 'Scope protected group', 'amount_type': 'group',
            'type_tax_use': 'sale', 'company_id': self.company.id, 'children_tax_ids': [Command.set(tax.ids)]})
        order.fiscal_position_id = False
        order.lines.tax_ids = [Command.set(group.ids)]
        order._compute_prices()
        report.env.invalidate_all()
        self.assertTrue(self._build(report)['rows'])
        for model, record in (('account.tax', tax), ('account.tax.repartition.line', reps)):
            rule = self.env['ir.rule'].create({'name': 'Scope hidden group child ' + model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {record.id})]"})
            try:
                report.env.invalidate_all()
                with self.assertRaises(AccessError):
                    self._build(report)
            finally:
                rule.unlink()

    def test_foreign_company_and_non_tobacco_source_membership_are_denied(self):
        tobacco = self._done(self._real_order([1]))
        unrelated = self._unrelated()
        unrelated.amount_total += 1
        foreign = self.env['res.company'].create({'name': 'Scope foreign SAR company',
                                                  'currency_id': self.env.ref('base.SAR').id})
        with self.assertRaises(AccessError):
            self.report._tobacco_candidates(tobacco, tobacco.lines, foreign)
        engine = self.env['baseer.report.drill']
        detail = engine.get_drilldown('tobacco', self.filters, {'kind': 'summary', 'metric': 'closing'}, 1)
        self.assertEqual(len(detail['rows']), 1)
        token = detail['rows'][0]['source']
        self.assertEqual(engine.open_source('tobacco', self.filters, token)['res_id'], tobacco.id)
        nonfee = {'kind': 'fee_row', 'order_id': unrelated.id, 'line_id': unrelated.lines.id, 'measure': 'fee'}
        with self.assertRaises(AccessError):
            engine.get_drilldown('tobacco', self.filters, nonfee, 1)
        with self.assertRaises(AccessError):
            engine.open_source('tobacco', self.filters, {**token, 'parent': nonfee,
                'order_id': unrelated.id, 'line_id': unrelated.lines.id})
        with self.assertRaises(AccessError):
            engine.get_drilldown('tobacco', self.filters,
                {'kind': 'exception', 'order_id': unrelated.id, 'metric': 'saved_total'}, 1)
        with self.assertRaises(AccessError):
            engine.get_drilldown('tobacco', dict(self.filters, company_id=foreign.id),
                                {'kind': 'summary', 'metric': 'closing'}, 1)
