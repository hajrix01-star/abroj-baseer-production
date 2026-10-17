"""C05/C06 real ORM journeys; mocked HTTP only at the external FCM boundary."""
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..contracts import ProtocolError
from ..models.push import _PUSH_TOKEN


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_notification_settings')
class BChatNotificationSettingsCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        def user(label):
            return self.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Private sender %s' % label, 'login': 'bchat-notification-%s' % uuid4().hex,
                'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
                'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            })
        self.actor, self.recipient = user('actor'), user('recipient')
        self.service = self.env['baseer.bchat.service'].with_user(self.recipient)
        self.installation = str(uuid4())
        self.registration = self.service._v2_push_register({
            'api_version': 2, 'installation_id': self.installation,
            'fcm_token': 'synthetic-notifications-' + 'a' * 64,
        })
        self.key = self.registration['account_key']
        self.device = self.env['baseer.bchat.push.device'].sudo().search([
            ('account_key', '=', self.key)], limit=1)
        self.events = self.env['baseer.bchat.push.event']

    def _preferences(self, mode, **extra):
        revision = self.service._v2_notification_preferences(self.installation)['revision']
        return self.service._v2_notification_set_preferences({
            'api_version': 2, 'installation_id': self.installation, 'account_key': self.key,
            'client_uuid': str(uuid4()), 'expected_revision': revision, 'preview_mode': mode, **extra,
        })

    def _test_payload(self, **extra):
        return {'api_version': 2, 'installation_id': self.installation,
                'account_key': self.key, 'client_uuid': str(uuid4()), **extra}

    def _send_event(self):
        actor = self.env['baseer.bchat.service'].with_user(self.actor)
        group = actor._v2_group_create({
            'api_version': 2, 'company_id': self.company.id, 'client_uuid': str(uuid4()),
            'name': 'Private preview fixture', 'member_user_ids': [self.recipient.id],
        })
        sent = actor._v2_send(group['room_id'], {
            'api_version': 2, 'membership_id': group['membership_id'], 'client_uuid': str(uuid4()),
            'text': '<b>Secret content</b>\nprivate',
        })
        return self.events.sudo().search([('message_id', '=', sent['message_id'])], limit=1)

    def _outgoing_data(self, event):
        with patch.object(type(self.events), '_fcm_access_token', return_value='synthetic-access-token'), \
                patch('requests.post', return_value=SimpleNamespace(status_code=200)) as post:
            self.events._fcm_send(event, {'project_id': 'synthetic-project'})
        return post.call_args.kwargs['json']['message']['data']

    def test_defaults_get_is_read_only_and_versions_do_not_add_unknown_capabilities(self):
        before = (self.device.write_date, self.events.sudo().search_count([]),
                  self.env['baseer.bchat.social.operation'].sudo().search_count([]))
        first = self.service._v2_notification_preferences(self.installation)
        self.assertEqual(first['preview_mode'], 'none')
        self.assertEqual(first['revision'], 1)
        self.assertEqual(self.service._v2_notification_preferences(self.installation), first)
        self.assertEqual(before, (self.device.write_date, self.events.sudo().search_count([]),
                                 self.env['baseer.bchat.social.operation'].sudo().search_count([])))
        bootstrap = self.service._v2_bootstrap()
        self.assertEqual(bootstrap['notification_preferences_version'], 1)
        self.assertEqual(bootstrap['notification_diagnostics_version'], 1)
        self.assertNotIn('notification_preferences', bootstrap['capabilities'])
        self.assertNotIn('notification_diagnostics', bootstrap['capabilities'])

    def test_preference_cas_replay_and_other_device_are_independent(self):
        token = str(uuid4())
        changed = self._preferences('full', client_uuid=token)
        self.assertEqual((changed['preview_mode'], changed['revision'], changed['replayed']), ('full', 2, False))
        replay = self.service._v2_notification_set_preferences({
            'api_version': 2, 'installation_id': self.installation, 'account_key': self.key,
            'client_uuid': token, 'expected_revision': 1, 'preview_mode': 'full',
        })
        self.assertEqual((replay['revision'], replay['operation_revision'], replay['replayed']), (2, 2, True))
        with self.assertRaises(ProtocolError) as conflict:
            self._preferences('none', client_uuid=token, expected_revision=1)
        self.assertEqual(conflict.exception.code, 'idempotency_conflict')
        with self.assertRaises(ProtocolError) as stale:
            self._preferences('none', expected_revision=1)
        self.assertEqual(stale.exception.code, 'revision_conflict')
        other = str(uuid4())
        self.service._v2_push_register({'api_version': 2, 'installation_id': other, 'fcm_token': 'other-' + 'b' * 64})
        self.assertEqual(self.service._v2_notification_preferences(other)['preview_mode'], 'none')
        self.assertEqual(self.service._v2_notification_preferences(self.installation)['preview_mode'], 'full')

    def test_registration_preserves_opt_in_and_account_switch_does_not_inherit_it(self):
        self._preferences('full')
        self.service._v2_push_register({'api_version': 2, 'installation_id': self.installation,
                                      'fcm_token': 'synthetic-notifications-' + 'a' * 64})
        self.assertEqual(self.service._v2_notification_preferences(self.installation)['preview_mode'], 'full')
        other = self.env['baseer.bchat.service'].with_user(self.actor)
        registration = other._v2_push_register({'api_version': 2, 'installation_id': self.installation,
                                               'fcm_token': 'synthetic-notifications-' + 'a' * 64})
        self.assertNotEqual(registration['account_key'], self.key)
        self.assertEqual(other._v2_notification_preferences(self.installation)['preview_mode'], 'none')
        with self.assertRaises(AccessError):
            self.service._v2_notification_preferences(self.installation)

    def test_actual_outgoing_http_data_none_sender_full_and_downgrade(self):
        event = self._send_event()
        minimal = {'account_key': self.key, 'kind': 'chat', 'event_id': str(event.id)}
        self.assertEqual(self._outgoing_data(event), minimal)
        self._preferences('sender')
        sender = self._outgoing_data(event)
        self.assertEqual(set(sender), set(minimal) | {'sender_name'})
        self.assertNotIn('Secret', json.dumps(sender))
        self._preferences('full')
        full = self._outgoing_data(event)
        self.assertEqual(full['message_preview'], 'Secret content private')
        self.assertIn('sender_name', full)
        event._write_verified({'state': 'retry'}, _PUSH_TOKEN)
        self._preferences('none')
        self.assertEqual(self._outgoing_data(event), minimal)

    def test_diagnostic_is_generic_and_does_not_create_or_ack_business_content(self):
        message_event = self._send_event()
        receipt = self.env['baseer.bchat.message.receipt'].sudo().search([
            ('message_id', '=', message_event.message_id.id), ('recipient_user_id', '=', self.recipient.id)])
        before = (self.env['baseer.bchat.message'].sudo().search_count([]),
                  self.env['baseer.bchat.task'].sudo().search_count([]), receipt.read_at, receipt.delivered_at)
        self._preferences('full')
        payload = self._test_payload()
        with patch.object(type(self.events), '_fcm_config', return_value=None):
            response = self.service._v2_notification_test(payload)
        event = self.events.sudo().browse(response['test']['event_id'])
        self.assertEqual(self._outgoing_data(event), {
            'account_key': self.key, 'kind': 'diagnostic', 'event_id': str(event.id),
            'diagnostic_uuid': payload['client_uuid'],
        })
        self.assertEqual(before, (self.env['baseer.bchat.message'].sudo().search_count([]),
                                 self.env['baseer.bchat.task'].sudo().search_count([]), receipt.read_at, receipt.delivered_at))
        self.assertIsNone(response['test']['provider_accepted_at'])
        event._write_verified({'state': 'sent', 'sent_at': fields.Datetime.now()}, _PUSH_TOKEN)
        with patch.object(type(self.events), '_fcm_config', return_value=None):
            status = self.service._v2_notification_test_status(self.installation, event.id)
        self.assertTrue(status['test']['provider_accepted_at'])
        self.assertNotIn('received_at', status['test'])
        self.assertNotIn('read_at', status['test'])

    def test_diagnostic_retry_reuses_event_and_rate_limit_creates_nothing(self):
        payload = self._test_payload()
        with patch.object(type(self.events), '_fcm_config', return_value=None):
            first = self.service._v2_notification_test(payload)
            second = self.service._v2_notification_test(payload)
        self.assertEqual(first['test']['event_id'], second['test']['event_id'])
        self.assertTrue(second['replayed'])
        before = self.events.sudo().search_count([('event_kind', '=', 'diagnostic')])
        with self.assertRaises(ProtocolError) as limited:
            self.service._v2_notification_test(self._test_payload())
        self.assertEqual((limited.exception.code, limited.exception.status), ('rate_limited', 429))
        self.assertGreater(limited.exception.retry_after_seconds, 0)
        self.assertEqual(self.events.sudo().search_count([('event_kind', '=', 'diagnostic')]), before)

    def test_account_daily_limit_is_independent_of_installation_minute_limit(self):
        with patch.object(type(self.events), '_fcm_config', return_value=None):
            for _number in range(10):
                self.service._v2_notification_test(self._test_payload())
                self.env.cr.execute('''UPDATE baseer_bchat_push_event SET create_date = NOW() - INTERVAL '2 minutes'
                                       WHERE recipient_id = %s AND event_kind = 'diagnostic' ''', [self.recipient.id])
                self.events.invalidate_model(['create_date'])
        with self.assertRaises(ProtocolError) as daily:
            self.service._v2_notification_test(self._test_payload())
        self.assertEqual(daily.exception.status, 429)
        self.assertGreater(daily.exception.retry_after_seconds, 60)

    def test_daily_quota_includes_own_uncommitted_rows_across_installations(self):
        second = str(uuid4())
        registration = self.service._v2_push_register({
            'api_version': 2, 'installation_id': second,
            'fcm_token': 'synthetic-quota-second-' + 'q' * 64})
        with patch.object(type(self.events), '_fcm_config', return_value=None):
            for number in range(10):
                payload = self._test_payload()
                if number % 2:
                    payload.update(installation_id=second, account_key=registration['account_key'])
                self.service._v2_notification_test(payload)
                # Only synthetic fixture timestamps change; the service/locks,
                # PostgreSQL reads and event creation are genuine.
                self.env.cr.execute('''UPDATE baseer_bchat_push_event SET create_date=NOW()-INTERVAL '2 minutes'
                    WHERE recipient_id=%s AND event_kind='diagnostic' ''', [self.recipient.id])
            with self.assertRaises(ProtocolError) as limited:
                self.service._v2_notification_test(self._test_payload())
        self.assertEqual((limited.exception.code, limited.exception.status), ('rate_limited', 429))
        self.assertEqual(self.events.sudo().search_count([
            ('recipient_id', '=', self.recipient.id), ('event_kind', '=', 'diagnostic')]), 10)

    def test_private_models_and_forged_installations_are_denied(self):
        other = self.env['baseer.bchat.service'].with_user(self.actor)
        with self.assertRaises(AccessError):
            other._v2_notification_preferences(self.installation)
        with self.assertRaises(AccessError):
            self.service._v2_notification_test(self._test_payload(account_key=str(uuid4())))
        for user in (self.recipient, self.env.ref('base.user_admin')):
            with self.subTest(user=user.id), self.assertRaises(AccessError):
                self.env['baseer.bchat.social.operation'].with_user(user).search_count([])


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_notification_settings')
class BChatNotificationSettingsHttpCase(HttpCase):
    def test_http_preferences_and_self_test_require_session_csrf_and_current_installation(self):
        password = 'test-only-' + uuid4().hex
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Settings HTTP fixture', 'login': 'bchat-settings-http-' + uuid4().hex,
            'password': password, 'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.authenticate(user.login, password)
        csrf = self.url_open('/bchat/api/v2/bootstrap').json()['csrf_token']
        installation = str(uuid4())
        registered = self.url_open('/bchat/api/v2/notifications/register', data={
            'csrf_token': csrf, 'payload': json.dumps({'api_version': 2, 'installation_id': installation,
                                                     'fcm_token': 'synthetic-http-' + 'x' * 64}),
        }).json()
        path = '/bchat/api/v2/notifications/preferences'
        defaults = self.url_open(path + '?installation_id=' + installation)
        self.assertEqual(defaults.status_code, 200)
        self.assertEqual(defaults.json()['preview_mode'], 'none')
        payload = {'api_version': 2, 'installation_id': installation, 'account_key': registered['account_key'],
                   'client_uuid': str(uuid4()), 'expected_revision': 1, 'preview_mode': 'sender'}
        self.assertNotEqual(self.url_open(path, data={'payload': json.dumps(payload)},
                                        allow_redirects=False).status_code, 200)
        response = self.url_open(path, data={'csrf_token': csrf, 'payload': json.dumps(payload)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['preview_mode'], 'sender')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        test_payload = {key: value for key, value in payload.items()
                        if key not in ('expected_revision', 'preview_mode')}
        # Real HTTP/ORM, but no external provider callback from this test.
        with patch.object(type(self.env['baseer.bchat.push.event']), '_schedule_fast_dispatch', return_value=None):
            tested = self.url_open('/bchat/api/v2/notifications/test', data={
                'csrf_token': csrf, 'payload': json.dumps(test_payload),
            })
        self.assertEqual(tested.status_code, 200, tested.text)
        event_id = tested.json()['test']['event_id']
        status = self.url_open('/bchat/api/v2/notifications/test/%s?installation_id=%s' % (event_id, installation))
        self.assertEqual(status.status_code, 200, status.text)
        wrong = self.url_open('/bchat/api/v2/notifications/test/%s?installation_id=%s' % (event_id, uuid4()))
        self.assertEqual(wrong.status_code, 403)
