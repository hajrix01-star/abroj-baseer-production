"""C13 ORM/HTTP behavior over synthetic data, not device/cache or load evidence."""
import hashlib
import json
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..contracts import ProtocolError
from ..models.message import _SERVICE_TOKEN
from ..models.message_receipt import _RECEIPT_TOKEN
from ..models.room import _GROUP_TOKEN
from ..models import receipt_delivery_service as delivery


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_delivery_receipts')
class BChatDeliveryReceiptsCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.admin = self.env.ref('base.user_admin')
        self.admin.write({'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        self.owner, self.reader, self.other = self._users(3)
        room = self._service(self.owner)._v2_group_create({
            'api_version': 2, 'company_id': self.company.id, 'client_uuid': str(uuid4()),
            'name': 'Delivery receipt fixture', 'member_user_ids': [self.reader.id, self.other.id]})
        self.room = self.env['baseer.bchat.room'].sudo().browse(room['room_id'])
        self.members = {m.user_id.id: m for m in self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room.id), ('active', '=', True)])}
        self.message_id = self._service(self.owner)._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': room['membership_id'], 'client_uuid': str(uuid4()),
            'text': 'Canonical receipt source'})['message_id']

    def _users(self, count, company=None):
        company = company or self.company
        return self.env['res.users'].with_context(no_reset_password=True).create([{
            'name': 'Receipt reader %s' % index, 'login': 'bchat-delivery-' + uuid4().hex,
            'company_id': company.id, 'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        } for index in range(count)])

    def _service(self, user):
        return self.env['baseer.bchat.service'].with_user(user)

    def _receipts(self, message_ids=None):
        return self.env['baseer.bchat.message.receipt'].sudo().search([
            ('message_id', 'in', message_ids or [self.message_id])], order='id')

    def _fixture_messages(self, count, room=None, sender_member=None, reader_member=None):
        # Protected synthetic seed avoids generating hundreds of provider jobs.
        # Normal send and ACK remain covered separately; this is not an ACL bypass claim.
        room = room or self.room
        sender_member = sender_member or self.members[self.owner.id]
        reader_member = reader_member or self.members[self.reader.id]
        messages = self.env['baseer.bchat.message']._create_verified([{
            'room_id': room.id, 'company_id': room.company_id.id, 'membership_id': sender_member.id,
            'author_user_id': sender_member.user_id.id, 'client_uuid': str(uuid4()),
            'payload_digest': hashlib.sha256(('receipt seed %s' % index).encode()).hexdigest(),
            'text': 'Receipt seed %s' % index,
        } for index in range(count)], _SERVICE_TOKEN)
        self.env['baseer.bchat.message.receipt']._create_verified([{
            'message_id': message.id, 'membership_id': reader_member.id,
            'recipient_user_id': reader_member.user_id.id, 'company_id': room.company_id.id,
        } for message in messages], _RECEIPT_TOKEN)
        return messages

    def _legacy_members(self, users, *, administrator=False):
        # Imported legacy rooms may exceed the new 50-member creation limit.
        # Only test data uses this verified internal primitive; API reads are ordinary-user calls.
        return self.env['baseer.bchat.membership']._create_group_verified([{
            'room_id': self.room.id, 'company_id': self.company.id, 'user_id': user.id,
            'joined_after_message_id': 0, 'active': True, 'is_group_admin': administrator,
        } for user in users], _GROUP_TOKEN)

    def _add_fixture_receipts(self, members):
        return self.env['baseer.bchat.message.receipt']._create_verified([{
            'message_id': self.message_id, 'membership_id': member.id,
            'recipient_user_id': member.user_id.id, 'company_id': self.company.id,
        } for member in members], _RECEIPT_TOKEN)

    def test_bootstrap_version_is_top_level_and_legacy_capabilities_are_unchanged(self):
        result = self._service(self.reader)._v2_bootstrap()
        self.assertEqual(result['receipt_delivery_contract_version'], 1)
        self.assertNotIn('receipt_delivery_contract_version', result['capabilities'])
        self.assertTrue(result['capabilities']['delivery_receipts'])
        self.assertTrue(result['capabilities']['read_receipts'])
        self.assertNotIn('pending_receipts', result['capabilities'])

    def test_pending_refs_strict_cursor_page_and_utf8_byte_bound(self):
        self._fixture_messages(35)
        service = self._service(self.reader)
        page = service._v2_pending_receipts()
        self.assertEqual(set(page), {'api_version', 'refs', 'next_after_id', 'has_more'})
        self.assertEqual(len(page['refs']), 30)
        self.assertTrue(page['has_more'])
        self.assertEqual(page['next_after_id'], page['refs'][-1]['receipt_id'])
        for row in page['refs']:
            self.assertEqual(set(row), {'room_id', 'membership_id', 'message_id', 'receipt_id'})
            self.assertEqual(row['membership_id'], self.members[self.reader.id].id)
        self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode()), 65536)
        following = service._v2_pending_receipts(page['next_after_id'])
        self.assertFalse(set(r['receipt_id'] for r in page['refs']) & set(r['receipt_id'] for r in following['refs']))
        empty = service._v2_pending_receipts(following['next_after_id'])
        self.assertEqual((empty['refs'], empty['next_after_id'], empty['has_more']), ([], 0, False))
        # Shrink the real byte budget to exercise trimming without inventing invalid large IDs.
        with patch.object(delivery, 'MAX_RESPONSE_BYTES', 400):
            compact = service._v2_pending_receipts()
        self.assertTrue(compact['has_more'])
        self.assertEqual(compact['next_after_id'], compact['refs'][-1]['receipt_id'])
        self.assertLessEqual(len(json.dumps(compact, ensure_ascii=False).encode()), 400)
        for invalid in (True, -1, '0', 2147483648):
            with self.subTest(cursor=invalid), self.assertRaises(ProtocolError):
                service._v2_pending_receipts(invalid)

    def test_pending_eligibility_precedes_limit_and_old_epoch_never_reappears(self):
        old_echo = self._service(self.reader)._v2_message(self.room.id, self.message_id)
        self.assertEqual(old_echo['membership_id'], self.members[self.reader.id].id)
        self.assertNotEqual(old_echo['membership_id'], self.members[self.owner.id].id)
        old_messages = self._fixture_messages(35)
        old = self.members[self.reader.id]
        old.with_user(self.admin).action_revoke()
        fresh = self.env['baseer.bchat.membership'].with_user(self.admin).create({
            'room_id': self.room.id, 'user_id': self.reader.id})
        new_messages = self._fixture_messages(32, reader_member=fresh)
        before_changes = self.env['baseer.bchat.change'].sudo().search_count([])
        with self.assertRaises(ProtocolError) as stale:
            self._service(self.reader)._v2_receipt_ack(self.room.id, self.message_id, 'delivered',
                                                      membership_id=old_echo['membership_id'])
        self.assertEqual((stale.exception.code, stale.exception.status), ('membership_changed', 409))
        self.assertEqual(self.env['baseer.bchat.change'].sudo().search_count([]), before_changes)
        self.assertFalse(any(self._receipts().mapped('delivered_at')))
        page = self._service(self.reader)._v2_pending_receipts()
        self.assertEqual(len(page['refs']), 30)
        self.assertTrue(all(row['membership_id'] == fresh.id and row['message_id'] in new_messages.ids for row in page['refs']))
        self.assertFalse(set(old_messages.ids) & {row['message_id'] for row in page['refs']})
        matching = self._service(self.reader)._v2_receipt_ack(self.room.id, new_messages[0].id,
                                                             'delivered', membership_id=fresh.id)
        self.assertIsNotNone(matching['delivered_at'])
        self.reader.write({'bchat_chat_view': False})
        with self.assertRaises(AccessError):
            self._service(self.reader)._v2_pending_receipts()
        self.reader.write({'bchat_chat_view': True})
        self.assertEqual(len(self._service(self.reader)._v2_pending_receipts()['refs']), 30)

    def test_hundred_membership_candidate_bound_and_partial_index(self):
        rooms = self.env['baseer.bchat.room'].with_user(self.admin).create([
            {'name': 'Receipt lane %s' % index, 'company_id': self.company.id} for index in range(99)])
        self.env['baseer.bchat.membership'].with_user(self.admin).create([
            {'room_id': room.id, 'user_id': self.reader.id} for room in rooms])
        self.assertEqual(self.env['baseer.bchat.membership'].sudo().search_count([
            ('user_id', '=', self.reader.id), ('active', '=', True)]), 100)
        page = self._service(self.reader)._v2_pending_receipts()
        self.assertEqual(len(page['refs']), 1)
        self.env.cr.execute("SELECT indexdef FROM pg_indexes WHERE indexname=%s", [
            'baseer_bchat_receipt_pending_recipient_member_idx'])
        definition = self.env.cr.fetchone()[0]
        self.assertIn('(recipient_user_id, membership_id, id)', definition)
        self.assertIn('delivered_at IS NULL', definition)
        # Real planner evidence only; not a throughput or production capacity claim.
        self.env.cr.execute('''EXPLAIN (FORMAT JSON) SELECT id FROM baseer_bchat_message_receipt
            WHERE recipient_user_id=%s AND membership_id=%s AND delivered_at IS NULL AND id>0
            ORDER BY id LIMIT 31''', [self.reader.id, self.members[self.reader.id].id])
        self.assertIn('Plan', self.env.cr.fetchone()[0][0])

    def test_old_backlog_beyond_five_hundred_is_discovered_by_reset_pass(self):
        messages = self._fixture_messages(501)
        service = self._service(self.reader)
        initial = service._v2_pending_receipts()
        self.assertIn(self.message_id, [row['message_id'] for row in initial['refs']])
        self.assertEqual(service._v2_message(self.room.id, messages[0].id)['message']['id'], messages[0].id)
        self.assertEqual(service._v2_pending_receipts(initial['refs'][0]['receipt_id'])['refs'][0]['message_id'], messages[0].id)
        service._v2_receipt_ack(self.room.id, self.message_id, 'delivered')
        reset = service._v2_pending_receipts(0)
        self.assertNotIn(self.message_id, [row['message_id'] for row in reset['refs']])
        self.assertIn(messages[0].id, [row['message_id'] for row in reset['refs']])

    def test_gets_never_create_or_ack_and_ack_replay_preserves_timestamps(self):
        receipts = self._receipts()
        before = [(r.id, r.delivered_at, r.read_at, r.write_date) for r in receipts]
        events = self.env['baseer.bchat.change'].sudo().search_count([])
        self._service(self.reader)._v2_pending_receipts()
        canonical = self._service(self.reader)._v2_message(self.room.id, self.message_id)
        self.assertEqual((canonical['room_id'], canonical['membership_id']),
                         (self.room.id, self.members[self.reader.id].id))
        for before_id in (None, self.message_id):
            history = self._service(self.reader)._v2_history(self.room.id, before_id)
            self.assertEqual((history['room_id'], history['membership_id']),
                             (self.room.id, self.members[self.reader.id].id))
            if before_id is not None:
                self.assertEqual(history['messages'], [])
            self.assertLessEqual(len(json.dumps(history, ensure_ascii=False).encode()), 131072)
        self._service(self.owner)._v2_receipt_details(self.room.id, self.message_id)
        receipts.invalidate_recordset()
        self.assertEqual([(r.id, r.delivered_at, r.read_at, r.write_date) for r in receipts], before)
        self.assertEqual(self.env['baseer.bchat.change'].sudo().search_count([]), events)
        self.assertEqual(len(self._receipts()), len(before))
        for invalid in (None, True, False, 0, -1, 1.0, '1', 2147483648):
            with self.subTest(membership=invalid), self.assertRaises(ProtocolError) as malformed:
                self._service(self.reader)._v2_receipt_ack(self.room.id, self.message_id, 'read', membership_id=invalid)
            self.assertEqual(malformed.exception.code, 'invalid_payload')
        first = self._service(self.reader)._v2_receipt_ack(self.room.id, self.message_id, 'read',
                                                          membership_id=self.members[self.reader.id].id)
        replay = self._service(self.reader)._v2_receipt_ack(self.room.id, self.message_id, 'delivered')
        self.assertTrue(replay['replayed'])
        self.assertEqual((first['delivered_at'], first['read_at']), (replay['delivered_at'], replay['read_at']))

    def test_details_all_legacy_eligible_counts_precede_pagination_and_match_history(self):
        users = self._users(63)
        members = self._legacy_members(users)
        rows = self._add_fixture_receipts(members)
        # Leave >30 lower-ID receipts currently ineligible, without changing their timestamps.
        self.reader.write({'bchat_chat_view': False})
        self.other.write({'bchat_chat_view': False})
        users[:31].write({'bchat_chat_view': False})
        stamp = datetime(2026, 10, 18, 1, 2, 3)
        rows[31:]._write_verified({'delivered_at': stamp}, _RECEIPT_TOKEN)
        rows[31:]._write_verified({'read_at': stamp}, _RECEIPT_TOKEN)
        service = self._service(self.owner)
        details = service._v2_receipt_details(self.room.id, self.message_id)
        self.assertEqual(details['counts'], {'eligible': 32, 'delivered': 32, 'read': 32})
        self.assertEqual(details['state'], 'read')
        self.assertEqual(len(details['receipts']), 30)
        self.assertTrue(details['has_more'])
        next_page = service._v2_receipt_details(self.room.id, self.message_id, details['next_after_id'])
        self.assertEqual(len(next_page['receipts']), 2)
        self.assertEqual(next_page['counts'], details['counts'])
        self.assertEqual(service._v2_history(self.room.id)['messages'][0]['delivery_state'], details['state'])
        eligible_ids = {r.id for r in self._receipts() if not r._eligibility_exclusion_reason()}
        self.assertEqual(eligible_ids, {r['id'] for r in details['receipts'] + next_page['receipts']})
        users[31:].write({'bchat_chat_view': False})
        zero = service._v2_receipt_details(self.room.id, self.message_id)
        self.assertEqual((zero['state'], zero['counts'], zero['receipts'], zero['next_after_id'], zero['has_more']),
                         ('sent', {'eligible': 0, 'delivered': 0, 'read': 0}, [], 0, False))
        users[31:].write({'bchat_chat_view': True})
        self.assertEqual(service._v2_receipt_details(self.room.id, self.message_id)['counts'], details['counts'])

    def test_details_are_sender_only_company_and_current_sender_epoch_scoped(self):
        self._legacy_members(self.admin, administrator=True)
        for user in (self.reader, self.other, self.admin):
            with self.subTest(user=user.id), self.assertRaises(AccessError):
                self._service(user)._v2_receipt_details(self.room.id, self.message_id)
        company = self.env['res.company'].create({'name': 'Receipt foreign company'})
        foreign = self._users(1, company)
        with self.assertRaises(AccessError):
            self._service(foreign)._v2_receipt_details(self.room.id, self.message_id)
        self.members[self.owner.id].with_user(self.admin).action_revoke()
        new = self.env['baseer.bchat.membership'].with_user(self.admin).create({
            'room_id': self.room.id, 'user_id': self.owner.id})
        self.assertGreaterEqual(new.joined_after_message_id, self.message_id)
        with self.assertRaises(AccessError):
            self._service(self.owner)._v2_receipt_details(self.room.id, self.message_id)

    def test_detail_names_use_native_visibility_and_one_bounded_batch(self):
        users = self._users(30)
        self._add_fixture_receipts(self._legacy_members(users))
        hidden = users[0]
        self.env['ir.rule'].create({
            'name': 'Receipt name privacy fixture', 'model_id': self.env['ir.model']._get_id('res.users'),
            'domain_force': "[('id','!=',%s)]" % hidden.id,
            'perm_read': True, 'perm_write': False, 'perm_create': False, 'perm_unlink': False})
        service = self._service(self.owner)
        original = type(service)._v2_visible_user_names
        batches = []
        def observed(recordset, ids):
            batches.append(list(ids))
            return original(recordset, ids)
        with patch.object(type(service), '_v2_visible_user_names', observed):
            details = service._v2_receipt_details(self.room.id, self.message_id)
        self.assertEqual(len(batches), 1)
        self.assertLessEqual(len(batches[0]), 30)
        by_user = {row['user_id']: row['user_name'] for row in details['receipts']}
        self.assertEqual(by_user[hidden.id], 'User')
        self.assertEqual(by_user[users[1].id], users[1].name)


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_delivery_receipts')
class BChatDeliveryReceiptsHttpCase(HttpCase):
    def _fixture(self):
        company = self.env.company
        password = 'test-only-' + uuid4().hex
        users = self.env['res.users'].with_context(no_reset_password=True).create([{
            'name': 'Receipt HTTP %s' % index, 'login': 'bchat-receipt-http-' + uuid4().hex,
            'password': password, 'company_id': company.id, 'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        } for index in range(2)])
        owner, reader = users
        service = self.env['baseer.bchat.service'].with_user(owner)
        room = service._v2_group_create({'api_version': 2, 'company_id': company.id,
            'client_uuid': str(uuid4()), 'name': 'Receipt HTTP', 'member_user_ids': [reader.id]})
        message = service._v2_send(room['room_id'], {'api_version': 2, 'membership_id': room['membership_id'],
            'client_uuid': str(uuid4()), 'text': 'HTTP receipt canonical'})['message_id']
        return owner, reader, password, room['room_id'], message

    def test_authenticated_get_query_headers_and_recipient_privacy(self):
        owner, reader, password, room, message = self._fixture()
        self.authenticate(reader.login, password)
        pending = self.url_open('/bchat/api/v2/receipts/pending', allow_redirects=False)
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', pending.headers)
        self.assertEqual(pending.json()['refs'][0]['message_id'], message)
        details = '/bchat/api/v2/rooms/%s/messages/%s/receipts' % (room, message)
        self.assertEqual(self.url_open(details).status_code, 403)
        for query in ('after_id=00', 'after_id=-1', 'after_id=2147483648', 'after_id=0&after_id=1', 'limit=1', 'user_id=1'):
            self.assertEqual(self.url_open('/bchat/api/v2/receipts/pending?' + query).status_code, 400)
        self.authenticate(owner.login, password)
        response = self.url_open(details + '?after_id=0')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['counts'], {'eligible': 1, 'delivered': 0, 'read': 0})
        self.assertEqual(set(response.json()['receipts'][0]), {'id', 'user_id', 'user_name', 'delivered_at', 'read_at'})

    def test_legacy_post_ack_is_csrf_protected_and_get_never_acks(self):
        owner, reader, password, room, message = self._fixture()
        self.authenticate(reader.login, password)
        bootstrap = self.url_open('/bchat/api/v2/bootstrap').json()
        self.assertEqual(bootstrap['receipt_delivery_contract_version'], 1)
        endpoint = '/bchat/api/v2/rooms/%s/messages/%s/receipts' % (room, message)
        self.assertNotEqual(self.url_open(endpoint, data={'kind': 'delivered'}, allow_redirects=False).status_code, 200)
        member = self.url_open('/bchat/api/v2/receipts/pending').json()['refs'][0]['membership_id']
        for invalid in ('0', 'true', '00', '1.0', '', '2147483648'):
            self.assertEqual(self.url_open(endpoint, data={'csrf_token': bootstrap['csrf_token'],
                'kind': 'delivered', 'membership_id': invalid}).status_code, 400)
        duplicate = self.url_open(endpoint, data=[('csrf_token', bootstrap['csrf_token']),
            ('kind', 'delivered'), ('membership_id', str(member)), ('membership_id', str(member))])
        self.assertEqual(duplicate.status_code, 400)
        delivered = self.url_open(endpoint, data={'csrf_token': bootstrap['csrf_token'], 'kind': 'delivered',
                                                 'membership_id': str(member)})
        self.assertEqual(delivered.status_code, 200)
        self.assertIsNone(delivered.json()['read_at'])
        self.assertEqual(self.url_open('/bchat/api/v2/receipts/pending').json()['refs'], [])
        replay = self.url_open(endpoint, data={'csrf_token': bootstrap['csrf_token'], 'kind': 'delivered'})
        self.assertTrue(replay.json()['replayed'])
        self.assertEqual(replay.json()['delivered_at'], delivered.json()['delivered_at'])
