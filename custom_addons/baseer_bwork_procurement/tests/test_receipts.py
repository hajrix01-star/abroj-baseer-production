"""Focused BWork final-receipt checks against Odoo's native stock workflow."""
from unittest.mock import patch
from uuid import uuid4

from odoo.addons.baseer_bwork.compatibility import LEGACY_SOURCE_CHANNEL

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.baseer_bwork.contracts import ProtocolError
from odoo.addons.baseer_procurement_requests.models.procurement import REQUEST_CREATE_INTERNAL


@tagged('post_install', '-at_install', 'baseer_bwork_procurement')
class BWorkReceiptCase(TransactionCase):
    def setUp(self):
        super().setUp()
        if 'baseer_access_role' not in self.env['res.users']._fields:
            self.skipTest('BWork procurement requires the Baseer access role field')
        self.company = self.env['res.company'].create({'name': 'BWork receipt %s' % uuid4().hex[:8]})
        self.foreign = self.env['res.company'].create({'name': 'Foreign receipt %s' % uuid4().hex[:8]})
        group = self.env.ref('baseer_bwork_procurement.group_bwork_procurement_operator')
        self.operator = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BWork restaurant manager', 'login': 'bwork-receipt-%s' % uuid4().hex,
            # Receipt sharing exercises the authorized linked-chat path.
            'bwork_chat_view': True, 'bwork_chat_send': True,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id, group.id])],
        })
        self.operator.write({'baseer_access_role': 'pos_cashier'})
        self.operator.write({'group_ids': [Command.link(group.id)]})
        self.operator.write({'bwork_order_view': True, 'bwork_order_create': True,
                             'bwork_order_receive': True})
        self.outsider = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BWork no receipt role', 'login': 'bwork-receipt-no-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.service = self.env['baseer.bwork.service'].with_user(self.operator)
        self.warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.warehouse:
            self.warehouse = self.env['stock.warehouse'].create({
                'name': 'BWork receipt warehouse', 'code': 'BR%s' % self.company.id,
                'company_id': self.company.id,
            })
        category_values = {'name': 'BWork receipt standard cost'}
        if 'property_cost_method' in self.env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in self.env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        category = self.env['product.category'].create(category_values)
        product = self.env['product.product'].with_company(self.company).create({
            'name': 'BWork receipt ingredient', 'company_id': self.company.id,
            'categ_id': category.id, 'uom_id': self.env.ref('uom.product_uom_unit').id,
            'purchase_ok': True, 'is_storable': True,
        })
        self.option = self.env['baseer.procurement.purchase.option'].with_company(self.company).create({
            'name': 'Piece', 'company_id': self.company.id,
            'product_id': product.id, 'uom_id': product.uom_id.id,
        })
        self.representative = self.env['res.partner'].create({
            'name': 'BWork receipt buyer', 'is_company': False,
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

    def test_global_receipts_page_filters_company_state_channel_and_rechecks_grants(self):
        self.operator.write({'company_ids': [Command.link(self.foreign.id)]})
        foreign_warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.foreign.id)], limit=1)
        if not foreign_warehouse:
            foreign_warehouse = self.env['stock.warehouse'].create({
                'name': 'BWork global receipt warehouse', 'code': 'GR%s' % self.foreign.id,
                'company_id': self.foreign.id,
            })
        Order = self.env['baseer.procurement.request'].sudo().with_context(**{REQUEST_CREATE_INTERNAL: True})
        rows = Order.with_company(self.company).create([{
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'requester_id': self.operator.id, 'source_channel': LEGACY_SOURCE_CHANNEL, 'state': 'sent',
        } for _ in range(30)])
        foreign_order = Order.with_company(self.foreign).create({
            'company_id': self.foreign.id, 'warehouse_id': foreign_warehouse.id,
            'requester_id': self.operator.id, 'source_channel': LEGACY_SOURCE_CHANNEL, 'state': 'received',
        })
        excluded = Order.with_company(self.company).create([{
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'requester_id': self.operator.id, 'source_channel': channel, 'state': state,
        } for channel, state in [('odoo', 'sent'), (LEGACY_SOURCE_CHANNEL, 'draft'), (LEGACY_SOURCE_CHANNEL, 'cancel')]])
        first = self.service._v2_receipts_all()
        second = self.service._v2_receipts_all(first['next_before_id'])
        ids = [row['id'] for row in first['orders'] + second['orders']]
        self.assertEqual(len(first['orders']), 30)
        self.assertEqual(ids, sorted({self.order_id, foreign_order.id, *rows.ids}, reverse=True))
        self.assertFalse(set(excluded.ids) & set(ids))
        self.assertIsNone(second['next_before_id'])
        filtered = self.service._v2_receipts_all(company_id=self.foreign.id)
        self.assertEqual([row['id'] for row in filtered['orders']], [foreign_order.id])
        self.assertEqual(filtered['orders'][0]['warehouse_name'], foreign_warehouse.display_name)
        self.assertEqual(self.service._v2_order_options()['receipt_list_version'], 1)
        self.operator.write({'company_ids': [Command.unlink(self.foreign.id)]})
        self.assertNotIn(foreign_order.id, [row['id'] for row in self.service._v2_receipts_all()['orders']])
        with self.assertRaises(AccessError):
            self.service._v2_receipts_all(company_id=self.foreign.id)
        self.operator.write({'bwork_order_receive': False})
        with self.assertRaises(AccessError):
            self.service._v2_receipts_all()
        with self.assertRaises(AccessError):
            self.env['baseer.bwork.service'].with_user(self.outsider)._v2_receipts_all()

    def test_create_only_cannot_confirm_and_receive_only_can_finish(self):
        self.operator.write({'bwork_order_receive': False})
        with self.assertRaises(AccessError):
            self.service._v2_receipt_confirm(self.order_id, self._payload())
        self.assertEqual(self.order.state, 'sent')
        self.operator.write({'bwork_order_create': False, 'bwork_order_receive': True})
        with self.assertRaises(AccessError):
            self.service._v2_order_options(self.company.id)
        completed = self.service._v2_receipt_confirm(self.order_id, self._payload())
        self.assertEqual(completed['receipt']['state'], 'purchased')

    def _room_order(self):
        admin = self.env.ref('base.user_admin')
        admin.write({'company_ids': [Command.link(self.company.id)], 'group_ids': [Command.link(
            self.env.ref('baseer_bwork.group_bwork_manager').id,
        )]})
        room = self.env['baseer.bwork.room'].with_user(admin).with_company(self.company).create({
            'name': 'BWork receipt result', 'company_id': self.company.id,
        })
        membership = self.env['baseer.bwork.membership'].with_user(admin).with_company(
            self.company,
        ).create({'room_id': room.id, 'user_id': self.operator.id})
        order_id = self.service._v2_order_create({
            'api_version': 2, 'company_id': self.company.id,
            'warehouse_id': self.warehouse.id, 'representative_partner_id': None,
            'client_uuid': str(uuid4()), 'room_id': room.id,
            'lines': [{'option_id': self.option.id, 'quantity': '2.00'}],
        })['order']['id']
        return room, membership, self.env['baseer.procurement.request'].sudo().browse(order_id)

    def test_receipt_share_is_separate_server_authored_and_idempotent(self):
        room, membership, order = self._room_order()
        self.option.product_id.default_code = 'SECRET-SKU'
        self.order_id, self.order = order.id, order
        self.service._v2_receipt_confirm(order.id, self._payload(quantity='1.00', price='7.25'))
        share = {'api_version': 2, 'company_id': self.company.id}
        first = self.service._v2_receipt_share(order.id, share)
        second = self.service._v2_receipt_share(order.id, share)
        another = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Second BWork cashier', 'login': 'bwork-receipt-other-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'baseer_access_role': 'pos_cashier',
        })
        another.write({'group_ids': [Command.link(
            self.env.ref('baseer_bwork_procurement.group_bwork_procurement_operator').id,
        )]})
        another.write({'bwork_order_view': True, 'bwork_order_receive': True})
        self.env['baseer.bwork.membership'].with_user(
            self.env.ref('base.user_admin'),
        ).with_company(self.company).create({'room_id': room.id, 'user_id': another.id})
        cross_service = self.env['baseer.bwork.service'].with_user(another)
        self.assertFalse(cross_service.env.su)
        with self.assertRaises(AccessError):
            cross_service._v2_receipt_share(order.id, share)
        # Replay still requires explicit chat authorization under opt-in defaults.
        another.write({'bwork_chat_view': True, 'bwork_chat_send': True})
        cross_user = cross_service._v2_receipt_share(order.id, share)
        self.assertTrue(first['shared'])
        self.assertFalse(first['replayed'])
        self.assertTrue(second['replayed'])
        self.assertEqual(first['message_id'], second['message_id'])
        self.assertEqual(first['message_id'], cross_user['message_id'])
        self.assertTrue(cross_user['replayed'])
        order.invalidate_recordset()
        self.assertEqual(order.receipt_result_message_id.id, first['message_id'])
        self.assertEqual(order.receipt_result_message_id.room_id, room)
        self.assertEqual(order.receipt_result_message_id.membership_id, membership)
        self.assertIn('7.25', order.receipt_result_message_id.text)
        self.assertNotIn('SECRET-SKU', order.receipt_result_message_id.text)
        self.assertEqual(self.env['baseer.bwork.message'].sudo().search_count([
            ('room_id', '=', room.id), ('client_uuid', '=', order.receipt_share_uuid),
        ]), 1)

    def test_share_inflight_other_transaction_retries_then_replays_once(self):
        room, _membership, order = self._room_order()
        self.order_id, self.order = order.id, order
        self.service._v2_receipt_confirm(order.id, self._payload())
        payload = {'api_version': 2, 'company_id': self.company.id}
        with self.env.registry.cursor() as concurrent_cr:
            concurrent_cr.execute(
                'SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))',
                ['bwork-receipt-share:%s' % order.id],
            )
            self.assertTrue(concurrent_cr.fetchone()[0])
            with self.assertRaises(ProtocolError) as retry:
                self.service._v2_receipt_share(order.id, payload)
            self.assertEqual(retry.exception.status, 409)
            self.assertEqual(retry.exception.code, 'retry')
            order.invalidate_recordset()
            self.assertFalse(order.receipt_result_message_id)
            concurrent_cr.rollback()
        first = self.service._v2_receipt_share(order.id, payload)
        replay = self.service._v2_receipt_share(order.id, payload)
        self.assertFalse(first['replayed'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(first['message_id'], replay['message_id'])
        self.assertEqual(self.env['baseer.bwork.message'].sudo().search_count([
            ('room_id', '=', room.id), ('client_uuid', '=', order.receipt_share_uuid),
        ]), 1)

    def test_share_without_original_room_keeps_purchased_stock(self):
        self.service._v2_receipt_confirm(self.order_id, self._payload())
        picking = self.order.picking_id
        with self.assertRaises(ProtocolError) as denied:
            self.service._v2_receipt_share(self.order_id, {
                'api_version': 2, 'company_id': self.company.id,
            })
        self.assertEqual(denied.exception.code, 'room_unavailable')
        self.order.invalidate_recordset()
        self.assertEqual(self.order.state, 'purchased')
        self.assertEqual(self.order.picking_id, picking)
        self.assertFalse(self.order.receipt_result_message_id)

    def test_share_requires_completed_receipt_original_membership_and_company(self):
        room, membership, order = self._room_order()
        payload = {'api_version': 2, 'company_id': self.company.id}
        with self.assertRaises(ProtocolError) as unfinished:
            self.service._v2_receipt_share(order.id, payload)
        self.assertEqual(unfinished.exception.code, 'receipt_unavailable')
        self.order_id, self.order = order.id, order
        self.service._v2_receipt_confirm(order.id, self._payload())
        admin = self.env.ref('base.user_admin')
        membership.with_user(admin).with_company(self.company).action_revoke()
        with self.assertRaises(ProtocolError) as revoked:
            self.service._v2_receipt_share(order.id, payload)
        self.assertEqual(revoked.exception.code, 'room_unavailable')
        with self.assertRaises(AccessError):
            self.service._v2_receipt_share(order.id, {
                'api_version': 2, 'company_id': self.foreign.id,
            })
        order.invalidate_recordset()
        self.assertFalse(order.receipt_result_message_id)
        self.assertEqual(order.state, 'purchased')
        self.assertEqual(room.company_id, self.company)

    def test_receipt_product_label_has_no_code_and_keeps_real_parentheses(self):
        self.option.product_id.write({
            'name': 'Ingredient (large)',
            'default_code': 'BWORK-123',
        })

        detail = self.service._v2_receipt_detail(self.company.id, self.order_id)

        self.assertEqual(detail['lines'][0]['product_name'], 'Ingredient (large)')
        self.assertNotIn('BWORK-123', detail['lines'][0]['product_name'])

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
        with patch('odoo.addons.baseer_bwork_procurement.models.service.BWorkProcurementService._order_publish_change',
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
        # This is a hook-count test, not a BWork privilege escalation.  Use
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
                bwork_receipt_internal=True,
            ).confirm_actual_from_catalog(self.order_id, native_lines)
        with self.assertRaises(AccessError):
            self.order.with_user(self.operator).sudo().confirm_actual_from_catalog(
                self.order_id, native_lines,
            )
        with self.assertRaises(AccessError):
            self.env['baseer.bwork.service'].with_user(self.outsider)._v2_receipts(self.company.id)
        with self.assertRaises(AccessError):
            self.service._v2_receipt_detail(self.foreign.id, self.order_id)
        with self.assertRaises(AccessError):
            self.service._v2_receipt_confirm(self.order_id, {
                **self._payload(), 'company_id': self.foreign.id,
            })
        for payload in (
                self._payload(quantity='0.00', price='0.00'),
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
            'name': 'Native test manager', 'login': 'bwork-manager-%s' % uuid4().hex,
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

    def test_bwork_over_receipt_preserves_requested_quantity_and_replays_once(self):
        payload = self._payload(quantity='3.50', price='9.50')
        result = self.service._v2_receipt_confirm(self.order_id, payload)
        self.order.invalidate_recordset()
        self.assertEqual(result['receipt']['state'], 'purchased')
        self.assertEqual(result['receipt']['actual_total'], '33.25')
        self.assertEqual(self.order.line_ids.requested_qty, 2.0)
        self.assertEqual(self.order.line_ids.manager_received_qty, 3.5)
        self.assertEqual(self.order.line_ids.actual_qty, 3.5)
        self.assertEqual(self.order.line_ids.actual_price, 9.5)
        self.assertEqual(len(self.order.picking_id.move_ids), 1)
        self.assertEqual(self.order.picking_id.move_ids.quantity, 3.5)
        self.assertEqual(self.env['baseer.procurement.price.history'].sudo().search_count([
            ('request_id', '=', self.order_id),
        ]), 1)
        replay = self.service._v2_receipt_confirm(self.order_id, payload)
        self.assertTrue(replay['replayed'])
        self.assertEqual(self.env['stock.picking'].sudo().search_count([
            ('origin', '=', self.order.name),
        ]), 1)
        self.assertEqual(self.env['baseer.procurement.price.history'].sudo().search_count([
            ('request_id', '=', self.order_id),
        ]), 1)

    def test_native_receipt_overage_guard_is_not_relaxed(self):
        line = self.order.line_ids.with_company(self.company)
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                line.sudo().with_context(cashier_receipt_internal=True).write({
                    'manager_received_qty': 3.0,
                })
        self.order.invalidate_recordset()
        self.assertEqual(self.order.line_ids.manager_received_qty, 0.0)

    def test_received_state_bwork_overage_keeps_manager_audit(self):
        manager_group = self.env.ref('baseer_procurement_requests.group_procurement_manager')
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Native overage manager', 'login': 'bwork-manager-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id, manager_group.id])],
        })
        self.env['baseer.procurement.request'].with_user(manager).with_company(
            self.company,
        ).confirm_manager_receipt_from_catalog(self.order_id, [{
            'line_id': self.order.line_ids.id, 'manager_received_qty': '1.50',
        }])
        result = self.service._v2_receipt_confirm(self.order_id, self._payload(
            quantity='2.50', price='8.00',
        ))
        self.order.invalidate_recordset()
        self.assertEqual(result['receipt']['state'], 'purchased')
        self.assertEqual(self.order.line_ids.requested_qty, 2.0)
        self.assertEqual(self.order.line_ids.manager_received_qty, 1.5)
        self.assertEqual(self.order.line_ids.actual_qty, 2.5)
        self.assertEqual(result['receipt']['actual_total'], '20.00')

    def test_owner_with_explicit_bwork_grant_can_complete_receipt(self):
        owner = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BWork receipt owner', 'login': 'bwork-owner-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'baseer_access_role': 'owner',
        })
        owner.write({'bwork_order_view': True})
        owner_service = self.env['baseer.bwork.service'].with_user(owner)
        self.assertEqual(owner_service._v2_order_options()['access'], 'viewer')
        with self.assertRaises(AccessError):
            owner_service._v2_receipts(self.company.id)
        owner.write({'bwork_order_create': True, 'bwork_order_receive': True})
        self.assertEqual(owner_service._v2_order_options()['access'], 'operator')
        self.assertEqual(len(owner_service._v2_receipts(self.company.id)['orders']), 1)
        result = owner_service._v2_receipt_confirm(self.order_id, self._payload(
            quantity='1.25', price='8.50',
        ))
        self.assertEqual(result['receipt']['state'], 'purchased')
        self.assertEqual(result['receipt']['confirmed_by_id'], owner.id)
        self.order.invalidate_recordset()
        self.assertEqual(self.order.actual_confirmed_by_id, owner)

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
        for name, storable in (('BWork receipt service', False),
                               ('BWork receipt omitted ingredient', True)):
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
                ['bwork-receipt:%s' % payload['client_uuid']],
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

    def test_bwork_role_is_optional_per_user_not_inherited_from_preset(self):
        if 'baseer_access_role' not in self.env['res.users']._fields:
            self.skipTest('Baseer access-role module is not installed')
        group = self.env.ref('baseer_bwork_procurement.group_bwork_procurement_operator')
        users = []
        for role in ('cashier', 'pos_cashier', 'accountant'):
            users.append(self.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'BWork optional role %s' % role,
                'login': 'bwork-role-%s-%s' % (role, uuid4().hex),
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
