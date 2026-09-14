from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class CatalogRemediationCase(TransactionCase):
    """Regression coverage for PRC-REMEDIATION1 catalogue contracts."""

    def setUp(self):
        super().setUp()
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_user'
        )
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_cashier'
        )
        self.company = self.env.company
        self.warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.company.id)], limit=1
        )
        self.unit = self.env.ref('uom.product_uom_unit')
        self.dozen = self.env.ref('uom.product_uom_dozen')
        category_values = {'name': 'PRC remediation catalogue'}
        if 'property_cost_method' in self.env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in self.env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        self.category = self.env['product.category'].create(category_values)
        self.product_one = self._product('PRC grouped coffee')
        self.product_two = self._product('PRC grouped tea')
        self.option_one_small = self._option(
            self.product_one, self.unit, 'Small', 'PRC pack 250g'
        )
        self.option_one_large = self._option(
            self.product_one, self.unit, 'Large', 'PRC pack 1kg'
        )
        self.option_two_dozen = self._option(
            self.product_two, self.dozen, 'Wholesale', 'PRC box 12'
        )
        self.representative = self.env['res.partner'].create({
            'name': 'PRC searchable representative',
            'is_company': False,
            'company_id': self.company.id,
        })
        self.representative.with_company(self.company).is_purchase_representative = True

    def _product(self, name):
        return self.env['product.product'].create({
            'name': name,
            'company_id': self.company.id,
            'categ_id': self.category.id,
            'uom_id': self.unit.id,
            'is_storable': True,
        })

    def _option(self, product, uom, name, packaging):
        return self.env['baseer.procurement.purchase.option'].create({
            'name': name,
            'company_id': self.company.id,
            'product_id': product.id,
            'uom_id': uom.id,
            'packaging_note': packaging,
        })

    def _request(self, name, option=None, request_date=None):
        values = {
            'name': name,
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'request_date': request_date or fields.Datetime.now(),
            'representative_partner_id': self.representative.id,
        }
        if option:
            values['line_ids'] = [(0, 0, {
                'option_id': option.id,
                'requested_qty': 1,
                'requested_price': 10,
            })]
        return self.env['baseer.procurement.request'].create(values)

    def test_recent_requests_page_through_full_history_without_duplicates(self):
        start = fields.Datetime.now() - timedelta(days=1)
        requests = self.env['baseer.procurement.request'].create([{
            'name': 'PRC-PAGED-%03d' % index,
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'request_date': start + timedelta(minutes=index),
            'representative_partner_id': self.representative.id,
        } for index in range(120)])

        first = requests.cashier_recent_requests(0, 50, 'PRC-PAGED-')
        second = requests.cashier_recent_requests(first['next_offset'], 50, 'PRC-PAGED-')
        third = requests.cashier_recent_requests(second['next_offset'], 50, 'PRC-PAGED-')
        received_ids = [row['id'] for page in (first, second, third) for row in page['items']]

        self.assertEqual(len(received_ids), len(set(received_ids)))
        self.assertEqual(len(received_ids), 120)
        self.assertTrue(set(requests.ids).issubset(received_ids))
        self.assertTrue(first['has_more'])
        self.assertTrue(second['has_more'])
        self.assertFalse(third['has_more'])
        self.assertEqual(first['currency_symbol'], self.company.currency_id.symbol)
        self.assertEqual(first['currency_position'], self.company.currency_id.position)

    def test_recent_requests_searches_relations_and_filters_state(self):
        matching = self._request('PRC-SEARCH-TARGET', self.option_two_dozen)
        matching.action_mark_sent()
        self._request('PRC-SEARCH-DRAFT', self.option_one_small)

        by_product = matching.cashier_recent_requests(0, 20, 'grouped tea')
        by_package = matching.cashier_recent_requests(0, 20, 'PRC box 12')
        by_unit = matching.cashier_recent_requests(0, 20, self.dozen.name)
        by_rep = matching.cashier_recent_requests(0, 20, 'searchable representative')
        sent_only = matching.cashier_recent_requests(0, 20, False, 'sent')

        for response in (by_product, by_package, by_unit, by_rep):
            self.assertIn(matching.id, [row['id'] for row in response['items']])
        self.assertIn(matching.id, [row['id'] for row in sent_only['items']])
        self.assertTrue(all(row['state'] == 'sent' for row in sent_only['items']))
        self.assertEqual(
            next(row for row in sent_only['items'] if row['id'] == matching.id)['state_label'],
            'Sent to purchaser',
        )
        with self.assertRaises(ValidationError):
            matching.cashier_recent_requests(0, 20, False, 'not-a-state')
        with self.assertRaises(ValidationError):
            matching.cashier_recent_requests(0, 20, 'x' * 129)

    def test_catalog_pages_products_and_keeps_every_variant_together(self):
        first = self.env['baseer.procurement.request'].catalog_page(
            False, self.category.id, 0, 1
        )
        second = self.env['baseer.procurement.request'].catalog_page(
            False, self.category.id, first['next_offset'], 1
        )

        self.assertEqual({row['product_id'] for row in first['items']}, {self.product_one.id})
        first_option_ids = {row['id'] for row in first['items']}
        self.assertTrue(
            {self.option_one_small.id, self.option_one_large.id}.issubset(first_option_ids)
        )
        self.assertEqual(len(first_option_ids), 3)
        self.assertEqual({row['product_id'] for row in second['items']}, {self.product_two.id})
        self.assertTrue(first['has_more'])
        self.assertFalse(second['has_more'])
        self.assertEqual(first['next_offset'], 1)

    def test_catalog_search_matches_size_or_unit_then_returns_all_variants(self):
        by_size = self.env['baseer.procurement.request'].catalog_page(
            'PRC pack 1kg', self.category.id, 0, 10
        )
        by_unit = self.env['baseer.procurement.request'].catalog_page(
            self.dozen.name, self.category.id, 0, 10
        )

        self.assertEqual(
            {row['id'] for row in by_size['items']},
            set(self.env['baseer.procurement.purchase.option'].search([
                ('product_id', '=', self.product_one.id),
                ('active', '=', True),
            ]).ids),
        )
        self.assertEqual(
            {row['id'] for row in by_unit['items']},
            set(self.env['baseer.procurement.purchase.option'].search([
                ('product_id', '=', self.product_two.id),
                ('active', '=', True),
            ]).ids),
        )
        self.assertIn(self.option_two_dozen.id, {row['id'] for row in by_unit['items']})
        with self.assertRaises(ValidationError):
            self.env['baseer.procurement.request'].catalog_page(
                'x' * 129, self.category.id, 0, 10
            )

    def test_previous_sent_request_opens_original_record_in_cashier_cart(self):
        request = self._request('PRC-SAME-CART', self.option_one_small)
        request.action_mark_sent()

        action = request.open_cashier_request(request.id)
        cart = request.cashier_request_cart(request.id)

        self.assertEqual(action['tag'], 'baseer_procurement_requests.catalog')
        self.assertEqual(action['params']['request_id'], request.id)
        self.assertEqual(cart['id'], request.id)
        self.assertEqual(cart['items'][0]['line_id'], request.line_ids.id)
