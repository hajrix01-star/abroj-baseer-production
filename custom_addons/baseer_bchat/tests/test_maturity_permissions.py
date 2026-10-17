"""C03 real ORM permission, recovery, receipt and migration journeys."""
from datetime import datetime
import hashlib
import importlib.util
import io
from itertools import product
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image
from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..contracts import ProtocolError
from ..models.mobile_upload_grant import _MOBILE_UPLOAD_GRANT_TOKEN


@tagged('post_install', '-at_install', 'baseer_bchat', 'baseer_bchat_maturity')
class BChatMaturityPermissionsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref('base.user_admin')
        cls.company = cls.admin.company_id
        cls.admin.write({'group_ids': [Command.link(cls.env.ref('baseer_bchat.group_bchat_manager').id)]})
        cls.owner = cls._user('owner')
        cls.reader = cls._user('reader')
        cls.other = cls._user('other')

    @classmethod
    def _user(cls, name, **extra):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat maturity %s' % name, 'login': 'bchat-maturity-%s' % uuid4().hex,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])], **extra,
        })

    def _service(self, user):
        return self.env['baseer.bchat.service'].with_user(user)

    def _group(self):
        created = self._service(self.owner)._v2_group_create({
            'api_version': 2, 'company_id': self.company.id, 'name': 'Maturity group',
            'client_uuid': str(uuid4()), 'member_user_ids': [self.reader.id, self.other.id],
        })
        return self.env['baseer.bchat.room'].sudo().browse(created['room_id'])

    def _send(self, room):
        member = self._service(self.owner)._v2_current_member(room)
        return self._service(self.owner)._v2_send(room.id, {
            'api_version': 2, 'membership_id': member.id,
            'client_uuid': str(uuid4()), 'text': 'Synthetic maturity message',
        })['message_id']

    def _own_message(self, room, ident):
        rows = self._service(self.owner)._v2_history(room.id)['messages']
        return next(row for row in rows if row['id'] == ident)

    def test_create_requires_an_effective_creator_admin(self):
        self.owner.write({'bchat_group_manage': False})
        self.assertFalse(self._service(self.owner)._v2_bootstrap()['permissions']['group_create'])
        count = self.env['baseer.bchat.room'].sudo().search_count([])
        with self.assertRaises(AccessError):
            self._group()
        self.assertEqual(self.env['baseer.bchat.room'].sudo().search_count([]), count)

    def test_last_effective_admin_ignores_disabled_management_grants(self):
        room = self._group()
        self._service(self.owner)._v2_group_change(room.id, {
            'api_version': 2, 'action': 'promote_admin', 'user_id': self.reader.id})
        self.reader.write({'bchat_group_manage': False})
        with self.assertRaises(ProtocolError) as denied:
            self._service(self.owner)._v2_group_change(room.id, {
                'api_version': 2, 'action': 'leave'})
        self.assertEqual(denied.exception.code, 'last_admin')
        with self.assertRaises(ProtocolError) as ineligible:
            self._service(self.owner)._v2_group_change(room.id, {
                'api_version': 2, 'action': 'promote_admin', 'user_id': self.reader.id})
        self.assertEqual(ineligible.exception.code, 'admin_ineligible')

    def test_offboarding_allows_explicit_recovery_without_content_access(self):
        room = self._group()
        self._send(room)
        self.assertFalse(room.admin_recovery_required)
        self.owner.write({'active': False})
        self.assertTrue(room.admin_recovery_required)
        service = self._service(self.admin)
        with self.assertRaises(AccessError):
            service._v2_history(room.id)
        with self.assertRaises(AccessError):
            service._v2_group_detail(room.id)
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.group.admin.recovery'].with_user(self.reader).create({
                'room_id': room.id, 'user_id': self.reader.id})
        wizard = self.env['baseer.bchat.group.admin.recovery'].with_user(self.admin).create({
            'room_id': room.id, 'user_id': self.reader.id})
        wizard.action_recover()
        self.assertFalse(room.admin_recovery_required)
        self.assertTrue(self._service(self.reader)._v2_group_detail(room.id)['can_manage'])
        self.assertFalse(self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room.id), ('user_id', '=', self.admin.id), ('active', '=', True)]))
        with self.assertRaises(AccessError):
            service._v2_history(room.id)

    def test_company_revocation_marks_recovery_without_blocking_hr_change(self):
        room = self._group()
        second = self.env['res.company'].create({'name': 'Maturity second company'})
        self.owner.write({'company_id': second.id, 'company_ids': [Command.set(second.ids)]})
        self.assertTrue(room.admin_recovery_required)
        with self.assertRaises(AccessError):
            self._service(self.owner)._v2_group_change(room.id, {
                'api_version': 2, 'action': 'rename', 'name': 'Unavailable'})

    def test_revoked_receipts_are_excluded_without_fabricating_read_dates(self):
        room = self._group()
        ident = self._send(room)
        genuine_read = datetime(2026, 10, 1, 9, 30)
        with patch('odoo.addons.baseer_bchat.models.v2_service.fields.Datetime.now',
                   return_value=genuine_read):
            self._service(self.reader)._v2_receipt_ack(room.id, ident, 'read')
        receipt = self.env['baseer.bchat.message.receipt'].sudo().search([
            ('message_id', '=', ident), ('recipient_user_id', '=', self.other.id)])
        self.other.write({'bchat_chat_view': False})
        self.assertEqual(receipt._eligibility_exclusion_reason(), 'chat_revoked')
        row = self._own_message(room, ident)
        self.assertEqual(row['delivery_state'], 'read')
        self.assertEqual(row['read_at'], '2026-10-01 09:30:00')
        self.assertFalse(receipt.read_at)
        self.assertFalse(receipt.delivered_at)
        self.other.write({'bchat_chat_view': True})
        self.assertEqual(self._own_message(room, ident)['delivery_state'], 'sent')
        self.assertFalse(receipt.read_at)

    def test_zero_eligible_receipts_never_means_everybody_read(self):
        room = self._group()
        ident = self._send(room)
        self.reader.write({'bchat_chat_view': False})
        self.other.write({'active': False})
        row = self._own_message(room, ident)
        self.assertEqual(row['delivery_state'], 'sent')
        self.assertIsNone(row['read_at'])
        next_id = self._send(room)
        self.assertFalse(self.env['baseer.bchat.message.receipt'].sudo().search([
            ('message_id', '=', next_id)]))

    def test_receipt_reasons_cover_company_and_account_revocation(self):
        room = self._group()
        ident = self._send(room)
        receipt = self.env['baseer.bchat.message.receipt'].sudo().search([
            ('message_id', '=', ident), ('recipient_user_id', '=', self.reader.id)])
        second = self.env['res.company'].create({'name': 'Receipt other company'})
        self.reader.write({'company_id': second.id, 'company_ids': [Command.set(second.ids)]})
        self.assertEqual(receipt._eligibility_exclusion_reason(), 'company_revoked')
        self.reader.write({'active': False})
        self.assertEqual(receipt._eligibility_exclusion_reason(), 'account_inactive')
        self.assertFalse(receipt.read_at)
        self.assertFalse(receipt.delivered_at)

    def test_preview_only_user_gets_no_original_or_upload(self):
        room = self._group()
        stream = io.BytesIO()
        Image.new('RGB', (10, 10), '#123456').save(stream, format='PNG')
        raw = stream.getvalue()
        owner = self._service(self.owner)
        member = owner._v2_current_member(room)
        metadata = {'api_version': 2, 'membership_id': member.id,
                    'upload_uuid': str(uuid4()), 'kind': 'image', 'mime': 'image/png',
                    'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'name': 'fixture.png'}
        media = owner._v2_upload(room.id, metadata, raw)
        owner._v2_send(room.id, {'api_version': 2, 'membership_id': member.id,
                               'client_uuid': str(uuid4()), 'text': '', 'media_id': media['media_id']})
        self.reader.write({'bchat_media': False, 'bchat_media_view': True,
                           'bchat_media_download': False})
        reader = self._service(self.reader)
        rights = reader._v2_bootstrap()['permissions']
        self.assertEqual(rights['version'], 1)
        self.assertTrue(rights['media_view'])
        self.assertFalse(rights['media_upload'])
        self.assertFalse(rights['media_download'])
        self.assertFalse(rights['media'])  # Conservative v87 ability.
        self.assertTrue(reader._v2_media_content(media['media_id'], thumbnail=True)[0])
        with self.assertRaises(AccessError):
            reader._v2_media_content(media['media_id'])
        with self.assertRaises(AccessError):
            reader._v2_upload_scope(room.id, metadata)
        self.reader.write({'bchat_media_download': True})
        self.assertEqual(reader._v2_media_content(media['media_id'])[0], raw)
        self.reader.write({'bchat_media_view': False})
        with self.assertRaises(AccessError):
            reader._v2_media_content(media['media_id'], thumbnail=True)
        with self.assertRaises(AccessError):
            reader._v2_media_content(media['media_id'])

    def test_media_migration_preserves_old_denials_and_does_not_repeat(self):
        denied = self._user('legacy-denied', bchat_media=False)
        granted = self._user('legacy-granted')
        self.env.cr.execute('''
            UPDATE res_users SET bchat_media_rights_migrated = FALSE,
                                 bchat_media_view = TRUE, bchat_media_download = TRUE
            WHERE id = ANY(%s)
        ''', [[denied.id, granted.id]])
        path = Path(__file__).resolve().parents[1] / 'migrations' / '19.0.0.4.15' / 'post-migrate.py'
        spec = importlib.util.spec_from_file_location('bchat_maturity_migration', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.migrate(self.env.cr, '19.0.0.4.14')
        (denied | granted).invalidate_recordset()
        self.assertFalse(denied.bchat_media_view)
        self.assertFalse(denied.bchat_media_download)
        self.assertTrue(granted.bchat_media_view)
        self.assertTrue(granted.bchat_media_download)
        denied.write({'bchat_media_view': True})
        granted.write({'bchat_media_download': False})
        migration.migrate(self.env.cr, '19.0.0.4.14')
        (denied | granted).invalidate_recordset()
        self.assertTrue(denied.bchat_media_view)
        self.assertFalse(granted.bchat_media_download)

    def test_media_permission_matrix_has_no_implicit_escalation(self):
        service = self._service(self.reader)
        for view, upload, download in product((False, True), repeat=3):
            with self.subTest(view=view, upload=upload, download=download):
                self.reader.write({'bchat_media_view': view, 'bchat_media': upload,
                                   'bchat_media_download': download})
                rights = service._v2_bootstrap()['permissions']
                expected = {'view': view, 'upload': view and upload,
                            'download': view and download}
                for operation, allowed in expected.items():
                    self.assertEqual(rights['media_' + operation], allowed)
                    if allowed:
                        service._require_media_right(operation)
                    else:
                        with self.assertRaises(AccessError):
                            service._require_media_right(operation)
                self.assertEqual(rights['media'], view and upload and download)

    def test_native_grant_does_not_survive_upload_permission_revocation(self):
        room = self._group()
        service = self._service(self.owner)
        member = service._v2_current_member(room)
        raw = b'Synthetic UTF-8 upload fixture'
        metadata = {'api_version': 2, 'membership_id': member.id,
                    'upload_uuid': str(uuid4()), 'kind': 'file', 'mime': 'text/plain',
                    'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'name': 'fixture.txt'}
        issued = service._v2_issue_mobile_upload_grant(room.id, metadata)
        grant = self.env['baseer.bchat.mobile.upload.grant'].sudo().search([
            ('grant_id', '=', issued['grant_id'])])
        # Simulate the already-claimed native body inside this isolated test
        # transaction; a real claim uses a separate committed cursor.
        grant._write_verified({'state': 'uploading', 'upload_started_at': fields.Datetime.now()},
                              _MOBILE_UPLOAD_GRANT_TOKEN)
        snapshot = grant._snapshot()
        self.owner.write({'bchat_media': False})
        before = self.env['baseer.bchat.media'].sudo().search_count([])
        with self.assertRaises(AccessError):
            service._v2_mobile_upload_from_capability(snapshot, raw)
        self.assertEqual(self.env['baseer.bchat.media'].sudo().search_count([]), before)

    def test_permission_change_publishes_room_hint_for_peer_refresh(self):
        room = self._group()
        self._send(room)
        before = self._service(self.owner)._v2_changes()['watermark']
        self.reader.write({'bchat_chat_view': False})
        hints = self._service(self.owner)._v2_changes(after=before)['changes']
        self.assertTrue(any(row['kind'] == 'room' and row['room_id'] == room.id for row in hints))

    def test_all_peer_cursors_are_reserved_before_first_permission_hint(self):
        self._group()
        service_class = type(self.env['baseer.bchat.service'])
        reserve = service_class._change_lock_recipients
        publish = service_class._change_publish
        calls = []
        def reserve_real(service, user_ids):
            calls.append(('reserve', set(user_ids)))
            return reserve(service, user_ids)
        def publish_real(service, user_ids, kind, **values):
            calls.append((kind, set(user_ids)))
            return publish(service, user_ids, kind, **values)
        with patch.object(service_class, '_change_lock_recipients', reserve_real), \
                patch.object(service_class, '_change_publish', publish_real):
            self.reader.write({'bchat_chat_view': False})
        self.assertEqual(calls[0], ('reserve', {self.owner.id, self.reader.id, self.other.id}))
        self.assertEqual(calls[1], ('permissions', {self.reader.id}))
        self.assertEqual(calls[2], ('room', {self.owner.id, self.reader.id, self.other.id}))

    def _assert_union_reserved_before_hints(self, action, expected):
        """Observe real ORM calls; this is ordering coverage, not a race proof."""
        service_class = type(self.env['baseer.bchat.service'])
        reserve = service_class._change_lock_recipients
        publish = service_class._change_publish
        calls = []
        def reserve_real(service, user_ids):
            calls.append(('reserve', set(user_ids)))
            return reserve(service, user_ids)
        def publish_real(service, user_ids, kind, **values):
            calls.append((kind, set(user_ids)))
            return publish(service, user_ids, kind, **values)
        with patch.object(service_class, '_change_lock_recipients', reserve_real), \
                patch.object(service_class, '_change_publish', publish_real):
            action()
        self.assertEqual(calls[0], ('reserve', set(expected)))
        hints = [(kind, recipients) for kind, recipients in calls if kind != 'reserve']
        self.assertTrue(hints)
        self.assertTrue(all(recipients <= set(expected) for _kind, recipients in hints))

    def test_membership_create_reserves_the_whole_batch_before_hints(self):
        rooms = self.env['baseer.bchat.room'].with_user(self.admin).create([
            {'name': 'Batch membership one', 'company_id': self.company.id},
            {'name': 'Batch membership two', 'company_id': self.company.id},
        ])
        self._assert_union_reserved_before_hints(
            lambda: self.env['baseer.bchat.membership'].with_user(self.admin).create([
                {'room_id': rooms[0].id, 'user_id': self.other.id},
                {'room_id': rooms[1].id, 'user_id': self.reader.id},
            ]), [self.other.id, self.reader.id])

    def test_membership_revoke_reserves_all_rooms_and_departing_users(self):
        rooms = self._group() | self._group()
        members = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', 'in', rooms.ids), ('user_id', 'in', [self.reader.id, self.other.id]),
            ('active', '=', True),
        ])
        self._assert_union_reserved_before_hints(
            lambda: members.with_user(self.admin).action_revoke(),
            [self.owner.id, self.reader.id, self.other.id])
        self.assertFalse(any(members.mapped('active')))

    def test_group_remove_and_leave_reserve_departing_and_remaining_peers(self):
        for action in ('remove_member', 'leave'):
            room = self._group()
            actor = self.owner if action == 'remove_member' else self.reader
            payload = {'api_version': 2, 'action': action}
            if action == 'remove_member':
                payload['user_id'] = self.reader.id
            self._assert_union_reserved_before_hints(
                lambda: self._service(actor)._v2_group_change(room.id, payload),
                [self.owner.id, self.reader.id, self.other.id])

    def test_room_change_reserves_all_room_recipient_unions(self):
        rooms = self._group() | self._group()
        self._assert_union_reserved_before_hints(
            lambda: rooms.with_user(self.admin).write({'name': 'Batch room update'}),
            [self.owner.id, self.reader.id, self.other.id])

    def test_task_reassignment_reserves_former_and_new_assignees(self):
        task = self._service(self.other)._v2_task_create({
            'api_version': 2, 'company_id': self.company.id, 'room_id': None,
            'client_uuid': str(uuid4()), 'title': 'Cursor ordering task',
            'description': '', 'due_at': None, 'assignee_id': self.owner.id,
        })['task']
        self._assert_union_reserved_before_hints(
            lambda: self._service(self.other)._v2_task_transition(task['id'], {
                'api_version': 2, 'client_uuid': str(uuid4()), 'expected_revision': 1,
                'action': 'reassign', 'assignee_id': self.reader.id, 'reason': None,
            }), [self.owner.id, self.reader.id, self.other.id])
