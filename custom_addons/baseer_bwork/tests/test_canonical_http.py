"""Native sessions exercise canonical and distributed-client aliases equally."""
import hashlib
import json
from uuid import uuid4

from odoo import Command
from odoo.tests import HttpCase, tagged

from ..compatibility import routes


@tagged('post_install', '-at_install', 'bwork_canonical')
class BWorkCanonicalHttpCase(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'BCR-SYNTHETIC-' + uuid4().hex
        cls.company = cls.env.company
        cls.admin = cls.env.ref('base.user_admin')
        cls.admin.write({'group_ids': [Command.link(cls.env.ref('baseer_bwork.group_bwork_manager').id)]})
        cls.member = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BCR synthetic HTTP member', 'login': 'bcr-http-' + uuid4().hex,
            # Explicit opt-in keeps alias/replay tests about their original guard.
            'bwork_chat_view': True, 'bwork_chat_send': True, 'bwork_media': True,
            'password': cls.password, 'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set(cls.env.ref('base.group_user').ids)]})
        cls.stranger = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BCR synthetic HTTP nonmember', 'login': 'bcr-other-' + uuid4().hex,
            'bwork_chat_view': True, 'bwork_chat_send': True, 'bwork_media': True,
            'password': cls.password, 'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set(cls.env.ref('base.group_user').ids)]})
        cls.room = cls.env['baseer.bwork.room'].with_user(cls.admin).with_company(cls.company).create({
            'name': 'BCR synthetic alias room', 'company_id': cls.company.id})
        cls.member_epoch = cls.env['baseer.bwork.membership'].with_user(cls.admin).with_company(cls.company).create({
            'room_id': cls.room.id, 'user_id': cls.member.id})

    def test_old_and_canonical_bootstrap_contract_keys_and_session_are_same(self):
        self.authenticate(self.member.login, self.password)
        for version in (1, 2):
            current, old = [self.url_open(path) for path in routes('/bwork/api/v%s/bootstrap' % version)]
            self.assertEqual(current.status_code, 200)
            self.assertEqual(old.status_code, 200)
            first, second = current.json(), old.json()
            self.assertEqual(set(first), set(second))
            self.assertTrue(first.pop('csrf_token'))
            self.assertTrue(second.pop('csrf_token'))
            self.assertEqual(first, second)
            self.assertEqual(first['user_id'], self.member.id)
            self.assertEqual(current.headers['Cache-Control'], 'no-store')
            self.assertEqual(old.headers['Cache-Control'], 'no-store')
        self.logout()
        for path in routes('/bwork/api/v2/bootstrap'):
            self.assertNotEqual(self.url_open(path, allow_redirects=False).status_code, 200)

    def test_cross_alias_uuid_replay_and_csrf_then_permission_denial(self):
        self.authenticate(self.member.login, self.password)
        bootstrap = self.url_open('/bwork/api/v2/bootstrap').json()
        payload = {'api_version': 2, 'membership_id': self.member_epoch.id,
                   'client_uuid': str(uuid4()), 'text': 'BCR synthetic original text'}
        endpoints = routes('/bwork/api/v2/rooms/%s/messages' % self.room.id)
        responses = [self.url_open(path, data={'csrf_token': bootstrap['csrf_token'],
                                             'payload': json.dumps(payload)}, allow_redirects=False)
                     for path in reversed(endpoints)]
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertEqual(responses[0].json(), responses[1].json())
        self.assertEqual(self.env['baseer.bwork.message'].sudo().search_count([
            ('author_user_id', '=', self.member.id), ('client_uuid', '=', payload['client_uuid'])]), 1)
        for path in endpoints:
            self.assertNotEqual(self.url_open(path, data={'payload': json.dumps(payload)},
                                              allow_redirects=False).status_code, 200)
        self.member.write({'bwork_chat_send': False})
        denied = {**payload, 'client_uuid': str(uuid4())}
        for path in endpoints:
            self.assertEqual(self.url_open(path, data={'csrf_token': bootstrap['csrf_token'],
                                                       'payload': json.dumps(denied)}).status_code, 403)

    def test_private_bytes_dual_revision_headers_conflict_and_nonmember_denial(self):
        raw = b'%PDF-1.4\nBCR-SYNTHETIC-HTTP\n%%EOF\n'
        service = self.env['baseer.bwork.service'].with_user(self.member).with_company(self.company)
        upload = service._v2_upload(self.room.id, {
            'api_version': 2, 'membership_id': self.member_epoch.id, 'upload_uuid': str(uuid4()),
            'kind': 'file', 'mime': 'application/pdf', 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'name': 'BCR synthetic.pdf'}, raw)
        service._v2_send(self.room.id, {'api_version': 2, 'membership_id': self.member_epoch.id,
                                      'client_uuid': str(uuid4()), 'text': '', 'media_id': upload['media_id']})
        self.authenticate(self.member.login, self.password)
        paths = routes('/bwork/api/v2/media/%s/content' % upload['media_id'])
        for path in paths:
            response = self.url_open(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, raw)
            self.assertEqual(response.headers['X-BWork-Content-Revision'], response.headers['X-BChat-Content-Revision'])
            conflict = self.url_open(path, headers={'X-BWork-Content-Revision': '1', 'X-BChat-Content-Revision': '2'})
            self.assertEqual(conflict.status_code, 400)
        self.authenticate(self.stranger.login, self.password)
        for path in paths:
            self.assertEqual(self.url_open(path).status_code, 403)
