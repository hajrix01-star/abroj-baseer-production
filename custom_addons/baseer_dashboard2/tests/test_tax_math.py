from decimal import Decimal
from copy import deepcopy
from datetime import date
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models.tax_math import allocate_tax, convert_target


@tagged('post_install', '-at_install')
class TestTaxMath(TransactionCase):
    def test_largest_remainder_and_refund(self):
        self.assertEqual(allocate_tax('0.05', [(1, 1), (2, 1), (3, 1)]),
                         [(1, Decimal('0.02')), (2, Decimal('0.02')), (3, Decimal('0.01'))])
        self.assertEqual(allocate_tax('-0.05', [(1, -1), (2, -1), (3, -1)]),
                         [(1, Decimal('-0.01')), (2, Decimal('-0.02')), (3, Decimal('-0.02'))])

    def test_signed_bases_and_unallocated(self):
        allocated = allocate_tax('10.01', [(1, 200), (2, -100)])
        self.assertEqual(sum(value for _, value in allocated), Decimal('10.01'))
        self.assertIsNone(allocate_tax(10, []))
        self.assertIsNone(allocate_tax(10, [(1, 10), (2, -10)]))

    def test_target_conversion_and_missing_denominators(self):
        values = (100, 120, 40, 44, 20, 10, 26)
        self.assertEqual(convert_target('food_pct', 33, *values), 30.3)
        self.assertEqual(convert_target('salaries_pct', 25, *values), 20.8)
        self.assertEqual(convert_target('prime_pct', 60, *values), 53.3)
        self.assertEqual(convert_target('net_margin_pct', 12, *values), 23.3)
        self.assertIsNone(convert_target('food_pct', 33, 100, 120, 0, 0, 20, 10, 26))
        self.assertIsNone(convert_target('salaries_pct', 25, 100, 0, 40, 44, 20, 10, 26))
        self.assertIsNone(convert_target('unknown', 25, *values))

    def test_inclusive_profit_tobacco_and_breakeven(self):
        service = self.env['baseer.dashboard2.service']
        net = {'sales_net': 100.0, 'categories': {'revenue': 100.0, 'food_cost': 40.0, 'salaries': 20.0},
               'accounts': [], 'breakeven': 50.0, 'gross_profit': 60.0, 'operating_profit': 40.0,
               'net_profit': 40.0, 'ratios': {}, 'safety_margin': 50.0}
        taxes = {'accounts': {}, 'output_vat': 10.0, 'tobacco_fee': 2.0, 'input_vat': 0.0,
                 'unallocated_input_vat': 0.0, 'unallocated_input_vat_lines': 0, 'vat_payable': 10.0}
        with patch.object(type(service), '_accounting', side_effect=lambda *a: deepcopy(net)), \
             patch.object(type(service), '_tax_basis', return_value=taxes):
            result = service._accounting_gross([self.env.company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(result['sales_net'], 112)
        self.assertEqual(result['tax']['tobacco_fee'], 2)
        self.assertEqual(result['net_profit'], 52)
        self.assertEqual(result['ratios']['net_margin_pct'], 46.43)
        self.assertEqual(result['breakeven'], 56)
        self.assertEqual(result['sales_net'] / result['breakeven'], net['sales_net'] / net['breakeven'])
