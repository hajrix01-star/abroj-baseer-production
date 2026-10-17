"""C16 real PostgreSQL/ORM search, epoch isolation and HTTP read-only contract.

Synthetic history fixtures are not a load test or a claim about production size.
"""
import hashlib
import io
import json
from uuid import uuid4

from PIL import Image
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..contracts import ProtocolError
from ..models.message import _SERVICE_TOKEN


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_search')
class BChatSearchCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.admin = self.env.ref('base.user_admin')
        self.admin.write({'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        self.owner, self.reader = self._users(2)
        self.service = self.env['baseer.bchat.service'].with_user(self.owner)
        created = self.service._v2_group_create({
            'api_version': 2, 'company_id': self.company.id, 'client_uuid': str(uuid4()),
            'name': 'Search fixture', 'member_user_ids': [self.reader.id],
        })
        self.room = self.env['baseer.bchat.room'].sudo().browse(created['room_id'])
        self.member = self.env['baseer.bchat.membership'].sudo().browse(created['membership_id'])
        self.reader_member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room.id), ('user_id', '=', self.reader.id), ('active', '=', True)])
        self.reader_service = self.env['baseer.bchat.service'].with_user(self.reader)

    def _users(self, count, company=None):
        selected = company or self.company
        return self.env['res.users'].with_context(no_reset_password=True).create([{
            'name': 'BChat search %02d' % number, 'login': 'bchat-search-' + uuid4().hex,
            'company_id': selected.id, 'company_ids': [Command.set(selected.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        } for number in range(count)])

    def _payload(self, query='needle', **extra):
        return {'api_version': 2, 'membership_id': self.reader_member.id,
                'q': query, 'kind': 'all', 'before_id': None, **extra}

    def _send(self, text, **extra):
        return self.service._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.member.id, 'client_uuid': str(uuid4()),
            'text': text, **extra})['message_id']

    def _history_fixture(self, texts):
        # Private test-only creation avoids hundreds of provider jobs. It does
        # not replace the normal send/retry coverage in the text/media suites.
        return self.env['baseer.bchat.message']._create_verified([{
            'room_id': self.room.id, 'company_id': self.company.id, 'membership_id': self.member.id,
            'author_user_id': self.owner.id, 'client_uuid': str(uuid4()),
            'payload_digest': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'text': text,
        } for text in texts], _SERVICE_TOKEN)

    def _image(self, name, *, attach=True, caption=''):
        stream = io.BytesIO()
        Image.new('RGB', (12, 8), '#124567').save(stream, format='PNG')
        raw = stream.getvalue()
        media = self.service._v2_upload(self.room.id, {
            'api_version': 2, 'membership_id': self.member.id, 'upload_uuid': str(uuid4()),
            'kind': 'image', 'mime': 'image/png', 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'name': name,
        }, raw)
        message_id = self._send(caption, media_id=media['media_id']) if attach else None
        return media['media_id'], message_id

    def test_indexed_history_is_not_limited_to_the_500_cached_messages(self):
        ancient = self._history_fixture(['needle قديم'])[0]
        self._history_fixture(['Recent filler %s' % number for number in range(501)])
        result = self.reader_service._v2_room_search(self.room.id, self._payload())
        self.assertEqual([row['id'] for row in result['messages']], [ancient.id])
        arabic = self.reader_service._v2_room_search(self.room.id, self._payload('قديم'))
        self.assertEqual([row['id'] for row in arabic['messages']], [ancient.id])
        self.assertEqual(result['membership_id'], self.reader_member.id)
        self.assertIsNone(result['next_before_id'])

    def test_utf8_pages_have_no_overlap_or_skips_and_search_never_acks(self):
        ident = self._send('مطابقة رسمية')
        receipt = self.env['baseer.bchat.message.receipt'].sudo().search([
            ('message_id', '=', ident), ('recipient_user_id', '=', self.reader.id)])
        before_receipt = (receipt.read_at, receipt.delivered_at)
        large = self._history_fixture(['مطابقة ' + 'بيان ' * 1300 for _number in range(33)])
        before_id, seen, page_lengths = None, [], []
        for _page in range(35):
            result = self.reader_service._v2_room_search(self.room.id, self._payload('مطابقة', before_id=before_id))
            ids = [row['id'] for row in result['messages']]
            self.assertEqual(ids, sorted(ids))
            self.assertFalse(set(ids) & set(seen))
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode('utf-8')), 131072)
            page_lengths.append(len(ids))
            seen.extend(ids)
            if result['next_before_id'] is None:
                break
            self.assertTrue(ids)
            self.assertEqual(result['next_before_id'], ids[0])
            before_id = result['next_before_id']
        self.assertLess(page_lengths[0], 30)  # Actual UTF-8 JSON shrinking, not an item-count assumption.
        self.assertEqual(set(seen), {ident, *large.ids})
        self.assertEqual(before_receipt, (receipt.read_at, receipt.delivered_at))

    def test_current_epoch_company_and_chat_right_are_always_rechecked(self):
        old = self._send('needle old epoch')
        old_member = self.reader_member.id
        self.reader_member.with_user(self.admin).action_revoke()
        self.reader_member = self.env['baseer.bchat.membership'].with_user(self.admin).create({
            'room_id': self.room.id, 'user_id': self.reader.id})
        new = self._send('needle new epoch')
        result = self.reader_service._v2_room_search(self.room.id, self._payload())
        self.assertEqual([row['id'] for row in result['messages']], [new])
        self.assertNotIn(old, [row['id'] for row in result['messages']])
        with self.assertRaises(ProtocolError) as stale:
            self.reader_service._v2_room_search(self.room.id, self._payload(membership_id=old_member))
        self.assertEqual(stale.exception.code, 'membership_changed')
        foreign_company = self.env['res.company'].create({'name': 'Search foreign company'})
        foreign = self._users(1, foreign_company)
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(foreign)._v2_room_search(self.room.id, self._payload())
        self.reader.write({'bchat_chat_view': False})
        with self.assertRaises(AccessError):
            self.reader_service._v2_room_search(self.room.id, self._payload())

    def test_text_and_filename_union_is_distinct_attached_and_permission_scoped(self):
        media_id, ident = self._image('needle.png', caption='needle')
        self._image('needle-staged.png', attach=False)
        self._send('needle plain text')
        all_rows = self.reader_service._v2_room_search(self.room.id, self._payload())['messages']
        self.assertEqual(len(all_rows), 2)
        self.assertEqual(sum(row['id'] == ident for row in all_rows), 1)
        image_rows = self.reader_service._v2_room_search(self.room.id, self._payload(kind='image'))['messages']
        self.assertEqual([row['id'] for row in image_rows], [ident])
        gallery = self.reader_service._v2_room_media(self.room.id, self.reader_member.id)
        self.assertEqual([row['media']['id'] for row in gallery['messages']], [media_id])
        text_rows = self.reader_service._v2_room_search(self.room.id, self._payload(kind='text'))['messages']
        self.assertEqual(len(text_rows), 1)
        self.assertNotIn('media', text_rows[0])

    def test_view_only_gallery_does_not_grant_download_or_filename_search_without_view(self):
        media_id, ident = self._image('confidentialfilename.png')
        self.reader.write({'bchat_media': False, 'bchat_media_view': True, 'bchat_media_download': False})
        result = self.reader_service._v2_room_search(self.room.id, self._payload('confidentialfilename'))
        self.assertEqual([row['id'] for row in result['messages']], [ident])
        exact_name = self.reader_service._v2_room_search(self.room.id, self._payload('confidentialfilename.png'))
        self.assertEqual([row['id'] for row in exact_name['messages']], [ident])
        self.assertTrue(self.reader_service._v2_media_content(media_id, thumbnail=True)[0])
        with self.assertRaises(AccessError):
            self.reader_service._v2_media_content(media_id)
        self.reader.write({'bchat_media_view': False})
        self.assertEqual(self.reader_service._v2_room_search(
            self.room.id, self._payload('confidentialfilename'))['messages'], [])
        with self.assertRaises(AccessError):
            self.reader_service._v2_room_media(self.room.id, self.reader_member.id)
        with self.assertRaises(AccessError):
            self.reader_service._v2_room_search(self.room.id, self._payload(kind='image'))

    def test_query_is_parameterized_and_types_bounds_are_strict(self):
        self._send('public unrelated message')
        self.assertEqual(self.reader_service._v2_room_search(
            self.room.id, self._payload("needle' OR 1=1--"))['messages'], [])
        for extra in ({'q': ''}, {'q': ' '}, {'q': '界' * 43}, {'q': 'a ' * 9}, {'q': 'a\x00b'},
                      {'q': '\ud800'}, {'q': True}, {'kind': 'video'}, {'before_id': True},
                      {'membership_id': True}, {'api_version': True}, {'unrecognized': 1}):
            with self.subTest(extra=extra), self.assertRaises(ProtocolError):
                self.reader_service._v2_room_search(self.room.id, self._payload(**extra))

    def test_search_indexes_exist_and_postgres_can_plan_the_bound_query(self):
        self._history_fixture(['needle indexed fixture'])
        self.env.cr.execute('''SELECT indexname,indexdef FROM pg_indexes WHERE indexname IN (
            'baseer_bchat_message_text_search_idx','baseer_bchat_media_name_search_idx',
            'baseer_bchat_media_gallery_idx')''')
        indexes = dict(self.env.cr.fetchall())
        self.assertEqual(len(indexes), 3)
        self.assertIn('USING gin', indexes['baseer_bchat_message_text_search_idx'])
        self.assertIn('USING gin', indexes['baseer_bchat_media_name_search_idx'])
        self.assertIn('attached', indexes['baseer_bchat_media_gallery_idx'])
        self.env.cr.execute('''EXPLAIN (FORMAT JSON) SELECT id FROM baseer_bchat_message
            WHERE room_id=%s AND company_id=%s AND id>%s
            AND to_tsvector('simple'::regconfig,COALESCE(text,'')) @@ plainto_tsquery('simple'::regconfig,%s)
            ORDER BY id DESC LIMIT 31''', [self.room.id, self.company.id,
                                         self.reader_member.joined_after_message_id, 'needle'])
        plan = self.env.cr.fetchone()[0][0]
        self.assertIn('Plan', plan)
        # No assertion of an index scan on tiny data and no claimed capacity/FPS measurement.


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_search')
class BChatSearchHttpCase(HttpCase):
    def test_http_search_is_csrf_protected_read_only_post_and_gallery_has_no_query_text(self):
        password = 'test-only-' + uuid4().hex
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Search HTTP fixture', 'login': 'bchat-search-http-' + uuid4().hex,
            'password': password, 'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        peer = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Search HTTP peer', 'login': 'bchat-search-peer-' + uuid4().hex,
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        service = self.env['baseer.bchat.service'].with_user(user)
        created = service._v2_group_create({'api_version': 2, 'company_id': self.env.company.id,
            'client_uuid': str(uuid4()), 'name': 'HTTP search', 'member_user_ids': [peer.id]})
        sent = service._v2_send(created['room_id'], {'api_version': 2, 'membership_id': created['membership_id'],
            'client_uuid': str(uuid4()), 'text': 'needle HTTP fixture'})
        self.authenticate(user.login, password)
        csrf = self.url_open('/bchat/api/v2/bootstrap').json()['csrf_token']
        path = '/bchat/api/v2/rooms/%s/search' % created['room_id']
        payload = {'api_version': 2, 'membership_id': created['membership_id'],
                   'q': 'needle', 'kind': 'all', 'before_id': None}
        form = {'csrf_token': csrf, 'payload': json.dumps(payload)}
        self.assertNotEqual(self.url_open(path, data={'payload': json.dumps(payload)},
                                        allow_redirects=False).status_code, 200)
        self.assertNotEqual(self.url_open(path, allow_redirects=False).status_code, 200)
        queried = self.url_open(path + '?q=needle', data=form)
        self.assertEqual(queried.status_code, 400)
        response = self.url_open(path, data=form)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual([row['id'] for row in response.json()['messages']], [sent['message_id']])
        gallery = '/bchat/api/v2/rooms/%s/media?membership_id=%s' % (created['room_id'], created['membership_id'])
        self.assertEqual(self.url_open(gallery).status_code, 200)
        self.assertEqual(self.url_open(gallery + '&q=needle').status_code, 400)
