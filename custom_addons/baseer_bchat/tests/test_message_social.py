"""C32 behavior: private projections over immutable, epoch-bound messages."""
import hashlib
import io
import json
from uuid import uuid4
from unittest.mock import patch

from PIL import Image
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..contracts import ProtocolError


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_message_social')
class BChatMessageSocialCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.admin = self.env.ref('base.user_admin')
        self.admin.write({'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        self.owner, self.reader, self.other = self._users(3)
        self.owner_service = self._service(self.owner)
        created = self.owner_service._v2_group_create({
            'api_version': 2, 'company_id': self.company.id, 'client_uuid': str(uuid4()),
            'name': 'Message social fixture', 'member_user_ids': [self.reader.id, self.other.id],
        })
        self.room = self.env['baseer.bchat.room'].sudo().browse(created['room_id'])
        self.members = {row.user_id.id: row for row in self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room.id), ('active', '=', True)])}
        self.message_id = self._send(self.owner)['message_id']

    def _users(self, count, company=None):
        company = company or self.company
        return self.env['res.users'].with_context(no_reset_password=True).create([{
            'name': 'Message social user %s' % index, 'login': 'bchat-social-' + uuid4().hex,
            'company_id': company.id, 'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        } for index in range(count)])

    def _service(self, user):
        return self.env['baseer.bchat.service'].with_user(user)

    def _send(self, user, **extra):
        return self._service(user)._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.members[user.id].id,
            'client_uuid': str(uuid4()), 'text': 'Immutable source', **extra})

    def _mutation(self, user, **extra):
        return {'api_version': 2, 'membership_id': self.members[user.id].id,
                'client_uuid': str(uuid4()), 'expected_revision': 0, **extra}

    def _metadata(self, user, ids=None):
        return self._service(user)._v2_social_metadata(
            self.room.id, self.members[user.id].id, ids or [self.message_id])

    def test_default_gets_do_not_write_and_private_models_deny_ordinary_manager_and_portal(self):
        models = ('baseer.bchat.message.reaction', 'baseer.bchat.message.saved', 'baseer.bchat.message.mention')
        before = {name: self.env[name].sudo().search_count([]) for name in models}
        row = self._metadata(self.reader)['rows'][0]
        self.assertEqual(row, {'message_id': self.message_id, 'reaction_counts': [], 'own_reaction': None,
                               'reaction_revision': 0, 'saved': False, 'saved_revision': 0, 'mention_user_ids': []})
        self.assertEqual(self._service(self.reader)._v2_saved_messages()['saved'], [])
        self.assertEqual({name: self.env[name].sudo().search_count([]) for name in models}, before)
        portal = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Social portal', 'login': 'social-portal-' + uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_portal').id])],
        })
        for name in models:
            for user in (self.reader, self.admin, portal):
                with self.subTest(model=name, user=user.id):
                    for operation in ('read', 'create', 'write', 'unlink'):
                        self.assertFalse(self.env[name].with_user(user).has_access(operation))
        with self.assertRaises(AccessError):
            self._service(self.admin)._v2_social_metadata(self.room.id, self.members[self.reader.id].id, [self.message_id])

    def test_reaction_cas_retry_counts_and_receipts_are_unchanged(self):
        message = self.env['baseer.bchat.message'].sudo().browse(self.message_id)
        before_message = (message.text, message.payload_digest, message.write_date)
        receipts = self.env['baseer.bchat.message.receipt'].sudo().search([('message_id', '=', message.id)])
        before_receipts = [(row.id, row.delivered_at, row.read_at) for row in receipts]
        payload = self._mutation(self.reader, emoji='👍')
        first = self._service(self.reader)._v2_message_reaction(self.room.id, message.id, payload)
        self.assertEqual(first['reaction_revision'], 1)
        self.assertEqual(first['reaction_counts'], [{'emoji': '👍', 'count': 1}])
        self.assertTrue(self._service(self.reader)._v2_message_reaction(self.room.id, message.id, payload)['replayed'])
        with self.assertRaises(ProtocolError) as conflict:
            self._service(self.reader)._v2_message_reaction(self.room.id, message.id, {**payload, 'emoji': '❤️'})
        self.assertEqual(conflict.exception.code, 'idempotency_conflict')
        with self.assertRaises(ProtocolError) as stale:
            self._service(self.reader)._v2_message_reaction(self.room.id, message.id, self._mutation(self.reader, emoji='😂'))
        self.assertEqual(stale.exception.code, 'revision_conflict')
        self._service(self.other)._v2_message_reaction(self.room.id, message.id, self._mutation(self.other, emoji='👍'))
        self.assertEqual(self._metadata(self.owner)['rows'][0]['reaction_counts'], [{'emoji': '👍', 'count': 2}])
        removed = self._service(self.reader)._v2_message_reaction(self.room.id, message.id,
            self._mutation(self.reader, emoji=None, expected_revision=1))
        self.assertIsNone(removed['own_reaction'])
        self.assertEqual(removed['reaction_revision'], 2)
        self.assertEqual(removed['reaction_counts'], [{'emoji': '👍', 'count': 1}])
        message.invalidate_recordset()
        receipts.invalidate_recordset()
        self.assertEqual((message.text, message.payload_digest, message.write_date), before_message)
        self.assertEqual([(row.id, row.delivered_at, row.read_at) for row in receipts], before_receipts)

    def test_saved_is_private_view_only_and_rejoin_cannot_resurrect_old_reference(self):
        self.reader.write({'bchat_chat_send': False})
        payload = self._mutation(self.reader, saved=True)
        saved = self._service(self.reader)._v2_message_saved(self.room.id, self.message_id, payload)
        self.assertTrue(saved['saved'])
        self.assertEqual(saved['saved_revision'], 1)
        self.assertTrue(self._service(self.reader)._v2_message_saved(self.room.id, self.message_id, payload)['replayed'])
        self.assertEqual(self._service(self.other)._v2_saved_messages()['saved'], [])
        listing = self._service(self.reader)._v2_saved_messages()
        self.assertEqual(listing['saved'][0]['message']['id'], self.message_id)
        self.assertEqual(listing['message_edit_policy'], 'immutable')
        with self.assertRaises(AccessError):
            self._service(self.reader)._v2_message_reaction(self.room.id, self.message_id,
                self._mutation(self.reader, emoji='👍'))
        old = self.members[self.reader.id]
        old.with_user(self.admin).action_revoke()
        self.assertEqual(self._service(self.reader)._v2_saved_messages()['saved'], [])
        with self.assertRaises(AccessError):
            self._service(self.reader)._v2_message_saved(self.room.id, self.message_id, payload)
        new = self.env['baseer.bchat.membership'].with_user(self.admin).create({
            'room_id': self.room.id, 'user_id': self.reader.id})
        self.assertNotEqual(old.id, new.id)
        self.assertEqual(self._service(self.reader)._v2_saved_messages()['saved'], [])
        # The current epoch matches; only the old message is outside its visibility boundary.
        with self.assertRaises(AccessError):
            self._service(self.reader)._v2_social_metadata(self.room.id, new.id, [self.message_id])

    def test_saved_unset_and_current_permission_revocation(self):
        self._service(self.reader)._v2_message_saved(self.room.id, self.message_id, self._mutation(self.reader, saved=True))
        removed = self._service(self.reader)._v2_message_saved(self.room.id, self.message_id,
            self._mutation(self.reader, saved=False, expected_revision=1))
        self.assertFalse(removed['saved'])
        self.assertEqual(removed['saved_revision'], 2)
        self.assertEqual(self._service(self.reader)._v2_saved_messages()['saved'], [])
        self.reader.write({'bchat_chat_view': False})
        with self.assertRaises(AccessError):
            self._service(self.reader)._v2_saved_messages()
        with self.assertRaises(AccessError):
            self._metadata(self.reader)

    def test_explicit_mentions_share_one_send_and_cannot_upgrade_legacy_replay(self):
        payload = {'api_version': 2, 'membership_id': self.members[self.owner.id].id,
                   'client_uuid': str(uuid4()), 'text': '@Reader is not parsed', 'mention_user_ids': [self.reader.id]}
        receipts_before = self.env['baseer.bchat.message.receipt'].sudo().search_count([])
        sent = self.owner_service._v2_social_send(self.room.id, payload)
        self.assertEqual(self.owner_service._v2_social_send(self.room.id, payload), sent)
        self.assertEqual(self.env['baseer.bchat.message.receipt'].sudo().search_count([]), receipts_before + 2)
        mentions = self.env['baseer.bchat.message.mention'].sudo().search([('message_id', '=', sent['message_id'])])
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions.recipient_membership_id, self.members[self.reader.id])
        self.assertEqual(self._metadata(self.reader, [sent['message_id']])['rows'][0]['mention_user_ids'], [self.reader.id])
        with self.assertRaises(ProtocolError) as changed:
            self.owner_service._v2_social_send(self.room.id, {**payload, 'mention_user_ids': [self.other.id]})
        self.assertEqual(changed.exception.code, 'idempotency_conflict')
        legacy = {'api_version': 2, 'membership_id': self.members[self.owner.id].id,
                  'client_uuid': str(uuid4()), 'text': '@Reader only text'}
        old = self.owner_service._v2_send(self.room.id, legacy)
        self.assertEqual(self.owner_service._v2_social_send(self.room.id, {**legacy, 'mention_user_ids': []}), old)
        with self.assertRaises(ProtocolError):
            self.owner_service._v2_social_send(self.room.id, {**legacy, 'mention_user_ids': [self.reader.id]})
        self.assertFalse(self.env['baseer.bchat.message.mention'].sudo().search([('message_id', '=', old['message_id'])]))

    def test_mentions_reject_nonmembers_and_preserve_media_reply_digest(self):
        stranger = self._users(1)
        payload = {'api_version': 2, 'membership_id': self.members[self.owner.id].id,
                   'client_uuid': str(uuid4()), 'text': 'Mention', 'mention_user_ids': [stranger.id]}
        before = self.env['baseer.bchat.message'].sudo().search_count([])
        with self.assertRaises(AccessError):
            self.owner_service._v2_social_send(self.room.id, payload)
        self.assertEqual(self.env['baseer.bchat.message'].sudo().search_count([]), before)
        stream = io.BytesIO()
        Image.new('RGB', (8, 8), '#123456').save(stream, format='PNG')
        raw = stream.getvalue()
        media = self.owner_service._v2_upload(self.room.id, {
            'api_version': 2, 'membership_id': self.members[self.owner.id].id, 'upload_uuid': str(uuid4()),
            'kind': 'image', 'mime': 'image/png', 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'name': 'mention.png'}, raw)
        mixed = {**payload, 'client_uuid': str(uuid4()), 'mention_user_ids': [self.reader.id],
                 'media_id': media['media_id'], 'reply_to_message_id': self.message_id}
        # This is the real base finalization seam, not a claim that the
        # optional DMS adapter is installed in this isolated core database.
        original_finalize = type(self.owner_service)._v2_finalize_document
        with patch.object(type(self.owner_service), '_v2_finalize_document', autospec=True,
                          side_effect=original_finalize) as finalized:
            sent = self.owner_service._v2_social_send(self.room.id, mixed)
            self.assertEqual(self.owner_service._v2_social_send(self.room.id, mixed), sent)
        self.assertEqual(finalized.call_count, 1)
        message = self.env['baseer.bchat.message'].sudo().browse(sent['message_id'])
        self.assertEqual(message.reply_to_message_id.id, self.message_id)
        self.assertEqual(message.media_id.state, 'attached')
        self.assertEqual(message.media_id.message_id, message)
        self.members[self.reader.id].with_user(self.admin).action_revoke()
        self.assertEqual(self._metadata(self.owner, [message.id])['rows'][0]['mention_user_ids'], [])

    def test_saved_visibility_precedes_limit_and_utf8_cursor_never_skips_retained_rows(self):
        service = self._service(self.reader)
        visible = []
        for _index in range(20):
            message_id = self._send(self.owner, text='محتوى ' * 1000)['message_id']
            service._v2_message_saved(self.room.id, message_id, self._mutation(self.reader, saved=True))
            visible.append(message_id)
        hidden = self.owner_service._v2_group_create({
            'api_version': 2, 'company_id': self.company.id, 'client_uuid': str(uuid4()),
            'name': 'Revoked saved references', 'member_user_ids': [self.reader.id]})
        hidden_member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', hidden['room_id']), ('user_id', '=', self.reader.id), ('active', '=', True)])
        for _index in range(31):
            message = self.owner_service._v2_send(hidden['room_id'], {
                'api_version': 2, 'membership_id': hidden['membership_id'], 'client_uuid': str(uuid4()), 'text': 'Hidden'})
            service._v2_message_saved(hidden['room_id'], message['message_id'], {
                **self._mutation(self.reader, saved=True), 'membership_id': hidden_member.id})
        hidden_member.with_user(self.admin).action_revoke()
        seen, before_id = [], None
        for _page in range(21):
            page = service._v2_saved_messages(before_id)
            self.assertLessEqual(len(page['saved']), 30)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode('utf-8')), 131072)
            ids = [row['message']['id'] for row in page['saved']]
            self.assertFalse(set(ids) & set(seen))
            seen.extend(ids)
            if page['next_before_id'] is None:
                break
            self.assertEqual(page['next_before_id'], page['saved'][-1]['id'])
            before_id = page['next_before_id']
        self.assertEqual(set(seen), set(visible))
        self.assertEqual(len(seen), len(visible))

    def test_foreign_company_and_ineligible_mention_targets_do_not_receive_metadata(self):
        foreign_company = self.env['res.company'].create({'name': 'Social foreign company'})
        foreign = self._users(1, company=foreign_company)
        with self.assertRaises(AccessError):
            self._service(foreign)._v2_social_metadata(self.room.id, self.members[self.reader.id].id, [self.message_id])
        self.reader.write({'bchat_chat_view': False})
        with self.assertRaises(AccessError):
            self.owner_service._v2_social_send(self.room.id, {
                'api_version': 2, 'membership_id': self.members[self.owner.id].id,
                'client_uuid': str(uuid4()), 'text': 'No unauthorized target', 'mention_user_ids': [self.reader.id]})

    def test_strict_projection_and_mutation_bounds(self):
        for emoji in ('❤', '❤️x', '', 1, True, ['👍']):
            with self.subTest(emoji=emoji), self.assertRaises(ProtocolError):
                self._service(self.reader)._v2_message_reaction(self.room.id, self.message_id,
                    self._mutation(self.reader, emoji=emoji))
        for ids in ([], [self.message_id] * 2, list(range(1, 32)), [True]):
            with self.subTest(ids=ids), self.assertRaises(ProtocolError):
                self._service(self.reader)._v2_social_metadata(self.room.id, self.members[self.reader.id].id, ids)
        with self.assertRaises(ProtocolError):
            self._service(self.reader)._v2_message_saved(self.room.id, self.message_id,
                self._mutation(self.reader, saved=1))

    def test_author_name_resolver_is_query_bounded_and_preserves_native_visibility(self):
        authors = self._users(30)
        self.owner_service._v2_group_add_members(self.room.id, {
            'api_version': 2, 'membership_id': self.members[self.owner.id].id,
            'client_uuid': str(uuid4()), 'user_ids': authors.ids})
        members = {row.user_id.id: row.id for row in self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room.id), ('user_id', 'in', authors.ids), ('active', '=', True)])}
        message_ids = []
        expected = {author.id: author.name for author in authors}
        for author in authors:
            message_ids.append(self._service(author)._v2_send(self.room.id, {
                'api_version': 2, 'membership_id': members[author.id], 'client_uuid': str(uuid4()),
                'text': 'Distinct resolver author'})['message_id'])
        archived_id, hidden_id = authors[0].id, authors[-1].id
        authors[0].write({'active': False})
        # A native, read-only global rule in this rollback-only fixture, not
        # a product ACL or a fake permission resolver. It hides just one author.
        self.env['ir.rule'].create({
            'name': 'C32 author resolver visibility fixture',
            'model_id': self.env['ir.model']._get_id('res.users'),
            'domain_force': "[('id','!=',%s)]" % hidden_id,
            'perm_read': True, 'perm_write': False, 'perm_create': False, 'perm_unlink': False,
        })
        self.env.flush_all()
        measured = []
        for selected in (message_ids[:3], message_ids):
            self.env.invalidate_all()
            reader_users = self.env['res.users'].with_user(self.reader).with_context(active_test=False)
            # Prime only ACL/rule computation, then clear all record values.
            reader_users.search_read([('id', '=', self.reader.id)], fields=['name'], limit=1)
            self.env.invalidate_all()
            page = self.env['baseer.bchat.message'].sudo().browse(selected)
            # Input message FK reads are outside the resolver's measured work.
            page.mapped('author_user_id')
            before = self.env.cr.sql_log_count
            names = self._service(self.reader)._v2_author_names(page)
            measured.append(self.env.cr.sql_log_count - before)
            for author_id, name in names.items():
                self.assertEqual(name, 'User' if author_id == hidden_id else expected[author_id])
            self.assertEqual(names[archived_id], expected[archived_id])
            if len(selected) == 30:
                self.assertEqual(names[hidden_id], 'User')
        self.assertLessEqual(measured[1], measured[0] + 2)
        self.assertLessEqual(max(measured), 6)


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_message_social')
class BChatMessageSocialHttpCase(HttpCase):
    def test_authenticated_additive_routes_csrf_and_no_store(self):
        company = self.env.company
        password = 'test-only-' + uuid4().hex
        users = self.env['res.users'].with_context(no_reset_password=True).create([{
            'name': 'Social HTTP %s' % index, 'login': 'social-http-' + uuid4().hex,
            'password': password, 'company_id': company.id, 'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        } for index in range(2)])
        owner, reader = users
        service = self.env['baseer.bchat.service'].with_user(owner)
        room = service._v2_group_create({'api_version': 2, 'company_id': company.id,
            'client_uuid': str(uuid4()), 'name': 'Social HTTP', 'member_user_ids': [reader.id]})
        sent = service._v2_send(room['room_id'], {'api_version': 2, 'membership_id': room['membership_id'],
            'client_uuid': str(uuid4()), 'text': 'HTTP immutable message'})
        member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room['room_id']), ('user_id', '=', reader.id), ('active', '=', True)])
        self.authenticate(reader.login, password)
        csrf = self.url_open('/bchat/api/v2/bootstrap').json()['csrf_token']
        metadata_url = '/bchat/api/v2/rooms/%s/social-metadata?membership_id=%s&message_ids=%s' % (
            room['room_id'], member.id, sent['message_id'])
        projection = self.url_open(metadata_url, allow_redirects=False)
        self.assertEqual(projection.status_code, 200)
        self.assertEqual(projection.headers['Cache-Control'], 'no-store')
        self.assertEqual(projection.json()['rows'][0]['reaction_revision'], 0)
        reaction_url = '/bchat/api/v2/rooms/%s/messages/%s/reaction' % (room['room_id'], sent['message_id'])
        payload = {'api_version': 2, 'membership_id': member.id, 'client_uuid': str(uuid4()),
                   'expected_revision': 0, 'emoji': '❤️'}
        denied = self.url_open(reaction_url, data={'payload': json.dumps(payload)}, allow_redirects=False)
        self.assertNotEqual(denied.status_code, 200)
        changed = self.url_open(reaction_url, data={'csrf_token': csrf, 'payload': json.dumps(payload)}, allow_redirects=False)
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()['own_reaction'], '❤️')
        saved_url = '/bchat/api/v2/rooms/%s/messages/%s/saved' % (room['room_id'], sent['message_id'])
        saved = self.url_open(saved_url, data={'csrf_token': csrf, 'payload': json.dumps({
            'api_version': 2, 'membership_id': member.id, 'client_uuid': str(uuid4()),
            'expected_revision': 0, 'saved': True})}, allow_redirects=False)
        self.assertEqual(saved.status_code, 200)
        listing = self.url_open('/bchat/api/v2/social/saved', allow_redirects=False)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()['saved'][0]['message']['id'], sent['message_id'])
        mention = {'api_version': 2, 'membership_id': member.id, 'client_uuid': str(uuid4()),
                   'text': 'Explicit HTTP mention', 'mention_user_ids': [owner.id]}
        social_send = self.url_open('/bchat/api/v2/rooms/%s/social/messages' % room['room_id'],
            data={'csrf_token': csrf, 'payload': json.dumps(mention)}, allow_redirects=False)
        self.assertEqual(social_send.status_code, 200)
        legacy_send = self.url_open('/bchat/api/v2/rooms/%s/messages' % room['room_id'],
            data={'csrf_token': csrf, 'payload': json.dumps({**mention, 'client_uuid': str(uuid4())})}, allow_redirects=False)
        self.assertEqual(legacy_send.status_code, 400)
        self.assertEqual(self.url_open(metadata_url + '&user_id=%s' % owner.id).status_code, 400)
        edit = self.url_open('/bchat/api/v2/rooms/%s/messages/%s/edit' % (room['room_id'], sent['message_id']),
                             data={'csrf_token': csrf, 'payload': '{}'}, allow_redirects=False)
        self.assertNotEqual(edit.status_code, 200)
