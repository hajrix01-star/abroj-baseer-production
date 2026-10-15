"""BChat task authorization, lifecycle and HTTP on an isolated Odoo test DB."""
import json
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..contracts import ProtocolError


@tagged('post_install', '-at_install', 'baseer_bchat')
class BChatTaskCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.foreign_company = cls.env['res.company'].create({'name': 'BChat task foreign company'})
        # Only the original admin account may administer rooms.  Keep the
        # separate ``manager`` fixture below as a non-member/outsider for the
        # visibility assertions, and use the real room administrator solely
        # for the setup operations.
        cls.room_admin = cls.env.ref('base.user_admin')
        cls.room_admin.sudo().write({
            'group_ids': [Command.link(cls.env.ref('baseer_bchat.group_bchat_manager').id)],
        })
        cls.manager = cls._user('manager', cls.company, 'baseer_bchat.group_bchat_manager')
        cls.creator = cls._user('creator', cls.company)
        cls.assignee = cls._user('assignee', cls.company)
        cls.rescuer = cls._user('rescuer', cls.company)
        cls.foreign = cls._user('foreign', cls.foreign_company)
        cls.room = cls.env['baseer.bchat.room'].with_user(cls.room_admin).with_company(cls.company).create({
            'name': 'Task room', 'company_id': cls.company.id,
        })
        cls.memberships = {user.id: cls._join(user) for user in
                           (cls.creator, cls.assignee, cls.rescuer)}

    @classmethod
    def _user(cls, label, company, group='base.group_user'):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat task %s' % label,
            'login': 'bchat-task-%s-%s' % (label, uuid4().hex),
            'company_id': company.id, 'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([cls.env.ref(group).id])],
        })

    @classmethod
    def _join(cls, user):
        return cls.env['baseer.bchat.membership'].with_user(cls.room_admin).with_company(cls.company).create({
            'room_id': cls.room.id, 'user_id': user.id,
        })

    def _service(self, user):
        return self.env['baseer.bchat.service'].with_user(user)

    def _create(self, room=None, creator=None, assignee=None, client_uuid=None):
        creator = creator or self.creator
        assignee = assignee or self.assignee
        return self._service(creator)._v2_task_create({
            'api_version': 2, 'company_id': self.company.id,
            'room_id': room.id if room else None,
            'client_uuid': client_uuid or str(uuid4()),
            'title': 'Check refrigerator', 'description': 'Record the result',
            'due_at': None, 'assignee_id': assignee.id,
        })

    def _change(self, user, task_id, revision, action, assignee=None, reason=None, client_uuid=None):
        return self._service(user)._v2_task_transition(task_id, {
            'api_version': 2, 'client_uuid': client_uuid or str(uuid4()),
            'expected_revision': revision, 'action': action,
            'assignee_id': assignee.id if assignee else None, 'reason': reason,
        })

    def test_private_model_and_independent_visibility(self):
        for model in ('baseer.bchat.task', 'baseer.bchat.task.event'):
            for user in (self.creator, self.manager):
                self.assertFalse(self.env[model].with_user(user).has_access('read'))
                self.assertFalse(self.env[model].with_user(user).has_access('create'))
            with self.assertRaises(AccessError):
                self.env[model].with_user(self.manager).create({})
        created = self._create()
        task_id = created['task']['id']
        self.assertEqual(created['task']['state'], 'new')
        self.assertIsNone(created['task']['room_id'])
        self.assertEqual(self._service(self.creator)._v2_task_detail(task_id)['task']['id'], task_id)
        self.assertEqual(self._service(self.assignee)._v2_task_detail(task_id)['task']['id'], task_id)
        for outsider in (self.manager, self.rescuer, self.foreign):
            with self.assertRaises(AccessError):
                self._service(outsider)._v2_task_detail(task_id)
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.task'].sudo().browse(task_id).write({'title': 'Changed'})
        for user in (self.creator, self.manager):
            with self.assertRaises(AccessError):
                self.env['baseer.bchat.task'].with_user(user).search([])
            with self.assertRaises(AccessError):
                self.env['baseer.bchat.task'].with_user(user).browse(task_id).read(['title'])

    def test_room_current_member_visibility_and_revocation(self):
        task_id = self._create(self.room)['task']['id']
        self.assertEqual(self._service(self.rescuer)._v2_task_detail(task_id)['task']['room_id'], self.room.id)
        self.memberships[self.rescuer.id].with_user(self.manager).with_company(self.company).action_revoke()
        with self.assertRaises(AccessError):
            self._service(self.rescuer)._v2_task_detail(task_id)
        self.assertNotIn(task_id, [row['id'] for row in self._service(self.rescuer)._v2_tasks()['tasks']])
        with self.assertRaises(AccessError):
            self._service(self.rescuer)._v2_tasks(room_id=self.room.id)
        self.assertIn(task_id, [row['id'] for row in self._service(self.creator)._v2_tasks()['tasks']])

    def test_room_rows_expose_only_neutral_active_task_indicator(self):
        before = next(row for row in self._service(self.creator)._v2_rooms()['rooms']
                      if row['id'] == self.room.id)
        self.assertFalse(before['has_active_task'])
        self._create(self.room)
        active = next(row for row in self._service(self.creator)._v2_rooms()['rooms']
                      if row['id'] == self.room.id)
        self.assertTrue(active['has_active_task'])
        self._change(self.assignee, self._service(self.creator)._v2_tasks(
            room_id=self.room.id)['tasks'][0]['id'], 1, 'start')
        self._change(self.assignee, self._service(self.creator)._v2_tasks(
            room_id=self.room.id)['tasks'][0]['id'], 2, 'done')
        completed = next(row for row in self._service(self.creator)._v2_rooms()['rooms']
                         if row['id'] == self.room.id)
        self.assertFalse(completed['has_active_task'])

    def test_assignment_validation_and_options(self):
        options = self._service(self.creator)._v2_task_options(self.company.id, self.room.id)
        self.assertIn(self.assignee.id, [item['id'] for item in options['assignees']])
        self.assertNotIn(self.foreign.id, [item['id'] for item in options['assignees']])
        with self.assertRaises(AccessError):
            self._create(self.room, assignee=self.foreign)
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_task_options(self.company.id)
        self.assignee.write({'active': False})
        with self.assertRaises(AccessError):
            self._create(assignee=self.assignee)

    def test_lifecycle_reassignment_finality_and_replay(self):
        created = self._create(self.room)
        task_id = created['task']['id']
        with self.assertRaises(AccessError):
            self._change(self.creator, task_id, 1, 'start')
        started = self._change(self.assignee, task_id, 1, 'start')
        self.assertEqual(started['task']['state'], 'in_progress')
        with self.assertRaises(ProtocolError):
            self._change(self.assignee, task_id, 1, 'done')
        reassigned = self._change(self.creator, task_id, 2, 'reassign', self.rescuer)
        self.assertEqual(reassigned['task']['state'], 'new')
        self.assertEqual(reassigned['task']['assignee_id'], self.rescuer.id)
        self.assertEqual(reassigned['task']['revision'], 3)
        with self.assertRaises(AccessError):
            self._change(self.assignee, task_id, 3, 'start')
        operation = str(uuid4())
        started_again = self._change(self.rescuer, task_id, 3, 'start', client_uuid=operation)
        replay = self._change(self.rescuer, task_id, 3, 'start', client_uuid=operation)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['operation_revision'], started_again['operation_revision'])
        with self.assertRaises(ProtocolError):
            self._change(self.rescuer, task_id, 3, 'done', client_uuid=operation)
        self.assertEqual(self.env['baseer.bchat.task.event'].sudo().search_count([
            ('task_id', '=', task_id), ('client_uuid', '=', operation),
        ]), 1)
        done = self._change(self.rescuer, task_id, 4, 'done')
        self.assertEqual(done['task']['state'], 'done')
        replay_after_change = self._change(self.rescuer, task_id, 3, 'start', client_uuid=operation)
        self.assertTrue(replay_after_change['replayed'])
        self.assertEqual(replay_after_change['operation_revision'], 4)
        self.assertEqual(replay_after_change['task']['state'], 'done')
        for action, actor in (('cancel', self.creator), ('reassign', self.creator), ('start', self.rescuer)):
            with self.assertRaises(ProtocolError):
                self._change(actor, task_id, 5, action,
                             self.assignee if action == 'reassign' else None)

    def test_create_replay_and_no_cross_company_or_uuid_reuse(self):
        operation = str(uuid4())
        first = self._create(client_uuid=operation)
        self.assertEqual(first['client_uuid'], operation)
        self.assertFalse(first['replayed'])
        self._change(self.assignee, first['task']['id'], 1, 'start')
        replay = self._create(client_uuid=operation)
        self.assertEqual(replay['client_uuid'], operation)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['task']['id'], first['task']['id'])
        self.assertEqual(replay['task']['state'], 'in_progress')
        other_uuid = str(uuid4())
        other = self._create(client_uuid=other_uuid)
        self.assertEqual(other['client_uuid'], other_uuid)
        self.assertNotEqual(other['task']['id'], first['task']['id'])
        with self.assertRaises(ProtocolError):
            self._create(self.room, client_uuid=operation)
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_task_create({
                'api_version': 2, 'company_id': self.company.id, 'room_id': None,
                'client_uuid': str(uuid4()), 'title': 'Foreign',
                'description': '', 'due_at': None, 'assignee_id': self.foreign.id,
            })

    def test_rescue_when_assignee_leaves_and_both_present_rejected(self):
        task_id = self._create(self.room)['task']['id']
        with self.assertRaises(AccessError):
            self._change(self.rescuer, task_id, 1, 'rescue', self.rescuer, 'Neither actor is absent')
        self.memberships[self.assignee.id].with_user(self.manager).with_company(self.company).action_revoke()
        with self.assertRaises(AccessError):
            self._change(self.rescuer, task_id, 1, 'rescue', self.foreign,
                         'The replacement belongs to another company')
        operation = str(uuid4())
        saved = self._change(self.rescuer, task_id, 1, 'rescue', self.rescuer,
                             'The original assignee left this room', client_uuid=operation)
        self.assertEqual(saved['task']['assignee_id'], self.rescuer.id)
        self.assertEqual(saved['task']['state'], 'new')
        self.assertTrue(self._task_can_act(self.creator.id))
        replay = self._change(self.rescuer, task_id, 1, 'rescue', self.rescuer,
                              'The original assignee left this room', client_uuid=operation)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['operation_revision'], saved['operation_revision'])
        audit = self.env['baseer.bchat.task.event'].sudo().search([('task_id', '=', task_id)], limit=1)
        self.assertEqual(audit.action, 'rescue')
        self.assertEqual(audit.actor_id, self.rescuer)
        self.assertTrue(audit.reason)
        self.assertEqual(self.env['baseer.bchat.task.event'].sudo().search_count([
            ('task_id', '=', task_id),
        ]), 1)

    def test_rescue_when_creator_leaves_but_assignee_remains(self):
        task_id = self._create(self.room)['task']['id']
        self.memberships[self.creator.id].with_user(self.manager).with_company(self.company).action_revoke()
        saved = self._change(self.rescuer, task_id, 1, 'rescue', self.rescuer,
                             'The original creator left this room')
        self.assertEqual(saved['task']['assignee_id'], self.rescuer.id)
        self.assertEqual(saved['task']['revision'], 2)
        self.assertTrue(self._task_can_act(self.assignee.id))

    def _task_can_act(self, user_id):
        return self._service(self.rescuer)._task_can_act(self.company.id, user_id, self.room.id)

    def test_list_is_bounded_and_cursor_stable(self):
        created = [self._create()['task']['id'] for _ in range(33)]
        newest = self._service(self.creator)._v2_tasks()
        self.assertEqual([item['id'] for item in newest['tasks']], list(reversed(created[-30:])))
        self.assertEqual(newest['next_before_id'], created[-30])
        older = self._service(self.creator)._v2_tasks(before_id=newest['next_before_id'])
        self.assertEqual([item['id'] for item in older['tasks']], list(reversed(created[:3])))
        self.assertIsNone(older['next_before_id'])

    def test_list_open_state_includes_new_and_in_progress_only(self):
        new_id = self._create()['task']['id']
        started_id = self._create()['task']['id']
        done_id = self._create()['task']['id']
        self._change(self.assignee, started_id, 1, 'start')
        self._change(self.assignee, done_id, 1, 'start')
        self._change(self.assignee, done_id, 2, 'done')
        open_tasks = self._service(self.creator)._v2_tasks(state='open')['tasks']
        self.assertIn(new_id, [row['id'] for row in open_tasks])
        self.assertIn(started_id, [row['id'] for row in open_tasks])
        self.assertNotIn(done_id, [row['id'] for row in open_tasks])
        with self.assertRaises(ProtocolError):
            self._service(self.creator)._v2_tasks(state='not-a-state')

    def test_standalone_reassignment_emits_bounded_revocation_hint(self):
        created = self._create()
        task_id = created['task']['id']
        before = self._service(self.assignee)._v2_changes(0, 100)
        self.assertIn(task_id, [row.get('task_id') for row in before['changes']])
        changed = self._change(self.creator, task_id, 1, 'reassign', assignee=self.rescuer)
        self.assertEqual(changed['task']['assignee_id'], self.rescuer.id)
        old = self._service(self.assignee)._v2_changes(0, 100)
        self.assertIn({'seq': old['watermark'], 'kind': 'task_revoked',
                       'task_id': task_id}, old['changes'])
        self.assertIn(task_id, [row.get('task_id') for row in
                       self._service(self.rescuer)._v2_changes(0, 100)['changes']])
        self.assertNotIn('Check refrigerator', str(old['changes']))


@tagged('post_install', '-at_install', 'baseer_bchat')
class BChatTaskHttpCase(HttpCase):
    def test_task_options_create_list_and_csrf(self):
        company = self.env.company
        password = 'test-only-%s' % uuid4().hex
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat task HTTP user', 'login': 'bchat-task-http-%s' % uuid4().hex,
            'password': password, 'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.authenticate(user.login, password)
        bootstrap = self.url_open('/bchat/api/v2/bootstrap').json()
        self.assertFalse(bootstrap['capabilities']['tasks'])  # 0.6.0 compatibility.
        options = self.url_open('/bchat/api/v2/tasks/options?company_id=%s' % company.id)
        self.assertEqual(options.status_code, 200)
        self.assertIn(user.id, [item['id'] for item in options.json()['assignees']])
        request_uuid = str(uuid4())
        payload = json.dumps({
            'api_version': 2, 'company_id': company.id, 'room_id': None,
            'client_uuid': request_uuid, 'title': 'HTTP task',
            'description': '', 'due_at': None, 'assignee_id': user.id,
        })
        created = self.url_open('/bchat/api/v2/tasks', data={
            'csrf_token': bootstrap['csrf_token'], 'payload': payload,
        }, allow_redirects=False)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()['client_uuid'], request_uuid)
        self.assertFalse(created.json()['replayed'])
        task_id = created.json()['task']['id']
        registration = self.url_open('/bchat/api/v2/notifications/register', data={
            'csrf_token': bootstrap['csrf_token'], 'payload': json.dumps({
                'api_version': 2, 'installation_id': str(uuid4()), 'fcm_token': 'h' * 64,
            }),
        }, allow_redirects=False)
        self.assertEqual(registration.status_code, 200)
        self.assertTrue(registration.json()['push_enabled'])
        self.assertEqual(registration.json()['account_key'].count('-'), 4)
        event = self.env['baseer.bchat.push.event'].sudo().search([
            ('task_id', '=', task_id), ('recipient_id', '=', user.id),
        ], limit=1)
        # Registration happens after this task, so create another to exercise
        # the endpoint through the authenticated browser session.
        second_payload = {**json.loads(payload), 'client_uuid': str(uuid4()), 'title': 'HTTP push task'}
        second = self.url_open('/bchat/api/v2/tasks', data={
            'csrf_token': bootstrap['csrf_token'], 'payload': json.dumps(second_payload),
        }, allow_redirects=False)
        self.assertEqual(second.status_code, 200)
        event = self.env['baseer.bchat.push.event'].sudo().search([
            ('task_id', '=', second.json()['task']['id']), ('recipient_id', '=', user.id),
        ], limit=1)
        notification = self.url_open('/bchat/api/v2/notifications/%s' % event.id,
                                     allow_redirects=False)
        self.assertEqual(notification.status_code, 200)
        self.assertEqual(notification.json()['notification']['source_ref']['task_id'],
                         second.json()['task']['id'])
        replay = self.url_open('/bchat/api/v2/tasks', data={
            'csrf_token': bootstrap['csrf_token'], 'payload': payload,
        }, allow_redirects=False)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()['client_uuid'], request_uuid)
        self.assertTrue(replay.json()['replayed'])
        self.assertEqual(replay.json()['task']['id'], task_id)
        listing = self.url_open('/bchat/api/v2/tasks')
        self.assertIn(task_id, [item['id'] for item in listing.json()['tasks']])
        detail = self.url_open('/bchat/api/v2/tasks/%s' % task_id)
        self.assertEqual(detail.json()['task']['title'], 'HTTP task')
        mutation = self.url_open('/bchat/api/v2/tasks/%s/transition' % task_id, data={
            'csrf_token': bootstrap['csrf_token'], 'payload': json.dumps({
                'api_version': 2, 'client_uuid': str(uuid4()), 'expected_revision': 1,
                'action': 'start', 'assignee_id': None, 'reason': None,
            }),
        }, allow_redirects=False)
        self.assertEqual(mutation.status_code, 200)
        self.assertEqual(mutation.json()['task']['state'], 'in_progress')
        missing_csrf = self.url_open('/bchat/api/v2/tasks', data={'payload': payload},
                                     allow_redirects=False)
        self.assertNotEqual(missing_csrf.status_code, 200)

    def test_http_denies_foreign_company_revoked_room_and_private_rpc(self):
        company = self.env.company
        foreign_company = self.env['res.company'].create({'name': 'BChat HTTP foreign company'})
        password = 'test-only-%s' % uuid4().hex
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat HTTP member', 'login': 'bchat-http-member-%s' % uuid4().hex,
            'password': password, 'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        room_admin = self.env.ref('base.user_admin')
        room_admin.sudo().write({
            'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)],
        })
        room = self.env['baseer.bchat.room'].with_user(room_admin).with_company(company).create({
            'name': 'HTTP member room', 'company_id': company.id,
        })
        membership = self.env['baseer.bchat.membership'].with_user(room_admin).with_company(company).create({
            'room_id': room.id, 'user_id': user.id,
        })
        self.authenticate(user.login, password)
        csrf = self.url_open('/bchat/api/v2/bootstrap').json()['csrf_token']
        denied_options = self.url_open('/bchat/api/v2/tasks/options?company_id=%s' % foreign_company.id)
        self.assertEqual(denied_options.status_code, 403)
        foreign_payload = json.dumps({
            'api_version': 2, 'company_id': foreign_company.id, 'room_id': None,
            'client_uuid': str(uuid4()), 'title': 'Forbidden company',
            'description': '', 'due_at': None, 'assignee_id': user.id,
        })
        denied_create = self.url_open('/bchat/api/v2/tasks', data={
            'csrf_token': csrf, 'payload': foreign_payload,
        }, allow_redirects=False)
        self.assertEqual(denied_create.status_code, 403)
        room_payload = json.dumps({
            'api_version': 2, 'company_id': company.id, 'room_id': room.id,
            'client_uuid': str(uuid4()), 'title': 'Revoked room task',
            'description': '', 'due_at': None, 'assignee_id': user.id,
        })
        created = self.url_open('/bchat/api/v2/tasks', data={
            'csrf_token': csrf, 'payload': room_payload,
        }, allow_redirects=False)
        self.assertEqual(created.status_code, 200)
        task_id = created.json()['task']['id']
        membership.with_user(room_admin).with_company(company).action_revoke()
        self.assertEqual(self.url_open('/bchat/api/v2/tasks/%s' % task_id).status_code, 403)
        self.assertEqual(self.url_open('/bchat/api/v2/tasks?room_id=%s' % room.id).status_code, 403)
        self.assertNotIn(task_id, [task['id'] for task in
                         self.url_open('/bchat/api/v2/tasks').json()['tasks']])
        private_rpc = self.url_open('/web/dataset/call_kw/baseer.bchat.service/_v2_tasks',
                                    data=json.dumps({
                                        'jsonrpc': '2.0', 'method': 'call',
                                        'params': {'model': 'baseer.bchat.service',
                                                   'method': '_v2_tasks', 'args': [], 'kwargs': {}},
                                        'id': 1,
                                    }), headers={'Content-Type': 'application/json'})
        self.assertIn('error', private_rpc.json())
