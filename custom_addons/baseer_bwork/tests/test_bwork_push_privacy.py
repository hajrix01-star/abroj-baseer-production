"""BWork additive push contract, independent of the frozen legacy test count."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..contracts import ProtocolError
from ..models.task import _TASK_SERVICE_TOKEN


@tagged('post_install', '-at_install')
class BWorkPushPrivacyCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.author, cls.reader = [cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Private sender ' + name, 'login': 'bwork-push-' + uuid4().hex,
            # Chat and task wake-up tests explicitly authorize these actors.
            'bwork_chat_view': True, 'bwork_chat_send': True,
            'bwork_task_view': True, 'bwork_task_manage': True,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        }) for name in ('author', 'reader')]
        cls.admin = cls.env.ref('base.user_admin')
        cls.admin.write({'group_ids': [Command.link(cls.env.ref('baseer_bwork.group_bwork_manager').id)]})
        cls.room = cls.env['baseer.bwork.room'].with_user(cls.admin).with_company(cls.company).create({
            'name': 'BWork push room', 'company_id': cls.company.id})
        cls.members = cls.env['baseer.bwork.membership'].with_user(cls.admin).with_company(cls.company)
        cls.author_member = cls.members.create({'room_id': cls.room.id, 'user_id': cls.author.id})
        cls.reader_member = cls.members.create({'room_id': cls.room.id, 'user_id': cls.reader.id})

    def service(self, user=None):
        return self.env['baseer.bwork.service'].with_user(user or self.reader)

    def register(self, client='bwork', installation=None):
        payload = {'api_version': 2, 'installation_id': installation or str(uuid4()), 'fcm_token': 'p' * 64}
        if client is not None:
            payload['client'] = client
        return self.service()._v2_push_register(payload)

    def event(self):
        sent = self.service(self.author)._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.author_member.id,
            'client_uuid': str(uuid4()), 'text': 'PRIVATE CONTENT MUST NOT LEAVE IN BWORK PUSH',
        })
        return self.env['baseer.bwork.push.event'].sudo().search([('message_id', '=', sent['message_id'])], limit=1)

    def outbound(self, event):
        events = self.env['baseer.bwork.push.event']
        with patch.object(type(events), '_fcm_access_token', return_value='isolated-access-token'), patch('requests.post') as post:
            post.return_value.status_code = 200
            events._fcm_send(event, {'project_id': 'isolated-project'})
            self.assertEqual(post.call_count, 1)
            return post.call_args.kwargs['json']['message']

    def test_bwork_registration_ack_sticky_and_no_omission_downgrade(self):
        registration = self.register()
        self.assertEqual(registration['client'], 'bwork')
        self.assertIs(registration['preview_enabled'], False)
        again = self.register(client=None, installation=registration['installation_id'])
        self.assertEqual(again, registration)
        device = self.env['baseer.bwork.push.device'].sudo().search([('account_key', '=', registration['account_key'])])
        self.assertEqual(device.client_kind, 'bwork')
        for client in ('legacy', 'unknown', None, False):
            payload = {'api_version': 2, 'installation_id': str(uuid4()), 'fcm_token': 'q' * 64, 'client': client}
            with self.assertRaises(ProtocolError):
                self.service()._v2_push_register(payload)

    def test_actual_fcm_json_has_no_bwork_content_even_prequeued_legacy_event(self):
        legacy = self.register(client=None)
        self.assertNotIn('client', legacy)
        self.assertNotIn('preview_enabled', legacy)
        event = self.event()
        legacy_body = self.outbound(event)
        self.assertIn('sender_name', legacy_body['data'])
        self.assertIn('message_preview', legacy_body['data'])
        self.register(installation=legacy['installation_id'])
        body = self.outbound(event)
        self.assertEqual(body['data'], {'account_key': legacy['account_key'], 'kind': 'chat', 'event_id': str(event.id)})
        self.assertNotIn('notification', body)
        # Exercise the actual outbound attachment fallback too, not just the
        # native renderer: BWork must not emit message_preview_kind either.
        attachment_event = SimpleNamespace(id=event.id, device_id=event.device_id,
            message_id=SimpleNamespace(author_user_id=self.author, text='', media_id=True))
        self.assertEqual(set(self.outbound(attachment_event)['data']), {'account_key', 'kind', 'event_id'})

    def test_chat_company_ref_is_authorized_and_membership_rechecked(self):
        self.register()
        event = self.event()
        source = self.service()._v2_push_event(event.id)['notification']['source_ref']
        self.assertEqual(source, {'destination': 'room_message', 'company_id': self.company.id,
                                  'room_id': self.room.id, 'message_id': event.message_id.id})
        with self.assertRaises(AccessError):
            self.service(self.author)._v2_push_event(event.id)
        self.reader_member.action_revoke()
        with self.assertRaises(AccessError):
            self.service()._v2_push_event(event.id)

    def test_legacy_modern_and_reminder_refs_open_with_explicit_modern_company(self):
        self.register()
        for modern in (False, True):
            payload = dict(api_version=2, company_id=self.company.id, room_id=None,
                client_uuid=str(uuid4()), title='Scoped task', description='', due_at=None, assignee_id=self.reader.id)
            if modern:
                payload.update(work_tasks_version=1, reminder_at=None)
                task = self.service(self.author)._work_task_create(payload)['task']
            else:
                task = self.service(self.author)._v2_task_create(payload)['task']
            event = self.env['baseer.bwork.push.event'].sudo().search([('task_id', '=', task['id'])], limit=1)
            source = self.service()._v2_push_event(event.id)['notification']['source_ref']
            self.assertEqual(source, {'destination': 'task', 'task_id': task['id'], 'company_id': self.company.id})
            detail = self.service()._work_task_detail(source['task_id'], source['company_id'])['task']
            self.assertEqual(detail['id'], task['id'])
            self.assertEqual(detail['origin_api'], 'work_tasks_v1' if modern else 'tasks_v2')
            self.assertEqual(set(self.outbound(event)['data']), {'account_key', 'kind', 'event_id'})
            if modern:
                record = self.env['baseer.bwork.task'].browse(task['id'])
                record._write_verified({'reminder_at': fields.Datetime.now() - timedelta(minutes=1)}, _TASK_SERVICE_TOKEN)
                self.env['baseer.bwork.task']._cron_work_task_reminders()
                reminder = self.env['baseer.bwork.push.event'].sudo().search([
                    ('task_id', '=', task['id']), ('event_kind', '=', 'reminder')], limit=1)
                self.assertTrue(reminder)
                ref = self.service()._v2_push_event(reminder.id)['notification']['source_ref']
                self.assertEqual(self.service()._work_task_detail(ref['task_id'], ref['company_id'])['task']['id'], task['id'])
                self.assertEqual(set(self.outbound(reminder)['data']), {'account_key', 'kind', 'event_id'})

    def test_task_company_revocation_rejects_event_without_guessing_scope(self):
        self.register()
        task = self.service(self.author)._work_task_create(dict(api_version=2, work_tasks_version=1,
            company_id=self.company.id, room_id=None, client_uuid=str(uuid4()), title='Private task',
            description='', due_at=None, reminder_at=None, assignee_id=self.reader.id))['task']
        event = self.env['baseer.bwork.push.event'].sudo().search([('task_id', '=', task['id'])], limit=1)
        other = self.env['res.company'].create({'name': 'Push revoked company'})
        self.reader.sudo().write({'company_ids': [Command.set(other.ids)], 'company_id': other.id})
        with self.assertRaises(AccessError):
            self.service()._v2_push_event(event.id)
