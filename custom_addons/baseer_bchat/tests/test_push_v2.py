"""BChat push registration and task wake-up contracts."""
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'baseer_bchat')
class BChatPushCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.creator = cls._user('creator')
        cls.assignee = cls._user('assignee')
        cls.replacement = cls._user('replacement')

    @classmethod
    def _user(cls, label):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat push %s' % label,
            'login': 'bchat-push-%s-%s' % (label, uuid4().hex),
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })

    def _service(self, user):
        return self.env['baseer.bchat.service'].with_user(user)

    def _register(self, user, token):
        return self._service(user)._v2_push_register({
            'api_version': 2, 'installation_id': str(uuid4()), 'fcm_token': token,
        })

    def _create(self, assignee=None):
        return self._service(self.creator)._v2_task_create({
            'api_version': 2, 'company_id': self.company.id, 'room_id': None,
            'client_uuid': str(uuid4()), 'title': 'Push task', 'description': '',
            'due_at': None, 'assignee_id': (assignee or self.assignee).id,
        })

    def test_task_assignment_creates_private_event_and_rechecks_recipient(self):
        registration = self._register(self.assignee, 'a' * 64)
        self.assertTrue(registration['push_enabled'])
        self.assertEqual(registration['installation_id'].count('-'), 4)
        task = self._create()['task']
        event = self.env['baseer.bchat.push.event'].sudo().search([
            ('task_id', '=', task['id']),
        ], limit=1)
        self.assertTrue(event)
        self.assertEqual(event.recipient_id, self.assignee)
        self.assertEqual(event.event_kind, 'assigned')
        self.assertEqual(event.state, 'pending')
        received = self._service(self.assignee)._v2_push_event(event.id)
        self.assertEqual(received['notification']['kind'], 'task')
        self.assertEqual(received['notification']['source_ref'], {
            'destination': 'task', 'task_id': task['id'],
        })
        with self.assertRaises(AccessError):
            self._service(self.creator)._v2_push_event(event.id)

    def test_token_moves_to_current_user_and_reassign_never_wakes_previous_assignee(self):
        shared_token = 'b' * 64
        first = self._register(self.assignee, shared_token)
        self._register(self.replacement, shared_token)
        devices = self.env['baseer.bchat.push.device'].sudo().search([('fcm_token', '=', shared_token)])
        self.assertEqual(devices.user_id, self.replacement)
        self.assertFalse(self.env['baseer.bchat.push.device'].sudo().search([
            ('account_key', '=', first['account_key']),
        ]))
        self._register(self.creator, 'c' * 64)
        task = self._create()['task']
        self._service(self.creator)._v2_task_transition(task['id'], {
            'api_version': 2, 'client_uuid': str(uuid4()), 'expected_revision': 1,
            'action': 'reassign', 'assignee_id': self.replacement.id, 'reason': None,
        })
        events = self.env['baseer.bchat.push.event'].sudo().search([
            ('task_id', '=', task['id']), ('task_revision', '=', 2),
        ])
        self.assertEqual(set(events.mapped('recipient_id').ids), {self.creator.id, self.replacement.id})
        self.assertNotIn(self.assignee.id, events.mapped('recipient_id').ids)

    def test_reassignment_revokes_pending_assignment_event_for_previous_assignee(self):
        self._register(self.assignee, 'e' * 64)
        self._register(self.replacement, 'f' * 64)
        task = self._create()['task']
        old_event = self.env['baseer.bchat.push.event'].sudo().search([
            ('task_id', '=', task['id']), ('recipient_id', '=', self.assignee.id),
        ], limit=1)
        self._service(self.creator)._v2_task_transition(task['id'], {
            'api_version': 2, 'client_uuid': str(uuid4()), 'expected_revision': 1,
            'action': 'reassign', 'assignee_id': self.replacement.id, 'reason': None,
        })
        with self.assertRaises(AccessError):
            self._service(self.assignee)._v2_push_event(old_event.id)
        self.env['baseer.bchat.push.event']._cron_dispatch()
        old_event.invalidate_recordset()
        self.assertEqual(old_event.state, 'discarded')

    def test_unregister_and_private_models_do_not_grant_acl_access(self):
        registration = self._register(self.assignee, 'd' * 64)
        self._service(self.assignee)._v2_push_unregister({
            'api_version': 2, 'installation_id': registration['installation_id'],
        })
        device = self.env['baseer.bchat.push.device'].sudo().search([
            ('account_key', '=', registration['account_key']),
        ])
        self.assertFalse(device.active)
        for model in ('baseer.bchat.push.device', 'baseer.bchat.push.event'):
            self.assertFalse(self.env[model].with_user(self.creator).has_access('read'))
            self.assertFalse(self.env[model].with_user(self.creator).has_access('create'))
