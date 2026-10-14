"""Focused BChat final-receipt checks against Odoo's native stock workflow."""
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.baseer_bchat.contracts import ProtocolError


@tagged('post_install', '-at_install', 'baseer_bchat_procurement')
class BChatReceiptCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env['res.company'].create({'name': 'BChat receipt %s' % uuid4().hex[:8]})
        self.foreign = self.env['res.company'].create({'name': 'Foreign receipt %s' % uuid4().hex[:8]})
        group = self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator')
        self.operator = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat restaurant manager', 'login': 'bchat-receipt-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id, group.id])],
        })
        self.outsider = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat no receipt role', 'login': 'bchat-receipt-no-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.service = self.env['baseer.bchat.service'].with_user(self.operator)
        self.warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.warehouse:
            self.warehouse = self.env['stock.warehouse'].create({
                'name': 'BChat receipt warehouse', 'code': 'BR%s' % self.company.id,
                'company_id': self.company.id,
            })
        category_values = {'name': 'BChat receipt standard cost'}
        if 'property_cost_method' in self.env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in self.env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        category = self.env['product.category'].create(category_values)
        product = self.env['product.product'].with_company(self.company).create({
            'name': 'BChat receipt ingredient', 'company_id': self.company.id,
            'categ_id': category.id, 'uom_id': self.env.ref('uom.product_uom_unit').id,
            'purchase_ok': True, 'is_storable': True,
        })
        self.option = self.env['baseer.procurement.purchase.option'].with_company(self.company).create({
            'name': 'Piece', 'company_id': self.company.id,
            'product_id': product.id, 'uom_id': product.uom_id.id,
        })
        self.representative = self.env['res.partner'].create({
            'name': 'BChat receipt buyer', 'is_company': False,
        })
        self.representative.with_company(self.company).write({'is_purchase_representative': True})
        self.order_id = self.service._v2_order_create({
            'api_version': 2, 'company_id': self.company.id,
            'warehouse_id': self.warehouse.id, 'representative_partner_id': None,
            'client_uuid': str(uuid4()),
            'lines': [{'option_id': self.option.id, 'quantity': '2.00'}],
        })['order']['id']
        self.order = self.env['baseer.procurement.request'].sudo().browse(self.order_id)

    def _payload(self, token=None, quantity='1.00', price='7.25'):
        return {
            'api_version': 2, 'company_id': self.company.id,
            'client_uuid': token or str(uuid4()),
            'lines': [{'line_id': self.order.line_ids.id,
                       'actual_qty': quantity, 'actual_price': price}],
        }

    def test_receipt_product_label_has_no_code_and_keeps_real_parentheses(self):
        self.option.product_id.write({
            'name': 'Ingredient (large)',
            'default_code': 'BCHAT-123',
        })

        detail = self.service._v2_receipt_detail(self.company.id, self.order_id)

        self.assertEqual(detail['lines'][0]['product_name'], 'Ingredient (large)')
        self.assertNotIn('BCHAT-123', detail['lines'][0]['product_name'])

    def test_receipt_final_effect_replay_and_actor(self):
        initial_hints = [row for row in self.service._v2_changes(0, 100)['changes']
                         if row['kind'] == 'order' and row.get('order_id') == self.order_id]
        self.assertEqual(len(initial_hints), 1)
        self.assertFalse(self.operator.has_group('baseer_procurement_requests.group_procurement_cashier'))
        listed = self.service._v2_receipts(self.company.id)['orders']
        self.assertIn(self.order_id, [row['id'] for row in listed])
        detail = self.service._v2_receipt_detail(self.company.id, self.order_id)
        self.assertEqual(detail['lines'][0]['requested_qty'], '2.00')
        payload = self._payload()
        first = self.service._v2_receipt_confirm(self.order_id, payload)
        self.order.invalidate_recordset()
        self.assertEqual(first['receipt']['state'], 'purchased')
        self.assertEqual(first['receipt']['actual_total'], '7.25')
        self.assertEqual(first['receipt']['confirmed_by_id'], self.operator.id)
        self.assertEqual(self.order.actual_confirmed_by_id, self.operator)
        self.assertTrue(self.order.picking_id)
        self.assertEqual(self.order.picking_id.state, 'done')
        history = self.env['baseer.procurement.price.history'].sudo().search_count([
            ('request_id', '=', self.order_id),
        ])
        self.assertEqual(history, 1)
        replay = self.service._v2_receipt_confirm(self.order_id, payload)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['receipt'], first['receipt'])
        final_hints = [row for row in self.service._v2_changes(0, 100)['changes']
                       if row['kind'] == 'order' and row.get('order_id') == self.order_id]
        self.assertEqual(len(final_hints), 2)
        self.assertEqual(self.env['baseer.procurement.price.history'].sudo().search_count([
            ('request_id', '=', self.order_id),
        ]), history)
        with self.assertRaises(ProtocolError) as changed:
            self.service._v2_receipt_confirm(self.order_id, self._payload())
        self.assertEqual(changed.exception.status, 409)

    def test_state_hint_failure_rolls_back_receipt_and_stock(self):
        before = self.service._v2_changes(0, 100)['watermark']
        with patch('odoo.addons.baseer_bchat_procurement.models.service.BChatProcurementService._order_publish_change',
                   side_effect=RuntimeError('synthetic feed failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic feed failure'):
                self.service._v2_receipt_confirm(self.order_id, self._payload())
        self.order.invalidate_recordset()
        self.assertEqual(self.order.state, 'sent')
        self.assertFalse(self.order.picking_id)
        self.assertEqual(self.service._v2_changes(0, 100)['watermark'], before)

    def test_native_cancel_emits_exactly_one_order_hint(self):
        # Native actions can call write({'state': ...}) internally.  The
        # action and write hooks must not publish two hints for one change.
        # This is a hook-count test, not a BChat privilege escalation.  Use
        # the same native procurement-user setup as the native workflow tests.
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_user',
        )
        self.env.user.company_ids |= self.company
        native_order = self.order.with_company(self.company)
        native_order.write({
            'cancellation_reason': 'Duplicate feed regression test',
        })
        before = [row for row in self.service._v2_changes(0, 100)['changes']
                  if row['kind'] == 'order' and row.get('order_id') == self.order_id]
        self.assertEqual(len(before), 1)

        native_order.action_cancel()
        self.order.invalidate_recordset(['state'])
        self.assertEqual(self.order.state, 'cancel')
        after = [row for row in self.service._v2_changes(0, 100)['changes']
                 if row['kind'] == 'order' and row.get('order_id') == self.order_id]
        self.assertEqual(len(after), 2)

    def test_receipt_role_company_lines_and_decimals(self):
        native_lines = [{'line_id': self.order.line_ids.id,
                         'actual_qty': '1.00', 'actual_price': '7.25'}]
        with self.assertRaises(AccessError):
            self.order.with_user(self.operator).with_context(
                bchat_receipt_internal=True,
            ).confirm_actual_from_catalog(self.order_id, native_lines)
        with self.assertRaises(AccessError):
            self.order.with_user(self.operator).sudo().confirm_actual_from_catalog(
                self.order_id, native_lines,
            )
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.outsider)._v2_receipts(self.company.id)
        with self.assertRaises(AccessError):
            self.service._v2_receipt_detail(self.foreign.id, self.order_id)
        with self.assertRaises(AccessError):
            self.service._v2_receipt_confirm(self.order_id, {
                **self._payload(), 'company_id': self.foreign.id,
            })
        for payload in (
                self._payload(quantity='0.00', price='0.00'),
                self._payload(quantity='3.00'),
                self._payload(quantity='1.001'),
                self._payload(price='7.251'),
                {**self._payload(), 'lines': []},
                {**self._payload(), 'lines': self._payload()['lines'] * 2}):
            with self.subTest(payload=payload), self.assertRaises(ProtocolError):
                self.service._v2_receipt_confirm(self.order_id, payload)
        self.order.invalidate_recordset()
        self.assertEqual(self.order.state, 'sent')
        self.assertFalse(self.order.picking_id)
        self.assertFalse(self.order.receipt_client_token)

    def test_late_error_rolls_back_native_stock_cost_and_token(self):
        product = self.option.product_id.with_company(self.company)
        before_cost = product.standard_price
        before_history = self.env['baseer.procurement.price.history'].sudo().search_count([
            ('request_id', '=', self.order_id),
        ])
        before_pickings = self.env['stock.picking'].sudo().search_count([
            ('origin', '=', self.order.name),
        ])
        with patch.object(type(self.service), '_receipt_success', side_effect=ProtocolError(
                'test_late_failure', 'Simulated late response failure.', 409)):
            with self.assertRaises(ProtocolError):
                self.service._v2_receipt_confirm(self.order_id, self._payload())
        self.order.invalidate_recordset()
        product.invalidate_recordset()
        self.assertEqual(self.order.state, 'sent')
        self.assertFalse(self.order.picking_id)
        self.assertFalse(self.order.receipt_client_token)
        self.assertEqual(self.order.line_ids.manager_received_qty, 0)
        self.assertEqual(self.env['stock.picking'].sudo().search_count([
            ('origin', '=', self.order.name),
        ]), before_pickings)
        self.assertEqual(product.standard_price, before_cost)
        self.assertEqual(self.env['baseer.procurement.price.history'].sudo().search_count([
            ('request_id', '=', self.order_id),
        ]), before_history)

    def test_received_state_can_finish_with_lower_actual_quantity(self):
        manager_group = self.env.ref('baseer_procurement_requests.group_procurement_manager')
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Native test manager', 'login': 'bchat-manager-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id, manager_group.id])],
        })
        self.env['baseer.procurement.request'].with_user(manager).with_company(
            self.company,
        ).confirm_manager_receipt_from_catalog(self.order_id, [{
            'line_id': self.order.line_ids.id, 'manager_received_qty': '2.00',
        }])
        self.order.invalidate_recordset()
        self.assertEqual(self.order.state, 'received')
        result = self.service._v2_receipt_confirm(self.order_id, self._payload(
            quantity='1.00', price='9.50',
        ))
        self.order.invalidate_recordset()
        self.assertEqual(result['receipt']['state'], 'purchased')
        self.assertEqual(self.order.line_ids.manager_received_qty, 2.0)
        self.assertEqual(self.order.line_ids.actual_qty, 1.0)
        self.assertEqual(self.order.actual_confirmed_by_id, self.operator)

    def test_same_token_on_another_order_is_rejected(self):
        token = str(uuid4())
        self.service._v2_receipt_confirm(self.order_id, self._payload(token=token))
        second_id = self.service._v2_order_create({
            'api_version': 2, 'company_id': self.company.id,
            'warehouse_id': self.warehouse.id, 'representative_partner_id': None,
            'client_uuid': str(uuid4()),
            'lines': [{'option_id': self.option.id, 'quantity': '2.00'}],
        })['order']['id']
        second = self.env['baseer.procurement.request'].sudo().browse(second_id)
        payload = {
            'api_version': 2, 'company_id': self.company.id, 'client_uuid': token,
            'lines': [{'line_id': second.line_ids.id,
                       'actual_qty': '1.00', 'actual_price': '7.25'}],
        }
        with self.assertRaises(ProtocolError) as conflict:
            self.service._v2_receipt_confirm(second_id, payload)
        self.assertEqual(conflict.exception.status, 409)
        second.invalidate_recordset()
        self.assertEqual(second.state, 'sent')
        self.assertFalse(second.picking_id)

    def test_mixed_partial_zero_and_nonstorable_lines(self):
        category = self.option.product_id.categ_id
        uom = self.option.uom_id
        extra_options = []
        for name, storable in (('BChat receipt service', False),
                               ('BChat receipt omitted ingredient', True)):
            product = self.env['product.product'].with_company(self.company).create({
                'name': name, 'company_id': self.company.id, 'categ_id': category.id,
                'uom_id': uom.id, 'purchase_ok': True, 'is_storable': storable,
            })
            extra_options.append(self.env['baseer.procurement.purchase.option'].with_company(
                self.company,
            ).create({
                'name': 'Piece', 'company_id': self.company.id,
                'product_id': product.id, 'uom_id': uom.id,
            }))
        order_id = self.service._v2_order_create({
            'api_version': 2, 'company_id': self.company.id,
            'warehouse_id': self.warehouse.id, 'representative_partner_id': None,
            'client_uuid': str(uuid4()),
            'lines': [{'option_id': option.id, 'quantity': '2.00'}
                      for option in [self.option] + extra_options],
        })['order']['id']
        order = self.env['baseer.procurement.request'].sudo().browse(order_id)
        by_option = {line.option_id.id: line.id for line in order.line_ids}
        result = self.service._v2_receipt_confirm(order_id, {
            'api_version': 2, 'company_id': self.company.id,
            'client_uuid': str(uuid4()),
            'lines': [
                {'line_id': by_option[self.option.id],
                 'actual_qty': '1.00', 'actual_price': '7.25'},
                {'line_id': by_option[extra_options[0].id],
                 'actual_qty': '0.50', 'actual_price': '3.00'},
                {'line_id': by_option[extra_options[1].id],
                 'actual_qty': '0.00', 'actual_price': '0.00'},
            ],
        })
        order.invalidate_recordset()
        self.assertEqual(result['receipt']['state'], 'purchased')
        self.assertEqual(result['receipt']['actual_total'], '8.75')
        self.assertEqual({line.option_id.id: line.actual_qty for line in order.line_ids}, {
            self.option.id: 1.0, extra_options[0].id: 0.5, extra_options[1].id: 0.0,
        })
        self.assertEqual(len(order.picking_id.move_ids), 1)
        self.assertEqual(self.env['baseer.procurement.price.history'].sudo().search_count([
            ('request_id', '=', order_id),
        ]), 2)

    def test_inflight_same_token_returns_retry_without_receipt_effect(self):
        payload = self._payload()
        with self.env.registry.cursor() as concurrent_cr:
            concurrent_cr.execute(
                'SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))',
                ['bchat-receipt:%s' % payload['client_uuid']],
            )
            self.assertTrue(concurrent_cr.fetchone()[0])
            with self.assertRaises(ProtocolError) as retry:
                self.service._v2_receipt_confirm(self.order_id, payload)
            self.assertEqual(retry.exception.status, 409)
            self.assertEqual(retry.exception.code, 'retry')
            concurrent_cr.rollback()
        self.order.invalidate_recordset()
        self.assertEqual(self.order.state, 'sent')
        self.assertFalse(self.order.picking_id)
        self.assertFalse(self.order.receipt_client_token)
        result = self.service._v2_receipt_confirm(self.order_id, payload)
        self.assertEqual(result['receipt']['state'], 'purchased')

    def test_bchat_role_is_optional_per_user_not_inherited_from_preset(self):
        if 'baseer_access_role' not in self.env['res.users']._fields:
            self.skipTest('Baseer access-role module is not installed')
        group = self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator')
        users = []
        for role in ('cashier', 'pos_cashier', 'accountant'):
            users.append(self.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'BChat optional role %s' % role,
                'login': 'bchat-role-%s-%s' % (role, uuid4().hex),
                'company_id': self.company.id,
                'company_ids': [Command.set(self.company.ids)],
                'baseer_access_role': role,
            }))
        manager, cashier, accountant = users
        for user in users:
            self.assertNotIn(group, user.all_group_ids)
        manager.write({'group_ids': [Command.link(group.id)]})
        self.assertIn(group, manager.all_group_ids)
        self.assertNotIn(group, cashier.all_group_ids)
        self.assertNotIn(group, accountant.all_group_ids)
        self.assertEqual(manager.baseer_access_role, 'cashier')
        manager.write({'group_ids': [Command.unlink(group.id)]})
        self.assertNotIn(group, manager.all_group_ids)
        cashier.write({'group_ids': [Command.link(group.id)]})
        self.assertIn(group, cashier.all_group_ids)
        self.assertFalse(cashier.has_group('baseer_procurement_requests.group_procurement_cashier'))
        with self.assertRaises(ValidationError):
            accountant.write({'group_ids': [Command.link(group.id)]})
        self.assertNotIn(group, accountant.all_group_ids)
