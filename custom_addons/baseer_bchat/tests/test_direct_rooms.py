"""C18 canonical direct rooms and the administrative membership boundary."""
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..contracts import ProtocolError


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_direct_rooms')
class BChatDirectRoomsCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.admin = self.env.ref('base.user_admin')
        self.admin.write({'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        def user(label, company=None):
            selected = company or self.company
            return self.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Direct %s' % label, 'login': 'bchat-direct-' + uuid4().hex,
                'company_id': selected.id, 'company_ids': [Command.set(selected.ids)],
                'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            })
        self.a, self.b, self.third = user('A'), user('B'), user('third')
        foreign = self.env['res.company'].create({'name': 'Direct foreign fixture'})
        self.foreign = user('foreign', foreign)
        self.service = self.env['baseer.bchat.service'].with_user(self.a)

    def _payload(self, **extra):
        return {'api_version': 2, 'company_id': self.company.id,
                'peer_user_id': self.b.id, 'client_uuid': str(uuid4()), **extra}

    def test_reverse_open_returns_one_new_pair_and_normal_message_path(self):
        first = self.service._v2_direct_room(self._payload())
        second = self.env['baseer.bchat.service'].with_user(self.b)._v2_direct_room(self._payload(peer_user_id=self.a.id))
        self.assertEqual(first['room_id'], second['room_id'])
        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        self.assertEqual(self.env['baseer.bchat.direct.pair'].sudo().search_count([('room_id', '=', first['room_id'])]), 1)
        sent = self.service._v2_send(first['room_id'], {
            'api_version': 2, 'membership_id': first['membership_id'],
            'client_uuid': str(uuid4()), 'text': 'Direct uses canonical send',
        })
        self.assertEqual(sent['state'], 'sent')
        row = next(room for room in self.service._v2_social_rooms()['rooms'] if room['id'] == first['room_id'])
        self.assertTrue(row['is_direct'])
        self.assertEqual(row['peer']['user_id'], self.b.id)
        self.assertEqual(row['name'], self.b.name)

    def test_admin_membership_create_cannot_add_a_third_participant(self):
        direct = self.service._v2_direct_room(self._payload())
        room = self.env['baseer.bchat.room'].sudo().browse(direct['room_id'])
        self.assertFalse(room.is_group)
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.membership'].with_user(self.admin).create({
                'room_id': room.id, 'user_id': self.third.id,
            })
        self.assertEqual(self.env['baseer.bchat.membership'].sudo().search_count([
            ('room_id', '=', room.id), ('active', '=', True)]), 2)
        with self.assertRaises(ProtocolError) as not_group:
            self.service._v2_group_change(room.id, {
                'api_version': 2, 'action': 'add_member', 'user_id': self.third.id})
        self.assertEqual(not_group.exception.code, 'not_a_group')

    def test_revoked_pair_never_autorejoins_and_explicit_restore_starts_new_epoch(self):
        payload = self._payload()
        direct = self.service._v2_direct_room(payload)
        message = self.service._v2_send(direct['room_id'], {
            'api_version': 2, 'membership_id': direct['membership_id'],
            'client_uuid': str(uuid4()), 'text': 'Before explicit restore',
        })
        old_member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', direct['room_id']), ('user_id', '=', self.b.id), ('active', '=', True)])
        old_member.with_user(self.admin).action_revoke()
        with self.assertRaises(ProtocolError) as unavailable:
            self.service._v2_direct_room(payload)
        self.assertEqual(unavailable.exception.code, 'direct_unavailable')
        restored = self.env['baseer.bchat.membership'].with_user(self.admin).create({
            'room_id': direct['room_id'], 'user_id': self.b.id,
        })
        self.assertNotEqual(restored.id, old_member.id)
        self.assertEqual(restored.joined_after_message_id, message['message_id'])
        self.assertEqual(self.env['baseer.bchat.service'].with_user(self.b)._v2_history(direct['room_id'])['messages'], [])
        self.assertEqual(self.service._v2_direct_room(payload)['room_id'], direct['room_id'])

    def test_legacy_two_member_room_is_not_reclassified_merged_or_deleted(self):
        legacy = self.env['baseer.bchat.room'].with_user(self.admin).create({
            'name': 'Legacy preserved exactly', 'company_id': self.company.id,
        })
        self.env['baseer.bchat.membership'].with_user(self.admin).create([
            {'room_id': legacy.id, 'user_id': self.a.id}, {'room_id': legacy.id, 'user_id': self.b.id},
        ])
        direct = self.service._v2_direct_room(self._payload())
        self.assertNotEqual(direct['room_id'], legacy.id)
        self.assertFalse(legacy.direct_pair_id)
        self.assertEqual(legacy.name, 'Legacy preserved exactly')
        self.assertEqual(self.env['baseer.bchat.membership'].sudo().search_count([
            ('room_id', '=', legacy.id), ('active', '=', True)]), 2)

    def test_direct_scope_and_replay_do_not_broaden_permissions(self):
        payload = self._payload()
        direct = self.service._v2_direct_room(payload)
        self.assertTrue(self.service._v2_direct_room(payload)['replayed'])
        with self.assertRaises(ProtocolError) as changed:
            self.service._v2_direct_room({**payload, 'peer_user_id': self.third.id})
        self.assertEqual(changed.exception.code, 'idempotency_conflict')
        with self.assertRaises(ProtocolError):
            self.service._v2_direct_room(self._payload(peer_user_id=self.a.id))
        with self.assertRaises(AccessError):
            self.service._v2_direct_room(self._payload(peer_user_id=self.foreign.id))
        self.a.write({'bchat_group_create': False})
        with self.assertRaises(AccessError):
            self.service._v2_direct_room(payload)
        self.assertIn(direct['room_id'], [row['id'] for row in self.service._v2_rooms()['rooms']])

    def test_existing_capacity_guard_refusal_leaves_no_partial_pair(self):
        membership_class = type(self.env['baseer.bchat.membership'])
        before = self.env['baseer.bchat.room'].sudo().search_count([])
        with patch.object(membership_class, '_assert_room_capacity_for_users', side_effect=ProtocolError(
                'too_many_rooms', 'Synthetic capacity refusal', 409)):
            with self.assertRaises(ProtocolError):
                self.service._v2_direct_room(self._payload())
        self.assertEqual(self.env['baseer.bchat.room'].sudo().search_count([]), before)
        self.assertFalse(self.env['baseer.bchat.direct.pair'].sudo().search_count([]))
