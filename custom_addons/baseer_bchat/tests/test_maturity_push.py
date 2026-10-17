"""C04 provider envelopes and per-event recovery boundaries, without real FCM."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import BaseCase

from ..models import push as push_module


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
                patch('requests.post', return_value=response), \
                patch.object(push_module.random, 'random', return_value=0.0):
            self.events._dispatch_event_ids([self.event.id])
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
        self.assertTrue(self.event.device_id.active)


@tagged('post_install', '-at_install', 'baseer_bchat', 'baseer_bchat_maturity')
class BChatPushRecoveryBoundaryCase(BaseCase):
    def test_cron_budget_leaves_later_candidates_for_next_run(self):
        cursor = MagicMock()
        cursor.dbname = 'synthetic_isolated_database'
        cursor.fetchall.return_value = [(17,), (18,)]
        fake_self = SimpleNamespace(env=SimpleNamespace(cr=cursor))
        with patch.object(push_module.time, 'monotonic', side_effect=[0, 0, 21]), \
                patch.object(push_module, '_fast_dispatch_event') as dispatch:
            self.assertTrue(push_module.BChatPushEvent._cron_dispatch(fake_self))
        dispatch.assert_called_once_with('synthetic_isolated_database', 17)
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
