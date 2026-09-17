from odoo.tests.common import TransactionCase
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from datetime import timedelta
from uuid import uuid4


class ProcurementFlowCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_manager')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_cashier')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_accountant')
        self.env.user.group_ids |= self.env.ref('account.group_account_invoice')
        self.company = self.env.company
        self.warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        self.uom = self.env.ref('uom.product_uom_unit')
        category_values = {'name': 'PRC QA quantity only'}
        if 'property_cost_method' in self.env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in self.env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        self.category = self.env['product.category'].create(category_values)
        self.product = self.env['product.product'].create({
            'name': 'PRC tomato', 'categ_id': self.category.id, 'uom_id': self.uom.id,
            'is_storable': True, 'company_id': self.company.id,
        })
        self.option = self.env['baseer.procurement.purchase.option'].create({
            'name': 'Piece', 'company_id': self.company.id, 'product_id': self.product.id,
            'uom_id': self.uom.id,
        })
        self.purchaser = self.env['hr.employee'].create({'name': 'PRC standard buyer', 'company_id': self.company.id})

    def _request(self):
        return self.env['baseer.procurement.request'].create({
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'purchaser_id': self.purchaser.id,
            'line_ids': [(0, 0, {'option_id': self.option.id, 'requested_qty': 5, 'requested_price': 4})],
        })

    def _native_batch_accounting_fixture(self, company, expense, supplier):
        """Supply native journal/account and analytics for productless bills."""
        env = self.env(context={**self.env.context, 'allowed_company_ids': company.ids})
        env['account.journal'].create({
            'name': 'PRC native batch purchases', 'code': 'PRCNP', 'type': 'purchase',
            'company_id': company.id, 'sequence': -100, 'default_account_id': expense.id,
        })
        payable = env['account.account'].create({
            'name': 'PRC native supplier payable', 'code': 'PRCNP210',
            'account_type': 'liability_payable', 'reconcile': True,
            'company_ids': [Command.set(company.ids)],
        })
        supplier.with_env(env).property_account_payable_id = payable
        spend_plan = env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        if spend_plan:
            analytic = env['account.analytic.account'].create({
                'name': 'PRC native batch spend', 'plan_id': spend_plan.id, 'company_id': company.id,
            })
            env['account.analytic.distribution.model'].create({
                'partner_id': supplier.id, 'company_id': company.id,
                'analytic_distribution': {str(analytic.id): 100},
            })

    def _custody_accounting_fixture(self, code_prefix='PRC9', company=None):
        """Create only the native accounting primitives used by custody tests."""
        company = company or self.company
        env = self.env(context={**self.env.context, 'allowed_company_ids': company.ids})
        # account.journal.code is limited to five characters.  Use distinct
        # compact codes; longer descriptive prefixes are silently truncated
        # by Odoo and would otherwise collide inside one test transaction.
        journal_suffix = code_prefix[-3:].upper()
        Account = env['account.account']
        custody_account = Account.create({
            'name': '%s custody receivable' % code_prefix,
            'code': '%s01' % code_prefix,
            'account_type': 'asset_receivable',
            'reconcile': True,
            'company_ids': [Command.set(company.ids)],
        })
        cash_account = Account.create({
            'name': '%s cash' % code_prefix,
            'code': '%s02' % code_prefix,
            'account_type': 'asset_cash',
            'company_ids': [Command.set(company.ids)],
        })
        bank_account = Account.create({
            'name': '%s bank' % code_prefix,
            'code': '%s03' % code_prefix,
            'account_type': 'asset_cash',
            'company_ids': [Command.set(company.ids)],
        })
        journal = env['account.journal'].create({
            'name': '%s custody entries' % code_prefix,
            'code': 'J%s' % journal_suffix,
            'type': 'general',
            'company_id': company.id,
        })
        cash = env['account.journal'].create({
            'name': '%s cash journal' % code_prefix,
            'code': 'C%s' % journal_suffix,
            'type': 'cash',
            'company_id': company.id,
            'default_account_id': cash_account.id,
        })
        bank = env['account.journal'].create({
            'name': '%s bank journal' % code_prefix,
            'code': 'B%s' % journal_suffix,
            'type': 'bank',
            'company_id': company.id,
            'default_account_id': bank_account.id,
        })
        company.write({
            'baseer_procurement_custody_account_id': custody_account.id,
            'baseer_procurement_custody_journal_id': journal.id,
        })
        return custody_account, cash_account, bank_account, journal, cash, bank

    def _complete_request(self, actual_quantity=5, actual_price=4):
        request = self._request()
        request.action_mark_sent()
        request.line_ids.manager_received_qty = actual_quantity
        request.action_confirm_manager_receipt()
        request.line_ids.write({'actual_qty': actual_quantity, 'actual_price': actual_price})
        request.action_confirm_actual_purchase()
        return request

    def _complete_external_request(self, representative, actual_quantity=5, actual_price=4):
        """Completed receipt for shared-pool custody funding tests."""
        representative.with_company(self.company).write({'is_purchase_representative': True})
        request = self.env['baseer.procurement.request'].create({
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'representative_partner_id': representative.id,
            'line_ids': [Command.create({
                'option_id': self.option.id,
                'requested_qty': actual_quantity,
                'requested_price': actual_price,
            })],
        })
        request.action_mark_sent()
        request.line_ids.manager_received_qty = actual_quantity
        request.action_confirm_manager_receipt()
        request.line_ids.write({'actual_qty': actual_quantity, 'actual_price': actual_price})
        request.action_confirm_actual_purchase()
        return request

    def _complete_company_request(self, company, purchaser, actual_quantity=5, actual_price=4):
        env = self.env(context={**self.env.context, 'allowed_company_ids': company.ids})
        warehouse = env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
        if not warehouse:
            warehouse = env['stock.warehouse'].create({
                'name': 'PRC header test warehouse', 'code': 'PRCHW', 'company_id': company.id,
            })
        self.assertTrue(warehouse)
        category_values = {'name': 'PRC header quantity category'}
        if 'property_cost_method' in env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        category = env['product.category'].create(category_values)
        product = env['product.product'].create({
            'name': 'PRC header quantity product',
            'company_id': company.id,
            'categ_id': category.id,
            'uom_id': self.uom.id,
            'is_storable': True,
        })
        option = env['baseer.procurement.purchase.option'].create({
            'name': 'Piece',
            'company_id': company.id,
            'product_id': product.id,
            'uom_id': self.uom.id,
        })
        request = env['baseer.procurement.request'].create({
            'company_id': company.id,
            'warehouse_id': warehouse.id,
            'purchaser_id': purchaser.id,
            'line_ids': [Command.create({
                'option_id': option.id,
                'requested_qty': actual_quantity,
                'requested_price': actual_price,
            })],
        })
        request.action_mark_sent()
        request.line_ids.manager_received_qty = actual_quantity
        request.action_confirm_manager_receipt()
        request.line_ids.write({'actual_qty': actual_quantity, 'actual_price': actual_price})
        request.action_confirm_actual_purchase()
        return request

    def test_quantity_receipt_creates_one_picking_and_price_history(self):
        request = self._request()
        request.action_mark_sent()
        with self.assertRaisesRegex(Exception, 'cannot be deleted'):
            request.unlink()
        with self.assertRaisesRegex(Exception, 'cannot be deleted'):
            request.line_ids.unlink()
        with self.assertRaisesRegex(Exception, 'cannot exceed'):
            request.line_ids.manager_received_qty = 6
        request.line_ids.manager_received_qty = 4
        request.action_confirm_manager_receipt()
        actual_quote = request.quote_actual_cart(request.id, [{
            'line_id': request.line_ids.id, 'actual_qty': '4.00', 'actual_price': '5.00',
        }])
        self.assertEqual(actual_quote['total'], '20.00')
        self.assertEqual(actual_quote['lines'][0]['line_total_text'], '20.00')
        request.line_ids.write({'actual_qty': 4, 'actual_price': 5})
        self.assertEqual(request.line_ids.manager_shortage_qty, 1)
        self.assertEqual(request.line_ids.cashier_shortage_qty, 0)
        request.action_confirm_actual_purchase()
        self.assertEqual(request.state, 'purchased')
        self.assertEqual(request.picking_id.state, 'done')
        self.assertEqual(len(self.env['baseer.procurement.price.history'].search([('request_id', '=', request.id)])), 1)
        self.assertEqual(self.option.last_price, 5)
        request.action_confirm_actual_purchase()
        self.assertEqual(len(self.env['stock.picking'].search([('origin', '=', request.name)])), 1)

    def test_request_create_cannot_bypass_receipt_workflow(self):
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.request'].create({
                'company_id': self.company.id, 'warehouse_id': self.warehouse.id, 'purchaser_id': self.purchaser.id,
                'state': 'purchased',
            })
        request = self._request()
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.request.line'].create({
                'request_id': request.id, 'option_id': self.option.id, 'requested_qty': 1,
                'actual_qty': 1, 'actual_price': 4,
            })
        catalog_request_id = self.env['baseer.procurement.request'].create_from_catalog(
            [{'option_id': self.option.id, 'quantity': 2}], self.warehouse.id, self.purchaser.id,
        )
        catalog_request = self.env['baseer.procurement.request'].browse(catalog_request_id)
        self.assertEqual(catalog_request.state, 'draft')
        self.assertEqual(catalog_request.requester_id, self.env.user)
        self.assertEqual(catalog_request.line_ids.requested_qty, 2)
        self.assertIn(self.option.id, [row['id'] for row in self.env['baseer.procurement.request'].catalog_options('tomato')])

    def test_whatsapp_can_be_resent_during_every_active_request_stage(self):
        self.product.name = '[NOORIX-D6FF9A261F210586] PRC tomato'
        request = self._request()
        self.assertNotIn(request.name, request.whatsapp_text)
        self.assertNotIn('[NOORIX-D6FF9A261F210586]', request.whatsapp_text)
        self.assertIn('طلب مشتريات — %s' % self.company.name, request.whatsapp_text)
        self.assertIn('التاريخ:', request.whatsapp_text)
        self.assertNotIn('مندوب المشتريات:', request.whatsapp_text)
        self.assertNotIn('PRC standard buyer', request.whatsapp_text)
        self.assertIn('PRC tomato (Piece): 5.00 × 4.00 = 20.00', request.whatsapp_text)
        self.assertIn('الإجمالي التقديري:', request.whatsapp_text)

        def assert_share_keeps_stage(expected_state):
            action = request.action_open_whatsapp()
            self.assertEqual(request.state, expected_state)
            self.assertEqual(action['type'], 'ir.actions.act_url')
            self.assertIn('wa.me/?text=', action['url'])
            self.assertTrue(request.whatsapp_opened_at)

        assert_share_keeps_stage('draft')
        request.action_mark_sent()
        assert_share_keeps_stage('sent')
        request.line_ids.manager_received_qty = 5
        request.action_confirm_manager_receipt()
        assert_share_keeps_stage('received')
        request.line_ids.write({'actual_qty': 5, 'actual_price': 4})
        request.action_confirm_actual_purchase()
        assert_share_keeps_stage('purchased')

        cancelled = self._request()
        cancelled.cancellation_reason = 'PRC test cancellation'
        cancelled.action_cancel()
        with self.assertRaises(UserError):
            cancelled.action_open_whatsapp()

    def test_cashier_quote_accepts_sent_request_with_actual_price(self):
        """A cashier can price a sent request before the guarded confirmation."""
        request = self._request()
        request.action_mark_sent()
        quote = request.quote_actual_cart(request.id, [{
            'line_id': request.line_ids.id, 'actual_qty': '5.00', 'actual_price': '7.25',
        }])
        self.assertEqual(quote['total'], '36.25')
        self.assertEqual(quote['lines'][0]['unit_price'], '7.25')
        self.assertEqual(request.state, 'sent')
        self.assertFalse(request.picking_id)

    def test_cashier_confirms_sent_request_with_actual_price(self):
        """A sent request can be priced and received from its cashier cart."""
        request = self._request()
        request.action_mark_sent()

        request.confirm_actual_from_catalog(
            request.id,
            [{
                'line_id': request.line_ids.id,
                'actual_qty': '5.00',
                'actual_price': '7.25',
            }],
        )

        self.assertEqual(request.state, 'purchased')
        self.assertEqual(request.picking_id.state, 'done')
        self.assertEqual(request.line_ids.actual_price, 7.25)

    def test_cashier_confirmation_rejects_request_outside_active_company(self):
        """Allowed companies must not widen the cashier RPC's active company."""
        other_company = self.env['res.company'].create({
            'name': 'PRC cashier isolation company',
            'currency_id': self.company.currency_id.id,
        })
        self.env.user.company_ids |= other_company
        other_env = self.env(context={
            **self.env.context,
            'allowed_company_ids': [other_company.id, self.company.id],
        })
        other_warehouse = other_env['stock.warehouse'].search([
            ('company_id', '=', other_company.id),
        ], limit=1)
        self.assertTrue(other_warehouse)
        other_product = other_env['product.product'].create({
            'name': 'PRC isolated material',
            'company_id': other_company.id,
            'categ_id': self.category.id,
            'uom_id': self.uom.id,
            'is_storable': True,
        })
        other_option = other_env['baseer.procurement.purchase.option'].create({
            'name': 'Isolated piece',
            'company_id': other_company.id,
            'product_id': other_product.id,
            'uom_id': self.uom.id,
        })
        other_purchaser = other_env['hr.employee'].create({
            'name': 'PRC isolated buyer',
            'company_id': other_company.id,
        })
        other_request = other_env['baseer.procurement.request'].create({
            'company_id': other_company.id,
            'warehouse_id': other_warehouse.id,
            'purchaser_id': other_purchaser.id,
            'line_ids': [Command.create({
                'option_id': other_option.id,
                'requested_qty': 2,
                'requested_price': 3,
            })],
        })
        other_request.action_mark_sent()

        active_company_request = self.env['baseer.procurement.request'].with_context(
            allowed_company_ids=[self.company.id, other_company.id],
        )
        with self.assertRaisesRegex(AccessError, 'active company'):
            active_company_request.confirm_actual_from_catalog(other_request.id, [{
                'line_id': other_request.line_ids.id,
                'actual_qty': '2.00',
                'actual_price': '3.00',
            }])

        other_request.invalidate_recordset()
        self.assertEqual(other_request.state, 'sent')
        self.assertFalse(other_request.picking_id)
        self.assertEqual(other_request.line_ids.manager_received_qty, 0)

    def test_cashier_can_mark_a_request_line_not_received(self):
        """A zero-quantity original line remains in the guarded cart without a price."""
        second_product = self.env['product.product'].create({
            'name': 'PRC missing material', 'categ_id': self.category.id, 'uom_id': self.uom.id,
            'is_storable': True, 'company_id': self.company.id,
        })
        second_option = self.env['baseer.procurement.purchase.option'].create({
            'name': 'Piece', 'company_id': self.company.id, 'product_id': second_product.id,
            'uom_id': self.uom.id,
        })
        request = self.env['baseer.procurement.request'].create({
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'purchaser_id': self.purchaser.id,
            'line_ids': [
                Command.create({'option_id': self.option.id, 'requested_qty': 5, 'requested_price': 4}),
                Command.create({'option_id': second_option.id, 'requested_qty': 2, 'requested_price': 0}),
            ],
        })
        request.action_mark_sent()

        request.confirm_actual_from_catalog(request.id, [
            {'line_id': request.line_ids[0].id, 'actual_qty': '5.00', 'actual_price': '7.25'},
            {'line_id': request.line_ids[1].id, 'actual_qty': '0.00', 'actual_price': '0.00'},
        ])

        self.assertEqual(request.state, 'purchased')
        self.assertEqual(len(request.picking_id.move_ids), 1)
        self.assertEqual(request.line_ids[1].actual_qty, 0)
        self.assertEqual(request.line_ids[1].actual_price, 0)
    def test_pos_catalog_page_quote_and_idempotent_create(self):
        self.option.with_context(
            _baseer_procurement_option_system_write=True,
        ).write({'last_price': 0.01})
        categories = [self.category] + list(self.env['product.category'].create([
            {'name': 'PRC POS category %s' % index} for index in range(1, 12)
        ]))
        products = [self.product] + list(self.env['product.product'].create([
            {'name': 'PRC POS product %s' % index, 'categ_id': categories[index].id,
             'uom_id': self.uom.id, 'is_storable': True, 'company_id': self.company.id}
            for index in range(1, 12)
        ]))
        extra_options = []
        for category_index, product in enumerate(products):
            for option_index in range(100):
                extra_options.append({
                    'name': 'Piece %s' % option_index,
                    'company_id': self.company.id,
                    'product_id': product.id,
                    'uom_id': self.uom.id,
                    'packaging_note': 'Category %s pack %s' % (category_index, option_index),
                })
        self.env['baseer.procurement.purchase.option'].create(extra_options)
        first = self.env['baseer.procurement.request'].catalog_page('PRC POS product', False, 0, 1)
        second = self.env['baseer.procurement.request'].catalog_page(
            'PRC POS product', False, first['next_offset'], 1,
        )
        self.assertEqual(len(first['items']), 101)
        self.assertTrue(first['has_more'])
        self.assertEqual({row['product_id'] for row in first['items']}, {products[1].id})
        self.assertFalse(set(row['product_id'] for row in first['items']) & set(row['product_id'] for row in second['items']))
        self.assertIn('image_url', first['items'][0])
        self.assertEqual(first['items'][0]['image_url'], '')
        categories = self.env['baseer.procurement.request'].catalog_categories()
        self.assertIn(self.category.id, [row['id'] for row in categories])

        quote = self.env['baseer.procurement.request'].quote_catalog_cart([
            {'option_id': self.option.id, 'quantity': '3.00'},
        ])
        self.assertEqual(quote['lines'][0]['line_total'], '0.03')
        self.assertEqual(quote['total_text'], '0.03')
        self.assertTrue(all(character.isascii() for character in quote['total_text']))
        with self.assertRaisesRegex(Exception, 'twice'):
            self.env['baseer.procurement.request'].quote_catalog_cart([
                {'option_id': self.option.id, 'quantity': '1'},
                {'option_id': self.option.id, 'quantity': '1'},
            ])
        with self.assertRaisesRegex(Exception, 'decimal places'):
            self.env['baseer.procurement.request'].quote_catalog_cart([
                {'option_id': self.option.id, 'quantity': '1.001'},
            ])

        token = str(uuid4())
        values = [{'option_id': self.option.id, 'quantity': '3.00'}]
        first_id = self.env['baseer.procurement.request'].create_from_catalog(
            values, self.warehouse.id, self.purchaser.id, False, token,
        )
        second_id = self.env['baseer.procurement.request'].create_from_catalog(
            values, self.warehouse.id, self.purchaser.id, False, token,
        )
        self.assertEqual(first_id, second_id)
        self.assertEqual(self.env['baseer.procurement.request'].search_count([('client_token', '=', token)]), 1)
        with self.assertRaisesRegex(Exception, 'different request details'):
            self.env['baseer.procurement.request'].create_from_catalog(
                [{'option_id': self.option.id, 'quantity': '4.00'}],
                self.warehouse.id, self.purchaser.id, False, token,
            )

    def test_non_finite_quantities_and_prices_are_rejected(self):
        request = self._request()
        with self.assertRaises(Exception):
            request.line_ids.write({'requested_qty': float('inf')})
        request.action_mark_sent()
        with self.assertRaises(Exception):
            request.line_ids.write({'manager_received_qty': float('nan')})
        request.line_ids.manager_received_qty = 4
        request.action_confirm_manager_receipt()
        with self.assertRaisesRegex(Exception, 'invalid'):
            request.confirm_actual_from_catalog(request.id, [{
                'line_id': request.line_ids.id, 'actual_qty': 4, 'actual_price': float('inf'),
            }])
        with self.assertRaisesRegex(Exception, 'positive quantity'):
            self.env['baseer.procurement.request'].create_from_catalog(
                [{'option_id': self.option.id, 'quantity': float('nan')}], self.warehouse.id, self.purchaser.id,
            )

    def test_sent_request_requires_reasoned_cancellation_before_receipt(self):
        request = self._request()
        request.action_mark_sent()
        with self.assertRaisesRegex(Exception, 'cancellation reason'):
            request.action_cancel()
        request.write({'cancellation_reason': 'Supplier unavailable'})
        request.action_cancel()
        self.assertEqual(request.state, 'cancel')
        with self.assertRaisesRegex(Exception, 'current request state'):
            request.action_confirm_manager_receipt()

    def test_cashier_can_confirm_only_through_guarded_workflow(self):
        cashier_group = self.env.ref('baseer_procurement_requests.group_procurement_cashier')
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PRC restricted cashier', 'login': 'prc.restricted.cashier',
            'company_id': self.company.id, 'company_ids': [Command.set([self.company.id])],
            'group_ids': [Command.set([cashier_group.id])],
        })
        request = self._request()
        request.action_mark_sent()
        request.line_ids.manager_received_qty = 4
        request.action_confirm_manager_receipt()
        with self.assertRaises(AccessError):
            self.option.with_user(cashier).write({'last_price': 999})
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.price.history'].with_user(cashier).create({
                'company_id': self.company.id, 'option_id': self.option.id, 'request_id': request.id,
                'line_id': request.line_ids.id, 'purchase_date': fields.Datetime.now(), 'unit_price': 5, 'quantity': 1,
            })
        request.line_ids.with_user(cashier).write({'actual_qty': 4, 'actual_price': 5})
        request.with_user(cashier).action_confirm_actual_purchase()
        self.assertEqual(request.state, 'purchased')
        self.assertEqual(self.option.last_price, 5)

    def test_real_time_material_is_refused(self):
        if 'property_valuation' not in self.category._fields:
            self.skipTest('stock_account is not installed in this quantity-only QA database')
        request = self._request()
        request.action_mark_sent()
        request.line_ids.manager_received_qty = 1
        request.action_confirm_manager_receipt()
        request.line_ids.write({'actual_qty': 1, 'actual_price': 5})
        self.category.property_valuation = 'real_time'
        with self.assertRaisesRegex(Exception, 'Quantity-only'):
            request.action_confirm_actual_purchase()

    def test_custody_funding_creates_a_native_balanced_entry(self):
        account_model = self.env['account.account']
        custody_account = account_model.create({
            'name': 'PRC custody receivable', 'code': 'PRC901', 'account_type': 'asset_receivable',
            'reconcile': True, 'company_ids': [(6, 0, self.company.ids)],
        })
        cash_account = account_model.create({
            'name': 'PRC test cash', 'code': 'PRC902', 'account_type': 'asset_cash',
            'company_ids': [(6, 0, self.company.ids)],
        })
        general = self.env['account.journal'].create({
            'name': 'PRC custody entries', 'code': 'PRCJ', 'type': 'general', 'company_id': self.company.id,
        })
        cash = self.env['account.journal'].create({
            'name': 'PRC cash', 'code': 'PRCC', 'type': 'cash', 'company_id': self.company.id,
            'default_account_id': cash_account.id,
        })
        self.company.write({
            'baseer_procurement_custody_account_id': custody_account.id,
            'baseer_procurement_custody_journal_id': general.id,
        })
        employee = self.env['hr.employee'].create({'name': 'PRC buyer', 'company_id': self.company.id})
        custody = self.env['baseer.procurement.custody'].create({'company_id': self.company.id, 'employee_id': employee.id})
        event = self.env['baseer.procurement.custody.event'].create({
            'custody_id': custody.id, 'event_type': 'funding', 'amount': 2200,
            'cash_journal_id': cash.id, 'reference': 'QA transfer',
        })
        event.action_post()
        self.assertEqual(event.state, 'posted')
        self.assertEqual(event.move_id.state, 'posted')
        self.assertEqual(custody.funded_amount, 2200)
        self.assertEqual(custody.balance, 2200)
        self.assertEqual(sum(event.move_id.line_ids.mapped('debit')), sum(event.move_id.line_ids.mapped('credit')))
        rpc_user = self.env['res.users'].create({
            'name': 'PRC forged-link RPC user', 'login': 'prc-forged-link-rpc',
            'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('account.group_account_invoice').id])],
        })
        with self.assertRaisesRegex(Exception, 'controlled by the server'):
            self.env['account.move'].with_user(rpc_user).with_context(baseer_procurement_custody_internal=True).create({
                'move_type': 'entry', 'company_id': self.company.id, 'journal_id': general.id,
                'line_ids': [Command.create({
                    'name': 'forged custody link', 'account_id': custody_account.id,
                    'baseer_procurement_custody_id': custody.id,
                })],
            })
        with self.assertRaisesRegex(Exception, 'controlled by the server'):
            self.env['baseer.procurement.custody.event'].create({
                'custody_id': custody.id, 'event_type': 'funding', 'amount': 1,
                'cash_journal_id': cash.id, 'reference': 'forged', 'state': 'posted',
            })
        excessive_return = self.env['baseer.procurement.custody.event'].create({
            'custody_id': custody.id, 'event_type': 'return', 'amount': 2201,
            'cash_journal_id': cash.id, 'reference': 'invalid return',
        })
        with self.assertRaisesRegex(Exception, 'cannot exceed'):
            excessive_return.action_post()

    def test_external_representative_custody_posts_bank_funding_and_cash_return(self):
        """PRC-CUSTODY2 keeps external representatives out of employees/suppliers.

        Funding and return are two independently posted internal transfers:
        bank -> purchasing custody, then purchasing custody -> cash.  The
        posted source documents must identify the contact and respect the
        accountant-only and locked-period controls.
        """
        custody_account, cash_account, bank_account, _general, cash, bank = self._custody_accounting_fixture('PRC93')
        representative = self.env['res.partner'].create({
            'name': 'PRC external purchasing representative',
            'company_id': self.company.id,
            'is_purchase_representative': True,
        })
        individual_custody = self.env['baseer.procurement.custody'].create({
            'company_id': self.company.id,
            'representative_partner_id': representative.id,
        })
        with self.assertRaisesRegex(ValidationError, 'exactly one'):
            individual_custody.write({'employee_id': self.purchaser.id})
        custody = self.env['baseer.procurement.custody'].create({
            'company_id': self.company.id,
            'is_company_pool': True,
        })
        with self.assertRaisesRegex(ValidationError, 'already exists'):
            self.env['baseer.procurement.custody'].create({
                'company_id': self.company.id,
                'is_company_pool': True,
            })
        other_company = self.env['res.company'].create({
            'name': 'PRC custody foreign company',
            'currency_id': self.company.currency_id.id,
        })
        with self.env.cr.savepoint():
            with self.assertRaises(Exception):
                self.env['baseer.procurement.custody'].with_context(
                    allowed_company_ids=[self.company.id, other_company.id]
                ).create({
                    'company_id': other_company.id,
                    'representative_partner_id': representative.id,
                })

        funding = self.env['baseer.procurement.custody.event'].create({
            'custody_id': custody.id,
            'event_type': 'funding',
            'event_date': fields.Date.context_today(self),
            'amount': 2000,
            'cash_journal_id': bank.id,
            'representative_partner_id': representative.id,
            'procurement_request_id': self._complete_external_request(representative).id,
            'reference': 'PRC external bank transfer',
        })
        manager_only = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PRC custody manager only',
            'login': 'prc.custody.manager.only',
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('baseer_procurement_requests.group_procurement_manager').id,
                self.env.ref('account.group_account_invoice').id,
            ])],
        })
        with self.assertRaises(AccessError):
            funding.with_user(manager_only).action_post()
        funding.action_post()
        self.assertEqual(funding.move_id.state, 'posted')
        self.assertEqual(custody.balance, 2000)
        funding_custody_line = funding.move_id.line_ids.filtered(
            lambda line: line.account_id == custody_account
        )
        self.assertEqual(funding_custody_line.partner_id, representative.commercial_partner_id)
        self.assertEqual(sum(funding.move_id.line_ids.filtered(
            lambda line: line.account_id == bank_account
        ).mapped('credit')), 2000)

        returned = self.env['baseer.procurement.custody.event'].create({
            'custody_id': custody.id,
            'event_type': 'return',
            'event_date': fields.Date.context_today(self),
            'amount': 300,
            'cash_journal_id': cash.id,
            'representative_partner_id': representative.id,
            'reference': 'PRC external cash return',
        })
        returned.action_post()
        self.assertEqual(custody.balance, 1700)
        self.assertEqual(sum(returned.move_id.line_ids.filtered(
            lambda line: line.account_id == cash_account
        ).mapped('debit')), 300)

        locked = self.env['baseer.procurement.custody.event'].create({
            'custody_id': custody.id,
            'event_type': 'return',
            'event_date': fields.Date.context_today(self),
            'amount': 1,
            'cash_journal_id': bank.id,
            'representative_partner_id': representative.id,
            'reference': 'PRC locked-period return',
        })
        self.company.write({'fiscalyear_lock_date': fields.Date.context_today(self)})
        with self.assertRaisesRegex(ValidationError, 'locked'):
            locked.action_post()
        self.assertEqual(locked.state, 'draft')
        self.assertFalse(locked.move_id)

    def test_shared_pool_funding_is_request_locked_and_legacy_identity_is_immutable(self):
        """One completed receipt funds the pool once, without proxying a buyer.

        Reposting the same event is idempotent.  A second source event, a
        return carrying a request, or a post-funding identity edit must fail.
        Legacy employee custody also cannot accept an unrelated contact.
        """
        _custody_account, _cash_account, _bank_account, _general, cash, bank = self._custody_accounting_fixture('PRC96')
        representative = self.env['res.partner'].create({
            'name': 'PRC96 representative', 'company_id': self.company.id,
            'is_purchase_representative': True,
        })
        request = self._complete_external_request(representative, actual_quantity=2, actual_price=10)
        pool = self.env['baseer.procurement.custody'].create({
            'company_id': self.company.id, 'is_company_pool': True,
        })
        Event = self.env['baseer.procurement.custody.event']
        funding = Event.create({
            'custody_id': pool.id, 'event_type': 'funding', 'amount': 25,
            'cash_journal_id': bank.id, 'representative_partner_id': representative.id,
            'procurement_request_id': request.id,
        })
        funding.action_post()
        funding.action_post()
        self.assertEqual(self.env['account.move'].search_count([('ref', '=', funding.move_id.ref)]), 1)
        with self.assertRaises(Exception):
            Event.create({
                'custody_id': pool.id, 'event_type': 'funding', 'amount': 1,
                'cash_journal_id': bank.id, 'representative_partner_id': representative.id,
                'procurement_request_id': request.id,
            })
        with self.assertRaisesRegex(ValidationError, 'return cannot be linked'):
            Event.create({
                'custody_id': pool.id, 'event_type': 'return', 'amount': 1,
                'cash_journal_id': cash.id, 'representative_partner_id': representative.id,
                'procurement_request_id': self._complete_external_request(representative).id,
            })
        with self.assertRaisesRegex(UserError, 'identity cannot change'):
            pool.write({'name': 'forbidden custody rename'})

        legacy = self.env['baseer.procurement.custody'].create({
            'company_id': self.company.id, 'employee_id': self.purchaser.id,
        })
        with self.assertRaisesRegex(ValidationError, 'different purchase representative'):
            Event.create({
                'custody_id': legacy.id, 'event_type': 'funding', 'amount': 1,
                'cash_journal_id': cash.id, 'representative_partner_id': representative.id,
            }).action_post()

    def test_batch_header_reserves_completed_request_and_uses_actual_total_not_custody(self):
        """PRC-CUSTODY2 selects one receipt in the batch header, once only.

        The header amount is validated against the completed operational
        request.  It is deliberately *not* validated against the larger
        advance: remaining custody stays with the representative.
        """
        company = self.env['res.company'].search([('currency_id.name', '=', 'SAR')], limit=1)
        if not company:
            self.skipTest('No SAR company is available for the purchase-batch header integration test.')
        env = self.env(context={**self.env.context, 'allowed_company_ids': company.ids})
        custody_account, _cash_account, _bank_account, _general, cash, _bank = self._custody_accounting_fixture('PRC94', company)
        expense_account = env['account.account'].create({
            'name': 'PRC94 purchase expense',
            'code': 'PRC9404',
            'account_type': 'expense',
            'company_ids': [Command.set(company.ids)],
        })
        employee = env['hr.employee'].create({
            'name': 'PRC header purchasing representative',
            'company_id': company.id,
        })
        request = self._complete_company_request(company, employee, actual_quantity=5, actual_price=4)
        self.assertEqual(request.actual_total, 20)
        custody = env['baseer.procurement.custody'].create({
            'company_id': company.id,
            'employee_id': employee.id,
        })
        env['baseer.procurement.custody.event'].create({
            'custody_id': custody.id,
            'event_type': 'funding',
            'amount': 25,
            'cash_journal_id': cash.id,
            'reference': 'PRC header funding larger than actual receipt',
        }).action_post()
        supplier = env['res.partner'].create({
            'name': 'PRC header supplier',
            'supplier_rank': 1,
        })
        self._native_batch_accounting_fixture(company, expense_account, supplier)
        category = env['product.category'].create({'name': 'PRC94 supplier category'})
        service = env['product.product'].create({
            'name': 'PRC94 supplier service',
            'type': 'service',
            'categ_id': category.id,
            'property_account_expense_id': expense_account.id,
        })
        mapping = env['baseer.purchase.category.map'].create({
            'company_id': company.id,
            'category_id': category.id,
            'product_id': service.id,
        })
        batch = env['baseer.purchase.batch'].create({
            'company_id': company.id,
            'procurement_request_id': request.id,
            'procurement_custody_id': custody.id,
            'line_ids': [Command.create({
                'partner_id': supplier.id,
                'supplier_ref': 'PRC-HEADER-ACTUAL-1',
                'entry_type': 'purchase',
                'gross_amount': 20,
                'is_credit': True,
            })],
        })
        self.assertTrue(batch.line_ids.is_credit)
        self.assertFalse(batch.line_ids.payment_method_line_id)

        # Reservation is durable at draft time, so a second batch cannot win
        # a race merely because the first batch is not approved yet.
        with self.env.cr.savepoint():
            with self.assertRaises(Exception):
                env['baseer.purchase.batch'].create({
                    'company_id': company.id,
                    'procurement_request_id': request.id,
                })

        batch.action_approve()
        line = batch.line_ids
        self.assertFalse(line.move_id.invoice_line_ids.product_id)
        self.assertEqual(line.move_id.invoice_line_ids.account_id, expense_account)
        self.assertEqual(line.move_id.payment_state, 'paid')
        self.assertFalse(line.payment_id)
        self.assertTrue(line.procurement_settlement_id)
        self.assertEqual(line.procurement_settlement_id.amount, request.actual_total)
        self.assertEqual(custody.balance, 5)
        self.assertEqual(sum(line.procurement_settlement_move_id.line_ids.filtered(
            lambda account_line: account_line.account_id == custody_account
        ).mapped('credit')), request.actual_total)

        mismatched_request = self._complete_company_request(company, employee, actual_quantity=2, actual_price=5)
        mismatched_batch = env['baseer.purchase.batch'].create({
            'company_id': company.id,
            'procurement_request_id': mismatched_request.id,
            'line_ids': [Command.create({
                'partner_id': supplier.id,
                'supplier_ref': 'PRC-HEADER-MISMATCH-1',
                'entry_type': 'purchase',
                'gross_amount': 9,
                'is_credit': True,
            })],
        })
        with self.assertRaisesRegex(ValidationError, 'must equal'):
            mismatched_batch.action_approve()
        self.assertEqual(mismatched_batch.state, 'draft')
        self.assertFalse(mismatched_batch.line_ids.move_id)

    def test_catalog_representative_is_company_scoped_and_creates_request(self):
        """PRC-CUSTODY2 exposes standalone contacts only in their company.

        The catalog RPC must keep the existing employee argument optional while
        accepting the sixth contact argument.  A shared contact enabled in one
        company must neither leak through the other company's selector nor be
        accepted there.
        """
        other_company = self.env['res.company'].create({
            'name': 'PRC representative other company',
            'currency_id': self.company.currency_id.id,
        })
        self.env.user.company_ids |= other_company
        representative = self.env['res.partner'].create({
            'name': 'PRC standalone catalog representative',
            'company_id': False,
            'is_company': False,
        })
        representative.with_company(self.company).write({
            'is_purchase_representative': True,
        })

        Request = self.env['baseer.procurement.request']
        self.assertIn(
            representative.id,
            [row['id'] for row in Request.catalog_representatives()],
        )
        self.assertNotIn(
            representative.id,
            [row['id'] for row in Request.with_company(other_company).catalog_representatives()],
        )

        request_id = Request.create_from_catalog(
            [{'option_id': self.option.id, 'quantity': 2}],
            self.warehouse.id,
            False,
            False,
            str(uuid4()),
            representative.id,
        )
        request = Request.browse(request_id)
        self.assertFalse(request.purchaser_id)
        self.assertEqual(request.representative_partner_id, representative)
        self.assertEqual(request.state, 'draft')

    def test_custody_period_close_snapshots_carry_and_blocks_closed_month(self):
        """PRC-CUSTODY2 month close is a non-financial immutable snapshot.

        Closing carries the representative's balance without creating another
        accounting move.  It then blocks both a late transfer and the custody
        settlement path for that calendar month, while the current month is
        never closable.
        """
        _custody_account, _cash_account, _bank_account, _general, cash, bank = self._custody_accounting_fixture('PRC95')
        self.company.write({'fiscalyear_lock_date': False, 'tax_lock_date': False})
        representative = self.env['res.partner'].create({
            'name': 'PRC period-close representative',
            'company_id': self.company.id,
            'is_purchase_representative': True,
        })
        custody = self.env['baseer.procurement.custody'].create({
            'company_id': self.company.id,
            'is_company_pool': True,
        })
        today = fields.Date.context_today(self)
        prior_day = today.replace(day=1) - timedelta(days=1)
        prior_month = prior_day.replace(day=1)
        Event = self.env['baseer.procurement.custody.event']

        # `reference` is deliberately omitted: it is optional and posting
        # must still produce the native funding transfer.
        funding = Event.create({
            'custody_id': custody.id,
            'event_type': 'funding',
            'event_date': prior_day,
            'amount': 200,
            'cash_journal_id': bank.id,
            'representative_partner_id': representative.id,
            'procurement_request_id': self._complete_external_request(representative).id,
        })
        self.assertFalse(funding.reference)
        funding.action_post()
        returned = Event.create({
            'custody_id': custody.id,
            'event_type': 'return',
            'event_date': prior_day,
            'amount': 40,
            'cash_journal_id': cash.id,
            'representative_partner_id': representative.id,
            'reference': 'PRC95 partial cash return',
        })
        returned.action_post()
        self.assertEqual(custody._representative_balance(representative), 160)

        Close = self.env['baseer.procurement.custody.period.close']
        move_count_before_close = self.env['account.move'].search_count([])
        close = Close.create({
            'custody_id': custody.id,
            'representative_partner_id': representative.id,
            'month_start': prior_month,
            'note': 'PRC95 month-end carry',
        })
        close.action_close()
        self.assertEqual(close.state, 'closed')
        self.assertEqual(close.closed_by_id, self.env.user)
        self.assertTrue(close.closed_at)
        self.assertEqual(close.opening_balance, 0)
        self.assertEqual(close.funded_amount, 200)
        self.assertEqual(close.returned_amount, 40)
        self.assertEqual(close.settled_amount, 0)
        self.assertEqual(close.carry_forward_amount, 160)
        self.assertEqual(self.env['account.move'].search_count([]), move_count_before_close)
        self.assertEqual(custody._representative_balance(representative), 160)
        with self.assertRaises(UserError):
            close.write({'carry_forward_amount': 0})
        with self.assertRaises(UserError):
            close.unlink()

        late_return = Event.create({
            'custody_id': custody.id,
            'event_type': 'return',
            'event_date': prior_day,
            'amount': 1,
            'cash_journal_id': cash.id,
            'representative_partner_id': representative.id,
        })
        with self.assertRaisesRegex(ValidationError, 'month is closed'):
            late_return.action_post()
        self.assertEqual(late_return.state, 'draft')
        self.assertFalse(late_return.move_id)

        # Supplier settlement calls this same shared guard before its native
        # entry is created.  Keep the period test currency-neutral; the full
        # purchase-batch settlement test below already exercises the native
        # SAR-only bill path.
        with self.assertRaisesRegex(ValidationError, 'month is closed'):
            Close._ensure_month_open(custody, representative, prior_day)

        late_funding = Event.create({
            'custody_id': custody.id,
            'event_type': 'funding',
            'event_date': prior_day,
            'amount': 1,
            'cash_journal_id': bank.id,
            'representative_partner_id': representative.id,
            'procurement_request_id': self._complete_external_request(representative).id,
        })
        with self.assertRaisesRegex(ValidationError, 'month is closed'):
            late_funding.action_post()

        current_month = Close.create({
            'custody_id': custody.id,
            'representative_partner_id': representative.id,
            'month_start': today.replace(day=1),
        })
        with self.assertRaisesRegex(ValidationError, 'completed month'):
            current_month.action_close()
        self.assertEqual(current_month.state, 'draft')

    def test_custody_reconciliation_never_crosses_two_open_custodies(self):
        """A return to custody A must leave the same buyer's custody B intact."""
        Account = self.env['account.account']
        custody_account = Account.create({'name': 'PRC isolated custody', 'code': 'PRC921', 'account_type': 'asset_receivable', 'reconcile': True, 'company_ids': [Command.set(self.company.ids)]})
        cash_account = Account.create({'name': 'PRC isolated cash', 'code': 'PRC922', 'account_type': 'asset_cash', 'company_ids': [Command.set(self.company.ids)]})
        general = self.env['account.journal'].create({'name': 'PRC isolated entries', 'code': 'PRCI', 'type': 'general', 'company_id': self.company.id})
        cash = self.env['account.journal'].create({'name': 'PRC isolated cash', 'code': 'PRCK', 'type': 'cash', 'company_id': self.company.id, 'default_account_id': cash_account.id})
        self.company.write({'baseer_procurement_custody_account_id': custody_account.id, 'baseer_procurement_custody_journal_id': general.id})
        buyer = self.env['hr.employee'].create({'name': 'PRC shared buyer', 'company_id': self.company.id})
        first = self.env['baseer.procurement.custody'].create({'company_id': self.company.id, 'employee_id': buyer.id})
        second = self.env['baseer.procurement.custody'].create({'company_id': self.company.id, 'employee_id': buyer.id})
        for custody, amount in ((first, 100), (second, 200)):
            self.env['baseer.procurement.custody.event'].create({'custody_id': custody.id, 'event_type': 'funding', 'amount': amount, 'cash_journal_id': cash.id, 'reference': custody.name}).action_post()
        self.env['baseer.procurement.custody.event'].create({'custody_id': first.id, 'event_type': 'return', 'amount': 40, 'cash_journal_id': cash.id, 'reference': 'first return'}).action_post()
        self.assertEqual(first.balance, 60)
        self.assertEqual(second.balance, 200)
        lines = self.env['account.move.line'].search([('account_id', '=', custody_account.id), ('parent_state', '=', 'posted'), ('reconciled', '=', False)])
        for custody, expected in ((first, 60), (second, 200)):
            residual = sum(lines.filtered(lambda aml: aml.baseer_procurement_custody_id == custody).mapped('amount_residual'))
            self.assertEqual(residual, expected)

    def test_batch_bill_settles_against_custody_without_direct_payment(self):
        """The supplier is reconciled from custody, never by payment.register."""
        company = self.env['res.company'].search([('currency_id.name', '=', 'SAR')], limit=1)
        if not company:
            self.skipTest('No SAR company is available for the purchase-batch integration test.')
        Account = self.env['account.account'].with_company(company)
        custody_account = Account.create({
            'name': 'PRC batch custody receivable', 'code': 'PRC911', 'account_type': 'asset_receivable',
            'reconcile': True, 'company_ids': [Command.set(company.ids)],
        })
        cash_account = Account.create({
            'name': 'PRC batch cash', 'code': 'PRC912', 'account_type': 'asset_cash',
            'company_ids': [Command.set(company.ids)],
        })
        expense_account = Account.create({
            'name': 'PRC batch expense', 'code': 'PRC913', 'account_type': 'expense',
            'company_ids': [Command.set(company.ids)],
        })
        Journal = self.env['account.journal'].with_company(company)
        general = Journal.create({'name': 'PRC batch custody entries', 'code': 'PRCB', 'type': 'general', 'company_id': company.id})
        cash = Journal.create({'name': 'PRC batch cash', 'code': 'PRCC', 'type': 'cash', 'company_id': company.id, 'default_account_id': cash_account.id})
        company.write({'baseer_procurement_custody_account_id': custody_account.id, 'baseer_procurement_custody_journal_id': general.id})
        employee = self.env['hr.employee'].with_company(company).create({'name': 'PRC batch buyer', 'company_id': company.id})
        custody = self.env['baseer.procurement.custody'].with_company(company).create({'company_id': company.id, 'employee_id': employee.id})
        funding = self.env['baseer.procurement.custody.event'].with_company(company).create({
            'custody_id': custody.id, 'event_type': 'funding', 'amount': 25,
            'cash_journal_id': cash.id, 'reference': 'QA funding',
        })
        funding.action_post()
        warehouse = self.env['stock.warehouse'].with_company(company).search([('company_id', '=', company.id)], limit=1)
        if not warehouse:
            warehouse = self.env['stock.warehouse'].with_company(company).create({
                'name': 'PRC batch test warehouse', 'code': 'PRCBW', 'company_id': company.id,
            })
        self.assertTrue(warehouse)
        uom = self.env.ref('uom.product_uom_unit')
        category_values = {'name': 'PRC batch raw category'}
        if 'property_cost_method' in self.env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in self.env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        category = self.env['product.category'].with_company(company).create(category_values)
        product = self.env['product.product'].with_company(company).create({'name': 'PRC batch raw material', 'company_id': company.id, 'categ_id': category.id, 'uom_id': uom.id, 'is_storable': True})
        option = self.env['baseer.procurement.purchase.option'].with_company(company).create({'name': 'Piece', 'company_id': company.id, 'product_id': product.id, 'uom_id': uom.id})
        request = self.env['baseer.procurement.request'].with_company(company).create({
            'company_id': company.id, 'warehouse_id': warehouse.id, 'purchaser_id': employee.id,
            'line_ids': [Command.create({'option_id': option.id, 'requested_qty': 5, 'requested_price': 4})],
        })
        request.action_mark_sent()
        request.line_ids.manager_received_qty = 2.5
        request.action_confirm_manager_receipt()
        request.line_ids.write({'actual_qty': 2.5, 'actual_price': 4})
        request.action_confirm_actual_purchase()
        second_request = self.env['baseer.procurement.request'].with_company(company).create({
            'company_id': company.id, 'warehouse_id': warehouse.id, 'purchaser_id': employee.id,
            'line_ids': [Command.create({'option_id': option.id, 'requested_qty': 3, 'requested_price': 4})],
        })
        second_request.action_mark_sent()
        second_request.line_ids.manager_received_qty = 3
        second_request.action_confirm_manager_receipt()
        second_request.line_ids.write({'actual_qty': 3, 'actual_price': 4})
        second_request.action_confirm_actual_purchase()
        supplier = self.env['res.partner'].with_company(company).create({'name': 'PRC batch supplier', 'supplier_rank': 1})
        self._native_batch_accounting_fixture(company, expense_account, supplier)
        service_category = self.env['product.category'].with_company(company).create({'name': 'PRC batch expense category'})
        service = self.env['product.product'].with_company(company).create({
            'name': 'PRC batch expense service', 'type': 'service', 'categ_id': service_category.id,
            'property_account_expense_id': expense_account.id,
        })
        mapping = self.env['baseer.purchase.category.map'].with_company(company).create({
            'company_id': company.id, 'category_id': service_category.id, 'product_id': service.id,
        })
        # Request visibility can expose hr.employee.public while custody uses
        # hr.employee; identity must be compared by id, not recordset model.
        self.assertEqual(custody.employee_id.id, request.purchaser_id.id)
        self.assertFalse(custody.is_company_pool)
        invalid_batch = self.env['baseer.purchase.batch'].with_company(company).create({
            'company_id': company.id,
            'line_ids': [Command.create({
                'partner_id': supplier.id, 'supplier_ref': 'PRC-QA-INTEGRATION-INCOMPLETE', 'entry_type': 'purchase',
                'gross_amount': 20, 'is_credit': True,
                'procurement_custody_id': custody.id,
                'procurement_allocation_ids': [Command.create({'request_id': request.id, 'amount': 8})],
            })],
        })
        with self.assertRaisesRegex(Exception, 'must equal'):
            invalid_batch.action_approve()
        invalid_batch.invalidate_recordset()
        self.assertEqual(invalid_batch.state, 'draft')
        self.assertFalse(invalid_batch.line_ids.move_id)
        # Funding is an already-posted bank/cash -> custody transfer.  A bad
        # supplier-bill batch must be rolled back by its own savepoint only;
        # it must never undo that independent source document.
        funding.invalidate_recordset()
        custody.invalidate_recordset(['funded_amount', 'balance'])
        self.assertEqual(funding.state, 'posted')
        self.assertEqual(funding.move_id.state, 'posted')
        self.assertEqual(custody.funded_amount, 25)
        self.assertEqual(custody.balance, 25)
        batch = self.env['baseer.purchase.batch'].with_company(company).create({
            'company_id': company.id,
            'line_ids': [Command.create({
                'partner_id': supplier.id, 'supplier_ref': 'PRC-QA-INTEGRATION-1', 'entry_type': 'purchase',
                'gross_amount': 20, 'is_credit': True,
                'procurement_custody_id': custody.id,
                'procurement_allocation_ids': [
                    Command.create({'request_id': request.id, 'amount': 8}),
                    Command.create({'request_id': second_request.id, 'amount': 12}),
                ],
            })],
        })
        other_buyer = self.env['hr.employee'].with_company(company).create({'name': 'PRC other batch buyer', 'company_id': company.id})
        other_custody = self.env['baseer.procurement.custody'].with_company(company).create({'company_id': company.id, 'employee_id': other_buyer.id})
        with self.assertRaisesRegex(Exception, 'Clear request allocations'):
            batch.line_ids.write({'procurement_custody_id': other_custody.id})
        batch.action_approve()
        line = batch.line_ids
        self.assertFalse(line.move_id.invoice_line_ids.product_id)
        self.assertEqual(line.move_id.invoice_line_ids.account_id, expense_account)
        self.assertFalse(line.payment_id)
        self.assertTrue(line.is_credit)
        self.assertTrue(line.procurement_settlement_move_id)
        self.assertEqual(line.move_id.payment_state, 'paid')
        self.assertEqual(custody.balance, 5)
        self.assertEqual(line.procurement_allocated_amount, 20)
        self.assertEqual(len(line.procurement_allocation_ids), 2)
        self.assertEqual(request.actual_total, 10)
        monthly = self.env['baseer.procurement.custody.monthly.statement'].search([('custody_id', '=', custody.id)])
        self.assertEqual(len(monthly), 1)
        self.assertEqual(monthly.funded_amount, 25)
        self.assertEqual(monthly.settled_amount, 20)
        self.assertEqual(monthly.closing_balance, 5)
        settlement = line.procurement_settlement_id
        settlement.write({'reversal_reason': 'QA correction'})
        reversal_date = fields.Date.context_today(settlement)
        company.write({'fiscalyear_lock_date': reversal_date})
        self.assertEqual(settlement.company_id, company)
        self.assertEqual(reversal_date, company.fiscalyear_lock_date)
        self.assertTrue(settlement.company_id.with_context(ignore_exceptions=True)._get_violated_lock_dates(
            reversal_date, False, settlement.company_id.baseer_procurement_custody_journal_id,
        ))
        with self.assertRaisesRegex(Exception, 'reversal date is locked'):
            # Odoo permits a personal accounting-lock exception.  The custody
            # rule honours that native authorization, so force the global-lock
            # branch here rather than making the test depend on the admin's
            # exception records in the cloned database.
            settlement.with_context(ignore_exceptions=True).action_reverse()
        self.assertEqual(settlement.state, 'active')
        self.assertFalse(settlement.reversal_move_id)
        self.assertEqual(line.move_id.amount_residual, 0)
        company.write({'fiscalyear_lock_date': False})
        settlement.action_reverse()
        self.assertEqual(settlement.state, 'reversed')
        self.assertEqual(settlement.reversal_move_id.state, 'posted')
        self.assertEqual(custody.balance, 25)
        self.assertEqual(line.move_id.amount_residual, 20)
        self.env.invalidate_all()
        monthly = self.env['baseer.procurement.custody.monthly.statement'].search([('custody_id', '=', custody.id)])
        self.assertEqual(monthly.closing_balance, 25)
        batch.action_resettle_custody()
        line.invalidate_recordset(['procurement_settlement_id', 'procurement_settlement_move_id'])
        self.assertEqual(line.procurement_settlement_id.state, 'active')
        self.assertEqual(line.move_id.payment_state, 'paid')
        self.assertEqual(custody.balance, 5)
        self.env['baseer.procurement.custody.event'].with_company(company).create({
            'custody_id': custody.id, 'event_type': 'return', 'amount': 5,
            'cash_journal_id': cash.id, 'reference': 'QA close after resettle',
        }).action_post()
        custody.action_close()
        line.procurement_settlement_id.write({'reversal_reason': 'closed-custody rejection'})
        with self.assertRaisesRegex(Exception, 'closed petty cash'):
            line.procurement_settlement_id.action_reverse()
        self.assertEqual(custody.state, 'closed')
        open_custody_lines = self.env['account.move.line'].search([
            ('account_id', '=', custody_account.id), ('partner_id', '=', employee.work_contact_id.id),
            ('parent_state', '=', 'posted'), ('reconciled', '=', False),
        ])
        self.assertEqual(sum(open_custody_lines.mapped('amount_residual')), custody.balance)

        # A normal cash purchase is intentionally outside the custody route.
        # It must retain Baseer's native payment flow (one supplier bill and
        # one native account.payment), rather than creating a custody
        # settlement or moving money through the custody account.
        cash_method = cash.outbound_payment_method_line_ids.filtered(
            lambda method: method.code == 'manual'
        )[:1]
        self.assertTrue(cash_method, 'The cash journal needs its native manual outbound method.')
        cash_method.payment_account_id = cash_account
        direct_batch = self.env['baseer.purchase.batch'].with_company(company).create({
            'company_id': company.id,
            'line_ids': [Command.create({
                'partner_id': supplier.id,
                'supplier_ref': 'PRC-QA-DIRECT-CASH-1',
                'entry_type': 'purchase',
                'gross_amount': 1,
                'payment_method_line_id': cash_method.id,
                'is_credit': False,
            })],
        })
        direct_batch.action_approve()
        direct_line = direct_batch.line_ids
        self.assertTrue(direct_line.payment_id)
        self.assertEqual(direct_line.move_id.payment_state, 'paid')
        self.assertFalse(direct_line.procurement_custody_id)
        self.assertFalse(direct_line.procurement_settlement_id)
        liquidity = direct_line.payment_id.move_id.line_ids.filtered(
            lambda account_line: account_line.account_id == cash_account
        )
        self.assertEqual(-sum(liquidity.mapped('balance')), 1)

    def test_purchase_batch_settles_from_representative_petty_cash_without_payment(self):
        """Each invoice chooses its source; representative spend is cumulative."""
        sar = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'SAR')], limit=1)
        if not sar:
            sar = self.env['res.currency'].create({'name': 'SAR', 'symbol': 'SR', 'active': True})
        sar.active = True
        self.company = self.env['res.company'].create({
            'name': 'PRA21 SAR company', 'currency_id': sar.id,
        })
        self.env.user.company_ids |= self.company
        company_env = self.env['res.company'].with_company(self.company).env
        self.env = company_env
        self.warehouse = company_env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.warehouse:
            self.warehouse = company_env['stock.warehouse'].create({
                'name': 'PRA21 warehouse', 'code': 'PRA21', 'company_id': self.company.id,
            })
        category_values = {'name': 'PRA21 quantity category'}
        if 'property_cost_method' in company_env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in company_env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        self.category = company_env['product.category'].create(category_values)
        self.product = company_env['product.product'].create({
            'name': 'PRA21 stock product', 'company_id': self.company.id,
            'categ_id': self.category.id, 'uom_id': self.uom.id, 'is_storable': True,
        })
        self.option = company_env['baseer.procurement.purchase.option'].create({
            'name': 'Piece', 'company_id': self.company.id, 'product_id': self.product.id,
            'uom_id': self.uom.id,
        })
        advance_account, _cash_account, bank_account, general, _cash, bank = self._custody_accounting_fixture('PRA21')
        self.company.write({
            'baseer_procurement_representative_petty_cash_account_id': advance_account.id,
            'baseer_procurement_representative_petty_cash_journal_id': general.id,
            'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set([bank.id])],
        })
        representative = self.env['res.partner'].create({'name': 'PRA21 representative'})
        request = self._complete_external_request(representative)
        advance_id = self.env['baseer.procurement.representative.advance'].with_company(self.company).submit_funding(
            request.id, bank.id, representative.id, 25, str(uuid4()), fields.Date.context_today(self),
        )
        advance = self.env['baseer.procurement.representative.advance'].browse(advance_id)
        self.assertEqual(advance.remaining_amount, 25)

        expense_account = self.env['account.account'].create({
            'name': 'PRA21 purchase expense', 'code': 'PRA211', 'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        supplier = self.env['res.partner'].create({'name': 'PRA21 supplier', 'supplier_rank': 1})
        self._native_batch_accounting_fixture(self.company, expense_account, supplier)
        service_category = self.env['product.category'].create({'name': 'PRA21 expense category'})
        service = self.env['product.product'].create({
            'name': 'PRA21 expense service', 'type': 'service', 'categ_id': service_category.id,
            'property_account_expense_id': expense_account.id,
        })
        self.env['baseer.purchase.category.map'].create({
            'company_id': self.company.id, 'category_id': service_category.id, 'product_id': service.id,
        })
        with self.assertRaisesRegex(ValidationError, 'each invoice'):
            self.env['baseer.purchase.batch'].create({
                'company_id': self.company.id,
                'representative_petty_cash_id': advance.id,
                'line_ids': [Command.create({
                    'partner_id': supplier.id, 'supplier_ref': 'PRA21-HEADER', 'entry_type': 'purchase',
                    'gross_amount': 20, 'is_credit': True,
                })],
            })
        excessive_batch = self.env['baseer.purchase.batch'].create({
            'company_id': self.company.id,
            'line_ids': [Command.create({
                'partner_id': supplier.id, 'supplier_ref': 'PRA21-OVER', 'entry_type': 'purchase',
                'gross_amount': 26, 'payment_source_type': 'representative_petty_cash',
                'representative_petty_cash_representative_id': representative.id,
            })],
        })
        with self.assertRaisesRegex(UserError, 'exceed the available'):
            excessive_batch.action_approve()
        self.assertEqual(excessive_batch.state, 'draft')
        self.assertFalse(excessive_batch.line_ids.move_id)
        excessive_batch.unlink()
        batch = self.env['baseer.purchase.batch'].create({
            'company_id': self.company.id,
            'line_ids': [Command.create({
                'partner_id': supplier.id, 'supplier_ref': 'PRA21-1', 'entry_type': 'purchase',
                'gross_amount': 20, 'payment_source_type': 'representative_petty_cash',
                'representative_petty_cash_representative_id': representative.id,
            })],
        })
        self.assertEqual(batch.line_ids.representative_petty_cash_available_amount, 25)
        batch.action_approve()
        batch.invalidate_recordset()
        self.assertEqual(batch.state, 'approved')
        self.assertTrue(batch.line_ids.representative_petty_cash_invoice_settlement_id)
        self.assertEqual(batch.line_ids.representative_petty_cash_invoice_settlement_id.amount, 20)
        self.assertEqual(batch.line_ids.representative_petty_cash_invoice_settlement_id.move_id.state, 'posted')
        self.assertEqual(batch.line_ids.move_id.payment_state, 'paid')
        self.assertFalse(batch.line_ids.payment_id)
        self.assertEqual(
            self.env['baseer.procurement.representative.advance']._baseer_representative_available_amount(
                self.company, representative,
            ), 5,
        )
        settlement_credit = batch.line_ids.representative_petty_cash_invoice_settlement_id.move_id.line_ids.filtered(
            lambda line: line.account_id == advance_account and line.credit > 0 and line.partner_id == representative
        )
        self.assertEqual(len(settlement_credit), 1)

        # A client/RPC caller cannot attach an existing settlement link to a
        # new invoice line to make it look funded without consuming balance.
        with self.assertRaises(AccessError):
            self.env['baseer.purchase.batch'].create({
                'company_id': self.company.id,
                'line_ids': [Command.create({
                    'partner_id': supplier.id, 'supplier_ref': 'PRA21-RPC-BYPASS', 'entry_type': 'purchase',
                    'gross_amount': 1, 'payment_source_type': 'representative_petty_cash',
                    'representative_petty_cash_representative_id': representative.id,
                    'representative_petty_cash_invoice_settlement_id': batch.line_ids.representative_petty_cash_invoice_settlement_id.id,
                })],
            })

        # Returns use the representative's aggregate balance, not a selected
        # historical funding movement.  Five remains from the first funding;
        # add ten, then return eight from the combined fifteen.
        self.env['baseer.procurement.representative.advance'].with_company(self.company).submit_funding(
            request.id, bank.id, representative.id, 10, str(uuid4()), fields.Date.context_today(self),
        )
        aggregate_return_id = self.env['baseer.procurement.representative.advance'].with_company(self.company).submit_aggregate_return(
            representative.id, bank.id, 8, str(uuid4()), fields.Date.context_today(self),
        )
        aggregate_return = self.env['baseer.procurement.representative.advance'].browse(aggregate_return_id)
        self.assertFalse(aggregate_return.origin_id)
        self.assertEqual(
            self.env['baseer.procurement.representative.advance']._baseer_representative_available_amount(
                self.company, representative,
            ), 7,
        )

        bank_method = bank.outbound_payment_method_line_ids.filtered(lambda method: method.code == 'manual')[:1]
        self.assertTrue(bank_method)
        bank_method.payment_account_id = bank_account
        mixed_batch = self.env['baseer.purchase.batch'].create({
            'company_id': self.company.id,
            'line_ids': [
                Command.create({
                    'partner_id': supplier.id, 'supplier_ref': 'PRA21-MIX-REP', 'entry_type': 'purchase',
                    'gross_amount': 3, 'payment_source_type': 'representative_petty_cash',
                    'representative_petty_cash_representative_id': representative.id,
                }),
                Command.create({
                    'partner_id': supplier.id, 'supplier_ref': 'PRA21-MIX-BANK', 'entry_type': 'purchase',
                    'gross_amount': 1, 'payment_source_type': 'payment_method',
                    'payment_method_line_id': bank_method.id,
                }),
            ],
        })
        mixed_batch.action_approve()
        representative_line = mixed_batch.line_ids.filtered(
            lambda line: line.payment_source_type == 'representative_petty_cash'
        )
        direct_line = mixed_batch.line_ids.filtered(lambda line: line.payment_source_type == 'payment_method')
        self.assertTrue(representative_line.representative_petty_cash_invoice_settlement_id)
        self.assertFalse(representative_line.payment_id)
        self.assertTrue(direct_line.payment_id)
        self.assertEqual(
            self.env['baseer.procurement.representative.advance']._baseer_representative_available_amount(
                self.company, representative,
            ), 4,
        )
