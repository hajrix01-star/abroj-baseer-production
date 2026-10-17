"""C17 private preferences: manager isolation, epochs and current push policy."""
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..contracts import ProtocolError


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_social_preferences')
class BChatMembershipPreferencesCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.admin = self.env.ref('base.user_admin')
        self.admin.write({'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        def user(label):
            return self.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Preferences %s' % label, 'login': 'bchat-preference-' + uuid4().hex,
                'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
                'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            })
        self.owner, self.reader = user('owner'), user('reader')
        self.owner_service = self.env['baseer.bchat.service'].with_user(self.owner)
        self.service = self.env['baseer.bchat.service'].with_user(self.reader)
        created = self.owner_service._v2_group_create({
            'api_version': 2, 'company_id': self.company.id, 'client_uuid': str(uuid4()),
            'name': 'Private preferences group', 'member_user_ids': [self.reader.id],
        })
        self.room = self.env['baseer.bchat.room'].sudo().browse(created['room_id'])
        self.owner_member_id = created['membership_id']
        self.member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room.id), ('user_id', '=', self.reader.id), ('active', '=', True)], limit=1)
        self.preferences = self.env['baseer.bchat.membership.preference']

    def _payload(self, **extra):
        revision = self.service._v2_room_preferences(self.room.id, self.member.id)['revision']
        return {'api_version': 2, 'membership_id': self.member.id, 'client_uuid': str(uuid4()),
                'expected_revision': revision, 'muted_until': None, 'mute_forever': False,
                'pinned': False, 'archived': False, **extra}

    def _set(self, **extra):
        return self.service._v2_set_room_preferences(self.room.id, self._payload(**extra))

    def _send(self):
        return self.owner_service._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.owner_member_id,
            'client_uuid': str(uuid4()), 'text': 'Preference fixture message',
        })['message_id']

    def _register(self):
        return self.service._v2_push_register({
            'api_version': 2, 'installation_id': str(uuid4()), 'fcm_token': 'synthetic-pref-' + 'x' * 64,
        })

    def test_get_defaults_creates_no_row_receipt_or_hint(self):
        count = self.preferences.sudo().search_count([])
        watermark = self.service._v2_changes()['watermark']
        defaults = self.service._v2_room_preferences(self.room.id, self.member.id)
        self.assertEqual(defaults['revision'], 1)
        self.assertFalse(defaults['muted'])
        self.assertFalse(defaults['pinned'])
        self.assertFalse(defaults['archived'])
        self.assertEqual(self.preferences.sudo().search_count([]), count)
        self.assertEqual(self.service._v2_changes()['watermark'], watermark)

    def test_manager_can_read_membership_but_never_personal_preferences(self):
        self._set(mute_forever=True, archived=True, pinned=True)
        membership = self.member.with_user(self.admin)
        self.assertEqual(membership.read(['user_id'])[0]['user_id'][0], self.reader.id)
        for user in (self.reader, self.owner, self.admin):
            with self.subTest(user=user.id), self.assertRaises(AccessError):
                self.preferences.with_user(user).search_count([])
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.admin)._v2_room_preferences(self.room.id, self.member.id)
        with self.assertRaises(ProtocolError):
            self.owner_service._v2_room_preferences(self.room.id, self.member.id)
        self.assertNotIn('archived', self.member._fields)
        self.assertNotIn('muted_until', self.member._fields)

    def test_cas_replay_and_private_hint_only(self):
        payload = self._payload(archived=True, pinned=True)
        watermark = self.owner_service._v2_changes()['watermark']
        first = self.service._v2_set_room_preferences(self.room.id, payload)
        second = self.service._v2_set_room_preferences(self.room.id, payload)
        self.assertEqual((first['revision'], second['revision'], second['replayed']), (2, 2, True))
        self.assertEqual(self.preferences.sudo().search_count([('membership_id', '=', self.member.id)]), 1)
        self.assertEqual(self.owner_service._v2_changes(after=watermark)['changes'], [])
        with self.assertRaises(ProtocolError) as stale:
            self.service._v2_set_room_preferences(self.room.id, {**payload, 'client_uuid': str(uuid4())})
        self.assertEqual(stale.exception.code, 'revision_conflict')

    def test_archive_is_not_read_delete_or_legacy_revocation(self):
        message = self._send()
        before = next(row for row in self.service._v2_rooms()['rooms'] if row['id'] == self.room.id)['unread_count']
        self._set(archived=True)
        self.assertNotIn(self.room.id, [row['id'] for row in self.service._v2_social_rooms()['rooms']])
        self.assertIn(self.room.id, [row['id'] for row in self.service._v2_social_rooms(True)['rooms']])
        legacy = next(row for row in self.service._v2_rooms()['rooms'] if row['id'] == self.room.id)
        self.assertEqual(legacy['unread_count'], before)
        self.assertTrue(self.env['baseer.bchat.message'].sudo().browse(message).exists())
        self._send()
        self.assertIn(self.room.id, [row['id'] for row in self.service._v2_social_rooms(True)['rooms']])
        self.assertEqual(next(row for row in self.service._v2_rooms()['rooms']
                              if row['id'] == self.room.id)['unread_count'], before + 1)

    def test_mute_rechecks_dispatch_but_does_not_revoke_notification_content(self):
        self._register()
        message = self._send()
        events = self.env['baseer.bchat.push.event']
        event = events.sudo().search([('message_id', '=', message)], limit=1)
        self.assertTrue(event)
        self._set(mute_forever=True)
        self.assertEqual(self.service._v2_push_event(event.id)['notification']['kind'], 'chat')
        with patch.object(type(events), '_fcm_config', return_value={'synthetic': True}), \
                patch.object(type(events), '_fcm_send') as send:
            events._dispatch_event_ids([event.id])
        send.assert_not_called()
        self.assertEqual((event.state, event.last_error), ('discarded', 'muted'))
        next_message = self._send()
        self.assertFalse(events.sudo().search_count([('message_id', '=', next_message)]))
        standalone = self.owner_service._v2_task_create({
            'api_version': 2, 'company_id': self.company.id, 'room_id': None,
            'client_uuid': str(uuid4()), 'title': 'Standalone is not room mute',
            'description': '', 'due_at': None, 'assignee_id': self.reader.id,
        })['task']
        self.assertTrue(events.sudo().search_count([('task_id', '=', standalone['id'])]))

    def test_mute_expiry_is_computed_without_get_mutation(self):
        until = fields.Datetime.now() + timedelta(hours=1)
        self._set(muted_until=until.strftime('%Y-%m-%dT%H:%M:%SZ'))
        row = self.preferences.sudo().search([('membership_id', '=', self.member.id)])
        before = row.write_date
        with patch('odoo.addons.baseer_bchat.models.membership_preference.fields.Datetime.now',
                   return_value=until + timedelta(seconds=1)):
            self.assertFalse(self.service._v2_room_preferences(self.room.id, self.member.id)['muted'])
        self.assertEqual(row.write_date, before)

    def test_rejoin_has_fresh_defaults_and_old_intent_is_not_replayed(self):
        payload = self._payload(archived=True, mute_forever=True)
        self.service._v2_set_room_preferences(self.room.id, payload)
        self.owner_service._v2_group_change(self.room.id, {
            'api_version': 2, 'action': 'remove_member', 'user_id': self.reader.id})
        self.owner_service._v2_group_change(self.room.id, {
            'api_version': 2, 'action': 'add_member', 'user_id': self.reader.id})
        new_member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room.id), ('user_id', '=', self.reader.id), ('active', '=', True)], limit=1)
        self.assertNotEqual(new_member.id, self.member.id)
        defaults = self.service._v2_room_preferences(self.room.id, new_member.id)
        self.assertEqual(defaults['revision'], 1)
        self.assertFalse(defaults['archived'])
        self.assertFalse(defaults['muted'])
        with self.assertRaises(ProtocolError) as old:
            self.service._v2_set_room_preferences(self.room.id, payload)
        self.assertEqual(old.exception.code, 'membership_changed')

    def test_social_room_list_uses_one_scoped_preference_query_and_validates_cursor(self):
        preference_class = type(self.preferences)
        original = preference_class.search
        calls = []
        def scoped_search(model, domain, *args, **kwargs):
            calls.append(domain)
            return original(model, domain, *args, **kwargs)
        with patch.object(preference_class, 'search', scoped_search):
            result = self.service._v2_social_rooms()
        self.assertEqual(len(calls), 1)
        self.assertIn(('user_id', '=', self.reader.id), calls[0])
        self.assertEqual(result['rooms'][0]['id'], self.room.id)
        for invalid in ('%%%', 'a' * 513, 'YQ', '[]'):
            with self.subTest(cursor=invalid), self.assertRaises(ProtocolError):
                self.service._v2_social_rooms(cursor=invalid)
