from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase


class ProcurementProductSourceCase(TransactionCase):
    """Acceptance coverage for PRC-PRODUCT-SOURCE1.

    The public cart remains option-based for backwards compatibility, but the
    catalogue is authoritative from eligible company-owned Odoo products.
    """

    def setUp(self):
        super().setUp()
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_manager'
        )
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_cashier'
        )
        self.company = self.env.company
        self.warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(self.warehouse)
        self.unit = self.env.ref('uom.product_uom_unit')
        category_values = {'name': 'PRC product-source periodic standard'}
        category_fields = self.env['product.category']._fields
        if 'property_cost_method' in category_fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in category_fields:
            category_values['property_valuation'] = 'periodic'
        self.category = self.env['product.category'].create(category_values)
        self.purchaser = self.env['hr.employee'].create({
            'name': 'PRC product-source buyer',
            'company_id': self.company.id,
        })

    def _product(self, name, *, storable=False, company=None, **values):
        product_values = {
            'name': name,
            'company_id': (company or self.company).id if company is not False else False,
            'categ_id': self.category.id,
            'uom_id': self.unit.id,
            'type': 'consu',
            'is_storable': storable,
            'purchase_ok': True,
            'sale_ok': False,
        }
        product_values.update(values)
        return self.env['product.product'].create(product_values)

    def _option(self, product, *, uom=None, packaging=False):
        return self.env['baseer.procurement.purchase.option'].create({
            'name': (uom or product.uom_id).name,
            'company_id': self.company.id,
            'product_id': product.id,
            'uom_id': (uom or product.uom_id).id,
            'packaging_note': packaging,
        })

    def _request(self, options, quantities=None, prices=None):
        quantities = quantities or [5] * len(options)
        prices = prices or [4] * len(options)
        return self.env['baseer.procurement.request'].create({
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'purchaser_id': self.purchaser.id,
            'line_ids': [
                Command.create({
                    'option_id': option.id,
                    'requested_qty': quantity,
                    'requested_price': price,
                })
                for option, quantity, price in zip(options, quantities, prices)
            ],
        })

    def _complete(self, request, quantities=None, prices=None):
        quantities = quantities or [5] * len(request.line_ids)
        prices = prices or [4] * len(request.line_ids)
        request.action_mark_sent()
        for line, quantity in zip(request.line_ids, quantities):
            line.manager_received_qty = quantity
        request.action_confirm_manager_receipt()
        for line, quantity, price in zip(request.line_ids, quantities, prices):
            line.write({'actual_qty': quantity, 'actual_price': price})
        request.action_confirm_actual_purchase()
        return request

    def _catalog_product_ids(self, search_term):
        page = self.env['baseer.procurement.request'].catalog_page(
            search_term, False, 0, 48,
        )
        return page, {row['product_id'] for row in page['items']}

    def test_catalog_uses_exact_company_products_and_creates_default_options(self):
        eligible_nonstorable = self._product(
            'PRC source catalog eligible nonstorable', storable=False,
        )
        eligible_nonstorable.with_company(self.company).standard_price = 4.75
        eligible_storable = self._product(
            'PRC source catalog eligible storable', storable=True,
        )
        shared = self._product(
            'PRC source catalog shared', company=False,
        )
        service = self._product(
            'PRC source catalog service', type='service', is_storable=False,
        )
        nonpurchase = self._product(
            'PRC source catalog nonpurchase', purchase_ok=False,
        )
        inactive = self._product(
            'PRC source catalog inactive', active=False,
        )
        self.assertFalse(self.env['baseer.procurement.purchase.option'].search([
            ('product_id', 'in', (eligible_nonstorable | eligible_storable).ids),
        ]))

        _page, product_ids = self._catalog_product_ids('PRC source catalog')

        self.assertEqual(
            product_ids,
            {eligible_nonstorable.id, eligible_storable.id},
        )
        self.assertFalse(
            {shared.id, service.id, nonpurchase.id, inactive.id} & product_ids
        )
        default_options = self.env['baseer.procurement.purchase.option'].search([
            ('company_id', '=', self.company.id),
            ('product_id', 'in', [eligible_nonstorable.id, eligible_storable.id]),
            ('uom_id', '=', self.unit.id),
        ])
        self.assertEqual(len(default_options), 2)
        self.assertAlmostEqual(
            default_options.filtered(
                lambda option: option.product_id == eligible_nonstorable
            ).last_price,
            4.75,
        )

        self._catalog_product_ids('PRC source catalog')
        self.assertEqual(self.env['baseer.procurement.purchase.option'].search_count([
            ('company_id', '=', self.company.id),
            ('product_id', 'in', [eligible_nonstorable.id, eligible_storable.id]),
            ('uom_id', '=', self.unit.id),
        ]), 2, 'Repeated catalogue reads must reuse the default option.')

    def test_catalog_stays_in_active_company_and_shared_product_is_rejected(self):
        other_company = self.env['res.company'].create({
            'name': 'PRC source other company',
            'currency_id': self.company.currency_id.id,
        })
        self.env.user.company_ids |= other_company
        own = self._product('PRC source company isolation own')
        other = self._product(
            'PRC source company isolation other', company=other_company,
        )
        shared = self._product(
            'PRC source company isolation shared', company=False,
        )
        Request = self.env['baseer.procurement.request'].with_context(
            allowed_company_ids=[self.company.id, other_company.id],
        )

        page = Request.catalog_page('PRC source company isolation', False, 0, 48)

        self.assertEqual({row['product_id'] for row in page['items']}, {own.id})
        self.assertNotIn(other.id, {row['product_id'] for row in page['items']})
        self.assertNotIn(shared.id, {row['product_id'] for row in page['items']})
        with self.assertRaisesRegex(ValidationError, 'selected company|belong'):
            self._option(shared)

    def test_quote_and_create_reject_ineligible_and_duplicate_product(self):
        product = self._product('PRC source guarded cart')
        default_option = self._option(product)
        package_option = self._option(product, packaging='Supplier pack')
        duplicate_product_rows = [
            {'option_id': default_option.id, 'quantity': 1},
            {'option_id': package_option.id, 'quantity': 1},
        ]
        Request = self.env['baseer.procurement.request']
        with self.assertRaisesRegex(ValidationError, 'material.*twice|product.*twice'):
            Request.quote_catalog_cart(duplicate_product_rows)
        with self.assertRaisesRegex(ValidationError, 'material.*twice|product.*twice'):
            Request.create_from_catalog(
                duplicate_product_rows,
                self.warehouse.id,
                self.purchaser.id,
                False,
                str(uuid4()),
            )

        product.purchase_ok = False
        unavailable = [{'option_id': default_option.id, 'quantity': 1}]
        with self.assertRaises(AccessError):
            Request.quote_catalog_cart(unavailable)
        with self.assertRaises(AccessError):
            Request.create_from_catalog(
                unavailable,
                self.warehouse.id,
                self.purchaser.id,
            )

    def test_nonstorable_purchase_has_history_cost_audit_and_no_stock_or_move(self):
        product = self._product('PRC source nonstorable completion')
        option = self._option(product)
        product.with_company(self.company).standard_price = 2.5
        request = self._request([option], quantities=[3], prices=[2.5])
        account_moves_before = self.env['account.move'].search_count([])
        product_values_before = self.env['product.value'].search_count([])

        self._complete(request, quantities=[3], prices=[7.25])

        self.assertEqual(request.state, 'purchased')
        self.assertFalse(request.picking_id)
        self.assertFalse(self.env['stock.picking'].search([
            ('origin', '=', request.name),
        ]))
        history = self.env['baseer.procurement.price.history'].search([
            ('request_id', '=', request.id),
        ])
        self.assertEqual(len(history), 1)
        self.assertEqual(history.purchase_uom_id, self.unit)
        self.assertEqual(history.inventory_uom_id, self.unit)
        self.assertAlmostEqual(history.inventory_unit_cost, 7.25)
        self.assertAlmostEqual(history.previous_standard_price, 2.5)
        self.assertAlmostEqual(history.new_standard_price, 7.25)
        self.assertFalse(history.stock_receipt_created)
        self.assertAlmostEqual(product.with_company(self.company).standard_price, 7.25)
        self.assertEqual(self.env['account.move'].search_count([]), account_moves_before)
        self.assertEqual(
            self.env['product.value'].search_count([]),
            product_values_before + 1,
        )

        request.action_confirm_actual_purchase()
        self.assertEqual(self.env['baseer.procurement.price.history'].search_count([
            ('request_id', '=', request.id),
        ]), 1)
        self.assertEqual(self.env['product.value'].search_count([]), product_values_before + 1)
        self.assertFalse(request.picking_id)

    def test_mixed_request_receives_only_storable_and_audits_both_costs(self):
        storable = self._product('PRC source mixed storable', storable=True)
        nonstorable = self._product('PRC source mixed nonstorable', storable=False)
        storable_option = self._option(storable)
        nonstorable_option = self._option(nonstorable)
        storable.with_company(self.company).standard_price = 1
        nonstorable.with_company(self.company).standard_price = 2
        request = self._request(
            [storable_option, nonstorable_option],
            quantities=[2, 3],
            prices=[1, 2],
        )
        account_moves_before = self.env['account.move'].search_count([])

        self._complete(request, quantities=[2, 3], prices=[5, 7])

        self.assertTrue(request.picking_id)
        self.assertEqual(request.picking_id.state, 'done')
        self.assertEqual(request.picking_id.move_ids.product_id, storable)
        histories = self.env['baseer.procurement.price.history'].search([
            ('request_id', '=', request.id),
        ])
        self.assertEqual(len(histories), 2)
        by_product = {history.product_id.id: history for history in histories}
        self.assertTrue(by_product[storable.id].stock_receipt_created)
        self.assertFalse(by_product[nonstorable.id].stock_receipt_created)
        self.assertAlmostEqual(storable.with_company(self.company).standard_price, 5)
        self.assertAlmostEqual(nonstorable.with_company(self.company).standard_price, 7)
        self.assertEqual(self.env['account.move'].search_count([]), account_moves_before)

    def test_storable_periodic_purchase_creates_one_receipt_and_cost_audit(self):
        product = self._product('PRC source storable completion', storable=True)
        option = self._option(product)
        product.with_company(self.company).standard_price = 1.5
        request = self._request([option], quantities=[4], prices=[1.5])
        account_moves_before = self.env['account.move'].search_count([])

        self._complete(request, quantities=[4], prices=[6.75])

        self.assertEqual(request.picking_id.state, 'done')
        self.assertEqual(request.picking_id.move_ids.product_id, product)
        history = self.env['baseer.procurement.price.history'].search([
            ('request_id', '=', request.id),
        ])
        self.assertEqual(len(history), 1)
        self.assertTrue(history.stock_receipt_created)
        self.assertAlmostEqual(history.previous_standard_price, 1.5)
        self.assertAlmostEqual(history.new_standard_price, 6.75)
        self.assertAlmostEqual(product.with_company(self.company).standard_price, 6.75)
        self.assertEqual(self.env['account.move'].search_count([]), account_moves_before)

        request.action_confirm_actual_purchase()
        self.assertEqual(self.env['stock.picking'].search_count([
            ('origin', '=', request.name),
        ]), 1)
        self.assertEqual(self.env['baseer.procurement.price.history'].search_count([
            ('request_id', '=', request.id),
        ]), 1)

    def test_purchase_uom_price_is_converted_to_inventory_uom_cost(self):
        dozen = self.env.ref('uom.product_uom_dozen', raise_if_not_found=False)
        if not dozen:
            self.skipTest('The standard dozen UoM is unavailable in this database.')
        product = self._product('PRC source dozen conversion')
        option = self._option(product, uom=dozen, packaging='12 units')
        product.with_company(self.company).standard_price = 3
        request = self._request([option], quantities=[1], prices=[100])
        expected_inventory_cost = float(Decimal(str(
            dozen._compute_price(100, self.unit)
        )).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

        self._complete(request, quantities=[1], prices=[100])

        history = self.env['baseer.procurement.price.history'].search([
            ('request_id', '=', request.id),
        ])
        self.assertAlmostEqual(history.unit_price, 100)
        self.assertEqual(history.purchase_uom_id, dozen)
        self.assertEqual(history.inventory_uom_id, self.unit)
        self.assertAlmostEqual(history.inventory_unit_cost, expected_inventory_cost, places=6)
        self.assertAlmostEqual(history.previous_standard_price, 3)
        self.assertAlmostEqual(history.new_standard_price, expected_inventory_cost, places=6)
        self.assertAlmostEqual(
            product.with_company(self.company).standard_price,
            expected_inventory_cost,
            places=6,
        )

    def test_used_option_identity_and_history_product_snapshot_are_immutable(self):
        product = self._product('PRC source immutable option')
        replacement = self._product('PRC source immutable replacement')
        option = self._option(product, packaging='Original pack')
        request = self._request([option], quantities=[1], prices=[2])

        with self.assertRaisesRegex(UserError, 'historically frozen'):
            option.write({'product_id': replacement.id})
        with self.assertRaisesRegex(UserError, 'historically frozen'):
            option.write({'packaging_note': 'Changed pack'})
        with self.assertRaises(AccessError):
            option.write({'last_price': 99})

        manager_group = self.env.ref(
            'baseer_procurement_requests.group_procurement_manager'
        )
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PRC forged-context manager',
            'login': 'prc.forged.context.manager',
            'company_id': self.company.id,
            'company_ids': [Command.set([self.company.id])],
            'group_ids': [Command.set([manager_group.id])],
        })
        with self.assertRaises(AccessError):
            option.with_user(manager).with_context(
                _baseer_procurement_option_system_write=True,
            ).write({'last_price': 101})

        self._complete(request, quantities=[1], prices=[6])
        history = self.env['baseer.procurement.price.history'].search([
            ('request_id', '=', request.id),
        ])
        self.assertEqual(history.product_id, product)
        self.assertFalse(history._fields['product_id'].related)

    def test_second_purchase_carries_precise_previous_cost(self):
        product = self._product('PRC source sequential cost')
        option = self._option(product)
        product.with_company(self.company).standard_price = 1.13

        first = self._request([option], quantities=[1], prices=[1])
        self._complete(first, quantities=[1], prices=[8.13])
        second = self._request([option], quantities=[1], prices=[8.13])
        self._complete(second, quantities=[1], prices=[9.38])

        first_history = self.env['baseer.procurement.price.history'].search([
            ('request_id', '=', first.id),
        ])
        second_history = self.env['baseer.procurement.price.history'].search([
            ('request_id', '=', second.id),
        ])
        self.assertAlmostEqual(first_history.previous_standard_price, 1.13, places=2)
        self.assertAlmostEqual(first_history.new_standard_price, 8.13, places=2)
        self.assertAlmostEqual(second_history.previous_standard_price, 8.13, places=2)
        self.assertAlmostEqual(second_history.new_standard_price, 9.38, places=2)

    def test_injected_history_failure_rolls_back_receipt_cost_and_state(self):
        product = self._product('PRC source rollback after effects', storable=True)
        option = self._option(product)
        product.with_company(self.company).standard_price = 2.13
        request = self._request([option], quantities=[1], prices=[2])
        request.action_mark_sent()
        request.line_ids.manager_received_qty = 1
        request.action_confirm_manager_receipt()
        request.line_ids.write({'actual_qty': 1, 'actual_price': 7.875})
        HistoryModel = type(self.env['baseer.procurement.price.history'])

        with self.assertRaisesRegex(UserError, 'Injected history failure'):
            with self.env.cr.savepoint():
                with patch.object(
                    HistoryModel,
                    'create',
                    side_effect=UserError('Injected history failure'),
                ):
                    request.action_confirm_actual_purchase()

        request.invalidate_recordset()
        product.invalidate_recordset()
        option.invalidate_recordset()
        self.assertEqual(request.state, 'received')
        self.assertFalse(request.picking_id)
        self.assertFalse(self.env['stock.picking'].search([
            ('origin', '=', request.name),
        ]))
        self.assertFalse(self.env['baseer.procurement.price.history'].search([
            ('request_id', '=', request.id),
        ]))
        self.assertAlmostEqual(product.with_company(self.company).standard_price, 2.13, places=2)
        self.assertFalse(option.last_price_at)

    def test_nonstandard_and_real_time_policies_reject_before_any_effect(self):
        category_fields = self.category._fields
        if 'property_cost_method' not in category_fields:
            self.skipTest('Cost methods are unavailable in this database.')
        product = self._product('PRC source rejected policy', storable=True)
        option = self._option(product)
        product.with_company(self.company).standard_price = 2

        def assert_rejected_without_effect(request, expected):
            account_moves_before = self.env['account.move'].search_count([])
            product_values_before = self.env['product.value'].search_count([])
            with self.assertRaisesRegex((UserError, ValidationError), expected):
                self._complete(request, quantities=[1], prices=[9])
            self.assertEqual(request.state, 'received')
            self.assertFalse(request.picking_id)
            self.assertFalse(self.env['baseer.procurement.price.history'].search([
                ('request_id', '=', request.id),
            ]))
            self.assertAlmostEqual(product.with_company(self.company).standard_price, 2)
            self.assertEqual(self.env['product.value'].search_count([]), product_values_before)
            self.assertEqual(self.env['account.move'].search_count([]), account_moves_before)

        self.category.property_cost_method = 'fifo'
        assert_rejected_without_effect(
            self._request([option], quantities=[1], prices=[2]),
            'standard',
        )

        self.category.property_cost_method = 'standard'
        if 'property_valuation' not in category_fields:
            return
        self.category.property_valuation = 'real_time'
        assert_rejected_without_effect(
            self._request([option], quantities=[1], prices=[2]),
            'periodic|manual|real.?time',
        )
