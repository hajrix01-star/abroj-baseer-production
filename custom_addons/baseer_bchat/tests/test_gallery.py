"""Real ORM and HTTP gallery guards; disposable Odoo test database only."""
import hashlib
import io
from uuid import uuid4

from PIL import Image
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from .. import gallery_contracts as wire
from ..contracts import ProtocolError
from ..models.media import _MEDIA_TOKEN


class GalleryFixtures:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.admin = cls.env.ref('base.user_admin')
        cls.admin.sudo().write({'group_ids': [Command.link(cls.env.ref('baseer_bchat.group_bchat_manager').id)]})
        cls.password = 'gallery-test-' + uuid4().hex
        cls.reader = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Gallery reader', 'login': 'gallery-' + uuid4().hex, 'password': cls.password,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })
        cls.room = cls.env['baseer.bchat.room'].with_user(cls.admin).with_company(cls.company).create({
            'name': 'Gallery room', 'company_id': cls.company.id,
        })
        cls.member = cls.env['baseer.bchat.membership'].with_user(cls.admin).with_company(cls.company).create({
            'room_id': cls.room.id, 'user_id': cls.reader.id,
        })
        observer = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Gallery observer', 'login': 'gallery-observer-' + uuid4().hex,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })
        cls.env['baseer.bchat.membership'].with_user(cls.admin).with_company(cls.company).create({
            'room_id': cls.room.id, 'user_id': observer.id,
        })
        cls.service = cls.env['baseer.bchat.service'].with_user(cls.reader)
        cls.messages = [cls._send_file(b'aaa'), cls._send_file(b'bbbbb'), cls._send_file(b'ccccc')]

    @classmethod
    def _send_file(cls, raw, text='', kind='file', mime='text/plain', name='fixture.txt', reply=None):
        media = cls.service._v2_upload(cls.room.id, {
            'api_version': 2, 'membership_id': cls.member.id, 'upload_uuid': str(uuid4()),
            'kind': kind, 'mime': mime, 'name': name, 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
        }, raw)
        payload = {'api_version': 2, 'membership_id': cls.member.id,
                   'client_uuid': str(uuid4()), 'text': text, 'media_id': media['media_id']}
        if reply:
            payload['reply_to_message_id'] = reply
        return cls.service._v2_send(cls.room.id, payload)['message_id']


@tagged('post_install', '-at_install', 'baseer_bchat_gallery')
class BChatGalleryCase(GalleryFixtures, TransactionCase):
    def test_orders_keyset_ties_and_every_page_exactly_once(self):
        for order, expected in (('newest', list(reversed(self.messages))),
                                ('oldest', self.messages),
                                ('largest', [self.messages[2], self.messages[1], self.messages[0]])):
            seen, cursor = [], None
            while True:
                page = self.service._v2_gallery(self.room.id, order=order, limit=1, cursor=cursor)
                seen.extend(row['id'] for row in page['items'])
                cursor = page['next_cursor']
                if cursor is None:
                    break
                self.assertLessEqual(len(cursor), 256)
                self.assertLessEqual(len(seen), len(expected))
            self.assertEqual(seen, expected)

    def test_canonical_reply_filter_and_no_receipt_or_history_mutation(self):
        image = io.BytesIO()
        Image.new('RGB', (4, 4)).save(image, format='PNG')
        last = self._send_file(image.getvalue(), 'caption', kind='image', mime='image/png', name='x.png',
                               reply=self.messages[0])
        receipts = self.env['baseer.bchat.message.receipt'].sudo()
        before = receipts.search([]).read(['message_id', 'delivered_at', 'read_at'])
        self.assertTrue(before)
        page = self.service._v2_gallery(self.room.id, kind='image')
        self.assertEqual([row['id'] for row in page['items']], [last])
        row = page['items'][0]
        canonical = next(item for item in self.service._v2_history(self.room.id)['messages'] if item['id'] == last)
        label = row['media'].pop('size_label')
        self.assertEqual(label, wire.size_label(row['media']['size']))
        self.assertEqual(row, canonical)
        self.assertEqual(receipts.search([]).read(['message_id', 'delivered_at', 'read_at']), before)
        self.assertFalse(self.service._v2_gallery(self.room.id, kind='audio')['items'])

    def test_admin_without_membership_sudo_and_foreign_company_cannot_read(self):
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.admin)._v2_gallery(self.room.id)
        with self.assertRaises(AccessError):
            self.service.sudo()._v2_gallery(self.room.id)
        foreign = self.env['res.company'].create({'name': 'Gallery foreign company'})
        self.admin.sudo().write({'company_ids': [Command.link(foreign.id)]})
        room = self.env['baseer.bchat.room'].with_user(self.admin).with_company(foreign).create({
            'name': 'Foreign gallery', 'company_id': foreign.id,
        })
        with self.assertRaises(AccessError):
            self.service._v2_gallery(room.id)
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.media'].with_user(self.reader).search([])

    def test_media_or_chat_permission_revocation_is_not_admin_bypass(self):
        for flag in ('bchat_media', 'bchat_chat_view'):
            self.reader.sudo().write({flag: False})
            with self.assertRaises(AccessError):
                self.service._v2_gallery(self.room.id)
            self.reader.sudo().write({flag: True})

    def test_rejoin_invalidates_old_cursor_and_old_visibility(self):
        cursor = self.service._v2_gallery(self.room.id, limit=1)['next_cursor']
        self.member.with_user(self.admin).with_company(self.company).action_revoke()
        with self.assertRaises(AccessError):
            self.service._v2_gallery(self.room.id)
        self.env['baseer.bchat.membership'].with_user(self.admin).with_company(self.company).create({
            'room_id': self.room.id, 'user_id': self.reader.id,
        })
        self.assertEqual(self.service._v2_gallery(self.room.id)['items'], [])
        with self.assertRaises(ProtocolError):
            self.service._v2_gallery(self.room.id, cursor=cursor)

    def test_broken_inverse_link_and_unattached_media_never_list(self):
        message = self.env['baseer.bchat.message'].sudo().browse(self.messages[0])
        message.media_id._write_verified({'message_id': self.messages[1]}, _MEDIA_TOKEN)
        self.service._v2_upload(self.room.id, {'api_version': 2, 'membership_id': self.member.id,
            'upload_uuid': str(uuid4()), 'kind': 'file', 'mime': 'text/plain', 'name': 'staged.txt',
            'size': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}, b'x')
        self.assertEqual([row['id'] for row in self.service._v2_gallery(self.room.id)['items']],
                         list(reversed(self.messages[1:])))

    def test_real_canonical_rows_obey_byte_cap_without_missing_tail(self):
        ids = [self._send_file(b'x', 'ع' * 8000) for _ in range(10)]
        seen, cursor, pages = [], None, 0
        while True:
            page = self.service._v2_gallery(self.room.id, limit=60, cursor=cursor)
            self.assertLessEqual(wire.encoded_size(page), wire.MAX_BYTES)
            self.assertTrue(page['items'])
            seen.extend(row['id'] for row in page['items'])
            cursor = page['next_cursor']
            pages += 1
            if cursor is None:
                break
            self.assertLess(pages, 10)
        self.assertGreater(pages, 1)
        self.assertEqual(seen, list(reversed(self.messages + ids)))


@tagged('post_install', '-at_install', 'baseer_bchat_gallery')
class BChatGalleryHttpCase(GalleryFixtures, HttpCase):
    def test_authenticated_strict_route_and_existing_content_reads(self):
        self.authenticate(self.reader.login, self.password)
        path = '/bchat/api/v2/rooms/%s/media' % self.room.id
        response = self.url_open(path + '?limit=1&order=largest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        page = response.json()
        self.assertEqual(page['membership_id'], self.member.id)
        self.assertEqual(page['items'][0]['id'], self.messages[2])
        media = page['items'][0]['media']
        self.assertEqual(media['size_label'], '5 B')
        self.assertEqual(self.url_open('/bchat/api/v2/media/%s/content' % media['id']).content, b'ccccc')
        for query in ('limit=61', 'order=bad', 'kind=image&kind=file', 'token=x', 'cursor='):
            self.assertEqual(self.url_open(path + '?' + query).status_code, 400)
        self.reader.sudo().write({'bchat_media': False})
        self.assertEqual(self.url_open(path).status_code, 403)

    def test_unauthenticated_cannot_obtain_gallery(self):
        response = self.url_open('/bchat/api/v2/rooms/%s/media' % self.room.id, allow_redirects=False)
        self.assertNotEqual(response.status_code, 200)
