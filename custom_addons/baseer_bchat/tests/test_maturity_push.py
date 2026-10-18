"""C04 provider envelopes and per-event recovery boundaries, without real FCM."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import BaseCase

from ..models import push as push_module
from ..notification_presentation import room_mute_keys


@tagged('post_install', '-at_install', 'baseer_bchat', 'baseer_bchat_maturity')
class BChatMaturityPushCase(TransactionCase):
    def setUp(self):
        super().setUp()
        company = self.env.company
        users = self.env['res.users'].with_context(no_reset_password=True)
        def user(label):
            return users.create({
                'name': 'Synthetic FCM %s' % label, 'login': 'bchat-fcm-%s' % uuid4().hex,
                'company_id': company.id, 'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            })
        self.actor, self.recipient = user('actor'), user('recipient')
        self.env['baseer.bchat.service'].with_user(self.recipient)._v2_push_register({
            'api_version': 2, 'installation_id': str(uuid4()), 'fcm_token': 'synthetic-' + 'a' * 64,
        })
        created = self.env['baseer.bchat.service'].with_user(self.actor)._v2_task_create({
            'api_version': 2, 'company_id': company.id, 'room_id': None,
            'client_uuid': str(uuid4()), 'title': 'Synthetic provider fixture',
            'description': '', 'due_at': None, 'assignee_id': self.recipient.id,
        })
        self.events = self.env['baseer.bchat.push.event']
        self.event = self.events.sudo().search([('task_id', '=', created['task']['id'])], limit=1)
        self.assertTrue(self.event)

    def _dispatch_response(self, status, payload, headers=None):
        response = SimpleNamespace(status_code=status, headers=headers or {}, json=lambda: payload)
        model = type(self.events)
        with patch.object(model, '_fcm_config', return_value={'project_id': 'synthetic-project'}), \
                patch.object(model, '_fcm_access_token', return_value='synthetic-access-token'), \
                patch('requests.post', return_value=response) as post, \
                patch.object(push_module.random, 'random', return_value=0.0):
            self.events._dispatch_event_ids([self.event.id])
        post.assert_called_once()
        self.event.invalidate_recordset()
        self.event.device_id.invalidate_recordset()

    def test_fcm_http_v1_unregistered_disables_only_the_invalid_destination(self):
        self._dispatch_response(404, {'error': {'code': 404, 'status': 'NOT_FOUND', 'details': [{
            '@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError',
            'errorCode': 'UNREGISTERED',
        }]}})
        self.assertEqual(self.event.state, 'failed')
        self.assertEqual(self.event.last_error, 'unregistered')
        self.assertEqual(self.event.attempts, 1)
        self.assertFalse(self.event.device_id.active)
        self.assertEqual(self.event.device_id.inactive_reason, 'provider_invalid')

    def test_bare_404_keeps_the_token_and_records_configuration_failure(self):
        self._dispatch_response(404, {'error': {'code': 404, 'status': 'NOT_FOUND'}})
        self.assertTrue(self.event.device_id.active)
        self.assertEqual(self.event.state, 'configuration')
        self.assertEqual(self.event.last_error, 'configuration')

    def test_provider_quota_uses_retry_after_without_disabling_device(self):
        before = fields.Datetime.now()
        self._dispatch_response(429, {'error': {'status': 'RESOURCE_EXHAUSTED'}}, {'Retry-After': '120'})
        self.assertTrue(self.event.device_id.active)
        self.assertEqual(self.event.state, 'retry')
        self.assertEqual(self.event.attempts, 1)
        self.assertGreaterEqual(self.event.next_attempt_at, before + timedelta(seconds=120))
        self.assertLessEqual(self.event.next_attempt_at, fields.Datetime.now() + timedelta(seconds=120))

    def test_unavailable_is_retryable_and_invalid_payload_is_permanent(self):
        self._dispatch_response(503, {'error': {'status': 'UNAVAILABLE'}})
        self.assertEqual(self.event.state, 'retry')
        self.assertTrue(self.event.device_id.active)
        self.event._write_verified({'state': 'pending', 'next_attempt_at': False}, push_module._PUSH_TOKEN)
        self._dispatch_response(400, {'error': {'status': 'INVALID_ARGUMENT'}})
        self.assertEqual(self.event.state, 'failed')
        self.assertEqual(self.event.last_error, 'invalid_payload')
        self.assertEqual(self.event.attempts, 2)
        self.assertTrue(self.event.device_id.active)

    def _scoped_events(self):
        service = self.env['baseer.bchat.service'].with_user(self.actor)
        created = service._v2_group_create({
            'api_version': 2, 'company_id': self.env.company.id, 'client_uuid': str(uuid4()),
            'name': 'Synthetic mute payload scope', 'member_user_ids': [self.recipient.id],
        })
        member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', created['room_id']), ('user_id', '=', self.recipient.id),
            ('active', '=', True),
        ], limit=1)
        sent = service._v2_send(created['room_id'], {
            'api_version': 2, 'membership_id': created['membership_id'],
            'client_uuid': str(uuid4()), 'text': 'Synthetic scoped chat',
        })
        task = service._v2_task_create({
            'api_version': 2, 'company_id': self.env.company.id, 'room_id': created['room_id'],
            'client_uuid': str(uuid4()), 'title': 'Synthetic scoped task',
            'description': '', 'due_at': None, 'assignee_id': self.recipient.id,
        })
        chat = self.events.sudo().search([
            ('message_id', '=', sent['message_id']), ('recipient_id', '=', self.recipient.id),
        ], limit=1)
        task_event = self.events.sudo().search([
            ('task_id', '=', task['task']['id']), ('recipient_id', '=', self.recipient.id),
        ], limit=1)
        self.assertTrue(member and chat and task_event)
        return service, created, member, chat, task_event

    def _provider_payload(self, event):
        response = SimpleNamespace(status_code=200)
        with patch.object(type(self.events), '_fcm_access_token', return_value='synthetic-token'), \
                patch('requests.post', return_value=response) as post:
            self.events._fcm_send(event, {'project_id': 'synthetic-project'})
        post.assert_called_once()
        return post.call_args.kwargs['json']['message']['data']

    def test_chat_scope_is_current_recipient_membership_in_every_privacy_mode(self):
        _service, created, member, chat, _task = self._scoped_events()
        expected = room_mute_keys(chat.device_id.account_key, self.env.company.id,
                                  created['room_id'], member.id)
        self.assertNotEqual(member.id, created['membership_id'])
        for mode in ('none', 'sender', 'full'):
            chat.device_id._set_preview_verified(mode, chat.device_id.preference_revision,
                                                 push_module._PUSH_TOKEN)
            data = self._provider_payload(chat)
            self.assertEqual({key: data[key] for key in expected}, expected)
            self.assertEqual(data['room_key'], expected['mute_room_key'])
            self.assertTrue(all(type(value) is str for value in data.values()))
            if mode != 'full':
                self.assertNotIn('conversation_title', data)
                self.assertNotIn('message_preview', data)
            if mode == 'none':
                self.assertNotIn('sender_name', data)

    def test_room_task_scope_does_not_scope_standalone_tasks(self):
        _service, created, member, _chat, task = self._scoped_events()
        expected = room_mute_keys(task.device_id.account_key, self.env.company.id,
                                  created['room_id'], member.id)
        data = self._provider_payload(task)
        self.assertEqual({key: data[key] for key in expected}, expected)
        self.assertEqual(set(data), {'account_key', 'kind', 'event_id', *expected})
        standalone = self._provider_payload(self.event)
        self.assertEqual(set(standalone), {'account_key', 'kind', 'event_id'})

    def test_missing_scoped_member_never_falls_back_or_calls_provider(self):
        _service, _created, _member, chat, task = self._scoped_events()
        membership_model = type(self.env['baseer.bchat.membership'])
        for event in (chat, task):
            with self.subTest(kind='chat' if event.message_id else 'task'), \
                    patch.object(type(self.events), '_event_recipient_still_allowed', return_value=True), \
                    patch.object(membership_model, 'search', return_value=self.env['baseer.bchat.membership']), \
                    patch.object(type(self.events), '_fcm_access_token') as token, \
                    patch('requests.post') as post:
                with self.assertRaises(push_module._PushTransportError) as failure:
                    self.events._fcm_send(event, {'project_id': 'synthetic-project'})
                self.assertEqual(failure.exception.code, 'access_revoked')
                self.assertFalse(failure.exception.retry)
                token.assert_not_called()
                post.assert_not_called()

    def test_late_scoped_revocation_is_discarded_without_attempt_or_token_mutation(self):
        _service, _created, _member, chat, task = self._scoped_events()
        for event in (chat, task):
            before = event.attempts
            with patch.object(type(self.events), '_fcm_config', return_value={'project_id': 'synthetic-project'}), \
                    patch.object(type(self.events), '_event_recipient_still_allowed', side_effect=[True, False]), \
                    patch.object(type(self.events), '_fcm_access_token') as token, \
                    patch('requests.post') as post:
                self.events._dispatch_event_ids([event.id])
            event.invalidate_recordset()
            self.assertEqual((event.state, event.last_error, event.attempts),
                             ('discarded', 'access_revoked', before))
            self.assertFalse(event.next_attempt_at)
            self.assertFalse(event.sent_at)
            self.assertTrue(event.device_id.active)
            token.assert_not_called()
            post.assert_not_called()

    def test_rejoin_uses_new_task_scope_and_cannot_scope_old_chat(self):
        service, created, old, chat, task = self._scoped_events()
        admin = self.env.ref('base.user_admin')
        admin.write({'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        old.with_user(admin).action_revoke()
        service._v2_group_add_members(created['room_id'], {
            'api_version': 2, 'membership_id': created['membership_id'],
            'client_uuid': str(uuid4()), 'user_ids': [self.recipient.id],
        })
        current = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', created['room_id']), ('user_id', '=', self.recipient.id), ('active', '=', True),
        ], limit=1)
        self.assertNotEqual(current.id, old.id)
        data = self._provider_payload(task)
        expected = room_mute_keys(task.device_id.account_key, self.env.company.id,
                                  created['room_id'], current.id)
        self.assertEqual(data['mute_room_key'], expected['mute_room_key'])
        self.assertNotEqual(data['mute_room_key'], room_mute_keys(task.device_id.account_key,
                            self.env.company.id, created['room_id'], old.id)['mute_room_key'])
        with self.assertRaises(push_module._PushTransportError) as failure:
            self._provider_payload(chat)
        self.assertEqual(failure.exception.code, 'access_revoked')


@tagged('post_install', '-at_install', 'baseer_bchat', 'baseer_bchat_maturity')
class BChatPushRecoveryBoundaryCase(BaseCase):
    def test_diagnostic_payload_does_not_invent_room_scope(self):
        event = SimpleNamespace(event_kind='diagnostic', id=17, message_id=False, task_id=False,
            diagnostic_uuid=str(uuid4()), device_id=SimpleNamespace(account_key=str(uuid4()),
                                                                   fcm_token='synthetic-token'))
        fake = SimpleNamespace(_fcm_access_token=MagicMock(return_value='synthetic-access-token'))
        with patch('requests.post', return_value=SimpleNamespace(status_code=200)) as post:
            push_module.BChatPushEvent._fcm_send(fake, event, {'project_id': 'synthetic-project'})
        data = post.call_args.kwargs['json']['message']['data']
        self.assertEqual(set(data), {'account_key', 'kind', 'event_id', 'diagnostic_uuid'})

    def test_cron_budget_leaves_later_candidates_for_next_run(self):
        cursor = MagicMock()
        cursor.dbname = 'synthetic_isolated_database'
        cursor.fetchall.return_value = [(17,), (18,)]
        fake_self = SimpleNamespace(env=SimpleNamespace(cr=cursor), flush_model=MagicMock())
        with patch.object(push_module.time, 'monotonic', side_effect=[0, 0, 21]), \
                patch.object(push_module, '_fast_dispatch_event') as dispatch:
            self.assertTrue(push_module.BChatPushEvent._cron_dispatch(fake_self))
        dispatch.assert_called_once_with('synthetic_isolated_database', 17)
        fake_self.flush_model.assert_called_once_with(['state', 'next_attempt_at'])
        query = cursor.execute.call_args.args[0]
        self.assertIn('LIMIT 100', query)
        self.assertNotIn('FOR UPDATE', query)

    def test_each_event_has_its_own_commit_even_if_the_next_dispatch_fails(self):
        first, second = MagicMock(), MagicMock()
        registry = MagicMock()
        one, two = MagicMock(), MagicMock()
        one.__enter__.return_value = first
        two.__enter__.return_value = second
        registry.cursor.side_effect = [one, two]
        environment = MagicMock()
        dispatch = environment.__getitem__.return_value._dispatch_event_ids
        dispatch.side_effect = [True, RuntimeError('synthetic interruption')]
        with patch.object(push_module, 'Registry', return_value=registry), \
                patch.object(push_module.api, 'Environment', return_value=environment):
            self.assertTrue(push_module._fast_dispatch_event('synthetic_isolated_database', 17))
            self.assertFalse(push_module._fast_dispatch_event('synthetic_isolated_database', 18))
        first.commit.assert_called_once_with()
        second.commit.assert_not_called()
        self.assertEqual([call.args for call in dispatch.call_args_list], [([17],), ([18],)])
