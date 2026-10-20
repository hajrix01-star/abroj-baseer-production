"""Modern BWork task ORM/HTTP acceptance on an isolated Odoo test DB only."""
import json
from datetime import timedelta
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..contracts import ProtocolError
from ..models.task import _TASK_SERVICE_TOKEN
from ..models.push import _PUSH_TOKEN


@tagged('post_install', '-at_install', 'baseer_bwork', 'bwork_tasks')
class BWorkTaskCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other = cls.env['res.company'].create({'name': 'Work tasks second company'})
        cls.foreign_company = cls.env['res.company'].create({'name': 'Work tasks foreign company'})
        cls.creator = cls._user('creator', cls.company | cls.other)
        cls.assignee = cls._user('assignee', cls.company | cls.other)
        cls.replacement = cls._user('replacement', cls.company | cls.other)
        cls.outsider = cls._user('outsider', cls.company)
        cls.foreign = cls._user('foreign', cls.foreign_company)

    @classmethod
    def _user(cls, label, companies, **extra):
        values = dict(name='Work tasks ' + label, login='work-task-' + uuid4().hex,
            company_id=companies[0].id, company_ids=[Command.set(companies.ids)],
            group_ids=[Command.set([cls.env.ref('base.group_user').id])],
            bwork_chat_view=False, bwork_task_view=True, bwork_task_manage=True)
        values.update(extra)
        return cls.env['res.users'].with_context(no_reset_password=True).create(values)

    def service(self, user=None):
        return self.env['baseer.bwork.service'].with_user(user or self.creator)

    def create_payload(self, **changes):
        values = dict(api_version=2, work_tasks_version=1, company_id=self.company.id,
            room_id=None, client_uuid=str(uuid4()), title='Repair air conditioner', description='',
            due_at=None, reminder_at=None, assignee_id=self.assignee.id)
        values.update(changes)
        return values

    def create_task(self, **changes):
        return self.service()._work_task_create(self.create_payload(**changes))['task']

    def transition_payload(self, task, action='done', **changes):
        values = dict(api_version=2, work_tasks_version=1, company_id=task['company_id'],
            client_uuid=str(uuid4()), expected_revision=task['revision'], action=action,
            assignee_id=None, reason=None)
        values.update(changes)
        return values

    def test_task_only_options_single_company_and_no_rights(self):
        options = self.service()._work_task_options()
        self.assertEqual(options['work_tasks_version'], 1)
        self.assertIsNone(options['default_company_id'])
        self.assertEqual({row['id'] for row in options['companies']}, {self.company.id, self.other.id})
        single = self.service(self.outsider)._work_task_options()
        self.assertEqual(single['default_company_id'], self.company.id)
        self.assertTrue(single['can_manage'])
        self.outsider.sudo().write({'bwork_task_manage': False})
        self.assertFalse(self.service(self.outsider)._work_task_options()['can_manage'])
        with self.assertRaises(AccessError):
            self.service(self.outsider)._work_task_assignees(self.company.id)
        with self.assertRaises(AccessError):
            self.service(self.outsider)._work_task_create(self.create_payload())
        self.outsider.sudo().write({'bwork_task_view': False})
        with self.assertRaises(AccessError):
            self.service(self.outsider)._work_task_options()

    def test_all_company_perspective_filter_and_bounded_interleaved_cursor(self):
        expected = []
        for index in range(34):
            company = self.company if index % 2 else self.other
            expected.append(self.create_task(company_id=company.id)['id'])
        first = self.service(self.assignee)._work_tasks()
        self.assertEqual([row['id'] for row in first['tasks']], list(reversed(expected))[:30])
        self.assertIsNone(first['company_id'])
        second = self.service(self.assignee)._work_tasks(before_id=first['next_before_id'])
        self.assertEqual([row['id'] for row in second['tasks']], list(reversed(expected))[30:])
        self.assertIsNone(second['next_before_id'])
        filtered = self.service(self.assignee)._work_tasks(company_id=self.other.id)
        self.assertEqual(len(filtered['tasks']), 17)
        self.assertTrue(all(row['company_id'] == self.other.id for row in filtered['tasks']))
        self.assertEqual(self.service()._work_tasks()['tasks'], [])
        self.assertEqual(len(self.service()._work_tasks(view='created')['tasks']), 30)
        self.assertEqual(self.service(self.outsider)._work_tasks()['tasks'], [])
        with self.assertRaises(AccessError):
            self.service()._work_tasks(company_id=self.foreign_company.id)

    def test_detail_foreign_actual_row_company_and_no_manager_bypass(self):
        task = self.create_task()
        with self.assertRaises(AccessError):
            self.service()._work_task_detail(task['id'], self.other.id)
        with self.assertRaises(AccessError):
            self.service(self.outsider)._work_task_detail(task['id'], self.company.id)
        self.assertEqual(self.service(self.assignee)._work_task_detail(
            task['id'], self.company.id)['task']['id'], task['id'])

    def test_direct_done_canonical_completion_and_terminal_uuid_replay(self):
        task = self.create_task()
        self.assertEqual(task['origin_api'], 'work_tasks_v1')
        self.assertEqual(task['allowed_actions'], ['cancel', 'reassign'])
        payload = self.transition_payload(task, reason='Replaced the fan')
        result = self.service(self.assignee)._work_task_transition(task['id'], payload)
        done = result['task']
        self.assertEqual(done['state'], 'done')
        self.assertEqual(done['completion_note'], 'Replaced the fan')
        self.assertEqual(done['done_by_id'], self.assignee.id)
        self.assertIsNotNone(done['done_at'])
        self.assertEqual(done['allowed_actions'], [])
        replay = self.service(self.assignee)._work_task_transition(task['id'], payload)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['client_uuid'], payload['client_uuid'])
        self.assertEqual(replay['operation_revision'], 2)
        self.assertEqual(replay['task']['done_at'], done['done_at'])
        self.assertEqual(self.env['baseer.bwork.task.event'].sudo().search_count([
            ('task_id', '=', task['id'])]), 1)

    def test_action_ownership_revision_reassign_cancel_and_permission_revocation(self):
        task = self.create_task()
        for user, action in ((self.creator, 'done'), (self.assignee, 'cancel'),
                             (self.assignee, 'reassign'), (self.outsider, 'done')):
            with self.assertRaises(AccessError):
                self.service(user)._work_task_transition(task['id'], self.transition_payload(
                    task, action, assignee_id=self.replacement.id if action == 'reassign' else None))
        changed = self.service()._work_task_transition(task['id'], self.transition_payload(
            task, 'reassign', assignee_id=self.replacement.id))['task']
        self.assertEqual(changed['assignee_id'], self.replacement.id)
        with self.assertRaises(AccessError):
            self.service(self.assignee)._work_task_detail(task['id'], self.company.id)
        with self.assertRaises(ProtocolError):
            self.service()._work_task_transition(task['id'], self.transition_payload(task, 'cancel'))
        self.replacement.sudo().write({'bwork_task_manage': False})
        with self.assertRaises(AccessError):
            self.service(self.replacement)._work_task_transition(task['id'], self.transition_payload(changed))
        self.assertEqual(self.service()._work_task_transition(task['id'], self.transition_payload(
            changed, 'cancel'))['task']['state'], 'cancelled')

    def test_assignee_effective_rights_before_page_and_rechecked_at_write(self):
        self.assignee.sudo().write({'bwork_task_view': False})
        candidates = self.service()._work_task_assignees(self.company.id)['assignees']
        self.assertNotIn(self.assignee.id, [row['id'] for row in candidates])
        with self.assertRaises(AccessError):
            self.create_task()
        self.assignee.sudo().write({'bwork_task_view': True, 'bwork_task_manage': False})
        with self.assertRaises(AccessError):
            self.create_task()
        with self.assertRaises(AccessError):
            self.create_task(assignee_id=self.foreign.id)

    def test_assignee_pages_ascending_filtered_before_limit(self):
        for index in range(52):
            self._user('Paged-%02d' % index, self.company)
        self._user('Paged-no-rights', self.company, bwork_task_manage=False)
        first = self.service()._work_task_assignees(self.company.id, 'Paged-')
        self.assertEqual(len(first['assignees']), 50)
        self.assertEqual(first['next_after_id'], first['assignees'][-1]['id'])
        second = self.service()._work_task_assignees(self.company.id, 'Paged-', first['next_after_id'])
        self.assertEqual(len(second['assignees']), 2)
        self.assertIsNone(second['next_after_id'])
        self.assertTrue(all(row['id'] > first['next_after_id'] for row in second['assignees']))

    def test_cross_protocol_uuid_conflict_and_legacy_transition_semantics(self):
        payload = self.create_payload()
        created = self.service()._work_task_create(payload)
        self.assertTrue(self.service()._work_task_create(payload)['replayed'])
        legacy = {key: value for key, value in payload.items()
                  if key not in ('work_tasks_version', 'reminder_at')}
        with self.assertRaises(ProtocolError):
            self.service()._v2_task_create(legacy)
        transition = {key: value for key, value in self.transition_payload(created['task']).items()
                      if key not in ('work_tasks_version', 'company_id')}
        with self.assertRaises(ProtocolError):
            self.service(self.assignee)._v2_task_transition(created['task']['id'], transition)
        legacy['client_uuid'] = str(uuid4())
        old = self.service()._v2_task_create(legacy)['task']
        old_dto = self.service()._work_task_detail(old['id'], self.company.id)['task']
        self.assertEqual(old_dto['origin_api'], 'tasks_v2')
        self.assertIsNone(old_dto['done_by_id'])
        self.assertEqual(old_dto['completion_note'], '')

    def test_transition_cross_protocol_uuid_rejected(self):
        task = self.create_task()
        payload = self.transition_payload(task, 'start')
        self.service(self.assignee)._work_task_transition(task['id'], payload)
        old = {key: value for key, value in payload.items()
               if key not in ('work_tasks_version', 'company_id')}
        with self.assertRaises(ProtocolError):
            self.service(self.assignee)._v2_task_transition(task['id'], old)

    def reminder_task(self, **changes):
        now = fields.Datetime.now()
        changes.update(due_at=(now + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                       reminder_at=(now - timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ'))
        return self.create_task(**changes)

    def device(self, user):
        return self.env['baseer.bwork.push.device']._register_verified(
            user, str(uuid4()), 'test-task-token-' + uuid4().hex, _PUSH_TOKEN)

    def test_reminder_atomic_marker_once_no_device_and_visible_due(self):
        task = self.reminder_task()
        self.assertTrue(task['reminder_due'])
        self.assertEqual(self.env['baseer.bwork.task']._cron_work_task_reminders(), 1)
        self.assertEqual(self.env['baseer.bwork.task']._cron_work_task_reminders(), 0)
        detail = self.service()._work_task_detail(task['id'], self.company.id)['task']
        self.assertIsNotNone(detail['reminder_emitted_at'])
        self.assertTrue(detail['reminder_due'])
        self.assertEqual(detail['revision'], 1)

    def test_reminder_rollback_reverts_hint_and_marker(self):
        task = self.reminder_task()
        before = self.env['baseer.bwork.change'].sudo().search_count([('task_id', '=', task['id'])])
        with self.assertRaises(RuntimeError):
            with self.env.cr.savepoint():
                self.env['baseer.bwork.task']._cron_work_task_reminders()
                raise RuntimeError('test transaction rollback')
        record = self.env['baseer.bwork.task'].sudo().browse(task['id'])
        self.assertFalse(record.reminder_emitted_at)
        self.assertEqual(self.env['baseer.bwork.change'].sudo().search_count([
            ('task_id', '=', task['id'])]), before)
        self.assertEqual(self.env['baseer.bwork.task']._cron_work_task_reminders(), 1)

    def test_reminder_reassignment_before_emit_and_delivery_revocation(self):
        self.device(self.assignee)
        self.device(self.replacement)
        task = self.reminder_task()
        changed = self.service()._work_task_transition(task['id'], self.transition_payload(
            task, 'reassign', assignee_id=self.replacement.id))['task']
        self.env['baseer.bwork.task']._cron_work_task_reminders()
        events = self.env['baseer.bwork.push.event'].sudo().search([
            ('task_id', '=', task['id']), ('event_kind', '=', 'reminder')])
        self.assertEqual(events.mapped('recipient_id').ids, [self.replacement.id])
        self.assertTrue(events._event_recipient_still_allowed(events))
        self.replacement.sudo().write({'bwork_task_manage': False})
        self.assertFalse(events._event_recipient_still_allowed(events))
        self.replacement.sudo().write({'bwork_task_manage': True})
        self.service()._work_task_transition(task['id'], self.transition_payload(
            changed, 'reassign', assignee_id=self.assignee.id))
        self.assertFalse(events._event_recipient_still_allowed(events))
        self.assertEqual(self.env['baseer.bwork.task']._cron_work_task_reminders(), 0)

    def test_reminder_terminal_or_ineligible_not_scheduled(self):
        task = self.reminder_task()
        self.service(self.assignee)._work_task_transition(task['id'], self.transition_payload(task))
        other = self.reminder_task()
        self.assignee.sudo().write({'bwork_task_manage': False})
        self.assertEqual(self.env['baseer.bwork.task']._cron_work_task_reminders(), 0)
        self.assertFalse(self.env['baseer.bwork.task'].sudo().browse(other['id']).reminder_emitted_at)

    def test_room_member_former_assignee_cannot_receive_old_reminder(self):
        admin = self.env.ref('base.user_admin')
        admin.sudo().write({'group_ids': [Command.link(self.env.ref('baseer_bwork.group_bwork_manager').id)]})
        room = self.env['baseer.bwork.room'].with_user(admin).with_company(self.company).create({
            'name': 'Work task reminder room', 'company_id': self.company.id})
        for user in (self.creator, self.assignee, self.replacement):
            self.env['baseer.bwork.membership'].with_user(admin).with_company(self.company).create({
                'room_id': room.id, 'user_id': user.id})
        self.device(self.assignee)
        modern = self.create_payload()
        legacy = {key: value for key, value in modern.items()
                  if key not in ('work_tasks_version', 'reminder_at')}
        legacy['room_id'] = room.id
        task = self.service()._v2_task_create(legacy)['task']
        record = self.env['baseer.bwork.task'].sudo().browse(task['id'])
        record._write_verified({'reminder_at': fields.Datetime.now() - timedelta(minutes=1)},
                               _TASK_SERVICE_TOKEN)
        self.env['baseer.bwork.task']._cron_work_task_reminders()
        event = self.env['baseer.bwork.push.event'].sudo().search([
            ('task_id', '=', task['id']), ('event_kind', '=', 'reminder')], limit=1)
        self.assertTrue(event._event_recipient_still_allowed(event))
        self.service()._work_task_transition(task['id'], self.transition_payload(
            task, 'reassign', assignee_id=self.replacement.id))
        self.assertTrue(self.service()._task_member(room.id, self.assignee.id))
        self.assertFalse(event._event_recipient_still_allowed(event))

    def test_ineligible_old_reminders_do_not_starve_eligible_tail(self):
        for _index in range(51):
            self.reminder_task()
        self.assignee.sudo().write({'bwork_task_view': False})
        eligible = self.reminder_task(assignee_id=self.replacement.id)
        self.assertEqual(self.env['baseer.bwork.task']._cron_work_task_reminders(), 1)
        self.assertTrue(self.env['baseer.bwork.task'].sudo().browse(eligible['id']).reminder_emitted_at)

@tagged('post_install', '-at_install', 'baseer_bwork', 'bwork_tasks')
class BWorkTaskHttpCase(HttpCase):
    def test_modern_routes_exact_contract_csrf_company_and_task_only(self):
        password = 'isolated-test-' + uuid4().hex
        user = self.env['res.users'].with_context(no_reset_password=True).create(dict(
            name='Modern task HTTP', login='modern-task-' + uuid4().hex, password=password,
            company_id=self.env.company.id, company_ids=[Command.set(self.env.company.ids)],
            group_ids=[Command.set([self.env.ref('base.group_user').id])],
            bwork_chat_view=False, bwork_task_view=True, bwork_task_manage=True))
        self.authenticate(user.login, password)
        bootstrap = self.url_open('/bwork/api/v2/bootstrap').json()
        csrf = bootstrap['csrf_token']
        self.assertFalse(bootstrap['permissions']['chat_view'])
        self.assertEqual(bootstrap['capabilities']['work_tasks_version'], 1)
        root = '/bwork/api/v2/work-tasks'
        self.assertEqual(self.url_open(root + '/options').json()['default_company_id'], self.env.company.id)
        self.assertEqual(self.url_open(root + '/options?x=1').status_code, 400)
        self.assertEqual(self.url_open(root + '/assignees').status_code, 400)
        payload = dict(api_version=2, work_tasks_version=1, company_id=self.env.company.id,
            room_id=None, client_uuid=str(uuid4()), title='HTTP modern task', description='',
            due_at=None, reminder_at=None, assignee_id=user.id)
        result = self.url_open(root, data={'csrf_token': csrf, 'payload': json.dumps(payload)})
        self.assertEqual(result.status_code, 200)
        task = result.json()['task']
        self.assertEqual(self.url_open(root + '/%s' % task['id']).status_code, 400)
        self.assertEqual(self.url_open(root + '/%s?company_id=%s' % (
            task['id'], self.env.company.id)).status_code, 200)
        self.assertNotEqual(self.url_open(root, data={'payload': json.dumps(payload)}).status_code, 200)
        self.assertEqual(self.url_open(root + '?view=mine&view=created').status_code, 400)
        transition = dict(api_version=2, work_tasks_version=1, company_id=self.env.company.id,
            client_uuid=str(uuid4()), expected_revision=1, action='done', assignee_id=None, reason='Fixed')
        response = self.url_open(root + '/%s/transition' % task['id'],
            data={'csrf_token': csrf, 'payload': json.dumps(transition)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['task']['completion_note'], 'Fixed')
        replay = self.url_open(root + '/%s/transition' % task['id'],
            data={'csrf_token': csrf, 'payload': json.dumps(transition)})
        self.assertTrue(replay.json()['replayed'])
