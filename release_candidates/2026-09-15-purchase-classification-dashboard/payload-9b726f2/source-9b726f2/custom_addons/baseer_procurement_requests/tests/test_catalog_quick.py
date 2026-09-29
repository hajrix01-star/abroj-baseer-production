from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase


class ProcurementCatalogQuickCase(TransactionCase):
    """Acceptance coverage for PRC-CATALOG-QUICK1."""

    def setUp(self):
        super().setUp()
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_cashier'
        )
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_manager'
        )
        self.company = self.env.company
        self.unit = self.env.ref('uom.product_uom_unit')
        self.warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        category_values = {'name': 'PRC quick standard category'}
        if 'property_cost_method' in self.env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in self.env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        self.category = self.env['product.category'].create(category_values)
        self.purchaser = self.env['hr.employee'].create({
            'name': 'PRC quick buyer', 'company_id': self.company.id,
        })
        self.Request = self.env['baseer.procurement.request']

    def _quick(self, name, price='7.25'):
        return self.Request.create_quick_catalog_product(name, price, self.category.id)

    def _complete(self, option, price='5.00'):
        request = self.Request.create({
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'purchaser_id': self.purchaser.id,
            'line_ids': [Command.create({
                'option_id': option.id,
                'requested_qty': 1,
                'requested_price': float(price),
            })],
        })
        request.action_mark_sent()
        request.line_ids.manager_received_qty = 1
        request.action_confirm_manager_receipt()
        request.line_ids.write({'actual_qty': 1, 'actual_price': float(price)})
        request.action_confirm_actual_purchase()
        return request

    def _draft(self, option, price='5.00'):
        return self.Request.create({
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'purchaser_id': self.purchaser.id,
            'line_ids': [Command.create({
                'option_id': option.id,
                'requested_qty': 1,
                'requested_price': float(price),
            })],
        })

    def test_quick_product_is_company_goods_nonstorable_and_adds_one_value(self):
        marker = uuid4().hex[:10]
        counts_before = {
            model: self.env[model].search_count([])
            for model in ('stock.move', 'stock.quant', 'account.move', 'product.value')
        }

        result = self._quick('PRC quick %s' % marker, '12.34')

        product = self.env['product.product'].browse(result['product_id'])
        option = self.env['baseer.procurement.purchase.option'].search([
            ('product_id', '=', product.id), ('catalog_default_key', '=', str(product.id)),
        ])
        self.assertTrue(result['created'])
        self.assertEqual(product.company_id, self.company)
        self.assertEqual(product.type, 'consu')
        self.assertFalse(product.is_storable)
        self.assertTrue(product.purchase_ok)
        self.assertFalse(product.sale_ok)
        self.assertEqual(product.uom_id, self.unit)
        self.assertAlmostEqual(product.with_company(self.company).standard_price, 12.34)
        self.assertEqual(len(option), 1)
        self.assertAlmostEqual(option.last_price, 12.34)
        self.assertEqual(self.env['product.value'].search_count([]), counts_before['product.value'] + 1)
        for model in ('stock.move', 'stock.quant', 'account.move'):
            self.assertEqual(self.env[model].search_count([]), counts_before[model])

    def test_unused_quick_product_can_be_deleted_from_standard_product_card(self):
        result = self._quick('PRC template delete %s' % uuid4().hex[:8], '12.34')
        product = self.env['product.product'].browse(result['product_id'])
        template = product.product_tmpl_id
        option = self.env['baseer.procurement.purchase.option'].search([
            ('product_id', '=', product.id),
        ])
        identity = self.env['baseer.procurement.product.identity'].sudo().search([
            ('product_id', '=', product.id),
        ])
        self.Request.set_catalog_favorite(product.id, True)
        favorite = self.env['baseer.procurement.product.favorite'].sudo().search([
            ('product_id', '=', product.id),
        ])
        product_id, template_id = product.id, template.id
        option_id, identity_id, favorite_id = option.id, identity.id, favorite.id
        operational_counts = {
            model: self.env[model].search_count([])
            for model in ('stock.move', 'stock.quant', 'account.move')
        }
        value_count = self.env['product.value'].search_count([])

        template.unlink()

        self.assertFalse(self.env['product.product'].with_context(active_test=False).browse(product_id).exists())
        self.assertFalse(self.env['product.template'].with_context(active_test=False).browse(template_id).exists())
        self.assertFalse(self.env['baseer.procurement.purchase.option'].browse(option_id).exists())
        self.assertFalse(self.env['baseer.procurement.product.identity'].sudo().browse(identity_id).exists())
        self.assertFalse(self.env['baseer.procurement.product.favorite'].sudo().browse(favorite_id).exists())
        self.assertEqual(self.env['product.value'].search_count([]), value_count)
        for model, count in operational_counts.items():
            self.assertEqual(self.env[model].search_count([]), count)

    def test_unused_quick_product_variant_can_be_deleted(self):
        result = self._quick('PRC variant delete %s' % uuid4().hex[:8], '8.00')
        product = self.env['product.product'].browse(result['product_id'])
        template_id = product.product_tmpl_id.id
        option = self.env['baseer.procurement.purchase.option'].search([
            ('product_id', '=', product.id),
        ])
        product.unlink()
        self.assertFalse(product.exists())
        self.assertFalse(self.env['product.template'].with_context(active_test=False).browse(template_id).exists())
        self.assertFalse(option.exists())

    def test_quick_product_used_in_draft_request_must_be_archived(self):
        result = self._quick('PRC used delete %s' % uuid4().hex[:8], '4.00')
        product = self.env['product.product'].browse(result['product_id'])
        option = self.env['baseer.procurement.purchase.option'].browse(result['items'][0]['id'])
        request = self._draft(option)

        with self.assertRaisesRegex(UserError, 'Archive it instead'):
            product.product_tmpl_id.unlink()

        self.assertTrue(product.exists())
        self.assertTrue(option.exists())
        self.assertTrue(request.exists())
        self.assertTrue(request.line_ids.exists())

    def test_quick_product_with_price_history_must_be_archived(self):
        result = self._quick('PRC history delete %s' % uuid4().hex[:8], '5.00')
        product = self.env['product.product'].browse(result['product_id'])
        option = self.env['baseer.procurement.purchase.option'].browse(result['items'][0]['id'])
        request = self._complete(option, '5.00')
        histories = self.env['baseer.procurement.price.history'].search([
            ('option_id', '=', option.id),
        ])
        self.assertTrue(histories)

        with self.assertRaisesRegex(UserError, 'Archive it instead'):
            product.unlink()

        self.assertTrue(product.exists())
        self.assertTrue(option.exists())
        self.assertTrue(request.exists())
        self.assertTrue(histories.exists())

    def test_mixed_template_delete_is_atomic(self):
        unused_result = self._quick('PRC mixed unused %s' % uuid4().hex[:8], '2.00')
        used_result = self._quick('PRC mixed used %s' % uuid4().hex[:8], '3.00')
        unused = self.env['product.product'].browse(unused_result['product_id'])
        used = self.env['product.product'].browse(used_result['product_id'])
        used_option = self.env['baseer.procurement.purchase.option'].browse(used_result['items'][0]['id'])
        self._draft(used_option)
        templates = unused.product_tmpl_id | used.product_tmpl_id
        option_ids = self.env['baseer.procurement.purchase.option'].search([
            ('product_id', 'in', (unused | used).ids),
        ]).ids

        with self.assertRaisesRegex(UserError, 'Archive it instead'):
            templates.unlink()

        self.assertTrue(unused.exists())
        self.assertTrue(used.exists())
        self.assertEqual(
            set(self.env['baseer.procurement.purchase.option'].browse(option_ids).exists().ids),
            set(option_ids),
        )

    def test_normalized_duplicate_reuses_eligible_and_rejects_ineligible(self):
        marker = uuid4().hex[:10]
        first = self._quick('PRC   Duplicate %s' % marker, '3.00')
        second = self._quick('  prc duplicate %s  ' % marker.upper(), '99.00')
        self.assertFalse(second['created'])
        self.assertEqual(second['product_id'], first['product_id'])
        product = self.env['product.product'].browse(first['product_id'])
        self.assertAlmostEqual(product.with_company(self.company).standard_price, 3.00)
        product.active = False
        with self.assertRaisesRegex(ValidationError, 'cannot be reused'):
            self._quick('PRC duplicate %s' % marker, '8.00')

    def test_only_cashier_can_quick_create_or_favorite(self):
        product_id = self._quick('PRC quick guarded %s' % uuid4().hex[:8])['product_id']
        cashier_group = self.env.ref('baseer_procurement_requests.group_procurement_cashier')
        requester_group = self.env.ref('baseer_procurement_requests.group_procurement_user')
        requester = self.env['res.users'].create({
            'name': 'PRC requester only',
            'login': 'prc-requester-%s' % uuid4().hex,
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set(requester_group.ids)],
        })
        self.assertNotIn(cashier_group, requester.group_ids)
        with self.assertRaises(AccessError):
            self.Request.with_user(requester).create_quick_catalog_product(
                'PRC forbidden %s' % uuid4().hex[:8], '1.00', self.category.id,
            )
        with self.assertRaises(AccessError):
            self.Request.with_user(requester).set_catalog_favorite(product_id, True)

    def test_favorite_is_idempotent_and_isolated_by_user(self):
        product_id = self._quick('PRC favorite %s' % uuid4().hex[:8])['product_id']
        cashier_group = self.env.ref('baseer_procurement_requests.group_procurement_cashier')
        second_user = self.env['res.users'].create({
            'name': 'PRC second cashier',
            'login': 'prc-cashier-%s' % uuid4().hex,
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set(cashier_group.ids)],
        })
        self.Request.set_catalog_favorite(product_id, True)
        self.Request.set_catalog_favorite(product_id, True)
        Favorite = self.env['baseer.procurement.product.favorite'].sudo()
        self.assertEqual(Favorite.search_count([
            ('user_id', '=', self.env.user.id), ('company_id', '=', self.company.id),
            ('product_id', '=', product_id),
        ]), 1)
        second_highlights = self.Request.with_user(second_user).catalog_highlights()
        self.assertNotIn(product_id, {row['product_id'] for row in second_highlights['items']})
        self.Request.set_catalog_favorite(product_id, False)
        self.Request.set_catalog_favorite(product_id, False)
        domain = [
            ('user_id', '=', self.env.user.id), ('company_id', '=', self.company.id),
            ('product_id', '=', product_id),
        ]
        self.assertEqual(Favorite.search_count(domain), 1)
        self.assertFalse(Favorite.search(domain).is_favorite)
        self.assertNotIn(
            product_id,
            {row['product_id'] for row in self.Request.catalog_highlights()['items']},
        )

    def test_favorite_rolls_back_with_outer_transaction(self):
        product_id = self._quick('PRC favorite rollback %s' % uuid4().hex[:8])['product_id']
        Favorite = self.env['baseer.procurement.product.favorite'].sudo()
        domain = [
            ('user_id', '=', self.env.user.id), ('company_id', '=', self.company.id),
            ('product_id', '=', product_id),
        ]
        with self.assertRaisesRegex(RuntimeError, 'injected outer failure'):
            with self.env.cr.savepoint():
                self.Request.set_catalog_favorite(product_id, True)
                raise RuntimeError('injected outer failure')
        self.assertFalse(Favorite.search(domain))

    def test_favorite_and_highlights_are_isolated_by_company(self):
        product_id = self._quick('PRC company one %s' % uuid4().hex[:8])['product_id']
        self.Request.set_catalog_favorite(product_id, True)
        other_company = self.env['res.company'].create({
            'name': 'PRC other company %s' % uuid4().hex[:8],
        })
        other_request = self.Request.with_company(other_company).with_context(
            allowed_company_ids=[other_company.id, self.company.id],
        )
        with self.assertRaises(AccessError):
            other_request.set_catalog_favorite(product_id, True)
        other_highlights = other_request.catalog_highlights()
        self.assertNotIn(product_id, {row['product_id'] for row in other_highlights['items']})

    def test_highlights_put_favorite_before_purchase_frequency(self):
        favorite_result = self._quick('PRC highlight favorite %s' % uuid4().hex[:8])
        frequent_result = self._quick('PRC highlight frequent %s' % uuid4().hex[:8])
        recent_result = self._quick('PRC highlight recent %s' % uuid4().hex[:8])
        Option = self.env['baseer.procurement.purchase.option']
        frequent_option = Option.browse(frequent_result['items'][0]['id'])
        recent_option = Option.browse(recent_result['items'][0]['id'])
        self._complete(frequent_option, '4.00')
        self._complete(frequent_option, '5.00')
        self._complete(recent_option, '6.00')
        self.Request.set_catalog_favorite(favorite_result['product_id'], True)

        highlights = self.Request.catalog_highlights(12)
        ordered_ids = []
        for row in highlights['items']:
            if row['product_id'] not in ordered_ids:
                ordered_ids.append(row['product_id'])
        favorite_index = ordered_ids.index(favorite_result['product_id'])
        frequent_index = ordered_ids.index(frequent_result['product_id'])
        recent_index = ordered_ids.index(recent_result['product_id'])
        self.assertLess(favorite_index, frequent_index)
        self.assertLess(frequent_index, recent_index)
        frequent_rows = [
            row for row in highlights['items'] if row['product_id'] == frequent_result['product_id']
        ]
        self.assertEqual(frequent_rows[0]['usage_count'], 2)

    def test_failure_after_product_create_rolls_back_everything(self):
        marker = 'PRC rollback %s' % uuid4().hex[:10]
        Product = self.env['product.product'].with_context(active_test=False)
        counts_before = {
            'product': Product.search_count([('company_id', '=', self.company.id)]),
            'option': self.env['baseer.procurement.purchase.option'].search_count([]),
            'value': self.env['product.value'].search_count([]),
        }
        with self.assertRaisesRegex(RuntimeError, 'injected quick-product failure'):
            with self.env.cr.savepoint():
                with patch.object(type(self.Request), '_default_options_for_products', autospec=True,
                                  side_effect=RuntimeError('injected quick-product failure')):
                    self._quick(marker, '9.00')
        self.assertEqual(Product.search_count([('company_id', '=', self.company.id)]), counts_before['product'])
        self.assertEqual(self.env['baseer.procurement.purchase.option'].search_count([]), counts_before['option'])
        self.assertEqual(self.env['product.value'].search_count([]), counts_before['value'])
