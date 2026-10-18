"""Real Odoo HTTP/CSRF boundary for terminal personal-preference cancellation.

Disposable HttpCase fixtures only; never contacts FCM or another server.
"""
from datetime import timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_social_preferences')
class BChatMembershipCancelHttpCase(HttpCase):
    def _fixture(self):
        self.password = 'test-only-' + uuid4().hex
        self.user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Cancellation HTTP ' + uuid4().hex, 'login': 'bchat-cancel-http-' + uuid4().hex,
            'password': self.password, 'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.owner = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Cancellation owner ' + uuid4().hex, 'login': 'bchat-cancel-owner-' + uuid4().hex,
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.owner_service = self.env['baseer.bchat.service'].with_user(self.owner)
        created = self.owner_service._v2_group_create({
            'api_version': 2, 'company_id': self.env.company.id, 'client_uuid': str(uuid4()),
            'name': 'Cancellation HTTP group', 'member_user_ids': [self.user.id],
        })
        self.room_id = created['room_id']
        self.member_id = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room_id), ('user_id', '=', self.user.id), ('active', '=', True)], limit=1).id
        self.path = '/bchat/api/v2/rooms/%s/preferences' % self.room_id
        self.authenticate(self.user.login, self.password)
        bootstrap = self.url_open('/bchat/api/v2/bootstrap')
        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.json()['room_preferences_cancel_contract_version'], 1)
        self.csrf = bootstrap.json()['csrf_token']
        return {'api_version': 2, 'membership_id': self.member_id, 'client_uuid': str(uuid4()),
                'expected_revision': 1, 'muted_until': None, 'mute_forever': False, 'pinned': False, 'archived': True}

    def _post(self, payload, cancel=True, suffix=''):
        return self.url_open(self.path + ('/cancel' if cancel else '') + suffix,
                             data={'csrf_token': self.csrf, 'payload': json.dumps(payload)}, allow_redirects=False)

    def test_cancel_http_session_csrf_form_query_and_shape_are_required(self):
        payload = self._fixture()
        missing = self.url_open(self.path + '/cancel', data={'payload': json.dumps(payload)}, allow_redirects=False)
        self.assertNotEqual(missing.status_code, 200)
        self.assertEqual(self._post(payload, suffix='?unexpected=1').status_code, 400)
        self.assertEqual(self._post({**payload, 'cancelled': True}).status_code, 400)
        self.assertEqual(self._post({**payload, 'membership_id': True}).status_code, 400)
        raw = self.url_open(self.path + '/cancel', data=json.dumps(payload),
                            headers={'Content-Type': 'application/json'}, allow_redirects=False)
        self.assertNotEqual(raw.status_code, 200)
        self.logout()
        anonymous = self._post(payload)
        self.assertNotEqual(anonymous.status_code, 200)
        self.assertFalse(self.env['baseer.bchat.social.operation'].sudo().search_count([
            ('actor_id', '=', self.user.id), ('action', '=', 'room_preferences')]))

    def test_cancel_http_expired_duplicate_and_late_original_exact_receipt(self):
        payload = {**self._fixture(), 'muted_until': '2020-01-01T00:00:00Z'}
        expected = {'api_version': 2, 'room_id': self.room_id, 'membership_id': self.member_id,
                    'client_uuid': payload['client_uuid'], 'expected_revision': 1, 'cancelled': True}
        self.assertEqual(self._post(payload, cancel=False).status_code, 400)
        for cancel in (True, True, False):
            response = self._post(payload, cancel=cancel)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), expected)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        conflict = self._post({**payload, 'pinned': True}, cancel=False)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()['error']['code'], 'idempotency_conflict')
        current = self.url_open(self.path + '?membership_id=%s' % self.member_id)
        self.assertEqual((current.status_code, current.json()['revision'], current.json()['archived']), (200, 1, False))
        rows = self.env['baseer.bchat.social.operation'].sudo().search([
            ('actor_id', '=', self.user.id), ('action', '=', 'room_preferences'), ('client_uuid', '=', payload['client_uuid'])])
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows.result_json), {'cancelled': True})

    def test_cancel_http_applied_expired_returns_authorized_current_ack(self):
        payload = self._fixture()
        until = fields.Datetime.now() + timedelta(hours=1)
        payload.update({'muted_until': until.strftime('%Y-%m-%dT%H:%M:%SZ'), 'pinned': True})
        applied = self._post(payload, cancel=False)
        self.assertEqual(applied.status_code, 200, applied.text)
        newer = {**payload, 'client_uuid': str(uuid4()), 'expected_revision': 2,
                 'muted_until': None, 'pinned': False, 'archived': False}
        changed = self._post(newer, cancel=False)
        self.assertEqual(changed.status_code, 200, changed.text)
        with patch('odoo.addons.baseer_bchat.models.membership_preference.fields.Datetime.now',
                   return_value=until + timedelta(seconds=1)):
            for cancel in (True, False):
                replay = self._post(payload, cancel=cancel)
                self.assertEqual(replay.status_code, 200, replay.text)
                data = replay.json()
                self.assertEqual((data['revision'], data['operation_revision']), (3, 2))
                self.assertTrue(data['replayed'])
                self.assertFalse(data['pinned'])
                self.assertFalse(data['muted'])
                self.assertNotIn('cancelled', data)

    def test_cancel_http_current_company_permission_and_epoch_are_rechecked(self):
        payload = self._fixture()
        self.assertEqual(self._post({**payload, 'membership_id': payload['membership_id'] + 1000000}).status_code, 409)
        admin = self.env.ref('base.user_admin')
        admin.write({'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        company = self.env['res.company'].create({'name': 'Cancellation HTTP foreign ' + uuid4().hex})
        admin.write({'company_ids': [Command.link(company.id)]})
        foreign = self.env['baseer.bchat.room'].with_user(admin).with_company(company).create({
            'name': 'Cancellation HTTP foreign room', 'company_id': company.id})
        denied = self.url_open('/bchat/api/v2/rooms/%s/preferences/cancel' % foreign.id,
                               data={'csrf_token': self.csrf, 'payload': json.dumps(payload)}, allow_redirects=False)
        self.assertEqual(denied.status_code, 403)
        self.user.with_user(admin).write({'bchat_chat_view': False})
        self.assertEqual(self._post(payload).status_code, 403)
        self.user.with_user(admin).write({'bchat_chat_view': True})
        self.owner_service._v2_group_change(self.room_id, {'api_version': 2, 'action': 'remove_member', 'user_id': self.user.id})
        self.owner_service._v2_group_change(self.room_id, {'api_version': 2, 'action': 'add_member', 'user_id': self.user.id})
        obsolete = self._post(payload)
        self.assertEqual(obsolete.status_code, 409)
        self.assertEqual(obsolete.json()['error']['code'], 'membership_changed')
