from decimal import Decimal

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
