from decimal import Decimal

from odoo.tests.common import TransactionCase


class SalesCategoryPerformanceCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.dashboard = self.env['spreadsheet.dashboard']

    def breakdown(self, values, total, complete=True):
        buckets = {
            identifier: {'name': name, 'kind': 'bank', 'sales': Decimal(amount)}
            for identifier, name, amount in values
        }
        return self.dashboard._baseer_category_performance(buckets, Decimal(total), complete)

    def test_complete_categories_have_truthful_shares_and_stable_ranks(self):
        result = self.breakdown([(1, 'Cash', '60'), (2, 'Card', '25'), (3, 'Apps', '15')], '100')
        self.assertTrue(result['performance']['available'])
        self.assertEqual(result['performance']['highest']['name'], 'Cash')
        self.assertEqual(result['performance']['lowest']['name'], 'Apps')
        self.assertEqual(sum(Decimal(row['share']['value']) for row in result['rows']), Decimal('100.00'))
        self.assertEqual([row['share']['value'] for row in result['rows']], ['60.00', '25.00', '15.00'])

    def test_rounding_remainder_is_kept_server_side(self):
        result = self.breakdown([(1, 'A', '1'), (2, 'B', '1'), (3, 'C', '1')], '3')
        self.assertEqual(sum(Decimal(row['share']['value']) for row in result['rows']), Decimal('100.00'))
        self.assertEqual(result['performance']['highest']['category_id'], 1)
        self.assertEqual(result['performance']['lowest']['category_id'], 1)

    def test_partial_or_zero_coverage_never_claims_share_or_rank(self):
        partial = self.breakdown([(1, 'Cash', '60'), (2, 'Card', '40')], '100', complete=False)
        self.assertFalse(partial['performance']['available'])
        self.assertIsNone(partial['performance']['highest'])
        self.assertTrue(all(not row['share']['available'] for row in partial['rows']))
        zero = self.breakdown([(1, 'Cash', '0')], '0')
        self.assertFalse(zero['performance']['available'])
        self.assertIsNone(zero['performance']['lowest'])

    def test_chart_is_server_limited_and_other_is_server_aggregated(self):
        result = self.breakdown([(identifier, f'Category {identifier}', '1') for identifier in range(1, 14)], '13')
        self.assertEqual(len(result['chart_rows']), 12)
        other = result['chart_rows'][-1]
        self.assertEqual(other['category_id'], 'other')
        self.assertEqual(other['sales']['value'], '2.00')
        self.assertEqual(sum(Decimal(row['share']['value']) for row in result['chart_rows']), Decimal('100.00'))
