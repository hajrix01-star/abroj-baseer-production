"""The employee-facing bridge must not confer procurement's broad ERP rights."""
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
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat order room manager', 'login': 'bchat-room-%s' % uuid4().hex,
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('baseer_bchat.group_bchat_manager').id])],
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
        self.assertEqual(len(message.splitlines()), 4)
        self.assertIn('BChat chicken (Kilogram) — الكمية: 2.50', message)
        self.assertIn('BChat onion (Crate) — الكمية: 3.00', message)
        self.assertIn('الإجمالي: 27.00', message)
        self.assertNotIn('BCHAT-CHICKEN-SKU', message)
        self.assertNotIn('BCHAT-ONION-SKU', message)
        self.assertNotIn('المستودع:', message)
        self.assertNotIn('مندوب المشتريات:', message)

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
        group = self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator')
        self.user.write({'group_ids': [Command.unlink(group.id)]})
        self.assertFalse(self.user.has_group('baseer_bchat_procurement.group_bchat_procurement_operator'))
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
        self.authenticate(user.login, password)
        bootstrap = self.url_open('/bchat/api/v2/bootstrap').json()
        csrf = bootstrap['csrf_token']
        choices = self.url_open('/bchat/api/v2/orders/options?company_id=%s' % company.id)
        self.assertEqual(choices.status_code, 200)
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
        detail_path = '/bchat/api/v2/orders/%s?company_id=%s' % (
            created.json()['order']['id'], company.id,
        )
        detail = self.url_open(detail_path, allow_redirects=False)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['lines'][0]['requested_qty'], '2.00')
        self.assertEqual(detail.json()['lines'][0]['current_option']['id'], option.id)
        self.assertEqual(detail.headers['Cache-Control'], 'no-store')
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
        group = self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator')
        user.write({'group_ids': [Command.unlink(group.id)]})
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
