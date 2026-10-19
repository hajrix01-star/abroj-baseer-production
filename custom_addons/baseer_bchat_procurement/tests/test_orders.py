"""The employee-facing bridge must not confer procurement's broad ERP rights."""
import hashlib
import json
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.baseer_bchat.contracts import ProtocolError
from odoo.addons.baseer_procurement_requests.models.procurement import (
    OPTION_SYSTEM_WRITE, REQUEST_CREATE_INTERNAL,
)


@tagged('post_install', '-at_install', 'baseer_bchat_procurement')
class BChatOrderCase(TransactionCase):
    def setUp(self):
        super().setUp()
        if 'baseer_access_role' not in self.env['res.users']._fields:
            self.skipTest('BChat procurement requires the Baseer access role field')
        self.company = self.env['res.company'].create({'name': 'BChat order company %s' % uuid4().hex[:8]})
        self.other_company = self.env['res.company'].create({'name': 'BChat foreign company %s' % uuid4().hex[:8]})
        self.user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat order employee', 'login': 'bchat-order-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator').id,
            ])],
        })
        self.user.write({'baseer_access_role': 'pos_cashier'})
        self.user.write({'group_ids': [Command.link(
            self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator').id,
        )]})
        self.user.write({'bchat_order_view': True, 'bchat_order_create': True,
                         'bchat_order_receive': True})
        self.other_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat foreign employee', 'login': 'bchat-order-foreign-%s' % uuid4().hex,
            'company_id': self.other_company.id,
            'company_ids': [Command.set(self.other_company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.warehouse:
            self.warehouse = self.env['stock.warehouse'].create({
                'name': 'BChat order warehouse', 'code': 'BC%s' % self.company.id,
                'company_id': self.company.id,
            })
        uom = self.env.ref('uom.product_uom_unit')
        self.category = self.env['product.category'].create({'name': 'BChat ingredients'})
        self.product = self.env['product.product'].with_company(self.company).create({
            'name': 'BChat chicken', 'company_id': self.company.id,
            'categ_id': self.category.id, 'uom_id': uom.id,
            'purchase_ok': True, 'is_storable': True,
        })
        self.option = self.env['baseer.procurement.purchase.option'].with_company(self.company).create({
            'name': 'Kilogram', 'company_id': self.company.id,
            'product_id': self.product.id, 'uom_id': uom.id,
            'packaging_note': 'Case of 12',
        })
        self.service = self.env['baseer.bchat.service'].with_user(self.user)

    def _representative(self, name, company=None):
        partner = self.env['res.partner'].create({
            'name': name, 'company_id': company.id if company else False,
            'is_company': False,
        })
        partner.with_company(company or self.company).write({'is_purchase_representative': True})
        return partner

    def _payload(self, token=None, representative=None, quantity='2.00'):
        return {
            'api_version': 2, 'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'representative_partner_id': representative.id if representative else None,
            'client_uuid': token or str(uuid4()),
            'lines': [{'option_id': self.option.id, 'quantity': quantity}],
        }

    def _quote_payload(self, quantity='2.00'):
        return {
            'api_version': 2, 'company_id': self.company.id,
            'warehouse_id': self.warehouse.id, 'cart_revision': 1,
            'lines': [{'option_id': self.option.id, 'quantity': quantity}],
        }

    def _workflow_order(self):
        result = self.service._v2_order_create({**self._payload(), 'purchase_route': 'cash'})
        return self.env['baseer.procurement.request'].sudo().browse(result['order']['id'])

    def test_workflow_version_and_company_filtered_all_preserve_legacy_scope(self):
        self.assertEqual(self.service._v2_order_options()['workflow_version'], 1)
        self.assertEqual(self.service._v2_order_options(self.company.id)['workflow_version'], 1)
        own = self._workflow_order()
        Order = self.env['baseer.procurement.request'].sudo().with_company(self.company).with_context(**{REQUEST_CREATE_INTERNAL: True})
        colleague_order = Order.create({
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'requester_id': self.other_user.id, 'source_channel': 'bchat', 'state': 'sent',
        })
        page_orders = Order.create([{
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'requester_id': self.other_user.id, 'source_channel': 'bchat', 'state': 'sent',
        } for _ in range(30)])
        first = self.service._v2_orders_all(company_id=self.company.id)
        second = self.service._v2_orders_all(first['next_before_id'], company_id=self.company.id)
        rows = first['orders'] + second['orders']
        self.assertEqual(len(first['orders']), 30)
        self.assertEqual({row['id'] for row in rows}, {own.id, colleague_order.id, *page_orders.ids})
        self.assertTrue(all(row['company_id'] == self.company.id for row in rows))
        self.assertEqual([row['id'] for row in rows], sorted([row['id'] for row in rows], reverse=True))
        self.assertEqual([row['id'] for row in self.service._v2_orders(self.company.id)['orders']], [own.id])
        with self.assertRaises(AccessError):
            self.service._v2_orders_all(company_id=self.other_company.id)

    def test_workflow_room_pages_search_and_preferred_are_names_only(self):
        rooms = [self._room_for_employee('Workflow room %02d' % number)[1] for number in range(52)]
        with patch.object(type(self.service), '_v2_room_rows', side_effect=AssertionError('Chat metadata must not be read')):
            first = self.service._v2_order_rooms(self.company.id, preferred_room_id=rooms[-1].id)
            second = self.service._v2_order_rooms(self.company.id, after_id=first['next_after_id'])
            searched = self.service._v2_order_rooms(self.company.id, 'Workflow room 00', preferred_room_id=rooms[-1].id)
        self.assertEqual([room['id'] for room in first['rooms']], [room.id for room in rooms[:50]])
        self.assertEqual([room['id'] for room in second['rooms']], [room.id for room in rooms[50:]])
        self.assertIsNone(second['next_after_id'])
        self.assertEqual(first['preferred_room'], {'id': rooms[-1].id, 'name': rooms[-1].name})
        self.assertEqual(searched['rooms'], [{'id': rooms[0].id, 'name': rooms[0].name}])
        self.assertEqual(searched['preferred_room'], first['preferred_room'])
        self.assertTrue(all(set(room) == {'id', 'name'} for room in first['rooms']))

    def test_workflow_room_preference_never_grants_membership_company_or_send_access(self):
        manager, room, membership = self._room_for_employee()
        membership.with_user(manager).with_company(self.company).action_revoke()
        self.assertIsNone(self.service._v2_order_rooms(self.company.id, preferred_room_id=room.id)['preferred_room'])
        with self.assertRaises(AccessError):
            self.service._v2_order_rooms(self.other_company.id, preferred_room_id=room.id)
        self.user.write({'bchat_chat_send': False})
        with self.assertRaises(AccessError):
            self.service._v2_order_rooms(self.company.id)
        self.user.write({'bchat_chat_send': True, 'bchat_chat_view': False})
        # Existing effective chat_send intersects chat_view; the new route does not bypass it.
        with self.assertRaises(AccessError):
            self.service._v2_order_rooms(self.company.id)
        self.assertEqual(self.service._v2_order_options()['workflow_version'], 1)

    def test_workflow_room_query_boundaries(self):
        for term in (True, 1, [], 'a' * 257, 'أ' * 129, '\ud800'):
            with self.subTest(term=repr(term)), self.assertRaises(ProtocolError):
                self.service._v2_order_rooms(self.company.id, search_term=term)
        self.service._v2_order_rooms(self.company.id, search_term='أ' * 128)
        for field in ('after_id', 'preferred_room_id'):
            for invalid in (0, True, -1, '1', 2147483648):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ProtocolError):
                    self.service._v2_order_rooms(self.company.id, **{field: invalid})

    def test_workflow_room_revoke_after_search_requires_reload_instead_of_false_end(self):
        fixtures = [self._room_for_employee('Workflow race %02d' % number) for number in range(52)]
        manager, first_room, first_membership = fixtures[0]
        Room = type(first_room)
        real_lock = Room._lock_for_read
        revoked = False

        def revoke_after_search(records, room_id):
            nonlocal revoked
            result = real_lock(records, room_id)
            if not revoked:
                revoked = True
                first_membership.with_user(manager).with_company(self.company).action_revoke()
            return result

        with patch.object(Room, '_lock_for_read', revoke_after_search):
            with self.assertRaises(ProtocolError) as changed:
                self.service._v2_order_rooms(self.company.id)
        self.assertEqual((changed.exception.code, changed.exception.status), ('retry', 409))
        # Odoo assertRaises rolls back the injected revoke; restore it for the reload.
        first_membership.with_user(manager).with_company(self.company).action_revoke()
        refreshed = self.service._v2_order_rooms(self.company.id)
        self.assertEqual(len(refreshed['rooms']), 50)
        self.assertIsNotNone(refreshed['next_after_id'])
        self.assertNotIn(first_room.id, [row['id'] for row in refreshed['rooms']])
        final = self.service._v2_order_rooms(self.company.id, after_id=refreshed['next_after_id'])
        self.assertEqual([row['id'] for row in final['rooms']], [fixtures[-1][1].id])
        self.assertIsNone(final['next_after_id'])

    def test_workflow_share_is_once_atomic_preserves_creation_intent_and_stored_prices(self):
        self.option.sudo().with_context(**{OPTION_SYSTEM_WRITE: True}).write({'last_price': 6})
        order = self._workflow_order()
        _, room, _membership = self._room_for_employee()
        self.option.sudo().with_context(**{OPTION_SYSTEM_WRITE: True}).write({'last_price': 99})
        original = (order.client_token, order.client_payload_hash, order.state)
        payload = {'api_version': 2, 'company_id': self.company.id, 'room_id': room.id}
        first = self.service._v2_order_share(order.id, payload)
        replay = self.service._v2_order_share(order.id, payload)
        self.assertFalse(first['replayed'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(first['message_id'], replay['message_id'])
        order.invalidate_recordset()
        self.assertEqual((order.client_token, order.client_payload_hash, order.state), original)
        self.assertEqual(order.bchat_room_id, room)
        self.assertIn('سعر الوحدة: 6.00', order.bchat_message_id.text)
        self.assertNotIn('99.00', order.bchat_message_id.text)
        self.assertEqual(self.env['baseer.bchat.message'].sudo().search_count([
            ('room_id', '=', room.id), ('author_user_id', '=', self.user.id),
        ]), 1)
        retry_creation = self.service._v2_order_create({**self._payload(order.client_token), 'purchase_route': 'cash'})
        self.assertTrue(retry_creation['replayed'])
        self.assertEqual(retry_creation['order']['id'], order.id)

    def test_workflow_share_rejects_retarget_revocation_and_foreign_requesters(self):
        order = self._workflow_order()
        manager, room, membership = self._room_for_employee('Original')
        _, other_room, _ = self._room_for_employee('Other')
        payload = {'api_version': 2, 'company_id': self.company.id, 'room_id': room.id}
        self.service._v2_order_share(order.id, payload)
        with self.assertRaises(ProtocolError) as conflict:
            self.service._v2_order_share(order.id, {**payload, 'room_id': other_room.id})
        self.assertEqual(conflict.exception.code, 'order_share_conflict')
        membership.with_user(manager).with_company(self.company).action_revoke()
        with self.assertRaises(ProtocolError) as unavailable:
            self.service._v2_order_share(order.id, payload)
        self.assertEqual(unavailable.exception.code, 'room_unavailable')
        self.user.write({'bchat_order_create': False})
        with self.assertRaises(AccessError):
            self.service._v2_order_share(order.id, payload)
        self.user.write({'bchat_order_create': True})
        foreign = self.env['baseer.procurement.request'].sudo().with_company(self.company).with_context(**{REQUEST_CREATE_INTERNAL: True}).create({
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'requester_id': self.other_user.id, 'source_channel': 'bchat', 'state': 'sent',
        })
        with self.assertRaises(ProtocolError) as forbidden:
            self.service._v2_order_share(foreign.id, payload)
        self.assertEqual(forbidden.exception.status, 404)

    def test_workflow_share_failure_rolls_back_message_and_link_but_not_created_order(self):
        order = self._workflow_order()
        _, room, _ = self._room_for_employee()
        payload = {'api_version': 2, 'company_id': self.company.id, 'room_id': room.id}
        Model = type(order)
        real_write = Model.write

        def reject_link(records, values):
            if 'bchat_message_id' in values:
                raise AccessError('Test link persistence failure')
            return real_write(records, values)

        with patch.object(Model, 'write', reject_link), self.assertRaises(AccessError):
            self.service._v2_order_share(order.id, payload)
        order.invalidate_recordset()
        self.assertEqual(order.state, 'sent')
        self.assertFalse(order.bchat_room_id)
        self.assertFalse(order.bchat_message_id)
        self.assertFalse(self.env['baseer.bchat.message'].sudo().search_count([('room_id', '=', room.id)]))
        self.assertTrue(self.service._v2_order_share(order.id, payload)['shared'])

    def test_workflow_share_partial_links_and_body_overflow_do_not_mutate_order(self):
        order = self._workflow_order()
        _, room, _ = self._room_for_employee()
        payload = {'api_version': 2, 'company_id': self.company.id, 'room_id': room.id}
        with patch('odoo.addons.baseer_bchat_procurement.models.service.MAX_ROOM_MESSAGE_BYTES', 10):
            with self.assertRaises(ProtocolError) as too_large:
                self.service._v2_order_share(order.id, payload)
        self.assertEqual(too_large.exception.code, 'room_message_too_long')
        order.invalidate_recordset()
        self.assertEqual(order.state, 'sent')
        self.assertFalse(order.bchat_room_id)
        self.assertFalse(self.env['baseer.bchat.message'].sudo().search_count([('room_id', '=', room.id)]))
        order.with_context(**{REQUEST_CREATE_INTERNAL: True}).write({'bchat_room_id': room.id})
        with self.assertRaises(ProtocolError) as partial:
            self.service._v2_order_share(order.id, payload)
        self.assertEqual(partial.exception.code, 'order_share_incomplete')

    def test_workflow_share_inflight_lock_returns_retry_without_message(self):
        order = self._workflow_order()
        _, room, _ = self._room_for_employee()
        with self.env.registry.cursor() as concurrent_cr:
            concurrent_cr.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))', ['bchat-order-share:%s' % order.id])
            self.assertTrue(concurrent_cr.fetchone()[0])
            with self.assertRaises(ProtocolError) as retry:
                self.service._v2_order_share(order.id, {'api_version': 2, 'company_id': self.company.id, 'room_id': room.id})
            self.assertEqual(retry.exception.code, 'retry')
        self.assertFalse(self.env['baseer.bchat.message'].sudo().search_count([('room_id', '=', room.id)]))

    def test_workflow_share_checks_room_scope_before_foreign_lock_and_validates_payload(self):
        order = self._workflow_order()
        manager, _room, _ = self._room_for_employee()
        manager.write({'company_ids': [Command.link(self.other_company.id)]})
        foreign_room = self.env['baseer.bchat.room'].with_user(manager).with_company(self.other_company).create({
            'name': 'Foreign room must not be locked', 'company_id': self.other_company.id,
        })
        payload = {'api_version': 2, 'company_id': self.company.id, 'room_id': foreign_room.id}
        with patch.object(type(self.service), '_v2_lock_room', side_effect=AssertionError('Foreign room lock')):
            with self.assertRaises(ProtocolError) as denied:
                self.service._v2_order_share(order.id, payload)
        self.assertEqual(denied.exception.code, 'room_unavailable')
        for malformed in ({**payload, 'api_version': True}, {**payload, 'room_id': 0},
                          {**payload, 'room_id': '1'}, {**payload, 'company_id': 2147483648},
                          {**payload, 'client_uuid': str(uuid4())}, {**payload, 'text': 'Client total'}):
            with self.subTest(malformed=malformed), self.assertRaises(ProtocolError):
                self.service._v2_order_share(order.id, malformed)

    def test_workflow_share_rejects_a_message_link_authored_by_someone_else(self):
        order = self._workflow_order()
        manager, room, _membership = self._room_for_employee()
        payload = {'api_version': 2, 'company_id': self.company.id, 'room_id': room.id}
        self.service._v2_order_share(order.id, payload)
        self.other_user.write({'company_ids': [Command.link(self.company.id)]})
        membership = self.env['baseer.bchat.membership'].with_user(manager).with_company(self.company).create({
            'room_id': room.id, 'user_id': self.other_user.id,
        })
        forged = self.env['baseer.bchat.service'].with_user(self.other_user)._v2_send(room.id, {
            'api_version': 2, 'membership_id': membership.id, 'client_uuid': str(uuid4()), 'text': 'Unrelated message',
        })
        order.with_context(**{REQUEST_CREATE_INTERNAL: True}).write({'bchat_message_id': forged['message_id']})
        before = self.env['baseer.bchat.message'].sudo().search_count([('room_id', '=', room.id)])
        with self.assertRaises(ProtocolError) as invalid:
            self.service._v2_order_share(order.id, payload)
        self.assertEqual(invalid.exception.code, 'order_share_incomplete')
        self.assertEqual(self.env['baseer.bchat.message'].sudo().search_count([('room_id', '=', room.id)]), before)

    def test_owner_reads_without_grant_and_operates_after_explicit_grant(self):
        representative = self._representative('Owner read-only representative', self.company)
        order_id = self.service._v2_order_create(
            self._payload(representative=representative))['order']['id']
        self.user.write({'baseer_access_role': 'owner'})
        self.user.write({'bchat_order_create': False, 'bchat_order_receive': False})
        self.assertEqual(self.service._v2_order_options()['access'], 'viewer')
        self.assertIn(order_id, [row['id'] for row in self.service._v2_orders_all()['orders']])
        self.assertEqual(
            self.service._v2_order_detail(self.company.id, order_id, scope='all')['order']['id'],
            order_id,
        )
        for operation in (
                lambda: self.service._v2_order_options(self.company.id),
                lambda: self.service._v2_order_quote(self._quote_payload()),
                lambda: self.service._v2_order_create(self._payload()),
                lambda: self.service._v2_receipts(self.company.id),
                lambda: self.service._v2_receipt_share(
                    order_id, {'api_version': 2, 'company_id': self.company.id}),
        ):
            with self.assertRaises(AccessError):
                operation()
        self.user.write({'bchat_order_create': True, 'bchat_order_receive': True})
        self.assertEqual(self.service._v2_order_options()['access'], 'operator')
        self.assertEqual(self.service._v2_order_create(self._payload())['order']['state'], 'sent')
        self.user.write({'bchat_order_create': False, 'bchat_order_receive': False})
        self.assertEqual(self.service._v2_order_options()['access'], 'viewer')

    def test_representative_flag_does_not_grant_order_api(self):
        self.other_user.partner_id.with_company(self.other_company).write({
            'is_purchase_representative': True,
        })
        service = self.env['baseer.bchat.service'].with_user(self.other_user)
        with self.assertRaises(AccessError):
            service._v2_order_options()

    def test_quote_reads_current_price_without_writing_and_create_reprices(self):
        self._representative('Buyer')
        Order = self.env['baseer.procurement.request'].sudo()
        Option = self.env['baseer.procurement.purchase.option'].sudo()
        before_orders = Order.search_count([('company_id', '=', self.company.id)])
        before_options = Option.search_count([('company_id', '=', self.company.id)])
        payload = self._quote_payload('2.50')
        for price, expected in [(0, '0.00'), (0.01, '0.03'), (8.86, '22.15')]:
            self.option.sudo().with_company(self.company).with_context(**{
                OPTION_SYSTEM_WRITE: True,
            }).write({'last_price': price})
            quote = self.service._v2_order_quote(payload)
            self.assertEqual(quote['cart_revision'], 1)
            self.assertEqual(quote['estimated_total'], expected)
            self.assertEqual(quote['lines'], [{
                'option_id': self.option.id, 'quantity': '2.50',
                'unit_price': '%.2f' % price, 'line_total': expected,
            }])
            self.assertEqual(quote['currency_code'], self.company.currency_id.name)
            self.assertRegex(quote['quoted_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertEqual(Order.search_count([('company_id', '=', self.company.id)]), before_orders)
        self.assertEqual(Option.search_count([('company_id', '=', self.company.id)]), before_options)
        self.option.sudo().with_company(self.company).with_context(**{
            OPTION_SYSTEM_WRITE: True,
        }).write({'last_price': 9})
        created = self.service._v2_order_create(self._payload(quantity='2.50'))
        self.assertEqual(created['order']['requested_total'], '22.50')

    def test_quote_rejects_foreign_unavailable_duplicate_and_malformed_lines(self):
        payload = self._quote_payload()
        with self.assertRaises(AccessError):
            self.service._v2_order_quote({**payload, 'company_id': self.other_company.id})
        with self.assertRaises(ProtocolError) as warehouse:
            self.service._v2_order_quote({**payload, 'warehouse_id': 2147483647})
        self.assertEqual(warehouse.exception.status, 403)
        with self.assertRaises(ProtocolError) as option:
            self.service._v2_order_quote({**payload, 'lines': [
                {'option_id': 2147483647, 'quantity': '1.00'},
            ]})
        self.assertEqual(option.exception.status, 409)
        second = self.env['baseer.procurement.purchase.option'].with_company(self.company).create({
            'name': 'Other pack', 'company_id': self.company.id,
            'product_id': self.product.id, 'uom_id': self.option.uom_id.id,
        })
        with self.assertRaises(ProtocolError) as duplicate_product:
            self.service._v2_order_quote({**payload, 'lines': payload['lines'] + [
                {'option_id': second.id, 'quantity': '1.00'},
            ]})
        self.assertEqual(duplicate_product.exception.status, 409)
        for malformed in (
                {**payload, 'cart_revision': True},
                {**payload, 'cart_revision': 2147483648},
                {**payload, 'lines': []},
                {**payload, 'lines': payload['lines'] * 2},
                {**payload, 'lines': [{'option_id': self.option.id, 'quantity': '0'}]},
                {**payload, 'lines': [{'option_id': self.option.id, 'quantity': '1.001'}]},
                {**payload, 'extra': 1}):
            with self.subTest(malformed=malformed), self.assertRaises(ProtocolError) as invalid:
                self.service._v2_order_quote(malformed)
            self.assertEqual(invalid.exception.status, 400)

    def _room_for_employee(self, name='Purchase updates'):
        manager = self.env.ref('base.user_admin')
        manager.write({
            'company_ids': [Command.link(self.company.id)],
            'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)],
        })
        room = self.env['baseer.bchat.room'].with_user(manager).with_company(self.company).create({
            'name': name, 'company_id': self.company.id,
        })
        membership = self.env['baseer.bchat.membership'].with_user(manager).with_company(self.company).create({
            'room_id': room.id, 'user_id': self.user.id,
        })
        return manager, room, membership

    def test_room_order_is_atomic_and_replays_after_membership_revocation(self):
        self._representative('Buyer')
        manager, room, membership = self._room_for_employee()
        payload = {**self._payload(), 'room_id': room.id}
        created = self.service._v2_order_create(payload)
        order = self.env['baseer.procurement.request'].sudo().browse(created['order']['id'])
        self.assertEqual(order.bchat_room_id, room)
        self.assertTrue(order.bchat_message_id)
        self.assertEqual(order.bchat_message_id.room_id, room)
        self.assertEqual(order.bchat_message_id.author_user_id, self.user)
        self.assertIn(order.name, order.bchat_message_id.text)
        self.assertIn(self.product.name, order.bchat_message_id.text)
        self.assertIn(created['order']['requested_total'], order.bchat_message_id.text)
        self.assertEqual(created['order']['room_id'], room.id)
        self.assertEqual(self.service._v2_order_create(payload)['order']['id'], order.id)
        self.assertEqual(self.env['baseer.bchat.message'].sudo().search_count([
            ('room_id', '=', room.id), ('author_user_id', '=', self.user.id),
        ]), 1)
        membership.with_user(manager).with_company(self.company).action_revoke()
        self.assertTrue(self.service._v2_order_create(payload)['replayed'])
        with self.assertRaises(ProtocolError) as denied:
            self.service._v2_order_create({**self._payload(), 'room_id': room.id})
        self.assertEqual(denied.exception.code, 'room_unavailable')

    def test_room_order_text_has_names_quantities_and_server_total_without_skus(self):
        self._representative('Buyer')
        _, room, _ = self._room_for_employee()
        self.product.default_code = 'BCHAT-CHICKEN-SKU'
        second_product = self.env['product.product'].with_company(self.company).create({
            'name': 'BChat onion', 'default_code': 'BCHAT-ONION-SKU',
            'company_id': self.company.id, 'categ_id': self.category.id,
            'uom_id': self.option.uom_id.id, 'purchase_ok': True, 'is_storable': True,
        })
        second_option = self.env['baseer.procurement.purchase.option'].with_company(self.company).create({
            'name': 'Crate', 'company_id': self.company.id,
            'product_id': second_product.id, 'uom_id': self.option.uom_id.id,
        })
        self.option.sudo().with_company(self.company).with_context(**{
            OPTION_SYSTEM_WRITE: True,
        }).write({'last_price': 6})
        second_option.sudo().with_company(self.company).with_context(**{
            OPTION_SYSTEM_WRITE: True,
        }).write({'last_price': 4})
        payload = {**self._payload(quantity='2.50'), 'room_id': room.id}
        payload['lines'].append({'option_id': second_option.id, 'quantity': '3.00'})
        created = self.service._v2_order_create(payload)
        order = self.env['baseer.procurement.request'].sudo().browse(created['order']['id'])
        message = order.bchat_message_id.text
        self.assertEqual(created['order']['requested_total'], '27.00')
        self.assertIn('1. BChat chicken (Kilogram)', message)
        self.assertIn('2. BChat onion (Crate)', message)
        self.assertIn('الكمية: 2.50', message)
        self.assertIn('سعر الوحدة: 6.00', message)
        self.assertIn('مجموع الصنف: 15.00', message)
        self.assertIn('الشركة: %s' % self.company.name, message)
        self.assertIn('الإجمالي: 27.00', message)
        self.assertNotIn('BCHAT-CHICKEN-SKU', message)
        self.assertNotIn('BCHAT-ONION-SKU', message)
        self.assertNotIn('المستودع:', message)
        self.assertIn('مندوب المشتريات: Buyer', message)

    def test_room_change_and_explicit_null_conflict_with_same_order_token(self):
        self._representative('Buyer')
        token = str(uuid4())
        old = self._payload(token)
        first = self.service._v2_order_create(old)
        self.assertIsNone(first['order']['room_id'])
        self.assertTrue(self.service._v2_order_create(old)['replayed'])
        with self.assertRaises(ProtocolError) as changed:
            self.service._v2_order_create({**old, 'room_id': None})
        self.assertEqual(changed.exception.code, 'idempotency_conflict')
        manager, room, _ = self._room_for_employee()
        second = {**self._payload(), 'room_id': room.id}
        self.service._v2_order_create(second)
        other = self.env['baseer.bchat.room'].with_user(manager).with_company(self.company).create({
            'name': 'Second purchase room', 'company_id': self.company.id,
        })
        with self.assertRaises(ProtocolError) as moved:
            self.service._v2_order_create({**second, 'room_id': other.id})
        self.assertEqual(moved.exception.code, 'idempotency_conflict')

    def test_failed_room_message_rolls_back_order_and_protects_links(self):
        self._representative('Buyer')
        _, room, _ = self._room_for_employee()
        payload = {**self._payload(), 'room_id': room.id}
        with patch.object(type(self.service), '_v2_send', side_effect=ProtocolError(
                'message_failed', 'Test message failure.', 409)):
            with self.assertRaises(ProtocolError):
                self.service._v2_order_create(payload)
        self.assertFalse(self.env['baseer.procurement.request'].sudo().search([
            ('client_token', '=', payload['client_uuid']),
        ]))
        created = self.service._v2_order_create(payload)
        order = self.env['baseer.procurement.request'].sudo().browse(created['order']['id'])
        with self.assertRaises(AccessError):
            order.with_user(self.user).write({'bchat_room_id': False})
        with self.assertRaises(AccessError):
            order.sudo().write({'bchat_message_id': False})

    def test_zero_one_many_representatives_and_internal_send(self):
        with self.assertRaises(ProtocolError) as no_rep:
            self.service._v2_order_create(self._payload())
        self.assertEqual(no_rep.exception.code, 'no_representative')
        first = self._representative('Buyer One')
        options = self.service._v2_order_options(self.company.id)
        self.assertEqual([row['id'] for row in options['representatives']], [first.id])
        self.assertIn(self.warehouse.id, [row['id'] for row in options['warehouses']])
        catalog_items = self.service._v2_order_catalog(self.company.id)['items']
        self.assertIn(self.option.id, [row['id'] for row in catalog_items])
        self.assertEqual(next(row for row in catalog_items if row['id'] == self.option.id)['packaging_note'],
                         'Case of 12')
        created = self.service._v2_order_create(self._payload())
        order = self.env['baseer.procurement.request'].sudo().browse(created['order']['id'])
        self.assertEqual(order.state, 'sent')
        self.assertEqual(order.source_channel, 'bchat')
        self.assertEqual(order.requester_id, self.user)
        self.assertEqual(order.representative_partner_id, first)
        self.assertTrue(order.internal_submitted_at)
        self.assertFalse(order.whatsapp_sent_at)
        self.assertFalse(order.picking_id)
        self.assertEqual([row['id'] for row in self.service._v2_orders(self.company.id)['orders']], [order.id])
        self._representative('Buyer Two')
        with self.assertRaises(ProtocolError) as multiple:
            self.service._v2_order_create(self._payload())
        self.assertEqual(multiple.exception.code, 'representative_required')
        selected = self.service._v2_order_create(self._payload(representative=first))
        self.assertEqual(selected['order']['representative_id'], first.id)

    def test_purchase_route_options_and_direct_orders_without_representative(self):
        options = self.service._v2_order_options(self.company.id)
        self.assertEqual([row['code'] for row in options['purchase_routes']],
                         ['representative', 'cash', 'bank_transfer'])
        self.assertTrue(all(row['name'] for row in options['purchase_routes']))
        _, room, _ = self._room_for_employee()
        for route in ('cash', 'bank_transfer'):
            payload = {**self._payload(), 'purchase_route': route, 'room_id': room.id}
            with patch.object(type(self.service), '_representatives', side_effect=AssertionError(
                    'Direct purchases must not look up representatives')):
                created = self.service._v2_order_create(payload)
            order = self.env['baseer.procurement.request'].sudo().browse(created['order']['id'])
            self.assertEqual(order.purchase_route, route)
            self.assertFalse(order.representative_partner_id)
            self.assertFalse(order.purchaser_id)
            self.assertEqual(created['order']['purchase_route'], route)
            self.assertEqual(created['order']['purchase_route_name'], order._purchase_route_label())
            self.assertIsNone(created['order']['representative_id'])
            self.assertEqual(created['order']['representative_name'], '')
            self.assertIn(order._purchase_route_label(), order.bchat_message_id.text)
            self.assertIn(created['order']['requested_total'], order.bchat_message_id.text)
            detail = self.service._v2_order_detail(self.company.id, order.id)['order']
            self.assertEqual(detail['purchase_route'], route)
            self.assertEqual(detail['representative_id'], None)
            self.assertTrue(self.service._v2_order_create(payload)['replayed'])
        listed = self.service._v2_orders_all()['orders']
        self.assertEqual([row['purchase_route'] for row in listed[:2]],
                         ['bank_transfer', 'cash'])
        self.assertEqual(self.env['baseer.bchat.message'].sudo().search_count([
            ('room_id', '=', room.id), ('author_user_id', '=', self.user.id),
        ]), 2)

    def test_purchase_route_validation_and_changed_route_replay_conflict(self):
        representative = self._representative('Route buyer')
        for invalid in (None, False, '', 'credit', 3):
            with self.assertRaises(ProtocolError) as error:
                self.service._v2_order_create({**self._payload(), 'purchase_route': invalid})
            self.assertEqual(error.exception.code, 'invalid_purchase_route')
        for route in ('cash', 'bank_transfer'):
            with self.assertRaises(ProtocolError) as error:
                self.service._v2_order_create({
                    **self._payload(representative=representative), 'purchase_route': route,
                })
            self.assertEqual(error.exception.code, 'invalid_representative')
        token = str(uuid4())
        payload = {**self._payload(token), 'purchase_route': 'cash'}
        created = self.service._v2_order_create(payload)
        with self.assertRaises(ProtocolError) as error:
            self.service._v2_order_create({**payload, 'purchase_route': 'bank_transfer'})
        self.assertEqual(error.exception.code, 'idempotency_conflict')
        with self.assertRaises(ProtocolError) as error:
            self.service._v2_order_create({**payload, 'purchase_route': 'representative'})
        self.assertEqual(error.exception.code, 'idempotency_conflict')
        self.assertEqual(self.service._v2_order_create(payload)['order']['id'],
                         created['order']['id'])
        self.assertEqual(self.env['baseer.procurement.request'].sudo().search_count([
            ('client_token', '=', token),
        ]), 1)

    def test_legacy_representative_fingerprint_and_explicit_route_replay(self):
        representative = self._representative('Legacy route buyer')
        payload = self._payload(representative=representative)
        created = self.service._v2_order_create(payload)
        order = self.env['baseer.procurement.request'].sudo().browse(created['order']['id'])
        legacy_intent = {
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'representative_partner_id': representative.id,
            'lines': [{'option_id': self.option.id, 'quantity': '2.00'}],
        }
        expected_hash = hashlib.sha256(json.dumps(
            legacy_intent, sort_keys=True, separators=(',', ':'),
        ).encode()).hexdigest()
        self.assertEqual(order.client_payload_hash, expected_hash)
        replay = self.service._v2_order_create({**payload, 'purchase_route': 'representative'})
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['order']['id'], order.id)
        self.assertEqual(replay['order']['purchase_route'], 'representative')

    def test_replay_keeps_original_representative_after_catalog_change(self):
        representative = self._representative('Original Buyer')
        token = str(uuid4())
        payload = self._payload(token)
        created = self.service._v2_order_create(payload)
        representative.with_company(self.company).write({'is_purchase_representative': False})
        self._representative('Replacement Buyer')
        self.option.sudo().with_company(self.company).with_context(**{
            OPTION_SYSTEM_WRITE: True,
        }).write({'last_price': 99})
        replay = self.service._v2_order_create(payload)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['order']['id'], created['order']['id'])
        self.assertEqual(replay['order']['representative_id'], representative.id)
        with self.assertRaises(ProtocolError) as conflict:
            self.service._v2_order_create(self._payload(token, quantity='3.00'))
        self.assertEqual(conflict.exception.code, 'idempotency_conflict')
        self.assertEqual(self.env['baseer.procurement.request'].sudo().search_count([
            ('company_id', '=', self.company.id), ('client_token', '=', token),
        ]), 1)

    def test_order_detail_is_owned_read_only_and_uses_current_option_price(self):
        self._representative('Buyer')
        self.option.sudo().with_context(**{OPTION_SYSTEM_WRITE: True}).write({'last_price': 8.86})
        order_id = self.service._v2_order_create(self._payload(quantity='2.50'))['order']['id']
        order = self.env['baseer.procurement.request'].sudo().browse(order_id)
        original_price = order.line_ids.requested_price
        original_total = order.requested_total
        before_options = self.env['baseer.procurement.purchase.option'].sudo().search_count([
            ('company_id', '=', self.company.id),
        ])
        self.option.sudo().with_context(**{OPTION_SYSTEM_WRITE: True}).write({'last_price': 11.00})
        shown = self.service._v2_order_detail(self.company.id, order_id)
        self.assertEqual(shown['order']['id'], order_id)
        self.assertEqual(shown['order']['company_id'], self.company.id)
        self.assertEqual(shown['order']['warehouse_id'], self.warehouse.id)
        self.assertEqual(len(shown['lines']), 1)
        line = shown['lines'][0]
        self.assertEqual(line['line_id'], order.line_ids.id)
        self.assertEqual(line['option_id'], self.option.id)
        self.assertEqual(line['requested_qty'], '2.50')
        self.assertTrue(line['available'])
        self.assertEqual(line['current_option']['last_price'], '11.00')
        self.assertNotIn('requested_price', line)
        self.assertEqual(order.line_ids.requested_price, original_price)
        self.assertEqual(order.requested_total, original_total)
        self.assertEqual(self.env['baseer.procurement.purchase.option'].sudo().search_count([
            ('company_id', '=', self.company.id),
        ]), before_options)

    def test_order_detail_hides_foreign_non_owned_and_non_bchat_orders(self):
        self._representative('Buyer')
        order_id = self.service._v2_order_create(self._payload())['order']['id']
        same_company_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Another BChat requester', 'login': 'bchat-other-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator').id,
            ])],
        })
        same_company_user.write({'baseer_access_role': 'pos_cashier'})
        same_company_user.write({'group_ids': [Command.link(
            self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator').id,
        )]})
        same_company_user.write({'bchat_order_view': True})
        for service, company_id, tested_id in (
                (self.env['baseer.bchat.service'].with_user(same_company_user), self.company.id, order_id),
                (self.service, self.other_company.id, order_id),
                (self.service, self.company.id, order_id + 2147483)):
            with self.subTest(company_id=company_id, user_id=service.env.uid), self.assertRaises(ProtocolError) as denied:
                service._v2_order_detail(company_id, tested_id)
            self.assertEqual(denied.exception.status, 404)
        order = self.env['baseer.procurement.request'].sudo().browse(order_id)
        order.with_company(self.company).with_context(**{REQUEST_CREATE_INTERNAL: True}).write({
            'source_channel': 'odoo',
        })
        with self.assertRaises(ProtocolError) as not_bchat:
            self.service._v2_order_detail(self.company.id, order_id)
        self.assertEqual(not_bchat.exception.status, 404)

    def test_order_detail_marks_archived_option_unavailable_and_caps_bytes(self):
        self._representative('Buyer')
        order_id = self.service._v2_order_create(self._payload())['order']['id']
        self.option.sudo().write({'active': False})
        shown = self.service._v2_order_detail(self.company.id, order_id)
        self.assertEqual(len(shown['lines']), 1)
        self.assertFalse(shown['lines'][0]['available'])
        self.assertIsNone(shown['lines'][0]['current_option'])
        self.assertEqual(shown['lines'][0]['option_id'], self.option.id)
        with patch('odoo.addons.baseer_bchat_procurement.models.service.MAX_RESPONSE_BYTES', 256):
            with self.assertRaises(ProtocolError) as too_large:
                self.service._v2_order_detail(self.company.id, order_id)
        self.assertEqual(too_large.exception.status, 413)
        with patch('odoo.addons.baseer_bchat_procurement.models.service.MAX_CART_LINES', 0):
            with self.assertRaises(ProtocolError) as too_many:
                self.service._v2_order_detail(self.company.id, order_id)
        self.assertEqual(too_many.exception.status, 413)

    def test_all_orders_authorization_global_page_and_snapshot(self):
        self.user.write({'company_ids': [Command.link(self.other_company.id)]})
        warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.other_company.id),
        ], limit=1)
        if not warehouse:
            warehouse = self.env['stock.warehouse'].create({
                'name': 'BChat second warehouse', 'code': 'BS%s' % self.other_company.id,
                'company_id': self.other_company.id,
            })
        colleague = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat colleague', 'login': 'bchat-colleague-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        Order = self.env['baseer.procurement.request'].sudo().with_context(**{
            REQUEST_CREATE_INTERNAL: True,
        })
        own = Order.with_company(self.company).create({
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'requester_id': self.user.id, 'source_channel': 'bchat', 'state': 'sent',
        })
        other_channel = Order.with_company(self.company).create({
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'requester_id': self.user.id, 'source_channel': 'odoo', 'state': 'sent',
        })
        colleague_order = Order.with_company(self.company).create({
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'requester_id': colleague.id, 'source_channel': 'bchat', 'state': 'sent',
        })
        foreign = self.env['res.company'].create({'name': 'BChat excluded company'})
        foreign_warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', foreign.id),
        ], limit=1)
        if not foreign_warehouse:
            foreign_warehouse = self.env['stock.warehouse'].create({
                'name': 'BChat excluded warehouse', 'code': 'BE%s' % foreign.id,
                'company_id': foreign.id,
            })
        excluded = Order.with_company(foreign).create({
            'company_id': foreign.id, 'warehouse_id': foreign_warehouse.id,
            'requester_id': self.user.id, 'source_channel': 'bchat', 'state': 'sent',
        })
        second_company = Order.with_company(self.other_company).create({
            'company_id': self.other_company.id, 'warehouse_id': warehouse.id,
            'requester_id': self.other_user.id, 'source_channel': 'bchat', 'state': 'sent',
        })
        page_orders = Order.with_company(self.company).create([{
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'requester_id': colleague.id, 'source_channel': 'bchat', 'state': 'sent',
        } for _ in range(30)])

        legacy = self.service._v2_orders(self.company.id)['orders']
        self.assertEqual([row['id'] for row in legacy], [own.id])
        with self.assertRaises(ProtocolError) as legacy_colleague:
            self.service._v2_order_detail(self.company.id, colleague_order.id)
        self.assertEqual(legacy_colleague.exception.status, 404)

        first = self.service._v2_orders_all()
        second = self.service._v2_orders_all(first['next_before_id'])
        rows = first['orders'] + second['orders']
        ids = [row['id'] for row in rows]
        self.assertEqual(len(first['orders']), 30)
        self.assertEqual(len(rows), 33)
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {own.id, colleague_order.id, second_company.id, *page_orders.ids})
        self.assertNotIn(other_channel.id, ids)
        self.assertNotIn(excluded.id, ids)
        row = next(row for row in rows if row['id'] == colleague_order.id)
        self.assertEqual((row['company_id'], row['requester_id']), (self.company.id, colleague.id))
        self.assertEqual(row['company_name'], self.company.name)
        self.assertEqual(row['requester_name'], colleague.name)
        detail = self.service._v2_order_detail(self.company.id, colleague_order.id, scope='all')
        self.assertEqual(detail['order']['requester_id'], colleague.id)
        for company_id, order_id in ((foreign.id, excluded.id),
                                     (self.company.id, second_company.id),
                                     (self.company.id, other_channel.id)):
            with self.assertRaises(ProtocolError) as denied:
                self.service._v2_order_detail(company_id, order_id, scope='all')
            self.assertEqual(denied.exception.status, 404)

        watermark = self.service._v2_changes(0, 1)['watermark']
        snapshot = self.service._v2_change_snapshot('orders', watermark=watermark)
        self.assertEqual(snapshot['orders'][0]['id'], first['orders'][0]['id'])
        snapshot_next = self.service._v2_change_snapshot(
            'orders', snapshot['next_before_id'], watermark,
        )
        self.assertEqual([row['id'] for row in snapshot['orders'] + snapshot_next['orders']], ids)

        self.user.write({'company_ids': [Command.unlink(self.other_company.id)]})
        after_revoke = self.service._v2_orders_all()
        after_ids = [row['id'] for row in after_revoke['orders']]
        after_ids += [row['id'] for row in self.service._v2_orders_all(
            after_revoke['next_before_id'],
        )['orders']]
        self.assertNotIn(second_company.id, after_ids)
        with self.assertRaises(ProtocolError) as revoked_detail:
            self.service._v2_order_detail(self.other_company.id, second_company.id, scope='all')
        self.assertEqual(revoked_detail.exception.status, 404)
        self.user.write({'bchat_order_view': False, 'bchat_order_create': False,
                         'bchat_order_receive': False})
        with self.assertRaises(AccessError):
            self.service._v2_orders_all()

    def test_company_catalog_and_general_erp_rights_are_isolated(self):
        self._representative('Buyer')
        self._representative('Foreign Buyer', self.other_company)
        with self.assertRaises(AccessError):
            self.service._v2_order_options(self.other_company.id)
        with self.assertRaises(AccessError):
            self.service._v2_order_catalog(self.other_company.id)
        with self.assertRaises(AccessError):
            self.service._v2_order_create({**self._payload(), 'company_id': self.other_company.id})
        with self.assertRaises(ProtocolError):
            self.service._v2_order_create({**self._payload(), 'warehouse_id': 2147483647})
        with self.assertRaises(ProtocolError):
            self.service._v2_order_create({**self._payload(), 'lines': [
                {'option_id': 2147483647, 'quantity': '2.00'},
            ]})
        self.assertFalse(self.user.has_group('baseer_procurement_requests.group_procurement_user'))
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.request'].with_user(self.user).create_from_catalog(
                [{'option_id': self.option.id, 'quantity': 1}], self.warehouse.id,
            )
        self.assertFalse(self.env['baseer.procurement.request'].with_user(self.user).has_access('create'))
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.other_user)._v2_orders(self.other_company.id)

    def test_order_operator_gate_rejects_native_rights_and_role_revocation(self):
        self._representative('Buyer')
        native_only = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Native cashier without BChat role', 'login': 'native-cashier-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('baseer_procurement_requests.group_procurement_cashier').id,
            ])],
        })
        native_service = self.env['baseer.bchat.service'].with_user(native_only)
        with self.assertRaises(AccessError):
            native_service._v2_order_options(self.company.id)
        self.assertEqual(native_service._v2_rooms()['rooms'], [])
        self.assertEqual(native_service._v2_tasks()['tasks'], [])
        payload = self._payload()
        order_id = self.service._v2_order_create(payload)['order']['id']
        _, room, _ = self._room_for_employee()
        self.user.write({'bchat_order_view': False, 'bchat_order_create': False,
                         'bchat_order_receive': False})
        denied_calls = (
            lambda: self.service._v2_order_options(self.company.id),
            lambda: self.service._v2_order_catalog(self.company.id),
            lambda: self.service._v2_order_image(self.company.id, self.product.id),
            lambda: self.service._v2_orders(self.company.id),
            lambda: self.service._v2_order_detail(self.company.id, order_id),
            lambda: self.service._v2_order_quote(self._quote_payload()),
            lambda: self.service._v2_order_create(payload),  # An old UUID does not bypass the role gate.
        )
        for call in denied_calls:
            with self.subTest(call=call), self.assertRaises(AccessError):
                call()
        self.assertIn(room.id, [row['id'] for row in self.service._v2_rooms()['rooms']])
        self.assertEqual(self.service._v2_tasks()['tasks'], [])

    def test_inactive_order_operator_is_denied(self):
        self.user.active = False
        with self.assertRaises(AccessError):
            self.service._v2_order_options(self.company.id)

    def test_changed_representative_list_requires_current_choice(self):
        first = self._representative('Buyer One')
        shown = self.service._v2_order_options(self.company.id)
        self.assertEqual(len(shown['representatives']), 1)
        second = self._representative('Buyer Two')
        with self.assertRaises(ProtocolError) as changed:
            self.service._v2_order_create(self._payload())
        self.assertEqual(changed.exception.code, 'representative_required')
        second.with_company(self.company).write({'is_purchase_representative': False})
        with self.assertRaises(ProtocolError) as forged:
            self.service._v2_order_create(self._payload(representative=second))
        self.assertEqual(forged.exception.code, 'invalid_representative')
        saved = self.service._v2_order_create(self._payload(representative=first))
        self.assertEqual(saved['order']['representative_id'], first.id)

    def test_catalog_materializes_existing_odoo_default_option_and_bounds_quantity(self):
        uom = self.env.ref('uom.product_uom_unit')
        product = self.env['product.product'].with_company(self.company).create({
            'name': 'BChat onion without option', 'company_id': self.company.id,
            'categ_id': self.category.id, 'uom_id': uom.id,
            'purchase_ok': True, 'is_storable': True,
        })
        self.assertFalse(self.env['baseer.procurement.purchase.option'].search([
            ('product_id', '=', product.id),
        ]))
        page = self.service._v2_order_catalog(self.company.id)
        self.assertIn(product.id, [item['product_id'] for item in page['items']])
        self.assertIn(self.category.id, [row['id'] for row in
                                         self.service._v2_order_options(self.company.id)['categories']])
        self._representative('Buyer')
        with self.assertRaises(ProtocolError):
            self.service._v2_order_create(self._payload(quantity='9999999999999999'))
        with self.assertRaises(ProtocolError):
            self.service._v2_order_create(self._payload(quantity='1000000'))

    def test_catalog_25_products_can_return_to_first_page(self):
        category = self.env['product.category'].create({'name': 'BChat paging %s' % uuid4().hex[:8]})
        uom = self.env.ref('uom.product_uom_unit')
        products = self.env['product.product'].with_company(self.company).create([{
            'name': 'BChat page item %02d' % number,
            'company_id': self.company.id, 'categ_id': category.id,
            'uom_id': uom.id, 'purchase_ok': True, 'is_storable': True,
        } for number in range(25)])
        first = self.service._v2_order_catalog(self.company.id, category_id=category.id)
        self.assertEqual(len(first['items']), 24)
        self.assertEqual([row['product_id'] for row in first['items']], products[:24].ids)
        self.assertEqual(first['next_after_id'], products[23].id)
        second = self.service._v2_order_catalog(
            self.company.id, category_id=category.id, after_id=first['next_after_id'])
        self.assertEqual([row['product_id'] for row in second['items']], products[24:].ids)
        self.assertIsNone(second['next_after_id'])
        returned = self.service._v2_order_catalog(self.company.id, category_id=category.id)
        self.assertEqual([row['id'] for row in returned['items']],
                         [row['id'] for row in first['items']])


@tagged('post_install', '-at_install', 'baseer_bchat_procurement')
class BChatOrderHttpCase(HttpCase):
    def test_http_submission_csrf_company_and_private_rpc(self):
        if 'baseer_access_role' not in self.env['res.users']._fields:
            self.skipTest('BChat procurement requires the Baseer access role field')
        company = self.env['res.company'].create({'name': 'BChat HTTP order %s' % uuid4().hex[:8]})
        foreign = self.env['res.company'].create({'name': 'BChat HTTP foreign %s' % uuid4().hex[:8]})
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
        if not warehouse:
            warehouse = self.env['stock.warehouse'].create({
                'name': 'BChat HTTP warehouse', 'code': 'BH%s' % company.id,
                'company_id': company.id,
            })
        uom = self.env.ref('uom.product_uom_unit')
        category_values = {'name': 'BChat HTTP standard cost'}
        if 'property_cost_method' in self.env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in self.env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        category = self.env['product.category'].create(category_values)
        product = self.env['product.product'].with_company(company).create({
            'name': 'BChat HTTP ingredient', 'company_id': company.id,
            'uom_id': uom.id, 'categ_id': category.id,
            'purchase_ok': True, 'is_storable': True,
            'image_1920': (
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC'
                'AAAAC0lEQVR42mP8/x8AAusB9Y9LJykAAAAASUVORK5CYII='
            ),
        })
        option = self.env['baseer.procurement.purchase.option'].with_company(company).create({
            'name': 'Piece', 'company_id': company.id, 'product_id': product.id,
            'uom_id': uom.id,
        })
        unconfigured = self.env['product.product'].with_company(company).create({
            'name': 'BChat HTTP unconfigured ingredient', 'company_id': company.id,
            'uom_id': uom.id, 'purchase_ok': True, 'is_storable': True,
        })
        representative = self.env['res.partner'].create({'name': 'BChat HTTP buyer'})
        representative.with_company(company).is_purchase_representative = True
        password = 'test-only-%s' % uuid4().hex
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat HTTP order employee', 'login': 'bchat-order-http-%s' % uuid4().hex,
            'password': password, 'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator').id,
            ])],
        })
        user.write({'baseer_access_role': 'pos_cashier'})
        user.write({'group_ids': [Command.link(
            self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator').id,
        )]})
        user.write({'bchat_order_view': True, 'bchat_order_create': True,
                    'bchat_order_receive': True})
        manager = self.env.ref('base.user_admin')
        manager.write({'company_ids': [Command.link(company.id)], 'group_ids': [Command.link(
            self.env.ref('baseer_bchat.group_bchat_manager').id,
        )]})
        room = self.env['baseer.bchat.room'].with_user(manager).with_company(company).create({
            'name': 'HTTP order sharing', 'company_id': company.id,
        })
        self.env['baseer.bchat.membership'].with_user(manager).with_company(company).create({
            'room_id': room.id, 'user_id': user.id,
        })
        self.authenticate(user.login, password)
        bootstrap = self.url_open('/bchat/api/v2/bootstrap').json()
        csrf = bootstrap['csrf_token']
        choices = self.url_open('/bchat/api/v2/orders/options?company_id=%s' % company.id)
        self.assertEqual(choices.status_code, 200)
        self.assertEqual(choices.json()['workflow_version'], 1)
        self.assertEqual([row['id'] for row in choices.json()['representatives']], [representative.id])
        denied_foreign = self.url_open('/bchat/api/v2/orders/options?company_id=%s' % foreign.id)
        self.assertEqual(denied_foreign.status_code, 403, denied_foreign.text)
        catalog_path = '/bchat/api/v2/orders/catalog?company_id=%s' % company.id
        unconfigured_domain = [
            ('company_id', '=', company.id), ('product_id', '=', unconfigured.id),
        ]
        self.assertFalse(self.env['baseer.procurement.purchase.option'].sudo().search_count(unconfigured_domain))
        self.assertNotEqual(self.url_open(catalog_path, allow_redirects=False).status_code, 200)
        self.assertFalse(self.env['baseer.procurement.purchase.option'].sudo().search_count(unconfigured_domain))
        self.assertNotEqual(self.url_open(catalog_path, data={
            'payload': json.dumps({'api_version': 2}),
        }, allow_redirects=False).status_code, 200)
        self.assertFalse(self.env['baseer.procurement.purchase.option'].sudo().search_count(unconfigured_domain))
        catalog = self.url_open(catalog_path, data={
            'csrf_token': csrf, 'payload': json.dumps({'api_version': 2}),
        }, allow_redirects=False)
        self.assertEqual(catalog.status_code, 200)
        self.assertIn(option.id, [item['id'] for item in catalog.json()['items']])
        self.assertIn(unconfigured.id, [item['product_id'] for item in catalog.json()['items']])
        self.assertEqual(self.env['baseer.procurement.purchase.option'].sudo().search_count(unconfigured_domain), 1)
        shown = next(item for item in catalog.json()['items'] if item['id'] == option.id)
        self.assertTrue(shown['image_url'])
        thumbnail = self.url_open(shown['image_url'])
        self.assertEqual(thumbnail.status_code, 200)
        self.assertTrue(thumbnail.headers['Content-Type'].startswith('image/'))
        quote_payload = {
            'api_version': 2, 'company_id': company.id,
            'warehouse_id': warehouse.id, 'cart_revision': 3,
            'lines': [{'option_id': option.id, 'quantity': '2.00'}],
        }
        quote_path = '/bchat/api/v2/orders/quote'
        before_quote = self.env['baseer.procurement.request'].sudo().search_count([
            ('company_id', '=', company.id), ('source_channel', '=', 'bchat'),
        ])
        no_csrf_quote = self.url_open(quote_path, data={
            'payload': json.dumps(quote_payload),
        }, allow_redirects=False)
        self.assertNotEqual(no_csrf_quote.status_code, 200)
        quote = self.url_open(quote_path, data={
            'csrf_token': csrf, 'payload': json.dumps(quote_payload),
        }, allow_redirects=False)
        self.assertEqual(quote.status_code, 200, quote.text)
        self.assertEqual(quote.json()['cart_revision'], 3)
        self.assertEqual(quote.json()['lines'][0]['quantity'], '2.00')
        self.assertEqual(self.env['baseer.procurement.request'].sudo().search_count([
            ('company_id', '=', company.id), ('source_channel', '=', 'bchat'),
        ]), before_quote)
        foreign_quote = self.url_open(quote_path, data={
            'csrf_token': csrf, 'payload': json.dumps({**quote_payload, 'company_id': foreign.id}),
        }, allow_redirects=False)
        self.assertEqual(foreign_quote.status_code, 403)
        invalid_quote = self.url_open(quote_path, data={
            'csrf_token': csrf, 'payload': json.dumps({**quote_payload, 'lines': []}),
        }, allow_redirects=False)
        self.assertEqual(invalid_quote.status_code, 400)
        token = str(uuid4())
        payload = json.dumps({
            'api_version': 2, 'company_id': company.id,
            'warehouse_id': warehouse.id, 'representative_partner_id': None,
            'client_uuid': token, 'lines': [{'option_id': option.id, 'quantity': '2.00'}],
        })
        missing_csrf = self.url_open('/bchat/api/v2/orders', data={'payload': payload}, allow_redirects=False)
        self.assertNotEqual(missing_csrf.status_code, 200)
        created = self.url_open('/bchat/api/v2/orders', data={
            'csrf_token': csrf, 'payload': payload,
        }, allow_redirects=False)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()['client_uuid'], token)
        self.assertEqual(created.json()['order']['state'], 'sent')
        self.assertEqual(created.json()['order']['representative_id'], representative.id)
        replay = self.url_open('/bchat/api/v2/orders', data={
            'csrf_token': csrf, 'payload': payload,
        }, allow_redirects=False)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()['replayed'])
        self.assertEqual(replay.json()['order']['id'], created.json()['order']['id'])
        listed = self.url_open('/bchat/api/v2/orders?company_id=%s' % company.id)
        self.assertIn(created.json()['order']['id'], [row['id'] for row in listed.json()['orders']])
        all_orders = self.url_open('/bchat/api/v2/orders?scope=all', allow_redirects=False)
        self.assertEqual(all_orders.status_code, 200, all_orders.text)
        self.assertEqual(all_orders.json()['orders'][0]['requester_id'], user.id)
        company_orders = self.url_open('/bchat/api/v2/orders?scope=all&company_id=%s' % company.id, allow_redirects=False)
        self.assertEqual(company_orders.status_code, 200, company_orders.text)
        self.assertTrue(all(row['company_id'] == company.id for row in company_orders.json()['orders']))
        for path in ('/bchat/api/v2/orders',
                     '/bchat/api/v2/orders?scope=unknown',
                     '/bchat/api/v2/orders?scope=all&company_id=0'):
            self.assertEqual(self.url_open(path, allow_redirects=False).status_code, 400)
        rooms_path = '/bchat/api/v2/orders/rooms?company_id=%s' % company.id
        room_choices = self.url_open('%s&preferred_room_id=%s' % (rooms_path, room.id), allow_redirects=False)
        self.assertEqual(room_choices.status_code, 200, room_choices.text)
        self.assertEqual(room_choices.json()['rooms'], [{'id': room.id, 'name': room.name}])
        self.assertEqual(room_choices.json()['preferred_room'], {'id': room.id, 'name': room.name})
        self.assertEqual(room_choices.headers['Cache-Control'], 'no-store')
        for path in ('/bchat/api/v2/orders/rooms', '%s&company_id=%s' % (rooms_path, company.id),
                     '%s&after_id=0' % rooms_path, '%s&history=1' % rooms_path):
            self.assertEqual(self.url_open(path, allow_redirects=False).status_code, 400)
        order_share_path = '/bchat/api/v2/orders/%s/share' % created.json()['order']['id']
        order_sharing_payload = json.dumps({'api_version': 2, 'company_id': company.id, 'room_id': room.id})
        self.assertNotEqual(self.url_open(order_share_path, data={'payload': order_sharing_payload}, allow_redirects=False).status_code, 200)
        self.assertEqual(self.url_open(order_share_path, data={
            'csrf_token': csrf, 'payload': json.dumps({'api_version': 2, 'company_id': company.id, 'room_id': room.id, 'text': 'Client amount'}),
        }, allow_redirects=False).status_code, 400)
        order_shared = self.url_open(order_share_path, data={'csrf_token': csrf, 'payload': order_sharing_payload}, allow_redirects=False)
        self.assertEqual(order_shared.status_code, 200, order_shared.text)
        self.assertFalse(order_shared.json()['replayed'])
        order_replayed = self.url_open(order_share_path, data={'csrf_token': csrf, 'payload': order_sharing_payload}, allow_redirects=False)
        self.assertEqual(order_replayed.json()['message_id'], order_shared.json()['message_id'])
        self.assertTrue(order_replayed.json()['replayed'])
        detail_path = '/bchat/api/v2/orders/%s?company_id=%s' % (
            created.json()['order']['id'], company.id,
        )
        detail = self.url_open(detail_path, allow_redirects=False)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['lines'][0]['requested_qty'], '2.00')
        self.assertEqual(detail.json()['lines'][0]['current_option']['id'], option.id)
        self.assertEqual(detail.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.url_open('%s&scope=all' % detail_path,
                                       allow_redirects=False).status_code, 200)
        self.assertEqual(self.url_open('%s&scope=unknown' % detail_path,
                                       allow_redirects=False).status_code, 400)
        foreign_detail = self.url_open('/bchat/api/v2/orders/%s?company_id=%s' % (
            created.json()['order']['id'], foreign.id,
        ), allow_redirects=False)
        self.assertEqual(foreign_detail.status_code, 404)
        self.assertEqual(self.url_open('/bchat/api/v2/orders/%s' % (
            created.json()['order']['id'],
        ), allow_redirects=False).status_code, 400)
        receipt_root = '/bchat/api/v2/orders/receipts'
        receipt_list = self.url_open('%s?company_id=%s' % (receipt_root, company.id),
                                     allow_redirects=False)
        self.assertEqual(receipt_list.status_code, 200, receipt_list.text)
        self.assertIn(created.json()['order']['id'],
                      [row['id'] for row in receipt_list.json()['orders']])
        global_receipts = self.url_open('%s?scope=all' % receipt_root, allow_redirects=False)
        self.assertEqual(global_receipts.status_code, 200, global_receipts.text)
        self.assertIn(created.json()['order']['id'], [row['id'] for row in global_receipts.json()['orders']])
        scoped_receipts = self.url_open('%s?scope=all&company_id=%s' % (receipt_root, company.id), allow_redirects=False)
        self.assertEqual(scoped_receipts.status_code, 200, scoped_receipts.text)
        for suffix in ('', '?scope=mine', '?scope=all&company_id=0', '?scope=all&before_id=0'):
            self.assertEqual(self.url_open('%s%s' % (receipt_root, suffix), allow_redirects=False).status_code, 400)
        receipt_detail = self.url_open('%s/%s?company_id=%s' % (
            receipt_root, created.json()['order']['id'], company.id,
        ), allow_redirects=False)
        self.assertEqual(receipt_detail.status_code, 200, receipt_detail.text)
        self.assertEqual(len(receipt_detail.json()['lines']), 1)
        receipt_payload = json.dumps({
            'api_version': 2, 'company_id': company.id, 'client_uuid': str(uuid4()),
            'lines': [{'line_id': receipt_detail.json()['lines'][0]['line_id'],
                       'actual_qty': '1.00', 'actual_price': '7.25'}],
        })
        confirm_path = '%s/%s/confirm' % (receipt_root, created.json()['order']['id'])
        self.assertNotEqual(self.url_open(confirm_path, data={
            'payload': receipt_payload,
        }, allow_redirects=False).status_code, 200)
        confirmed = self.url_open(confirm_path, data={
            'csrf_token': csrf, 'payload': receipt_payload,
        }, allow_redirects=False)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()['receipt']['state'], 'purchased')
        self.assertEqual(confirmed.json()['receipt']['confirmed_by_id'], user.id)
        share_path = '%s/%s/share' % (receipt_root, created.json()['order']['id'])
        sharing = self.url_open(share_path, data={
            'csrf_token': csrf,
            'payload': json.dumps({'api_version': 2, 'company_id': company.id}),
        }, allow_redirects=False)
        self.assertEqual(sharing.status_code, 200, sharing.text)
        self.assertEqual(sharing.json()['room_id'], room.id)
        self.assertNotEqual(sharing.json()['message_id'], order_shared.json()['message_id'])
        user.write({'bchat_order_view': False, 'bchat_order_create': False,
                    'bchat_order_receive': False})
        self.assertEqual(self.url_open('%s?company_id=%s' % (
            receipt_root, company.id,
        ), allow_redirects=False).status_code, 403)
        self.assertEqual(self.url_open(confirm_path, data={
            'csrf_token': csrf, 'payload': receipt_payload,
        }, allow_redirects=False).status_code, 403)
        self.assertEqual(self.url_open('/bchat/api/v2/orders/options?company_id=%s' % (
            company.id,
        ), allow_redirects=False).status_code, 403)
        self.assertEqual(self.url_open(detail_path, allow_redirects=False).status_code, 403)
        self.assertEqual(self.url_open('/bchat/api/v2/orders?scope=all',
                                       allow_redirects=False).status_code, 403)
        replay_after_revocation = self.url_open('/bchat/api/v2/orders', data={
            'csrf_token': csrf, 'payload': payload,
        }, allow_redirects=False)
        self.assertEqual(replay_after_revocation.status_code, 403)
        private_rpc = self.url_open('/web/dataset/call_kw/baseer.bchat.service/_v2_order_create',
                                    data=json.dumps({
                                        'jsonrpc': '2.0', 'method': 'call',
                                        'params': {'model': 'baseer.bchat.service',
                                                   'method': '_v2_order_create', 'args': [json.loads(payload)],
                                                   'kwargs': {}}, 'id': 1,
                                    }), headers={'Content-Type': 'application/json'})
        self.assertIn('error', private_rpc.json())
