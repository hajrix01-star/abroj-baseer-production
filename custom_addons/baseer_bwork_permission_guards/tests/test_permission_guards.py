"""Revocation checks for the notification service."""

from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from odoo.addons.baseer_bchat_notifications.models.event import _NOTIFICATION_TOKEN
from odoo.addons.baseer_bchat_notifications.models.service import BChatNotificationService as BWorkNotificationService


@tagged('post_install', '-at_install', 'baseer_bwork_permission_guards')
class BWorkPermissionGuardsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BWork guard user',
            'login': 'bwork-guard-%s' % uuid4().hex,
            'company_id': cls.env.company.id,
            'company_ids': [Command.set(cls.env.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })

    def _service(self):
        return self.env['baseer.bwork.service'].with_user(self.user)

    def _recipient(self, source, role='room'):
        event = self.env['baseer.bwork.notification.event'].sudo()._create_verified({
            'kind': 'order' if source == 'order' else 'chat' if source == 'message' else 'task',
            'action': 'create', 'source_model': source, 'source_id': 2_000_000_000,
            'source_revision': 1, 'company_id': self.env.company.id,
            'actor_id': self.env.ref('base.user_admin').id,
        }, _NOTIFICATION_TOKEN)
        return self.env['baseer.bwork.notification.recipient'].sudo()._create_verified([{
            'event_id': event.id, 'user_id': self.user.id, 'target_role': role,
        }], _NOTIFICATION_TOKEN)

    def test_chat_revocation_hides_notification_and_message_detail(self):
        recipient = self._recipient('message')
        self.user.write({'bwork_chat_view': False})
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            self._service()._notify_recipient_ref(recipient)
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            self._service()._v2_room_message_detail(2_000_000_000, 2_000_000_000)

    def test_task_revocation_hides_notification(self):
        recipient = self._recipient('task', role='assignee')
        self.user.write({'bwork_task_view': False})
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            self._service()._notify_recipient_ref(recipient)

    def test_representative_uses_chat_permission_not_order_tab_permission(self):
        recipient = self._recipient('order', role='representative')
        self.user.write({'bwork_order_view': True})
        self.user.write({'bwork_order_view': False})
        self.assertFalse(self._service()._order_permissions()['can_view'])
        expected_ref = {'destination': 'representative_order', 'order_id': 42}
        expected_detail = {'api_version': 2, 'order': {'id': 42}}
        with patch.object(BWorkNotificationService, '_notify_recipient_ref',
                          return_value=expected_ref) as upstream:
            self.assertEqual(self._service()._notify_recipient_ref(recipient), expected_ref)
        upstream.assert_called_once()
        with patch.object(BWorkNotificationService, '_v2_order_representative_detail',
                          return_value=expected_detail) as upstream:
            self.assertEqual(self._service()._v2_order_representative_detail(42), expected_detail)
        upstream.assert_called_once()
        self.user.write({'bwork_chat_view': False})
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            self._service()._notify_recipient_ref(recipient)
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            self._service()._v2_order_representative_detail(2_000_000_000)

    def test_room_order_notification_keeps_chat_without_order_right(self):
        recipient = self._recipient('order')
        self.assertFalse(self.user.bwork_order_view)
        expected = {'destination': 'room_message', 'room_id': 17, 'message_id': 42}
        with patch.object(BWorkNotificationService, '_notify_recipient_ref',
                          return_value=expected) as upstream:
            self.assertEqual(self._service()._notify_recipient_ref(recipient), expected)
        upstream.assert_called_once()
        self.user.write({'bwork_chat_view': False})
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            self._service()._notify_recipient_ref(recipient)
