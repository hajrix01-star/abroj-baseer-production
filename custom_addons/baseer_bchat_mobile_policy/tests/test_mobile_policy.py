"""Disposable model tests; never create test users in an operational database."""
import hashlib
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from odoo.addons.baseer_bchat.contracts import ProtocolError
from odoo.addons.baseer_bchat.models.room import _GROUP_TOKEN


@tagged('post_install', '-at_install', 'baseer_bchat_mobile_policy')
class MobilePolicyCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Mobile policy synthetic A'})
        cls.foreign = cls.env['res.company'].create({'name': 'Mobile policy synthetic B'})
        cls.admin = cls.env.ref('base.user_admin')
        cls.admin.write({'company_ids': [Command.link(cls.company.id), Command.link(cls.foreign.id)]})
        cls.member = cls._user('member', cls.company)
        cls.colleague = cls._user('colleague', cls.company)
        cls.outsider = cls._user('outsider', cls.company)
        cls.foreign_user = cls._user('foreign', cls.foreign)
        cls.manager = cls._user('manager', cls.company, bchat_mobile_admin=True)
        cls.service = cls.env['baseer.bchat.service'].with_user(cls.member)
        cls.manager_service = cls.env['baseer.bchat.service'].with_user(cls.manager)

    @classmethod
    def _user(cls, name, company, **extra):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Mobile policy ' + name, 'login': 'mobile-policy-' + uuid4().hex,
            'company_id': company.id, 'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])], **extra,
        })

    def _toggle(self, enabled, company=None, service=None):
        return (service or self.manager_service)._mobile_policy_set({
            'api_version': 2, 'company_id': (company or self.company).id, 'direct_enabled': enabled,
        })

    def _open(self, target=None, service=None, company=None, **extra):
        return (service or self.service)._mobile_direct({
            'api_version': 2, 'company_id': (company or self.company).id,
            'user_id': (target or self.colleague).id, 'client_uuid': str(uuid4()), **extra,
        })

    def _text(self, opened, text='synthetic text'):
        return self.service._v2_send(opened['room_id'], {
            'api_version': 2, 'membership_id': opened['membership_id'],
            'client_uuid': str(uuid4()), 'text': text,
        })

    def test_defaults_and_bootstrap(self):
        self.assertFalse(self.company.bchat_mobile_direct_enabled)
        self.assertFalse(self.member.bchat_mobile_admin)
        policy = self.service._mobile_policy(self.company.id)
        self.assertEqual(policy, {'api_version': 2, 'company_id': self.company.id,
                                  'direct_enabled': False, 'can_manage': False})
        bootstrap = self.service._v2_bootstrap()
        self.assertEqual(bootstrap['mobile_policy'], [policy])
        self.assertFalse(bootstrap['permissions']['mobile_admin'])
        with self.assertRaises(ProtocolError) as disabled:
            self._open()
        self.assertEqual(disabled.exception.code, 'direct_disabled')

    def test_direct_candidates_do_not_require_group_creation_and_are_bounded_to_company(self):
        self.member.write({'bchat_group_create': False, 'bchat_group_manage': False})
        with self.assertRaises(AccessError):
            self.service._mobile_candidates(self.company.id)
        self._toggle(True)
        self.outsider.write({'bchat_chat_view': False})
        self.colleague.write({'name': 'Visible direct colleague'})
        found = self.service._mobile_candidates(self.company.id)
        ids = {row['user_id'] for row in found['users']}
        self.assertIn(self.colleague.id, ids)
        self.assertNotIn(self.member.id, ids)
        self.assertNotIn(self.outsider.id, ids)
        self.assertNotIn(self.foreign_user.id, ids)
        self.assertLessEqual(len(found['users']), 40)
        self.assertTrue(all(set(row) == {'user_id', 'name'} for row in found['users']))
        self.assertEqual(self.service._mobile_candidates(self.company.id, 'Visible direct colleague')['users'],
                         [{'user_id': self.colleague.id, 'name': 'Visible direct colleague'}])
        with self.assertRaises(AccessError):
            self.service._mobile_candidates(self.foreign.id)
        self.member.write({'bchat_chat_send': False})
        with self.assertRaises(AccessError):
            self.service._mobile_candidates(self.company.id)
        self.member.write({'bchat_group_create': True})
        self._toggle(False)
        self.assertTrue(self.service._mobile_candidates(self.company.id)['users'])
        for query in ('a' * 81, 'bad\nquery', None):
            with self.assertRaises(ProtocolError):
                self.service._mobile_candidates(self.company.id, query)

    def test_only_assigned_manager_and_allowed_company(self):
        with self.assertRaises(AccessError):
            self._toggle(True, service=self.service)
        with self.assertRaises(AccessError):
            self._toggle(True, company=self.foreign)
        with self.assertRaises(AccessError):
            self.service._mobile_policy(self.foreign.id)
        self.assertTrue(self._toggle(True)['direct_enabled'])
        # Assignment gives policy authority, not res.company write authority.
        with self.assertRaises(AccessError):
            self.company.with_user(self.manager).write({'bchat_mobile_direct_enabled': False})
        with self.assertRaises(AccessError):
            self.company.with_user(self.manager).write({'name': 'unauthorized rename'})
        self.manager.write({'bchat_mobile_admin': False})
        with self.assertRaises(AccessError):
            self._toggle(False)

    def test_permissions_cannot_be_forged_on_write_or_create(self):
        with self.assertRaises(AccessError):
            self.member.with_user(self.member).write({'bchat_mobile_admin': True})
        for key in ('bchat_mobile_admin', 'bchat_chat_view', 'bchat_permission_revision'):
            with self.assertRaises(AccessError):
                self.env['res.users'].with_user(self.manager).create({
                    'name': 'forged', 'login': uuid4().hex, key: True,
                })
            with self.assertRaises(AccessError):
                self.env['res.users'].with_user(self.manager).with_context(**{
                    'default_' + key: True,
                }).create({'name': 'forged default', 'login': uuid4().hex})
        before = self.service._v2_bootstrap()['permissions']['revision']
        self.member.write({'bchat_mobile_admin': True})
        self.assertGreater(self.service._v2_bootstrap()['permissions']['revision'], before)

    def test_pair_is_unique_in_both_directions_and_members_are_fixed(self):
        self._toggle(True)
        first = self._open()
        second = self._open(service=self.env['baseer.bchat.service'].with_user(self.colleague),
                            target=self.member)
        self.assertEqual(first['room_id'], second['room_id'])
        self.assertFalse(first['replayed'])
        self.assertTrue(second['replayed'])
        room = self.env['baseer.bchat.room'].browse(first['room_id'])
        self.assertTrue(room.mobile_direct)
        self.assertFalse(room.is_group)
        self.assertEqual(set(room.membership_ids.mapped('user_id').ids),
                         {self.member.id, self.colleague.id})
        with self.assertRaises(AccessError):
            room._write_group_verified({'name': 'converted'}, _GROUP_TOKEN)
        with self.assertRaises(AccessError):
            room.membership_ids._write_group_verified({'is_group_admin': True}, _GROUP_TOKEN)
        with self.assertRaises(AccessError):
            room.membership_ids.action_revoke()
        with self.assertRaises(AccessError):
            room.write({'name': 'forged direct rename'})
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.membership'].create({
                'room_id': room.id, 'company_id': self.company.id,
                'user_id': self.outsider.id,
            })
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.membership']._create_group_verified({
                'room_id': room.id, 'company_id': self.company.id,
                'user_id': self.outsider.id, 'joined_after_message_id': 0,
                'active': True, 'is_group_admin': True,
            }, _GROUP_TOKEN)
        for action in ({'action': 'rename', 'name': 'forged group rename'},
                       {'action': 'add_member', 'user_id': self.outsider.id},
                       {'action': 'leave'}):
            with self.assertRaises(ProtocolError):
                self.service._v2_group_change(room.id, {'api_version': 2, **action})
        self.assertTrue(self.service._v2_rooms()['rooms'][0]['mobile_direct'])

    def test_nonmember_foreign_company_and_invalid_targets(self):
        self._toggle(True)
        opened = self._open()
        for actor in (self.outsider, self.foreign_user, self.manager):
            unauthorized = self.env['baseer.bchat.service'].with_user(actor)
            with self.assertRaises(AccessError):
                unauthorized._v2_history(opened['room_id'])
            with self.assertRaises(AccessError):
                unauthorized._v2_send(opened['room_id'], {
                    'api_version': 2, 'membership_id': opened['membership_id'],
                    'client_uuid': str(uuid4()), 'text': 'forged',
                })
        for target in (self.member, self.foreign_user):
            with self.assertRaises(AccessError):
                self._open(target=target)
        self.colleague.write({'bchat_chat_view': False})
        with self.assertRaises(AccessError):
            self._open()
        with self.assertRaises(AccessError):
            self._text(opened)

    def test_policy_off_preserves_history_and_blocks_original_send_media_and_group_paths(self):
        self._toggle(True)
        opened = self._open()
        self._text(opened)
        self._toggle(False)
        history = self.service._v2_history(opened['room_id'])
        self.assertEqual(len(history['messages']), 1)
        with self.assertRaises(ProtocolError) as disabled:
            self._text(opened, 'must not be stored')
        self.assertEqual(disabled.exception.code, 'direct_disabled')
        raw = b'%PDF-1.4\nsynthetic'
        metadata = {
            'api_version': 2, 'membership_id': opened['membership_id'],
            'upload_uuid': str(uuid4()), 'kind': 'file', 'mime': 'application/pdf',
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'name': 'synthetic.pdf',
        }
        for operation in (
                lambda: self.service._v2_upload_scope(opened['room_id'], metadata),
                lambda: self.service._v2_issue_mobile_upload_grant(opened['room_id'], metadata),
                lambda: self.service._v2_upload(opened['room_id'], metadata, raw)):
            with self.assertRaises(ProtocolError) as media_disabled:
                operation()
            self.assertEqual(media_disabled.exception.code, 'direct_disabled')
        detail = self.service._v2_group_detail(opened['room_id'])
        self.assertFalse(detail['room']['is_group'])
        self.assertFalse(detail['can_manage'])
        self.assertEqual(len(self.service._v2_history(opened['room_id'])['messages']), 1)

    def test_legacy_rooms_and_groups_are_not_reclassified(self):
        room = self.env['baseer.bchat.room']._create_group_verified({
            'name': 'Synthetic normal group', 'company_id': self.company.id, 'is_group': True,
            'group_creator_user_id': self.member.id, 'group_create_uuid': str(uuid4()),
            'group_create_digest': 'a' * 64,
        }, _GROUP_TOKEN)
        self.assertFalse(room.mobile_direct)
        # Off applies only to explicitly marked direct rooms.
        self.service._v2_lock_room(room.id, mutate=True)

    def test_payload_types_are_strict(self):
        with self.assertRaises(ProtocolError):
            self._toggle('false')
        self._toggle(True)
        for change in ({'user_id': True}, {'company_id': True}, {'client_uuid': 'not-a-uuid'},
                       {'api_version': True}, {'extra_admin': True}):
            with self.assertRaises(ProtocolError):
                self._open(**change)
