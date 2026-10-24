from decimal import Decimal

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from .test_tobacco_report import TestTobaccoReport


@tagged('post_install', '-at_install', 'reports_unified_drill')
class TestTobaccoDrillSelectors(TransactionCase):
    # Reuse the native POS/tax fixture without inheriting its whole test suite.
    _pos_fixture = TestTobaccoReport._pos_fixture
    _real_order = TestTobaccoReport._real_order
    def test_refund_debit_and_zero_credit_use_their_display_measure(self):
        report = self.env['baseer.pos.tobacco.report.wizard']
        data = {'rows': [{'_order_id': 9, '_line_id': 10, '_fee': Decimal('-10.00')}], 'exceptions': []}
        _kind, debit = report._selected(data, {'kind': 'fee_row', 'order_id': 9, 'line_id': 10, 'measure': 'debit'})
        _kind, credit = report._selected(data, {'kind': 'fee_row', 'order_id': 9, 'line_id': 10, 'measure': 'credit'})
        self.assertEqual(report._total({'kind': 'fee_row', 'measure': 'debit'}, debit), Decimal('10.00'))
        self.assertEqual(report._total({'kind': 'fee_row', 'measure': 'credit'}, credit), Decimal('0'))
        with self.assertRaises(ValidationError):
            report._selected(data, {'kind': 'fee_row', 'order_id': 9, 'line_id': 10, 'measure': []})

    def test_central_dispatch_returns_honest_zero_opening_scope(self):
        self.env.company.currency_id = self.env.ref('base.SAR')
        filters = {'company_id': self.env.company.id, 'period': 'month', 'month': 10, 'year': 2099,
                   'date_from': '2099-10-01', 'date_to': '2099-10-31', 'show_products': False}
        result = self.env['baseer.report.drill'].get_drilldown('tobacco', filters, {'kind': 'summary', 'metric': 'opening'}, 1)
        self.assertEqual(result['value'], '0.00')
        self.assertEqual(result['rows'], [])

    def test_central_dispatch_actual_refund_debit_and_source_membership(self):
        self.env.company.currency_id = self.env.ref('base.SAR')
        refund = self._real_order([-1])
        other = self._real_order([1])
        refund.write({'state': 'done', 'date_order': '2099-10-03 10:00:00', 'amount_total': '1.00'})
        other.write({'state': 'done', 'date_order': '2099-10-04 10:00:00'})
        filters = {'company_id': self.env.company.id, 'period': 'month', 'month': 10, 'year': 2099,
                   'date_from': '2099-10-01', 'date_to': '2099-10-31', 'show_products': False}
        selector = {'kind': 'fee_row', 'order_id': refund.id, 'line_id': refund.lines.id, 'measure': 'debit'}
        result = self.env['baseer.report.drill'].get_drilldown('tobacco', filters, selector, 1)
        self.assertGreater(Decimal(result['value'].replace(',', '')), Decimal('0'))
        self.assertEqual(result['rows'][0]['cells']['credit'], '0.00')
        fee = self.env['baseer.report.drill'].get_drilldown('tobacco', filters, {**selector, 'measure': 'fee'}, 1)
        credit = self.env['baseer.report.drill'].get_drilldown('tobacco', filters, {**selector, 'measure': 'credit'}, 1)
        running = self.env['baseer.report.drill'].get_drilldown('tobacco', filters, {'kind': 'running', 'order_id': refund.id, 'line_id': refund.lines.id}, 1)
        self.assertLess(Decimal(fee['value'].replace(',', '')), Decimal('0'))
        self.assertEqual(credit['value'], '0.00')
        self.assertEqual(running['value'], fee['value'])
        action = self.env['baseer.report.drill'].open_source('tobacco', filters, result['rows'][0]['source'])
        self.assertEqual(action['res_model'], 'pos.order')
        self.assertEqual(action['views'], [[False, 'form']])
        with self.assertRaises(AccessError):
            self.env['baseer.report.drill'].open_source('tobacco', filters, {
                **result['rows'][0]['source'], 'order_id': other.id, 'line_id': other.lines.id,
            })
        exception = self.env['baseer.report.drill'].get_drilldown('tobacco', filters, {
            'kind': 'exception', 'order_id': refund.id, 'metric': 'saved_total',
        }, 1)
        with self.assertRaises(AccessError):
            self.env['baseer.report.drill'].open_source('tobacco', filters, {
                **exception['rows'][0]['source'], 'line_id': refund.lines.id,
            })
