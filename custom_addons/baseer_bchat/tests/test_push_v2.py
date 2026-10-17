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

    def _room(self):
        manager = self.env.ref('base.user_admin')
        manager.write({'group_ids': [Command.link(
            self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        room = self.env['baseer.bchat.room'].with_user(manager).with_company(self.company).create({
            'name': 'Push chat %s' % uuid4().hex, 'company_id': self.company.id,
        })
        memberships = self.env['baseer.bchat.membership'].with_user(manager).with_company(self.company)
        creator = memberships.create({'room_id': room.id, 'user_id': self.creator.id})
        recipient = memberships.create({'room_id': room.id, 'user_id': self.assignee.id})
        return room, creator, recipient

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
        replaced = self.env['baseer.bchat.push.device'].sudo().search([
            ('account_key', '=', first['account_key']),
        ])
        self.assertTrue(replaced)
        self.assertFalse(replaced.active)
        self.assertEqual(replaced.inactive_reason, 'replaced')
        self.assertTrue(replaced.inactive_at)
        self.assertNotEqual(replaced.fcm_token, shared_token)
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
        # This transaction has not committed the fixture. Exercise the locked
        # event dispatcher directly; cron now owns independent committed cursors.
        self.env['baseer.bchat.push.event']._dispatch_event_ids([old_event.id])
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
        self.assertEqual(device.inactive_reason, 'logout')
        self.assertTrue(device.inactive_at)
        for model in ('baseer.bchat.push.device', 'baseer.bchat.push.event'):
            self.assertFalse(self.env[model].with_user(self.creator).has_access('read'))
            self.assertFalse(self.env[model].with_user(self.creator).has_access('create'))

    def test_registration_reactivates_the_same_device_after_logout(self):
        installation = str(uuid4())
        payload = {
            'api_version': 2,
            'installation_id': installation,
            'fcm_token': 'reconnect-' + ('h' * 56),
        }
        first = self._service(self.assignee)._v2_push_register(payload)
        self._service(self.assignee)._v2_push_unregister({
            'api_version': 2, 'installation_id': installation,
        })
        restored = self._service(self.assignee)._v2_push_register(payload)
        self.assertEqual(restored['account_key'], first['account_key'])
        devices = self.env['baseer.bchat.push.device'].sudo().with_context(
            active_test=False).search([
                ('user_id', '=', self.assignee.id),
                ('installation_id', '=', installation),
            ])
        self.assertEqual(len(devices), 1)
        self.assertTrue(devices.active)
        self.assertFalse(devices.inactive_reason)
        self.assertFalse(devices.inactive_at)

    def test_chat_message_queues_one_private_event_per_device_and_opens_only_for_recipient(self):
        self._register(self.assignee, 'g' * 64)
        room, author_member, recipient_member = self._room()
        request = {
            'api_version': 2, 'membership_id': author_member.id,
            'client_uuid': str(uuid4()), 'text': 'Private push preview',
        }
        sent = self._service(self.creator)._v2_send(room.id, request)
        self.assertEqual(self._service(self.creator)._v2_send(room.id, request), sent)
        events = self.env['baseer.bchat.push.event'].sudo().search([
            ('message_id', '=', sent['message_id']),
        ])
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.recipient_id, self.assignee)
        self.assertEqual(event.event_kind, 'message')
        self.assertFalse(event.task_id)
        self.assertFalse(event.task_revision)
        received = self._service(self.assignee)._v2_push_event(event.id)
        self.assertEqual(received['notification'], {
            'id': event.id, 'kind': 'chat',
            'source_ref': {'destination': 'room_message', 'room_id': room.id,
                           'message_id': sent['message_id']},
        })
        with self.assertRaises(AccessError):
            self._service(self.creator)._v2_push_event(event.id)
        detail = self._service(self.assignee)._v2_message(room.id, sent['message_id'])
        self.assertEqual(detail['message']['text'], 'Private push preview')
        self.assertEqual(recipient_member.user_id, self.assignee)

    def test_notification_preview_is_bounded_and_removes_controls(self):
        from ..models.push import _notification_text
        self.assertEqual(_notification_text('\u202e<b>Hello</b>\nworld\x00', 160), 'Hello world')
        self.assertEqual(_notification_text('x' * 200, 160), 'x' * 160)

    def test_largest_qa_group_creates_one_event_per_active_device(self):
        """35-user QA bound: sender + 34 recipients, five devices each."""
        room, author_member, _recipient = self._room()
        memberships = self.env['baseer.bchat.membership'].with_user(
            self.env.ref('base.user_admin')).with_company(self.company)
        recipients = []
        for index in range(34):
            user = self._user('group-%s' % index)
            recipients.append(user)
            memberships.create({'room_id': room.id, 'user_id': user.id})
            for device in range(5):
                token = ('g%03d%02d' % (index, device)) + ('x' * 58)
                self._register(user, token)
        sent = self._service(self.creator)._v2_send(room.id, {
            'api_version': 2, 'membership_id': author_member.id,
            'client_uuid': str(uuid4()), 'text': 'QA maximum group',
        })
        events = self.env['baseer.bchat.push.event'].sudo().search([
            ('message_id', '=', sent['message_id']),
        ])
        self.assertEqual(len(events), 170)
        self.assertEqual(len(set(events.mapped('device_id').ids)), 170)
        self.assertNotIn(self.creator.id, events.mapped('recipient_id').ids)

    def test_room_task_notifies_every_active_task_viewer_except_the_actor(self):
        """Room tasks follow room visibility, not just creator/assignee roles."""
        room, creator_member, _assignee_member = self._room()
        memberships = self.env['baseer.bchat.membership'].with_user(
            self.env.ref('base.user_admin')).with_company(self.company)
        memberships.create({'room_id': room.id, 'user_id': self.replacement.id})
        self._register(self.creator, 'creator-room-' + ('a' * 51))
        self._register(self.assignee, 'assignee-room-' + ('b' * 50))
        self._register(self.replacement, 'observer-room-' + ('c' * 50))
        created = self._service(self.creator)._v2_task_create({
            'api_version': 2, 'company_id': self.company.id, 'room_id': room.id,
            'client_uuid': str(uuid4()), 'title': 'Visible room task',
            'description': '', 'due_at': None, 'assignee_id': self.assignee.id,
        })['task']
        assignment_events = self.env['baseer.bchat.push.event'].sudo().search([
            ('task_id', '=', created['id']), ('task_revision', '=', 1),
        ])
        self.assertEqual(set(assignment_events.mapped('recipient_id').ids), {
            self.assignee.id, self.replacement.id,
        })
        self.assertNotIn(self.creator.id, assignment_events.mapped('recipient_id').ids)
        self._service(self.assignee)._v2_task_transition(created['id'], {
            'api_version': 2, 'client_uuid': str(uuid4()), 'expected_revision': 1,
            'action': 'start', 'assignee_id': None, 'reason': None,
        })
        updated_events = self.env['baseer.bchat.push.event'].sudo().search([
            ('task_id', '=', created['id']), ('task_revision', '=', 2),
        ])
        self.assertEqual(set(updated_events.mapped('recipient_id').ids), {
            self.creator.id, self.replacement.id,
        })
        self.assertNotIn(self.assignee.id, updated_events.mapped('recipient_id').ids)

    def test_postgres_skip_locked_excludes_a_row_locked_by_another_worker(self):
        """The dispatcher lock primitive must not hand a locked row to a second worker."""
        with self.env.registry.cursor() as first_worker:
            first_worker.execute('SELECT id FROM res_users WHERE id = %s FOR UPDATE', [1])
            with self.env.registry.cursor() as second_worker:
                second_worker.execute(
                    'SELECT id FROM res_users WHERE id = %s FOR UPDATE SKIP LOCKED', [1])
                self.assertFalse(second_worker.fetchall())
