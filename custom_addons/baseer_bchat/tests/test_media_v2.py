"""Media service checks; run only on an isolated Odoo test database."""
import base64
import hashlib
import io
import json
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch

from PIL import Image

from odoo import SUPERUSER_ID, Command, fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..contracts import ProtocolError
from ..models import media_service as media_service_module
from ..models.media import _MEDIA_TOKEN


@tagged('post_install', '-at_install', 'baseer_bchat_media')
class BChatMediaCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.room_admin = cls.env.ref('base.user_admin')
        cls.room_admin.sudo().write({
            'group_ids': [Command.link(cls.env.ref('baseer_bchat.group_bchat_manager').id)],
        })
        cls.manager = cls._user('manager', 'baseer_bchat.group_bchat_manager')
        cls.member = cls._user('member', 'base.group_user')
        cls.room = cls.env['baseer.bchat.room'].with_user(cls.room_admin).with_company(cls.company).create({
            'name': 'Media test room', 'company_id': cls.company.id,
        })
        cls.manager_epoch = cls._join(cls.manager)
        cls.member_epoch = cls._join(cls.member)

    @classmethod
    def _user(cls, label, group):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat media ' + label,
            'login': 'bchat-media-%s-%s' % (label, uuid4().hex),
            'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref(group).id])],
        })

    @classmethod
    def _join(cls, user):
        return cls.env['baseer.bchat.membership'].with_user(cls.room_admin).with_company(cls.company).create({
            'room_id': cls.room.id, 'user_id': user.id,
        })

    @staticmethod
    def _image():
        image = Image.new('RGB', (30, 20), (25, 80, 140))
        output = io.BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()

    def _metadata(self, raw, *, kind='image', mime='image/png', uuid=None, epoch=None, name=None):
        return {
            'api_version': 2,
            'membership_id': (epoch or self.manager_epoch).id,
            'upload_uuid': uuid or str(uuid4()),
            'kind': kind, 'mime': mime, 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'name': name or ('sample.png' if kind == 'image' else 'sample.pdf'),
        }

    def test_image_upload_replay_history_read_and_revocation(self):
        raw = self._image()
        metadata = self._metadata(raw)
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        staged = service._v2_upload(self.room.id, metadata, raw)
        self.assertEqual(staged, service._v2_upload(self.room.id, metadata, raw))
        media = self.env['baseer.bchat.media'].sudo().browse(staged['media_id'])
        self.assertFalse(self.env['baseer.bchat.media'].with_user(self.manager).has_access('read'))
        with self.assertRaises(AccessError):
            self.env['ir.attachment'].with_user(self.manager).browse(
                media.attachment_id.id).check_access('read')
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.media'].with_user(self.manager).create({'room_id': self.room.id})
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.member)._v2_media_content(media.id)

        payload = {
            'api_version': 2, 'membership_id': self.manager_epoch.id,
            'client_uuid': str(uuid4()), 'text': '', 'media_id': media.id,
        }
        sent = service._v2_send(self.room.id, payload)
        self.assertEqual(sent, service._v2_send(self.room.id, payload))
        self.assertEqual(media.state, 'attached')
        self.assertEqual(media.message_id.id, sent['message_id'])
        history = self.env['baseer.bchat.service'].with_user(self.member)._v2_history(self.room.id)
        self.assertEqual(history['messages'][-1]['media']['id'], media.id)
        self.assertNotIn('attachment_id', history['messages'][-1]['media'])
        self.assertEqual(service._v2_media_content(media.id)[0], raw)
        thumbnail, thumbnail_type, _ = service._v2_media_content(media.id, True)
        self.assertEqual(thumbnail_type, 'image/jpeg')
        self.assertLessEqual(len(thumbnail), 128 * 1024)
        self.member_epoch.with_user(self.room_admin).with_company(self.company).action_revoke()
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.member)._v2_media_content(media.id)
        self._join(self.member)
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.member)._v2_media_content(media.id)

    @staticmethod
    def _camera_jpeg():
        output = io.BytesIO()
        Image.new('RGB', (2400, 1800), (30, 80, 120)).save(output, format='JPEG', quality=95)
        return output.getvalue()

    def test_camera_jpeg_preserves_original_through_send(self):
        raw = self._camera_jpeg()
        metadata = self._metadata(raw, mime='image/jpeg', name='camera.jpg')
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        staged = service._v2_upload(self.room.id, metadata, raw)
        media = self.env['baseer.bchat.media'].sudo().browse(staged['media_id'])
        self.assertEqual(media.attachment_id.file_size, len(raw))
        self.assertEqual(base64.b64decode(media.attachment_id.datas), raw)
        service._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.manager_epoch.id,
            'client_uuid': str(uuid4()), 'text': '', 'media_id': media.id,
        })
        self.assertEqual(service._v2_media_content(media.id)[0], raw)

    def test_upload_replay_repairs_old_resized_camera_copy(self):
        raw = self._camera_jpeg()
        metadata = self._metadata(raw, mime='image/jpeg', name='camera-pending.jpg')
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        staged = service._v2_upload(self.room.id, metadata, raw)
        media = self.env['baseer.bchat.media'].sudo().browse(staged['media_id'])
        media.attachment_id.with_context(image_no_postprocess=False).write({
            'datas': base64.b64encode(raw),
        })
        self.assertNotEqual(base64.b64decode(media.attachment_id.datas), raw)
        self.assertEqual(staged, service._v2_upload(self.room.id, metadata, raw))
        self.assertEqual(base64.b64decode(media.attachment_id.datas), raw)
        service._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.manager_epoch.id,
            'client_uuid': str(uuid4()), 'text': '', 'media_id': media.id,
        })
        self.assertEqual(service._v2_media_content(media.id)[0], raw)

    def test_media_uuid_collision_and_cross_epoch_rejected(self):
        raw = self._image()
        first = self._metadata(raw)
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        media_id = service._v2_upload(self.room.id, first, raw)['media_id']
        changed = {**first, 'name': 'changed.png'}
        with self.assertRaises(ProtocolError) as collision:
            service._v2_upload(self.room.id, changed, raw)
        self.assertEqual(collision.exception.status, 409)
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.member)._v2_send(self.room.id, {
                'api_version': 2, 'membership_id': self.member_epoch.id,
                'client_uuid': str(uuid4()), 'text': '', 'media_id': media_id,
            })
        with self.assertRaises(ProtocolError):
            service._v2_send(self.room.id, {
                'api_version': 2, 'membership_id': self.manager_epoch.id,
                'client_uuid': str(uuid4()), 'text': '', 'media_id': True,
            })

    def test_pdf_opaque_and_invalid_audio_fail_closed(self):
        raw = b'%PDF-1.7\n1 0 obj <</Type/Catalog>> endobj\n%%EOF\n'
        metadata = self._metadata(raw, kind='file', mime='application/pdf')
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        media_id = service._v2_upload(self.room.id, metadata, raw)['media_id']
        service._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.manager_epoch.id,
            'client_uuid': str(uuid4()), 'text': 'PDF', 'media_id': media_id,
        })
        content, mime, _ = service._v2_media_content(media_id)
        self.assertEqual((content, mime), (raw, 'application/pdf'))
        with self.assertRaises(AccessError):
            service._v2_media_content(media_id, True)
        audio = {**metadata, 'kind': 'audio', 'mime': 'audio/mp4', 'name': 'voice.m4a'}
        with self.assertRaises(ProtocolError) as unsupported:
            service._v2_upload(self.room.id, audio, raw)
        self.assertEqual(unsupported.exception.status, 415)

    def test_audio_and_plain_file_upload_send_read_and_classification_guard(self):
        def box(kind, body):
            return (len(body) + 8).to_bytes(4, 'big') + kind + body
        audio = (box(b'ftyp', b'M4A \x00\x00\x00\x00isom') +
                 box(b'mdat', b'\x00\x01') + box(b'moov', b'sounmp4a'))
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        for raw, kind, mime, name in (
            (audio, 'audio', 'audio/mp4', 'voice.m4a'),
            ('مذكرة\n'.encode('utf-8'), 'file', 'text/plain', 'note.txt'),
        ):
            with self.subTest(kind=kind):
                media_id = service._v2_upload(self.room.id, self._metadata(
                    raw, kind=kind, mime=mime, name=name), raw)['media_id']
                self.room.with_user(self.manager).with_company(self.company).write({
                    'invoice_policy': 'select_on_upload',
                })
                payload = {
                    'api_version': 2, 'membership_id': self.manager_epoch.id,
                    'client_uuid': str(uuid4()), 'text': '', 'media_id': media_id,
                    'document_type': 'invoice',
                    'policy_version': self.room.invoice_policy_version,
                }
                with self.assertRaises(ProtocolError) as rejected:
                    service._v2_send(self.room.id, payload)
                self.assertEqual(rejected.exception.status, 415)
                sent = service._v2_send(self.room.id, {
                    **payload, 'client_uuid': str(uuid4()), 'document_type': 'other',
                })
                self.assertEqual(service._v2_media_content(media_id), (raw, mime, name))
                self.assertEqual(self.env['baseer.bchat.media'].sudo().browse(media_id).document_type, 'other')
                self.assertEqual(service._v2_history(self.room.id)['messages'][-1]['media']['kind'], kind)
                self.assertEqual(sent['media_id'], media_id)

    def test_cancel_staged_upload_is_private_idempotent_and_frees_bytes(self):
        raw = self._image()
        metadata = self._metadata(raw)
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        media_id = service._v2_upload(self.room.id, metadata, raw)['media_id']
        media = self.env['baseer.bchat.media'].sudo().browse(media_id)
        attachment_ids = [media.attachment_id.id, media.thumbnail_attachment_id.id]
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.member)._v2_cancel_upload(media_id)
        self.assertEqual(service._v2_cancel_upload(media_id)['state'], 'cancelled')
        self.assertEqual(service._v2_cancel_upload(media_id)['state'], 'cancelled')
        self.assertFalse(media.attachment_id)
        self.assertFalse(media.thumbnail_attachment_id)
        self.assertFalse(self.env['ir.attachment'].sudo().browse(attachment_ids).exists())
        with self.assertRaises(ProtocolError) as closed:
            service._v2_upload(self.room.id, metadata, raw)
        self.assertEqual((closed.exception.code, closed.exception.status), ('upload_closed', 409))
        with self.assertRaises(AccessError):
            service._v2_send(self.room.id, {
                'api_version': 2, 'membership_id': self.manager_epoch.id,
                'client_uuid': str(uuid4()), 'text': '', 'media_id': media_id,
            })

    def test_staged_expiry_only_closes_old_unsent_uploads(self):
        raw = self._image()
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        old_metadata = self._metadata(raw)
        old_id = service._v2_upload(self.room.id, old_metadata, raw)['media_id']
        recent_id = service._v2_upload(self.room.id, self._metadata(raw), raw)['media_id']
        old = self.env['baseer.bchat.media'].sudo().browse(old_id)
        old_attachment_id = old.attachment_id.id
        self.env.cr.execute('''
            UPDATE baseer_bchat_media SET create_date = %s WHERE id = %s
        ''', [fields.Datetime.now() - timedelta(hours=25), old_id])
        old.invalidate_recordset(['create_date'])
        with self.assertRaises(AccessError):
            service._v2_expire_staged_uploads()
        cleanup = self.env['baseer.bchat.service'].with_user(SUPERUSER_ID)
        self.assertEqual(cleanup._v2_expire_staged_uploads()['expired_count'], 1)
        self.assertEqual(old.state, 'expired')
        self.assertFalse(self.env['ir.attachment'].sudo().browse(old_attachment_id).exists())
        with self.assertRaises(ProtocolError) as expired:
            service._v2_upload(self.room.id, old_metadata, raw)
        self.assertEqual((expired.exception.code, expired.exception.status), ('upload_expired', 409))
        self.assertEqual(self.env['baseer.bchat.media'].sudo().browse(recent_id).state, 'staged')
        self.assertEqual(cleanup._v2_expire_staged_uploads()['expired_count'], 0)

    def test_cleanup_cron_drains_700_old_but_preserves_701_recent(self):
        cron = self.env.ref('baseer_bchat.cron_expire_staged_media')
        self.assertTrue(cron.active)
        self.assertEqual((cron.interval_number, cron.interval_type), (5, 'minutes'))
        self.assertEqual(cron.user_id.id, SUPERUSER_ID)

        # Synthetic rows keep this capacity fixture quick; real attachment
        # deletion and attached-message protection are covered separately.
        media_model = self.env['baseer.bchat.media'].sudo()
        marker = uuid4().hex[:12]
        old_date = fields.Datetime.now() - timedelta(hours=25)
        self.env.cr.execute('''
            INSERT INTO baseer_bchat_media
                (room_id, company_id, membership_id, author_user_id,
                 upload_uuid, kind, mime, size_bytes, sha256, name,
                 state, document_type, create_uid, create_date, write_uid, write_date)
            SELECT %s, %s, %s, %s, %s || '-' || n::text,
                   'file', 'application/pdf', 1, %s, 'capacity-test.pdf',
                   'staged', 'other', %s,
                   CASE WHEN n <= 700 THEN %s ELSE NOW() END, %s, NOW()
            FROM generate_series(1, 1401) AS n
        ''', [self.room.id, self.company.id, self.manager_epoch.id,
              self.manager.id, marker, 'a' * 64, SUPERUSER_ID,
              old_date, SUPERUSER_ID])

        with patch.object(media_service_module._logger, 'warning') as warning:
            first = media_model.with_user(SUPERUSER_ID)._cron_expire_staged_uploads()
        self.assertEqual(first['expired_count'], 100)
        warning.assert_called_once()
        for batch in range(2, 8):
            with patch.object(media_service_module._logger, 'warning') as warning:
                result = media_model.with_user(SUPERUSER_ID)._cron_expire_staged_uploads()
            self.assertEqual(result['expired_count'], 100)
            if batch < 7:
                warning.assert_called_once()
            else:
                warning.assert_not_called()
        self.env.cr.execute('''
            SELECT state, COUNT(*) FROM baseer_bchat_media
            WHERE upload_uuid LIKE %s GROUP BY state
        ''', [marker + '-%'])
        self.assertEqual(dict(self.env.cr.fetchall()), {'expired': 700, 'staged': 701})

    def test_staged_indexes_exist_and_init_is_idempotent(self):
        # Module upgrade may call init() repeatedly; it must not add copies.
        self.env['baseer.bchat.media'].init()
        self.env.cr.execute('''
            SELECT c.relname, pg_get_indexdef(i.indexrelid),
                   pg_get_expr(i.indpred, i.indrelid), i.indisvalid, i.indisready
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            WHERE i.indrelid = 'baseer_bchat_media'::regclass
              AND c.relname IN (
                'baseer_bchat_media_staged_expiry_idx',
                'baseer_bchat_media_staged_quota_idx'
              )
        ''')
        indexes = {name: (definition, predicate, valid, ready)
                   for name, definition, predicate, valid, ready in self.env.cr.fetchall()}
        self.assertEqual(set(indexes), {
            'baseer_bchat_media_staged_expiry_idx',
            'baseer_bchat_media_staged_quota_idx',
        })
        expiry = indexes['baseer_bchat_media_staged_expiry_idx']
        quota = indexes['baseer_bchat_media_staged_quota_idx']
        self.assertIn('(id, create_date)', expiry[0])
        self.assertIn('(author_user_id) INCLUDE (size_bytes)', quota[0])
        for definition, predicate, valid, ready in (expiry, quota):
            self.assertRegex(predicate, r"\bstate\b.*=\s*'staged'")
            self.assertTrue(valid and ready, definition)

    def test_cleanup_rechecks_expiry_after_room_lock(self):
        raw = self._image()
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        media_id = service._v2_upload(self.room.id, self._metadata(raw), raw)['media_id']
        media = self.env['baseer.bchat.media'].sudo().browse(media_id)
        attachment_id = media.attachment_id.id
        self.env.cr.execute('''
            UPDATE baseer_bchat_media SET create_date = %s WHERE id = %s
        ''', [fields.Datetime.now() - timedelta(hours=25), media_id])
        media.invalidate_recordset(['create_date'])
        room_type = type(self.env['baseer.bchat.room'])
        original_lock = room_type._lock_for_mutation

        def renew_age_after_lock(room_model, room_id):
            original_lock(room_model, room_id)
            self.env.cr.execute('''
                UPDATE baseer_bchat_media SET create_date = %s WHERE id = %s
            ''', [fields.Datetime.now(), media_id])

        with patch.object(room_type, '_lock_for_mutation', renew_age_after_lock):
            result = self.env['baseer.bchat.service'].with_user(
                SUPERUSER_ID)._v2_expire_staged_uploads()
        self.assertEqual(result['expired_count'], 0)
        self.assertEqual(media.state, 'staged')
        self.assertTrue(self.env['ir.attachment'].sudo().browse(attachment_id).exists())

    def test_attached_media_cannot_be_cancelled_or_expired(self):
        raw = self._image()
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        media_id = service._v2_upload(self.room.id, self._metadata(raw), raw)['media_id']
        service._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.manager_epoch.id,
            'client_uuid': str(uuid4()), 'text': '', 'media_id': media_id,
        })
        with self.assertRaises(ProtocolError) as closed:
            service._v2_cancel_upload(media_id)
        self.assertEqual(closed.exception.status, 409)
        self.assertEqual(self.env['baseer.bchat.service'].with_user(SUPERUSER_ID)
                         ._v2_expire_staged_uploads()['expired_count'], 0)
        self.assertEqual(service._v2_media_content(media_id)[0], raw)

    def test_staged_quota_and_attachment_company(self):
        raw = b'%PDF-1.7\n1 0 obj <</Type/Catalog>> endobj\n%%EOF\n'
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        first = self._metadata(raw, kind='file', mime='application/pdf')
        first_id = service._v2_upload(self.room.id, first, raw)['media_id']
        for _ in range(19):
            service._v2_upload(self.room.id,
                               self._metadata(raw, kind='file', mime='application/pdf'), raw)
        with self.assertRaises(ProtocolError) as full:
            service._v2_upload(self.room.id,
                               self._metadata(raw, kind='file', mime='application/pdf'), raw)
        self.assertEqual(full.exception.status, 429)
        self.assertEqual(service._v2_upload(self.room.id, first, raw)['media_id'], first_id)

        second = self.env['res.company'].create({'name': 'BChat media other company'})
        self.manager.sudo().write({'company_ids': [Command.link(second.id)]})
        other_room = self.env['baseer.bchat.room'].with_user(self.manager).with_company(second).create({
            'name': 'Media second company', 'company_id': second.id,
        })
        other_epoch = self.env['baseer.bchat.membership'].with_user(self.manager).with_company(second).create({
            'room_id': other_room.id, 'user_id': self.manager.id,
        })
        # A separate user avoids the deliberate per-account staged quota above.
        other_user = self._user('other-company', 'base.group_user')
        other_user.sudo().write({'company_ids': [Command.link(second.id)]})
        user_epoch = self.env['baseer.bchat.membership'].with_user(self.manager).with_company(second).create({
            'room_id': other_room.id, 'user_id': other_user.id,
        })
        upload = self.env['baseer.bchat.service'].with_user(other_user).with_company(self.company)._v2_upload(
            other_room.id, self._metadata(raw, kind='file', mime='application/pdf', epoch=user_epoch), raw)
        media = self.env['baseer.bchat.media'].sudo().browse(upload['media_id'])
        self.assertEqual(media.company_id, second)
        self.assertEqual(media.attachment_id.company_id, second)
        self.assertFalse(media.thumbnail_attachment_id)

    def test_invoice_policy_manager_version_and_legacy_replay(self):
        raw = self._image()
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        media_id = service._v2_upload(self.room.id, self._metadata(raw), raw)['media_id']
        original = {
            'api_version': 2, 'membership_id': self.manager_epoch.id,
            'client_uuid': str(uuid4()), 'text': '', 'media_id': media_id,
        }
        sent = service._v2_send(self.room.id, original)
        self.assertEqual(self.room.invoice_policy, 'off')
        self.assertEqual(self.room.invoice_policy_version, 1)
        with self.assertRaises(AccessError):
            self.room.with_user(self.member).write({'invoice_policy': 'invoice_default'})
        with self.assertRaises(AccessError):
            self.room.with_user(self.manager).write({'invoice_policy_version': 99})
        # The optional Documents addon enables this in integrated test DBs;
        # force the disabled boundary to test the base-module fallback itself.
        with patch.object(type(service), '_v2_documents_enabled', return_value=False):
            with self.assertRaises(AccessError):
                self.room.with_user(self.manager).write({'invoice_policy': 'invoice_default'})
        explicit_off = self.env['baseer.bchat.room'].with_user(self.manager).with_company(
            self.company).create({
                'name': 'Explicit off', 'company_id': self.company.id,
                'invoice_policy': 'off',
            })
        self.assertEqual(explicit_off.invoice_policy, 'off')
        with patch.object(type(service), '_v2_documents_enabled', return_value=False):
            with self.assertRaises(AccessError):
                self.env['baseer.bchat.room'].with_user(self.manager).with_company(
                    self.company).create({
                        'name': 'Forbidden enabled policy', 'company_id': self.company.id,
                        'invoice_policy': 'invoice_default',
                    })
        with patch.object(type(service), '_v2_documents_enabled', return_value=True):
            self.room.with_user(self.manager).with_company(self.company).write({
                'name': 'Renamed and enabled', 'invoice_policy': 'invoice_default',
            })
            self.assertEqual(self.room.name, 'Renamed and enabled')
            self.assertEqual(self.room.invoice_policy_version, 2)
            self.assertEqual(service._v2_send(self.room.id, original), sent)
            self.room.with_user(self.manager).with_company(self.company).write({
                'invoice_policy': 'invoice_default',
            })
            self.assertEqual(self.room.invoice_policy_version, 2)
            fresh_id = service._v2_upload(self.room.id, self._metadata(raw), raw)['media_id']
            fresh = {**original, 'client_uuid': str(uuid4()), 'media_id': fresh_id}
            for changed in ({}, {'document_type': 'invoice', 'policy_version': 1},
                            {'document_type': 'payment_receipt', 'policy_version': 2},
                            {'document_type': 'other', 'invoice_case_id': 10, 'policy_version': 2}):
                with self.subTest(changed=changed), self.assertRaises(ProtocolError):
                    service._v2_send(self.room.id, {**fresh, **changed})
            staged = self.env['baseer.bchat.media'].sudo().browse(fresh_id)
            self.assertEqual(staged.state, 'staged')
            selected = {**fresh, 'document_type': 'other', 'policy_version': 2}
            with patch.object(type(service), '_v2_finalize_document') as finalize:
                service._v2_send(self.room.id, selected)
            self.assertEqual(finalize.call_count, 1)
            self.assertEqual(finalize.call_args.args[-1]['document_type'], 'other')
            self.assertNotIn('invoice_case_id', finalize.call_args.args[-1])
            self.assertEqual(staged.document_type, 'other')
            self.assertEqual(staged.document_policy_version, 2)
            self.assertEqual(service._v2_send(self.room.id, selected)['media_id'], fresh_id)

    def test_document_finalize_failure_keeps_staged_upload(self):
        raw = self._image()
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        with patch.object(type(service), '_v2_documents_enabled', return_value=True):
            self.room.with_user(self.manager).with_company(self.company).write({
                'invoice_policy': 'select_on_upload',
            })
            media_id = service._v2_upload(self.room.id, self._metadata(raw), raw)['media_id']
            media = self.env['baseer.bchat.media'].sudo().browse(media_id)
            uuid = str(uuid4())
            payload = {
                'api_version': 2, 'membership_id': self.manager_epoch.id,
                'client_uuid': uuid, 'text': '', 'media_id': media_id,
                'document_type': 'invoice', 'policy_version': self.room.invoice_policy_version,
            }
            with patch.object(type(service), '_v2_finalize_document', side_effect=ValueError('DMS failed')):
                with self.assertRaisesRegex(ValueError, 'DMS failed'):
                    service._v2_send(self.room.id, payload)
            self.assertEqual(media.state, 'staged')
            self.assertTrue(media.attachment_id)
            self.assertFalse(self.env['baseer.bchat.message'].sudo().search([
                ('author_user_id', '=', self.manager.id), ('client_uuid', '=', uuid),
            ]))
            sent = service._v2_send(self.room.id, payload)
            self.assertEqual(media.document_type, 'invoice')
            self.assertEqual(sent['media_id'], media.id)

    def test_media_original_bytes_hook_is_after_membership_check(self):
        raw = self._image()
        service = self.env['baseer.bchat.service'].with_user(self.manager)
        media_id = service._v2_upload(self.room.id, self._metadata(raw), raw)['media_id']
        service._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.manager_epoch.id,
            'client_uuid': str(uuid4()), 'text': '', 'media_id': media_id,
        })
        media = self.env['baseer.bchat.media'].sudo().browse(media_id)
        media._write_verified({'document_file_id': 123, 'attachment_id': False}, _MEDIA_TOKEN)
        with self.assertRaises(AccessError):
            service._v2_media_content(media.id)
        with patch.object(type(service), '_v2_media_original_bytes', return_value=raw) as read:
            self.assertEqual(service._v2_media_content(media.id)[0], raw)
            read.assert_called_once()
            self.member_epoch.with_user(self.manager).with_company(self.company).action_revoke()
            with self.assertRaises(AccessError):
                self.env['baseer.bchat.service'].with_user(self.member)._v2_media_content(media.id)
            read.assert_called_once()


@tagged('post_install', '-at_install', 'baseer_bchat_media')
class BChatMediaHttpCase(HttpCase):
    def test_media_routes_and_direct_attachment_rpc_denial(self):
        company = self.env.company
        password = 'test-only-%s' % uuid4().hex
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat media HTTP user',
            'login': 'bchat-media-http-%s' % uuid4().hex,
            'password': password,
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat media HTTP manager',
            'login': 'bchat-media-http-manager-%s' % uuid4().hex,
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('baseer_bchat.group_bchat_manager').id])],
        })
        room = self.env['baseer.bchat.room'].with_user(manager).with_company(company).create({
            'name': 'Media HTTP room', 'company_id': company.id,
        })
        epoch = self.env['baseer.bchat.membership'].with_user(manager).with_company(company).create({
            'room_id': room.id, 'user_id': user.id,
        })
        output = io.BytesIO()
        Image.new('RGB', (12, 9), (10, 20, 30)).save(output, format='PNG')
        raw = output.getvalue()
        service = self.env['baseer.bchat.service'].with_user(user)
        staged = service._v2_upload(room.id, {
            'api_version': 2, 'membership_id': epoch.id,
            'upload_uuid': str(uuid4()), 'kind': 'image', 'mime': 'image/png',
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'name': 'http.png',
        }, raw)
        media = self.env['baseer.bchat.media'].sudo().browse(staged['media_id'])
        service._v2_send(room.id, {
            'api_version': 2, 'membership_id': epoch.id,
            'client_uuid': str(uuid4()), 'text': '', 'media_id': media.id,
        })
        self.authenticate(user.login, password)
        csrf = self.url_open('/bchat/api/v2/bootstrap').json()['csrf_token']
        upload_metadata = {
            'api_version': 2, 'membership_id': epoch.id,
            'upload_uuid': str(uuid4()), 'kind': 'image', 'mime': 'image/png',
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'name': 'multipart.png',
        }
        native_metadata = {**upload_metadata, 'upload_uuid': str(uuid4()), 'name': 'native.png'}
        issued = self.url_open('/bchat/api/v2/rooms/%s/mobile-upload-grants' % room.id,
                               data={'csrf_token': csrf, 'metadata': json.dumps(native_metadata)},
                               method='POST')
        self.assertEqual(issued.status_code, 200)
        grant = issued.json()
        self.assertRegex(grant['grant_id'], r'^[0-9a-f-]{36}$')
        self.assertRegex(grant['secret'], r'^[A-Za-z0-9_-]{43,128}$')
        native_url = '/bchat/api/v2/mobile-upload-grants/%s/content' % grant['grant_id']
        capability_headers = {
            'Authorization': 'BChatUpload %s.%s' % (grant['grant_id'], grant['secret']),
            'Content-Type': 'image/png',
        }
        # A session cookie must not silently authenticate a native route.
        cookie_rejected = self.url_open(native_url, data=raw, headers=capability_headers, method='POST')
        self.assertEqual(cookie_rejected.status_code, 401)
        self.opener.cookies.clear()
        native_uploaded = self.url_open(native_url, data=raw, headers=capability_headers, method='POST')
        self.assertEqual(native_uploaded.status_code, 200)
        self.assertEqual(native_uploaded.json()['upload_uuid'], native_metadata['upload_uuid'])
        native_media_id = native_uploaded.json()['media_id']
        # Retrying a POST after a lost client response returns the persisted receipt, not a new row.
        native_replay = self.url_open(native_url, data=raw, headers=capability_headers, method='POST')
        self.assertEqual((native_replay.status_code, native_replay.json()['media_id']), (200, native_media_id))
        native_status = self.url_open('/bchat/api/v2/mobile-upload-grants/%s' % grant['grant_id'],
                                      headers={'Authorization': capability_headers['Authorization']})
        self.assertEqual((native_status.status_code, native_status.json()['media_id']), (200, native_media_id))
        self.authenticate(user.login, password)
        csrf = self.url_open('/bchat/api/v2/bootstrap').json()['csrf_token']
        reconciled_native = self.url_open(
            '/bchat/api/v2/rooms/%s/uploads/%s/reconcile' % (room.id, native_metadata['upload_uuid']))
        self.assertEqual((reconciled_native.status_code, reconciled_native.json()['media_id']),
                         (200, native_media_id))
        uploaded = self.url_open('/bchat/api/v2/rooms/%s/uploads' % room.id,
                                 data={'csrf_token': csrf, 'metadata': json.dumps(upload_metadata)},
                                 files={'file': ('multipart.png', raw, 'image/png')}, method='POST')
        self.assertEqual(uploaded.status_code, 200)
        self.assertGreater(uploaded.json()['media_id'], 0)
        cancel_url = '/bchat/api/v2/uploads/%s/cancel' % uploaded.json()['media_id']
        oversized_cancel = self.url_open(cancel_url,
                                         data={'csrf_token': csrf, 'padding': 'x' * 2048},
                                         method='POST')
        self.assertEqual(oversized_cancel.status_code, 413)
        cancelled = self.url_open(cancel_url, data={'csrf_token': csrf}, method='POST')
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()['state'], 'cancelled')
        too_large = {**upload_metadata, 'upload_uuid': str(uuid4()), 'size': 5 * 1024 * 1024 + 1}
        rejected = self.url_open('/bchat/api/v2/rooms/%s/uploads' % room.id,
                                 data={'csrf_token': csrf, 'metadata': json.dumps(too_large)},
                                 files={'file': ('multipart.png', raw, 'image/png')}, method='POST')
        self.assertEqual(rejected.status_code, 413)
        allowed = self.url_open('/bchat/api/v2/media/%s/content' % media.id)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.content, raw)
        preview = self.url_open('/bchat/api/v2/media/%s/thumbnail' % media.id)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.headers['Content-Type'], 'image/jpeg')
        self.assertIn('no-store', preview.headers['Cache-Control'])
        for attachment in (media.attachment_id, media.thumbnail_attachment_id):
            if not attachment:
                # OCA consumes the staged original on send; it is then read
                # only through the membership-gated BChat content route.
                continue
            direct = self.url_open('/web/content/%s' % attachment.id, allow_redirects=False)
            self.assertNotEqual(direct.status_code, 200)
            rpc = self.url_open('/web/dataset/call_kw/ir.attachment/read',
                                data=json.dumps({
                                    'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                                    'params': {'model': 'ir.attachment', 'method': 'read',
                                               'args': [[attachment.id], ['datas']], 'kwargs': {}},
                                }), headers={'Content-Type': 'application/json'})
            rpc_payload = rpc.json()
            if 'error' not in rpc_payload:
                # Odoo may suppress denied binary fields as False/empty rather
                # than raising JSON-RPC error.  Neither bytes nor the private
                # attachment's identity may be disclosed.
                for row in rpc_payload.get('result', []):
                    self.assertNotEqual(row.get('id'), attachment.id)
                    self.assertFalse(row.get('datas'))
        media_rpc = self.url_open('/web/dataset/call_kw/baseer.bchat.media/read',
                                  data=json.dumps({
                                      'jsonrpc': '2.0', 'method': 'call', 'id': 2,
                                      'params': {'model': 'baseer.bchat.media', 'method': 'read',
                                                 'args': [[media.id]], 'kwargs': {}},
                                  }), headers={'Content-Type': 'application/json'})
        self.assertIn('error', media_rpc.json())
        epoch.with_user(manager).with_company(company).action_revoke()
        self.assertEqual(self.url_open('/bchat/api/v2/media/%s/content' % media.id).status_code, 403)
