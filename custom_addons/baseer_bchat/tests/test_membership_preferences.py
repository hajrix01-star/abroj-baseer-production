"""C17 private preferences: manager isolation, epochs and current push policy."""
from datetime import timedelta
import json
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

    def test_cancel_unapplied_is_immutable_and_late_original_has_no_effect(self):
        payload = self._payload(archived=True, mute_forever=True)
        watermark = self.service._v2_changes()['watermark']
        expected = {'api_version': 2, 'room_id': self.room.id, 'membership_id': self.member.id,
                    'client_uuid': payload['client_uuid'], 'expected_revision': 1, 'cancelled': True}
        for operation in (self.service._v2_cancel_room_preferences, self.service._v2_cancel_room_preferences,
                          self.service._v2_set_room_preferences):
            self.assertEqual(operation(self.room.id, payload), expected)
        self.assertEqual(self.service._v2_room_preferences(self.room.id, self.member.id)['revision'], 1)
        self.assertFalse(self.preferences.sudo().search_count([('membership_id', '=', self.member.id)]))
        self.assertEqual(self.service._v2_changes(after=watermark)['changes'], [])
        receipts = self.env['baseer.bchat.social.operation'].sudo().search([
            ('actor_id', '=', self.reader.id), ('action', '=', 'room_preferences'),
            ('client_uuid', '=', payload['client_uuid'])])
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts.result_json), {'cancelled': True})
        with self.assertRaises(AccessError):
            receipts.write({'result_json': '{"revision":2}'})
        for operation in (self.service._v2_cancel_room_preferences, self.service._v2_set_room_preferences):
            with self.subTest(operation=operation), self.assertRaises(ProtocolError) as conflict:
                operation(self.room.id, {**payload, 'archived': False})
            self.assertEqual(conflict.exception.code, 'idempotency_conflict')

    def test_cancel_expired_unapplied_and_failed_cas_do_not_require_future_time(self):
        expired = self._payload(muted_until='2020-01-01T00:00:00Z')
        with self.assertRaises(ProtocolError) as old:
            self.service._v2_set_room_preferences(self.room.id, expired)
        self.assertEqual(old.exception.code, 'invalid_payload')
        cancelled = self.service._v2_cancel_room_preferences(self.room.id, expired)
        self.assertTrue(cancelled['cancelled'])
        self.assertEqual(self.service._v2_set_room_preferences(self.room.id, expired), cancelled)
        stale = self._payload(expected_revision=9, pinned=True)
        with self.assertRaises(ProtocolError) as conflict:
            self.service._v2_set_room_preferences(self.room.id, stale)
        self.assertEqual(conflict.exception.code, 'revision_conflict')
        self.assertEqual(self.service._v2_cancel_room_preferences(self.room.id, stale)['expected_revision'], 9)
        self.assertFalse(self.preferences.sudo().search_count([('membership_id', '=', self.member.id)]))

    def test_cancel_applied_returns_current_snapshot_and_original_operation_revision(self):
        until = fields.Datetime.now() + timedelta(hours=1)
        payload = self._payload(pinned=True, muted_until=until.strftime('%Y-%m-%dT%H:%M:%SZ'))
        first = self.service._v2_set_room_preferences(self.room.id, payload)
        self._set(archived=True)
        watermark = self.service._v2_changes()['watermark']
        with patch('odoo.addons.baseer_bchat.models.membership_preference.fields.Datetime.now',
                   return_value=until + timedelta(seconds=1)):
            for operation in (self.service._v2_cancel_room_preferences, self.service._v2_set_room_preferences):
                replay = operation(self.room.id, payload)
                self.assertEqual((replay['operation_revision'], replay['revision']), (first['revision'], 3))
                self.assertTrue(replay['replayed'])
                self.assertTrue(replay['archived'])
                self.assertFalse(replay['pinned'])
                self.assertFalse(replay['muted'])
                self.assertNotIn('cancelled', replay)
        self.assertEqual(self.service._v2_changes(after=watermark)['changes'], [])

    def test_cancel_and_original_share_strict_shape_without_forged_markers(self):
        good = self._payload()
        invalid = [None, [], {**good, 'cancelled': True}, {key: value for key, value in good.items() if key != 'archived'}]
        for key, value in [('api_version', True), ('membership_id', True), ('membership_id', 2147483648),
                           ('expected_revision', 1.0), ('expected_revision', False), ('mute_forever', 0),
                           ('pinned', 'false'), ('archived', None), ('client_uuid', 'not-a-uuid'),
                           ('muted_until', '2026-1-01T00:00:000Z'), ('muted_until', '2026-02-30T00:00:00Z'),
                           ('muted_until', '2026-01-01T00:00:00+00:00')]:
            invalid.append({**good, key: value})
        invalid.append({**good, 'muted_until': '2020-01-01T00:00:00Z', 'mute_forever': True})
        for operation in (self.service._v2_cancel_room_preferences, self.service._v2_set_room_preferences):
            for payload in invalid:
                with self.subTest(operation=operation, payload=payload), self.assertRaises(ProtocolError):
                    operation(self.room.id, payload)

    def test_cancel_rechecks_current_permissions_company_and_membership(self):
        payload = self._payload()
        self.service._v2_cancel_room_preferences(self.room.id, payload)
        with self.assertRaises(ProtocolError) as wrong_member:
            self.service._v2_cancel_room_preferences(self.room.id, self._payload(membership_id=self.owner_member_id))
        self.assertEqual(wrong_member.exception.code, 'membership_changed')
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.admin)._v2_cancel_room_preferences(self.room.id, payload)
        self.reader.with_user(self.admin).write({'bchat_chat_view': False})
        with self.assertRaises(AccessError):
            self.service._v2_cancel_room_preferences(self.room.id, payload)
        self.reader.with_user(self.admin).write({'bchat_chat_view': True})
        other = self.env['res.company'].create({'name': 'Cancellation isolated company ' + uuid4().hex})
        self.admin.write({'company_ids': [Command.link(other.id)]})
        foreign = self.env['baseer.bchat.room'].with_user(self.admin).with_company(other).create({
            'name': 'Cancellation foreign room', 'company_id': other.id})
        with self.assertRaises(AccessError):
            self.service._v2_cancel_room_preferences(foreign.id, self._payload())
        self.owner_service._v2_group_change(self.room.id, {'api_version': 2, 'action': 'remove_member', 'user_id': self.reader.id})
        self.owner_service._v2_group_change(self.room.id, {'api_version': 2, 'action': 'add_member', 'user_id': self.reader.id})
        with self.assertRaises(ProtocolError) as obsolete:
            self.service._v2_cancel_room_preferences(self.room.id, payload)
        self.assertEqual(obsolete.exception.code, 'membership_changed')

    def test_room_preference_receipt_union_rejects_malformed_immutable_rows(self):
        for result in ({}, {'revision': True}, {'revision': 0}, {'revision': '2'}, {'revision': 2147483648}, {'revision': 2},
                       {'cancelled': False}, {'cancelled': 1}, {'cancelled': True, 'revision': 2}, []):
            payload = self._payload()
            digest, replay = self.service._social_lock_operation('room_preferences', payload['client_uuid'],
                                                                 {'room_id': self.room.id, **payload})
            self.assertIsNone(replay)
            self.service._social_complete_operation('room_preferences', payload['client_uuid'], digest, result)
            for operation in (self.service._v2_cancel_room_preferences, self.service._v2_set_room_preferences):
                with self.subTest(result=result, operation=operation), self.assertRaises(AccessError):
                    operation(self.room.id, payload)
        self.assertFalse(self.preferences.sudo().search_count([('membership_id', '=', self.member.id)]))

    def test_own_uncommitted_replay_nested_savepoint_then_rollback_has_no_ack(self):
        payload = self._payload(pinned=True)
        class RollbackFixture(Exception):
            pass
        with self.assertRaises(RollbackFixture):
            with self.env.cr.savepoint():
                applied = self.service._v2_set_room_preferences(self.room.id, payload)
                self.assertEqual(applied['operation_revision'], 2)
                with self.env.cr.savepoint(), patch.object(type(self.service), '_room_preference_scope',
                                                          side_effect=AssertionError('Replay must not lock MAIN room')):
                    replay = self.service._v2_cancel_room_preferences(self.room.id, payload)
                    self.assertEqual((replay['revision'], replay['operation_revision'], replay['replayed']), (2, 2, True))
                    self.assertTrue(replay['pinned'])
                raise RollbackFixture()
        self.env.cr.execute('''SELECT COUNT(*) FROM baseer_bchat_social_operation
            WHERE actor_id=%s AND action='room_preferences' AND client_uuid=%s''',
                            [self.reader.id, payload['client_uuid']])
        self.assertEqual(self.env.cr.fetchone()[0], 0)
        with self.assertRaises(AccessError):
            self.service._room_preference_applied_replay({'room_id': self.room.id, **payload}, payload['client_uuid'], 2)
        cancelled = self.service._v2_cancel_room_preferences(self.room.id, payload)
        self.assertEqual(set(cancelled), {'api_version', 'room_id', 'membership_id', 'client_uuid',
                                          'expected_revision', 'cancelled'})
        self.assertTrue(cancelled['cancelled'])
        self.assertFalse(self.preferences.sudo().search_count([('membership_id', '=', self.member.id)]))
