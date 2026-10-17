"""BChat-only text slice on an isolated Odoo database."""
import base64
import json
import hashlib
import io
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from xml.etree import ElementTree

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, HttpCase, TransactionCase, tagged
from PIL import Image

from ..contracts import ProtocolError


@tagged('post_install', '-at_install', 'baseer_bchat')
class BChatTextCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env.ref('base.user_admin')
        cls.company = cls.manager.company_id
        cls.foreign_company = cls.env['res.company'].create({'name': 'BChat v2 foreign test company'})
        cls.manager.write({'group_ids': [Command.link(
            cls.env.ref('baseer_bchat.group_bchat_manager').id)]})
        cls.member = cls._user('member', 'base.group_user', cls.company)
        cls.foreign = cls._user('foreign', 'base.group_user', cls.foreign_company)
        cls.portal = cls._user('portal', 'base.group_portal', cls.company)
        cls.room = cls.env['baseer.bchat.room'].with_user(cls.manager).with_company(cls.company).create({
            'name': 'BChat v2 test room', 'company_id': cls.company.id,
        })
        cls.manager_membership = cls._join(cls.manager)

    @classmethod
    def _user(cls, label, group, company):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat v2 %s' % label,
            'login': 'bchat-v2-%s-%s' % (label, uuid4().hex),
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([cls.env.ref(group).id])],
        })

    @classmethod
    def _join(cls, user):
        return cls.env['baseer.bchat.membership'].with_user(cls.manager).with_company(cls.company).create({
            'room_id': cls.room.id, 'user_id': user.id,
        })

    def _service(self, user):
        return self.env['baseer.bchat.service'].with_user(user)

    def _expected_company_profile(self, company, titles=None):
        profile = {'id': company.id, 'name': company.name or '',
                   'job_titles': titles or []}
        if 'baseer_name_ar' in company._fields:
            profile['name_ar'] = (company.baseer_name_ar or '').strip()
        if 'baseer_name_en' in company._fields:
            profile['name_en'] = (company.baseer_name_en or '').strip()
        return profile

    def _send(self, user, membership, text='hello', client_uuid=None):
        return self._service(user)._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': membership.id,
            'client_uuid': client_uuid or str(uuid4()), 'text': text,
        })

    def test_reply_contract_replay_and_membership_visibility(self):
        parent = self._send(self.manager, self.manager_membership, 'original')
        member_epoch = self._join(self.member)
        uuid = str(uuid4())
        reply = {
            'api_version': 2, 'membership_id': self.manager_membership.id,
            'client_uuid': uuid, 'text': 'response',
            'reply_to_message_id': parent['message_id'],
        }
        service = self._service(self.manager)
        sent = service._v2_send(self.room.id, reply)
        self.assertEqual(service._v2_send(self.room.id, reply), sent)
        self.assertEqual(self._service(self.member)._v2_history(self.room.id)['messages'][0]['reply'],
                         {'unavailable': True})
        owner_reply = service._v2_history(self.room.id)['messages'][-1]['reply']
        self.assertEqual(set(owner_reply), {'id', 'author_name', 'text'})
        self.assertEqual(owner_reply['id'], parent['message_id'])
        self.assertEqual(owner_reply['text'], 'original')
        with self.assertRaises(ProtocolError) as changed:
            service._v2_send(self.room.id, {**reply, 'reply_to_message_id': sent['message_id']})
        self.assertEqual(changed.exception.status, 409)
        with self.assertRaises(AccessError):
            self._service(self.member)._v2_send(self.room.id, {
                **reply, 'membership_id': member_epoch.id, 'client_uuid': str(uuid4()),
            })

    def test_reply_rejects_foreign_room_and_preserves_legacy_digest(self):
        from .. import v2_contracts
        uuid = str(uuid4())
        legacy = {'api_version': 2, 'membership_id': self.manager_membership.id,
                  'client_uuid': uuid, 'text': 'plain'}
        normalized = v2_contracts.normalize_send(legacy)
        encoded = json.dumps({
            'room_id': self.room.id, 'membership_id': normalized['membership_id'],
            'client_uuid': normalized['client_uuid'], 'text': normalized['text'],
        }, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.assertEqual(v2_contracts.digest(self.room.id, normalized), hashlib.sha256(encoded).hexdigest())
        other = self.env['baseer.bchat.room'].with_user(self.manager).with_company(self.company).create({
            'name': 'Other BChat room', 'company_id': self.company.id,
        })
        other_membership = self.env['baseer.bchat.membership'].with_user(self.manager).with_company(
            self.company).create({'room_id': other.id, 'user_id': self.manager.id})
        foreign_message = self._service(self.manager)._v2_send(other.id, {
            **legacy, 'membership_id': other_membership.id,
        })
        with self.assertRaises(AccessError):
            self._service(self.manager)._v2_send(self.room.id, {
                **legacy, 'client_uuid': str(uuid4()),
                'reply_to_message_id': foreign_message['message_id'],
            })
        with self.assertRaises(ProtocolError):
            v2_contracts.normalize_send({**legacy, 'reply_to_message_id': None})

    def test_reply_to_media_keeps_the_v2_reply_shape(self):
        image = io.BytesIO()
        Image.new('RGB', (8, 8), (20, 80, 140)).save(image, format='PNG')
        raw = image.getvalue()
        service = self._service(self.manager)
        staged = service._v2_upload(self.room.id, {
            'api_version': 2, 'membership_id': self.manager_membership.id,
            'upload_uuid': str(uuid4()), 'kind': 'image', 'mime': 'image/png',
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'name': 'reply-parent.png',
        }, raw)
        parent = service._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.manager_membership.id,
            'client_uuid': str(uuid4()), 'text': '', 'media_id': staged['media_id'],
        })
        service._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.manager_membership.id,
            'client_uuid': str(uuid4()), 'text': 'received',
            'reply_to_message_id': parent['message_id'],
        })
        reply = service._v2_history(self.room.id)['messages'][-1]['reply']
        self.assertEqual(set(reply), {'id', 'author_name', 'text'})
        self.assertEqual(reply['id'], parent['message_id'])
        self.assertEqual(reply['text'], '')

    def test_membership_admin_form_derives_company_from_room(self):
        form = Form(self.env['baseer.bchat.membership'].with_user(self.manager).with_company(self.company))
        form.room_id = self.room
        form.user_id = self.member
        created = form.save()
        self.assertEqual(created.company_id, self.room.company_id)
        self.assertEqual(created.user_id, self.member)

    def test_membership_admin_form_has_save_without_write_acl(self):
        model = self.env['baseer.bchat.membership'].with_user(self.manager).with_company(self.company)
        self.assertTrue(model.has_access('create'))
        self.assertFalse(model.has_access('write'))
        view = model.get_view(
            view_id=self.env.ref('baseer_bchat.view_bchat_membership_form').id,
            view_type='form',
        )
        arch = ElementTree.fromstring(view['arch'])
        self.assertEqual(arch.get('edit'), '1')
        revoke = arch.find(".//button[@name='action_revoke']")
        self.assertIn('not id', revoke.get('invisible', ''))

    def test_v1_stays_disabled_and_v2_bootstrap_has_no_demo(self):
        self.assertFalse(self._service(self.member)._bootstrap()['integration_enabled'])
        v2 = self._service(self.member)._v2_bootstrap()
        self.assertEqual(v2['api_version'], 2)
        self.assertEqual(v2['user_id'], self.member.id)
        self.assertEqual(v2['current_company_id'], self.company.id)
        self.assertTrue(v2['capabilities']['messages'])
        self.assertTrue(v2['capabilities']['attachments'])
        self.assertNotIn('channels', v2)
        self.assertEqual(v2['profile']['name'], self.member.name)
        self.assertEqual(v2['profile']['companies'][0]['id'], self.company.id)
        self.assertEqual(v2['profile']['companies'][0]['name'], self.company.name)
        self.assertEqual(v2['profile']['companies'][0],
                         self._expected_company_profile(self.company))
        self.assertIsInstance(v2['profile']['companies'][0]['job_titles'], list)
        self.assertNotIn('profile_error', v2)
        with self.assertRaises(AccessError):
            self._service(self.portal)._v2_bootstrap()

    def test_member_candidates_are_limited_to_caller_company(self):
        candidate = self._user('candidate', 'base.group_user', self.company)
        listed = self._service(self.member)._v2_group_member_candidates(
            self.company.id, 'BChat v2 candidate')
        self.assertEqual(listed['api_version'], 2)
        self.assertEqual(listed['users'], [
            {'user_id': candidate.id, 'name': candidate.name},
        ])
        all_ids = {row['user_id'] for row in self._service(self.member)
                   ._v2_group_member_candidates(self.company.id, '')['users']}
        self.assertNotIn(self.member.id, all_ids)
        self.assertNotIn(self.foreign.id, all_ids)
        self.assertNotIn(self.portal.id, all_ids)
        with self.assertRaises(AccessError):
            self._service(self.member)._v2_group_member_candidates(
                self.foreign_company.id, '')

    def test_v2_profile_scopes_active_employee_titles_to_self_and_allowed_companies(self):
        if not self.env.registry.models.get('hr.employee'):
            self.skipTest('HR is optional and not installed in this test database')
        second = self.env['res.company'].create({'name': 'BChat second allowed company'})
        empty = self.env['res.company'].create({'name': 'BChat no active employee company'})
        excluded = self.env['res.company'].create({'name': 'BChat excluded company'})
        self.member.write({'company_ids': [Command.set([
            self.company.id, second.id, empty.id, excluded.id,
        ])]})
        employees = self.env['hr.employee'].sudo()

        def add_employee(name, company, title, *, user=None, active=True):
            employee = employees.create({
                'name': name, 'company_id': company.id,
                'user_id': (user or self.member).id, 'job_title': title,
            })
            if not active:
                employee.write({'active': False})

        add_employee('Self one', self.company, 'Z Manager')
        add_employee('Inactive self', empty, 'Hidden inactive', active=False)
        add_employee('Another user', self.company, 'Hidden colleague', user=self.manager)
        add_employee('Self second company', second, 'Second title')
        add_employee('Self excluded company', excluded, 'Hidden company')
        self.member.write({'company_ids': [Command.set([
            self.company.id, second.id, empty.id,
        ])]})

        bootstrap = self._service(self.member)._v2_bootstrap()
        self.assertEqual(bootstrap['company_ids'], sorted(self.member.company_ids.ids))
        self.assertEqual(bootstrap['current_company_id'], self.company.id)
        self.assertEqual(bootstrap['profile']['name'], self.member.name)
        self.assertEqual(bootstrap['profile']['companies'], sorted([
            self._expected_company_profile(self.company, ['Z Manager']),
            self._expected_company_profile(second, ['Second title']),
            self._expected_company_profile(empty),
        ], key=lambda company: company['id']))
        self.assertEqual(set(bootstrap['profile']), {'name', 'companies'})
        expected_keys = {'id', 'name', 'job_titles'}
        if 'baseer_name_ar' in self.company._fields:
            expected_keys.add('name_ar')
        if 'baseer_name_en' in self.company._fields:
            expected_keys.add('name_en')
        self.assertTrue(all(set(company) == expected_keys
                            for company in bootstrap['profile']['companies']))

    def test_member_avatar_uses_private_room_membership_and_employee_image_first(self):
        if not self.env.registry.models.get('hr.employee'):
            self.skipTest('HR is optional and not installed in this test database')
        member_epoch = self._join(self.member)
        user_image = io.BytesIO()
        Image.new('RGB', (12, 12), '#aa1122').save(user_image, format='PNG')
        employee_image = io.BytesIO()
        Image.new('RGB', (12, 12), '#2474a7').save(employee_image, format='PNG')
        self.member.write({'image_128': base64.b64encode(user_image.getvalue())})
        self.env['hr.employee'].sudo().create({
            'name': 'BChat avatar employee', 'user_id': self.member.id,
            'company_id': self.company.id,
            'image_128': base64.b64encode(employee_image.getvalue()),
        })
        raw = self._service(self.manager)._v2_member_avatar(self.room.id, self.member.id)
        with Image.open(io.BytesIO(raw)) as avatar:
            self.assertEqual(avatar.size, (12, 12))
            self.assertEqual(avatar.convert('RGB').getpixel((4, 4)), (36, 116, 167))
        self.assertEqual(member_epoch.user_id, self.member)
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_member_avatar(self.room.id, self.member.id)
        member_epoch.with_user(self.manager).action_revoke()
        with self.assertRaises(AccessError):
            self._service(self.manager)._v2_member_avatar(self.room.id, self.member.id)

    def test_profile_avatar_uses_the_active_company_employee_image(self):
        if not self.env.registry.models.get('hr.employee'):
            self.skipTest('HR is optional and not installed in this test database')
        second = self.env['res.company'].create({'name': 'BChat avatar active company'})
        self.member.write({'company_ids': [Command.set([self.company.id, second.id])]})
        first_image = io.BytesIO()
        Image.new('RGB', (12, 12), '#aa1122').save(first_image, format='PNG')
        second_image = io.BytesIO()
        Image.new('RGB', (12, 12), '#2474a7').save(second_image, format='PNG')
        employees = self.env['hr.employee'].sudo()
        employees.create({
            'name': 'BChat first-company avatar', 'user_id': self.member.id,
            'company_id': self.company.id, 'image_128': base64.b64encode(first_image.getvalue()),
        })
        employees.create({
            'name': 'BChat second-company avatar', 'user_id': self.member.id,
            'company_id': second.id, 'image_128': base64.b64encode(second_image.getvalue()),
        })
        raw = self._service(self.member).with_company(second)._v2_profile_avatar()
        with Image.open(io.BytesIO(raw)) as avatar:
            self.assertEqual(avatar.convert('RGB').getpixel((4, 4)), (36, 116, 167))

    def test_v2_profile_company_names_are_optional_and_never_joined(self):
        if not {'baseer_name_ar', 'baseer_name_en'} <= self.company._fields.keys():
            row = self._service(self.member)._v2_bootstrap()['profile']['companies'][0]
            self.assertNotIn('name_ar', row)
            self.assertNotIn('name_en', row)
            self.assertEqual(row['name'], self.company.name)
            return
        self.company.write({
            'baseer_name_ar': '  شركة الاختبار  ',
            'baseer_name_en': '  Test Company  ',
        })
        row = self._service(self.member)._v2_bootstrap()['profile']['companies'][0]
        self.assertEqual(row['name_ar'], 'شركة الاختبار')
        self.assertEqual(row['name_en'], 'Test Company')
        self.assertNotEqual(row['name_ar'], row['name'])
        self.assertNotEqual(row['name_en'], row['name'])

    def test_v2_profile_bilingual_fields_are_read_only_when_available(self):
        # Exercise both optional-field branches even when this isolated DB
        # deliberately does not install baseer_service_seed.
        bilingual = SimpleNamespace(
            id=11, name='شركة الاختبار | Test Company',
            baseer_name_ar='  شركة الاختبار  ',
            baseer_name_en='  Test Company  ',
            _fields={'baseer_name_ar': True, 'baseer_name_en': True},
        )
        legacy = SimpleNamespace(id=12, name='Legacy company', _fields={})
        user = SimpleNamespace(id=self.member.id, name='Fixture user',
                               company_ids=[bilingual, legacy])
        with patch.dict(self.env.registry.models, {'hr.employee': None}):
            rows = self._service(self.member)._v2_profile(user)['companies']
        self.assertEqual(rows[0], {
            'id': 11, 'name': 'شركة الاختبار | Test Company',
            'name_ar': 'شركة الاختبار', 'name_en': 'Test Company',
            'job_titles': [],
        })
        self.assertEqual(rows[1], {
            'id': 12, 'name': 'Legacy company', 'job_titles': [],
        })

    def test_v2_profile_deduplicates_titles_and_whitelists_hr_read(self):
        if not self.env.registry.models.get('hr.employee'):
            self.skipTest('HR is optional and not installed in this test database')
        rows = [
            {'company_id': (self.company.id, self.company.name), 'job_title': 'Beta'},
            {'company_id': (self.company.id, self.company.name), 'job_title': ' Alpha '},
            {'company_id': (self.company.id, self.company.name), 'job_title': 'Beta'},
            {'company_id': (self.foreign_company.id, self.foreign_company.name),
             'job_title': 'Hidden foreign'},
        ]
        employee_class = type(self.env['hr.employee'])
        with patch.object(employee_class, 'search_read', return_value=rows) as read:
            profile = self._service(self.member)._v2_bootstrap()['profile']
        self.assertEqual(profile['companies'][0]['job_titles'], ['Alpha', 'Beta'])
        self.assertEqual(read.call_args.kwargs['fields'], ['company_id', 'job_title'])
        self.assertEqual(read.call_args.kwargs['limit'], 257)
        self.assertEqual(read.call_args.args[0], [
            ('active', '=', True), ('user_id', '=', self.member.id),
            ('company_id', 'in', [self.company.id]),
        ])

    def test_v2_profile_employee_limit_falls_back_without_partial_titles(self):
        if not self.env.registry.models.get('hr.employee'):
            self.skipTest('HR is optional and not installed in this test database')
        row = {'company_id': (self.company.id, self.company.name),
               'job_title': 'Too many'}
        employee_class = type(self.env['hr.employee'])
        with patch.object(employee_class, 'search_read', return_value=[row] * 257):
            bootstrap = self._service(self.member)._v2_bootstrap()
        self.assertEqual(bootstrap['profile']['companies'], [
            self._expected_company_profile(self.company),
        ])
        self.assertNotIn('profile_error', bootstrap)
        self.assertEqual(bootstrap['user_id'], self.member.id)

    def test_v2_profile_hr_failure_keeps_company_names_without_partial_titles(self):
        service = self._service(self.member)
        with patch.object(type(service), '_v2_employee_titles',
                          side_effect=RuntimeError('test HR failure')):
            bootstrap = service._v2_bootstrap()
        self.assertEqual(bootstrap['profile']['companies'], [
            self._expected_company_profile(self.company),
        ])
        self.assertNotIn('profile_error', bootstrap)
        self.assertEqual(bootstrap['current_company_id'], self.company.id)

    def test_v2_profile_without_hr_and_inactive_user(self):
        # Simulate an installation where HR is absent without changing the DB.
        with patch.dict(self.env.registry.models, {'hr.employee': None}):
            bootstrap = self._service(self.member)._v2_bootstrap()
        self.assertEqual(bootstrap['profile']['companies'][0]['job_titles'], [])
        self.member.write({'active': False})
        with self.assertRaises(AccessError):
            self._service(self.member)._v2_bootstrap()

    def test_v2_profile_size_and_read_failure_do_not_block_bootstrap(self):
        self.member.write({'name': '😀' * 5000})
        large = self._service(self.member)._v2_bootstrap()
        self.assertIsNone(large['profile'])
        self.assertEqual(large['profile_error'], 'profile_too_large')
        self.assertEqual(large['user_id'], self.member.id)
        self.assertTrue(large['capabilities']['messages'])
        service = self._service(self.manager)
        with patch.object(type(service), '_v2_profile', side_effect=RuntimeError('test HR failure')):
            unavailable = service._v2_bootstrap()
        self.assertIsNone(unavailable['profile'])
        self.assertEqual(unavailable['profile_error'], 'profile_unavailable')
        self.assertEqual(unavailable['user_id'], self.manager.id)

    def test_v2_profile_large_hr_titles_are_dropped_before_company_names(self):
        service = self._service(self.member)
        with patch.object(type(service), '_v2_employee_titles', return_value={
            self.company.id: ['Long title ' * 2000],
        }):
            bootstrap = service._v2_bootstrap()
        self.assertEqual(bootstrap['profile']['companies'], [
            self._expected_company_profile(self.company),
        ])
        self.assertNotIn('profile_error', bootstrap)

        # Company identity itself is still subject to the profile size limit.
        oversized_names = {'name': 'Fixture', 'companies': [{
            'id': self.company.id, 'name': 'N' * 17000,
            'job_titles': ['Long title ' * 2000],
        }]}
        with patch.object(type(service), '_v2_profile', return_value=oversized_names):
            oversized = service._v2_bootstrap()
        self.assertIsNone(oversized['profile'])
        self.assertEqual(oversized['profile_error'], 'profile_too_large')

    def test_manager_is_only_orm_administrator_and_no_message_acl(self):
        for user in (self.member, self.manager, self.portal):
            self.assertFalse(self.env['baseer.bchat.message'].with_user(user).has_access('read'))
            self.assertFalse(self.env['baseer.bchat.message'].with_user(user).has_access('create'))
        for model_name in ('baseer.bchat.room', 'baseer.bchat.membership'):
            self.assertFalse(self.env[model_name].with_user(self.member).has_access('read'))
            self.assertFalse(self.env[model_name].with_user(self.member).has_access('create'))
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.message'].with_user(self.manager).create({})
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.room'].with_user(self.member).create({
                'name': 'unauthorized', 'company_id': self.company.id,
            })
        with self.assertRaises(AccessError):
            self.room.with_user(self.manager).write({'company_id': self.foreign_company.id})
        with self.assertRaises(ValidationError):
            self.env['baseer.bchat.room'].with_user(self.manager).with_company(self.company).create({
                'name': 'invalid\nroom', 'company_id': self.company.id,
            })
        with self.assertRaises(AccessError):
            self.room.with_user(self.manager).write({'name': 'invalid\rroom'})
        with self.assertRaises(AccessError):
            self.manager_membership.with_user(self.manager).write({'joined_after_message_id': 0})

    def test_join_floor_revocation_and_rejoin_epoch(self):
        first = self._send(self.manager, self.manager_membership, 'before')
        member_epoch = self._join(self.member)
        self.assertEqual(member_epoch.joined_after_message_id, first['message_id'])
        self.assertEqual(self._service(self.member)._v2_rooms()['rooms'][0]['membership_id'], member_epoch.id)
        self.assertEqual(self._service(self.member)._v2_history(self.room.id)['messages'], [])
        later = self._send(self.manager, self.manager_membership, 'after')
        history = self._service(self.member)._v2_history(self.room.id)
        self.assertEqual([row['id'] for row in history['messages']], [later['message_id']])
        self.assertEqual(history['messages'][0]['author_name'], self.manager.name)
        self.assertNotIn(first['message_id'], [row['id'] for row in history['messages']])
        member_epoch.with_user(self.manager).with_company(self.company).action_revoke()
        with self.assertRaises(AccessError):
            self._service(self.member)._v2_history(self.room.id)
        self.assertEqual(self._service(self.member)._v2_rooms()['rooms'], [])
        rejoined = self._join(self.member)
        self.assertNotEqual(rejoined.id, member_epoch.id)
        self.assertEqual(rejoined.joined_after_message_id, later['message_id'])
        self.assertEqual(self._service(self.member)._v2_history(self.room.id)['messages'], [])
        with self.assertRaises(ProtocolError) as stale:
            self._send(self.member, member_epoch, 'stale')
        self.assertEqual(stale.exception.status, 409)

    def test_idempotent_send_and_conflict_after_rejoin(self):
        member_epoch = self._join(self.member)
        client_uuid = str(uuid4())
        first = self._send(self.member, member_epoch, 'exact', client_uuid)
        self.assertEqual(self._send(self.member, member_epoch, 'exact', client_uuid), first)
        with self.assertRaises(ProtocolError) as changed:
            self._send(self.member, member_epoch, 'changed', client_uuid)
        self.assertEqual(changed.exception.status, 409)
        self.assertEqual(self.env['baseer.bchat.message'].sudo().search_count([
            ('author_user_id', '=', self.member.id), ('client_uuid', '=', client_uuid),
        ]), 1)
        member_epoch.with_user(self.manager).with_company(self.company).action_revoke()
        new_epoch = self._join(self.member)
        with self.assertRaises(ProtocolError) as replay:
            self._send(self.member, new_epoch, 'exact', client_uuid)
        self.assertEqual(replay.exception.status, 409)

    def test_history_cursor_and_foreign_company_denial(self):
        self._join(self.member)
        ids = [self._send(self.manager, self.manager_membership, str(number))['message_id']
               for number in range(34)]
        newest = self._service(self.member)._v2_history(self.room.id)
        self.assertEqual(len(newest['messages']), 30)
        self.assertEqual([row['id'] for row in newest['messages']], ids[-30:])
        older = self._service(self.member)._v2_history(self.room.id, newest['next_before_id'])
        self.assertEqual([row['id'] for row in older['messages']], ids[:4])
        self.assertIsNone(older['next_before_id'])
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_history(self.room.id)
        with self.assertRaises(AccessError):
            self._join(self.foreign)
        with self.assertRaises(AccessError):
            self._join(self.portal)

    def test_manager_rpc_surface_cannot_edit_or_delete_history(self):
        member_epoch = self._join(self.member)
        sent = self._send(self.member, member_epoch)
        message = self.env['baseer.bchat.message'].sudo().browse(sent['message_id'])
        with self.assertRaises(AccessError):
            message.write({'text': 'altered'})
        with self.assertRaises(AccessError):
            message.unlink()
        with self.assertRaises(AccessError):
            member_epoch.with_user(self.manager).unlink()
        with self.assertRaises(AccessError):
            self.room.with_user(self.manager).unlink()

    def test_forbidden_send_rolls_back_room_revision(self):
        self.env.cr.execute('SELECT revision FROM baseer_bchat_room WHERE id = %s', [self.room.id])
        original = self.env.cr.fetchone()[0]
        with self.assertRaises(AccessError):
            self._send(self.member, self.manager_membership, 'not a member')
        self.env.cr.execute('SELECT revision FROM baseer_bchat_room WHERE id = %s', [self.room.id])
        self.assertEqual(self.env.cr.fetchone()[0], original)

    def test_change_feed_and_receipt_ack_are_epoch_scoped(self):
        member_epoch = self._join(self.member)
        member_service = self._service(self.member)
        initial = member_service._v2_changes(0, 1)
        self.assertEqual(initial['changes'][0]['kind'], 'room')
        self.assertTrue(initial['has_more'] is False)
        token = str(uuid4())
        sent = self._send(self.manager, self.manager_membership, 'private body', token)
        message_id = sent['message_id']
        self.assertEqual(self._send(self.manager, self.manager_membership, 'private body', token), sent)
        hints = member_service._v2_changes(0, 100)['changes']
        self.assertEqual([row['seq'] for row in hints], [1, 2])
        self.assertEqual(hints[-1]['message_id'], message_id)
        self.assertNotIn('private body', json.dumps(hints))
        self.assertEqual(member_service._v2_changes(1, 1)['changes'][0]['seq'], 2)
        self.assertEqual(self._service(self.manager)._v2_history(self.room.id)['messages'][0]['delivery_state'], 'sent')
        first = member_service._v2_receipt_ack(self.room.id, message_id, 'delivered')
        self.assertIsNotNone(first['delivered_at'])
        self.assertIsNone(first['read_at'])
        self.assertEqual(first['unread_count'], 1)
        self.assertEqual(first['last_message_id'], message_id)
        self.assertFalse(first['replayed'])
        second = member_service._v2_receipt_ack(self.room.id, message_id, 'read')
        self.assertIsNotNone(second['read_at'])
        self.assertEqual(second['unread_count'], 0)
        self.assertEqual(second['last_message_id'], message_id)
        replay = member_service._v2_receipt_ack(self.room.id, message_id, 'read')
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['unread_count'], 0)
        self.assertEqual(replay['last_message_id'], message_id)
        author_row = self._service(self.manager)._v2_history(self.room.id)['messages'][0]
        self.assertEqual(author_row['delivery_state'], 'read')
        self.assertIsNotNone(author_row['read_at'])
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_receipt_ack(self.room.id, message_id, 'read')
        member_epoch.with_user(self.manager).with_company(self.company).action_revoke()
        old_hints = member_service._v2_changes(0, 100)['changes']
        self.assertEqual([row['kind'] for row in old_hints], ['revoked'])
        new_epoch = self._join(self.member)
        self.assertNotEqual(new_epoch.id, member_epoch.id)
        with self.assertRaises(AccessError):
            member_service._v2_receipt_ack(self.room.id, message_id, 'read')
        visible = member_service._v2_changes(0, 100)['changes']
        self.assertNotIn(message_id, [row.get('message_id') for row in visible])
        self.assertIn('room', [row['kind'] for row in visible])

    def test_change_snapshot_pages_all_rooms_and_private_models_have_no_acl(self):
        for model in ('baseer.bchat.change', 'baseer.bchat.change.cursor',
                      'baseer.bchat.message.receipt'):
            private = self.env[model].with_user(self.member)
            self.assertFalse(private.has_access('read'))
            self.assertFalse(private.has_access('create'))
            with self.assertRaises(AccessError):
                private.create({})
        self._join(self.member)
        for index in range(30):
            room = self.env['baseer.bchat.room'].with_user(self.manager).with_company(self.company).create({
                'name': 'BChat snapshot %s' % index, 'company_id': self.company.id,
            })
            self.env['baseer.bchat.membership'].with_user(self.manager).with_company(self.company).create({
                'room_id': room.id, 'user_id': self.member.id,
            })
        service = self._service(self.member)
        watermark = service._v2_changes(0, 1)['watermark']
        first = service._v2_change_snapshot('rooms', watermark=watermark)
        self.assertEqual(len(first['rooms']), 30)
        self.assertIsNotNone(first['next_before_id'])
        second = service._v2_change_snapshot('rooms', first['next_before_id'], watermark)
        self.assertEqual(len(second['rooms']), 1)
        self.assertIsNone(second['next_before_id'])
        self.assertEqual(len({row['id'] for row in first['rooms'] + second['rooms']}), 31)
        self.assertEqual(first['snapshot_watermark'], second['snapshot_watermark'])
        self.assertTrue(service._v2_changes(watermark + 1)['reset_required'])

    def test_group_create_replay_membership_and_last_admin(self):
        service = self._service(self.member)
        payload = {'api_version': 2, 'client_uuid': str(uuid4()),
                   'company_id': self.company.id, 'name': 'Purchasing',
                   'member_user_ids': [self.manager.id]}
        created = service._v2_group_create(payload)
        self.assertFalse(created['replayed'])
        self.assertEqual(service._v2_group_create(payload)['room_id'], created['room_id'])
        self.assertTrue(service._v2_group_create(payload)['replayed'])
        with self.assertRaises(ProtocolError):
            service._v2_group_create({**payload, 'name': 'Different'})
        room_id = created['room_id']
        detail = service._v2_group_detail(room_id)
        self.assertEqual(detail['room']['name'], 'Purchasing')
        self.assertTrue(detail['can_manage'])
        self.assertEqual(sum(item['is_admin'] for item in detail['members']), 1)
        self.assertTrue(next(row for row in service._v2_rooms()['rooms']
                             if row['id'] == room_id)['is_group'])
        with self.assertRaises(ProtocolError):
            service._v2_group_change(room_id, {'api_version': 2, 'action': 'leave'})
        service._v2_group_change(room_id, {'api_version': 2,
                                            'action': 'promote_admin', 'user_id': self.manager.id})
        service._v2_group_change(room_id, {'api_version': 2, 'action': 'leave'})
        with self.assertRaises(AccessError):
            service._v2_group_detail(room_id)
        self.assertFalse(any(row['id'] == room_id for row in service._v2_rooms()['rooms']))

    def test_group_description_legacy_create_digest_and_replay(self):
        from .. import group_contracts
        service = self._service(self.member)
        legacy = {'api_version': 2, 'client_uuid': str(uuid4()),
                  'company_id': self.company.id, 'name': 'Old request',
                  'member_user_ids': [self.manager.id]}
        normalized = group_contracts.normalize_create(legacy)
        self.assertEqual(set(normalized), {
            'client_uuid', 'company_id', 'name', 'member_user_ids',
        })
        self.assertEqual(group_contracts.normalize_create({**legacy, 'description': ''}), normalized)
        self.assertEqual(group_contracts.create_digest(normalized),
                         group_contracts.create_digest(group_contracts.normalize_create({
                             **legacy, 'description': '',
                         })))
        old = service._v2_group_create(legacy)
        self.assertTrue(service._v2_group_create({**legacy, 'description': ''})['replayed'])
        self.assertEqual(service._v2_group_detail(old['room_id'])['room']['description'], '')
        with self.assertRaises(ProtocolError) as changed:
            service._v2_group_create({**legacy, 'description': 'A new description'})
        self.assertEqual(changed.exception.code, 'idempotency_conflict')
        new_empty = {**legacy, 'client_uuid': str(uuid4()), 'description': ''}
        created = service._v2_group_create(new_empty)
        self.assertTrue(service._v2_group_create({
            key: value for key, value in new_empty.items() if key != 'description'
        })['replayed'])
        self.assertEqual(service._v2_group_detail(created['room_id'])['room']['description'], '')

    def test_group_description_create_edit_visibility_and_authorization(self):
        service = self._service(self.member)
        observer = self._user('description-observer', 'base.group_user', self.company)
        payload = {'api_version': 2, 'client_uuid': str(uuid4()),
                   'company_id': self.company.id, 'name': 'Described group',
                   'member_user_ids': [self.manager.id, observer.id],
                   'description': 'First line\nSecond line'}
        created = service._v2_group_create(payload)
        room_id = created['room_id']
        self.assertTrue(service._v2_group_create(payload)['replayed'])
        self.assertEqual(self._service(observer)._v2_group_detail(room_id)['room']['description'],
                         payload['description'])
        with self.assertRaises(ProtocolError) as changed:
            service._v2_group_create({**payload, 'description': 'Different'})
        self.assertEqual(changed.exception.code, 'idempotency_conflict')
        with self.assertRaises(AccessError):
            self._service(observer)._v2_group_change(room_id, {
                'api_version': 2, 'action': 'set_description', 'description': 'Unauthorized',
            })
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_group_detail(room_id)
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_group_change(room_id, {
                'api_version': 2, 'action': 'set_description', 'description': 'Foreign',
            })
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.room'].with_user(self.manager).with_company(self.company).browse(
                room_id).write({'group_description': 'Bypass'})
        updated = service._v2_group_change(room_id, {
            'api_version': 2, 'action': 'set_description', 'description': 'Updated',
        })
        self.assertEqual(updated['action'], 'set_description')
        self.assertEqual(self._service(observer)._v2_group_detail(room_id)['room']['description'],
                         'Updated')
        service._v2_group_change(room_id, {
            'api_version': 2, 'action': 'set_description', 'description': '',
        })
        self.assertEqual(service._v2_group_detail(room_id)['room']['description'], '')
        service._v2_group_change(room_id, {
            'api_version': 2, 'action': 'remove_member', 'user_id': observer.id,
        })
        with self.assertRaises(AccessError):
            self._service(observer)._v2_group_detail(room_id)

    def test_group_description_utf8_limit_and_invalid_controls(self):
        from .. import group_contracts
        payload = {'api_version': 2, 'client_uuid': str(uuid4()),
                   'company_id': self.company.id, 'name': 'Limits',
                   'member_user_ids': [self.manager.id],
                   'description': 'أ' * 512}
        self.assertEqual(len(group_contracts.normalize_create(payload)['description'].encode('utf-8')),
                         1024)
        service = self._service(self.member)
        created = service._v2_group_create(payload)
        self.assertEqual(service._v2_group_detail(created['room_id'])['room']['description'],
                         payload['description'])
        for invalid in ('أ' * 513, None, 42, 'hidden\x00text', '\ud800'):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(ProtocolError):
                    group_contracts.normalize_create({**payload, 'description': invalid})
                with self.assertRaises(ProtocolError):
                    group_contracts.normalize_change({
                        'api_version': 2, 'action': 'set_description',
                        'description': invalid,
                    })
        self.assertEqual(service._v2_group_detail(created['room_id'])['room']['description'],
                         payload['description'])

    def test_group_member_epoch_and_room_metadata(self):
        service = self._service(self.manager)
        made = service._v2_group_create({
            'api_version': 2, 'client_uuid': str(uuid4()),
            'company_id': self.company.id, 'name': 'Epoch test',
            'member_user_ids': [self.member.id],
        })
        room_id = made['room_id']
        first = service._v2_send(room_id, {
            'api_version': 2, 'membership_id': made['membership_id'],
            'client_uuid': str(uuid4()), 'text': 'Before departure',
        })
        member_service = self._service(self.member)
        initial = next(row for row in member_service._v2_rooms()['rooms']
                       if row['id'] == room_id)
        self.assertEqual(initial['last_message_id'], first['message_id'])
        self.assertEqual(initial['last_message_preview'], 'Before departure')
        self.assertEqual(initial['unread_count'], 1)
        self.assertIsNotNone(initial['last_message_at'])
        member_service._v2_receipt_ack(room_id, first['message_id'], 'read')
        self.assertEqual(next(row for row in member_service._v2_rooms()['rooms']
                              if row['id'] == room_id)['unread_count'], 0)
        service._v2_group_change(room_id, {'api_version': 2, 'action': 'remove_member',
                                            'user_id': self.member.id})
        service._v2_group_change(room_id, {'api_version': 2, 'action': 'add_member',
                                            'user_id': self.member.id})
        current = next(row for row in member_service._v2_rooms()['rooms']
                       if row['id'] == room_id)
        self.assertEqual(current['last_message_id'], 0)
        self.assertEqual(current['unread_count'], 0)
        self.assertEqual(member_service._v2_history(room_id)['messages'], [])
        second = service._v2_send(room_id, {
            'api_version': 2, 'membership_id': made['membership_id'],
            'client_uuid': str(uuid4()), 'text': 'After return',
        })
        current = next(row for row in member_service._v2_rooms()['rooms']
                       if row['id'] == room_id)
        self.assertEqual(current['last_message_id'], second['message_id'])
        self.assertEqual(current['unread_count'], 1)
        watermark = member_service._v2_changes(0, 1)['watermark']
        snapshot = member_service._v2_change_snapshot('rooms', watermark=watermark)
        row = next(item for item in snapshot['rooms'] if item['id'] == room_id)
        self.assertEqual(row['last_message_id'], second['message_id'])
        self.assertEqual(row['unread_count'], 1)

    def test_room_unread_count_matches_join_for_valid_receipts(self):
        member_epoch = self._join(self.member)
        member_service = self._service(self.member)

        def checked_count(service, membership):
            # The previous query is the reference while fixtures retain the
            # receipt -> message room/company/user/epoch integrity invariant.
            self.env.cr.execute('''
                SELECT COUNT(*)
                FROM baseer_bchat_message_receipt AS receipt
                JOIN baseer_bchat_message AS message ON message.id = receipt.message_id
                WHERE receipt.membership_id = %s
                  AND receipt.recipient_user_id = %s
                  AND receipt.read_at IS NULL
                  AND message.room_id = %s
                  AND message.id > %s
            ''', [membership.id, membership.user_id.id, membership.room_id.id,
                  membership.joined_after_message_id])
            previous = self.env.cr.fetchone()[0]
            row = next(item for item in service._v2_rooms()['rooms']
                       if item['membership_id'] == membership.id)
            self.assertEqual(row['unread_count'], previous)
            return previous

        self.assertEqual(checked_count(member_service, member_epoch), 0)
        other_room = self.env['baseer.bchat.room'].with_user(self.manager).with_company(
            self.company).create({'name': 'Other unread room', 'company_id': self.company.id})
        other_owner = self.env['baseer.bchat.membership'].with_user(self.manager).with_company(
            self.company).create({'room_id': other_room.id, 'user_id': self.manager.id})
        other_member = self.env['baseer.bchat.membership'].with_user(self.manager).with_company(
            self.company).create({'room_id': other_room.id, 'user_id': self.member.id})
        self._service(self.manager)._v2_send(other_room.id, {
            'api_version': 2, 'membership_id': other_owner.id,
            'client_uuid': str(uuid4()), 'text': 'Other room only',
        })
        self.assertEqual(checked_count(member_service, member_epoch), 0)
        self.assertEqual(checked_count(member_service, other_member), 1)

        self.manager.write({'company_ids': [Command.link(self.foreign_company.id)]})
        foreign_room = self.env['baseer.bchat.room'].with_user(self.manager).with_company(
            self.foreign_company).create({
                'name': 'Foreign unread room', 'company_id': self.foreign_company.id,
            })
        foreign_owner = self.env['baseer.bchat.membership'].with_user(
            self.manager).with_company(self.foreign_company).create({
                'room_id': foreign_room.id, 'user_id': self.manager.id,
            })
        foreign_member = self.env['baseer.bchat.membership'].with_user(
            self.manager).with_company(self.foreign_company).create({
                'room_id': foreign_room.id, 'user_id': self.foreign.id,
            })
        self._service(self.manager)._v2_send(foreign_room.id, {
            'api_version': 2, 'membership_id': foreign_owner.id,
            'client_uuid': str(uuid4()), 'text': 'Foreign company only',
        })
        self.assertEqual(checked_count(self._service(self.foreign), foreign_member), 1)
        self.assertNotIn(foreign_room.id, [row['id'] for row in member_service._v2_rooms()['rooms']])
        self.assertEqual(checked_count(member_service, member_epoch), 0)

        first = self._send(self.manager, self.manager_membership, 'Unread here')
        self.assertEqual(checked_count(member_service, member_epoch), 1)
        member_service._v2_receipt_ack(self.room.id, first['message_id'], 'read')
        self.assertEqual(checked_count(member_service, member_epoch), 0)
        self._send(self.manager, self.manager_membership, 'Before leaving')
        self.assertEqual(checked_count(member_service, member_epoch), 1)
        member_epoch.with_user(self.manager).with_company(self.company).action_revoke()
        rejoined = self._join(self.member)
        self.assertNotEqual(rejoined.id, member_epoch.id)
        self.assertEqual(checked_count(member_service, rejoined), 0)
        self._send(self.manager, self.manager_membership, 'After rejoining')
        self.assertEqual(checked_count(member_service, rejoined), 1)
        self.assertEqual(checked_count(member_service, other_member), 1)

    def test_group_foreign_member_and_legacy_api_rejected(self):
        service = self._service(self.member)
        with self.assertRaises(AccessError):
            service._v2_group_create({
                'api_version': 2, 'client_uuid': str(uuid4()),
                'company_id': self.company.id, 'name': 'Invalid',
                'member_user_ids': [self.foreign.id],
            })
        legacy = self._service(self.manager)._v2_group_detail(self.room.id)
        self.assertFalse(legacy['room']['is_group'])
        self.assertFalse(legacy['can_manage'])
        self.assertEqual(legacy['members'][0]['user_id'], self.manager.id)
        with self.assertRaises(AccessError):
            service._v2_group_detail(self.room.id)
        with self.assertRaises(ProtocolError):
            service._v2_group_change(self.room.id, {
                'api_version': 2, 'action': 'rename', 'name': 'No',
            })
        self.room.with_user(self.manager).with_company(self.company).write({'name': 'Legacy still works'})
        self.assertEqual(self.room.name, 'Legacy still works')

    def test_group_rejected_mutation_rolls_back_revision_and_avatar_is_private(self):
        service = self._service(self.member)
        observer = self._user('observer', 'base.group_user', self.company)
        created = service._v2_group_create({
            'api_version': 2, 'client_uuid': str(uuid4()),
            'company_id': self.company.id, 'name': 'Private group',
            'member_user_ids': [self.manager.id, observer.id],
        })
        room_id = created['room_id']
        self.env.cr.execute('SELECT revision FROM baseer_bchat_room WHERE id = %s', [room_id])
        before = self.env.cr.fetchone()[0]
        with self.assertRaises(AccessError):
            self._service(observer)._v2_group_change(room_id, {
                'api_version': 2, 'action': 'rename', 'name': 'Forbidden',
            })
        self.env.cr.execute('SELECT revision FROM baseer_bchat_room WHERE id = %s', [room_id])
        self.assertEqual(self.env.cr.fetchone()[0], before)
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_group_detail(room_id)
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_group_avatar(room_id)
        with self.assertRaises(ProtocolError):
            service._v2_group_set_avatar(room_id, b'not an image')
        self.assertEqual(service._v2_group_detail(room_id)['room']['avatar_version'], 0)
        image = io.BytesIO()
        Image.new('RGB', (12, 12), '#2474a7').save(image, format='PNG')
        uploaded = service._v2_group_set_avatar(room_id, image.getvalue())
        self.assertEqual(uploaded['avatar_version'], 1)
        self.assertTrue(service._v2_group_avatar(room_id)[0].startswith(b'\x89PNG\r\n'))
        with self.assertRaises(AccessError):
            self._service(self.foreign)._v2_group_avatar(room_id)

    def test_room_capacity_100_replay_and_add_member(self):
        rooms = self.env['baseer.bchat.room'].with_user(self.manager).with_company(self.company)
        memberships = self.env['baseer.bchat.membership'].with_user(self.manager).with_company(self.company)
        for number in range(99):
            room = rooms.create({'name': 'Capacity %s' % number,
                                 'company_id': self.company.id})
            memberships.create({'room_id': room.id, 'user_id': self.member.id})
        service = self._service(self.member)
        payload = {'api_version': 2, 'client_uuid': str(uuid4()),
                   'company_id': self.company.id, 'name': 'One hundred',
                   'member_user_ids': [self.manager.id]}
        created = service._v2_group_create(payload)
        self.assertEqual(service._v2_group_create(payload)['room_id'], created['room_id'])
        self.assertTrue(service._v2_group_create(payload)['replayed'])
        self.assertEqual(len(service._v2_rooms()['rooms']), 100)
        with self.assertRaises(ProtocolError) as limit:
            service._v2_group_create({**payload, 'client_uuid': str(uuid4()),
                                      'name': 'One too many'})
        self.assertEqual(limit.exception.code, 'too_many_rooms')
        other = self._user('capacity-other', 'base.group_user', self.company)
        separate = self._service(self.manager)._v2_group_create({
            'api_version': 2, 'client_uuid': str(uuid4()),
            'company_id': self.company.id, 'name': 'Another group',
            'member_user_ids': [other.id],
        })
        with self.assertRaises(ProtocolError) as add_limit:
            self._service(self.manager)._v2_group_change(separate['room_id'], {
                'api_version': 2, 'action': 'add_member', 'user_id': self.member.id,
            })
        self.assertEqual(add_limit.exception.code, 'too_many_rooms')
        self.assertEqual(len(service._v2_rooms()['rooms']), 100)

    def test_admin_membership_batch_99_plus_two_rolls_back_without_crossing_100(self):
        rooms = self.env['baseer.bchat.room'].with_user(self.manager).with_company(self.company)
        memberships = self.env['baseer.bchat.membership'].with_user(self.manager).with_company(self.company)
        for number in range(99):
            room = rooms.create({'name': 'Batch capacity %s' % number, 'company_id': self.company.id})
            memberships.create({'room_id': room.id, 'user_id': self.member.id})
        targets = rooms.create([{'name': 'Batch capacity target %s' % number,
                                 'company_id': self.company.id} for number in range(2)])
        before_changes = self.env['baseer.bchat.change'].sudo().search_count([('user_id', '=', self.member.id)])
        with self.assertRaises(ProtocolError) as limited:
            memberships.create([{'room_id': room.id, 'user_id': self.member.id} for room in targets])
        self.assertEqual(limited.exception.code, 'too_many_rooms')
        # The first row is rolled back as part of the same protected batch.
        self.assertEqual(memberships.sudo().search_count([
            ('user_id', '=', self.member.id), ('active', '=', True)]), 99)
        self.assertFalse(memberships.sudo().search_count([
            ('user_id', '=', self.member.id), ('room_id', 'in', targets.ids)]))
        self.assertEqual(self.env['baseer.bchat.change'].sudo().search_count([
            ('user_id', '=', self.member.id)]), before_changes)
        memberships.create({'room_id': targets[0].id, 'user_id': self.member.id})
        self.assertEqual(memberships.sudo().search_count([
            ('user_id', '=', self.member.id), ('active', '=', True)]), 100)
        with self.assertRaises(ProtocolError) as full:
            memberships.create({'room_id': targets[1].id, 'user_id': self.member.id})
        self.assertEqual(full.exception.code, 'too_many_rooms')

    def test_read_completion_excludes_departed_recipient(self):
        one = self._join(self.member)
        other = self._user('other-reader', 'base.group_user', self.company)
        second = self._join(other)
        message_id = self._send(self.manager, self.manager_membership)['message_id']
        self._service(self.member)._v2_receipt_ack(self.room.id, message_id, 'read')
        genuine_read_at = self.env['baseer.bchat.message.receipt'].sudo().search([
            ('message_id', '=', message_id), ('membership_id', '=', one.id),
        ]).read_at
        self.assertEqual(self._service(self.manager)._v2_history(self.room.id)['messages'][0]['delivery_state'], 'sent')
        second.with_user(self.manager).with_company(self.company).action_revoke()
        row = self._service(self.manager)._v2_history(self.room.id)['messages'][0]
        self.assertEqual(row['delivery_state'], 'read')
        self.assertIsNotNone(row['read_at'])
        self.assertEqual(row['read_at'], genuine_read_at.strftime('%Y-%m-%d %H:%M:%S'))
        late = self._join(other)
        self.assertNotEqual(late.id, second.id)
        with self.assertRaises(AccessError):
            self._service(other)._v2_receipt_ack(self.room.id, message_id, 'read')
        self.assertTrue(one.active)


@tagged('post_install', '-at_install', 'baseer_bchat')
class BChatTextHttpCase(HttpCase):
    def test_v2_bootstrap_and_room_listing_use_existing_odoo_account(self):
        company = self.env.company
        password = 'test-only-%s' % uuid4().hex
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat v2 HTTP manager', 'login': 'bchat-v2-http-manager-%s' % uuid4().hex,
            'password': password, 'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('baseer_bchat.group_bchat_manager').id])],
        })
        member = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat v2 HTTP member', 'login': 'bchat-v2-http-member-%s' % uuid4().hex,
            'password': password, 'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.room'].with_user(manager).with_company(company).create({
                'name': 'Role-only manager remains unauthorized', 'company_id': company.id,
            })
        room_admin = self.env.ref('base.user_admin')
        room_admin.write({'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        room = self.env['baseer.bchat.room'].with_user(room_admin).with_company(company).create({
            'name': 'BChat v2 HTTP room', 'company_id': company.id,
        })
        joined = self.env['baseer.bchat.membership'].with_user(room_admin).with_company(company).create({
            'room_id': room.id, 'user_id': member.id,
        })
        self.authenticate(member.login, password)
        bootstrap = self.url_open('/bchat/api/v2/bootstrap')
        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.json()['user_id'], member.id)
        self.assertEqual(bootstrap.json()['api_version'], 2)
        self.assertEqual(bootstrap.json()['profile']['name'], member.name)
        self.assertEqual(bootstrap.json()['profile']['companies'][0]['id'], company.id)
        self.assertEqual(bootstrap.headers['Cache-Control'], 'no-store')
        listing = self.url_open('/bchat/api/v2/rooms')
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(any(row['id'] == room.id and row['company_id'] == company.id
                            and row['name'] == room.name and row['membership_id'] == joined.id
                            and row['invoice_policy'] == 'off'
                            and row['invoice_policy_version'] == 1
                            for row in listing.json()['rooms']))
        invalid = self.url_open('/bchat/api/v2/rooms?unknown=1')
        self.assertEqual(invalid.status_code, 400)
        endpoint = '/bchat/api/v2/rooms/%s/messages' % room.id
        payload = json.dumps({
            'api_version': 2, 'membership_id': joined.id,
            'client_uuid': str(uuid4()), 'text': 'HTTP BChat text',
        })
        sent = self.url_open(endpoint, data={
            'csrf_token': bootstrap.json()['csrf_token'], 'payload': payload,
        }, allow_redirects=False)
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.json()['state'], 'sent')
        history = self.url_open(endpoint)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()['messages'][0]['text'], 'HTTP BChat text')
        self.assertEqual(history.json()['messages'][0]['author_name'], member.name)
        missing_csrf = self.url_open(endpoint, data={'payload': payload}, allow_redirects=False)
        self.assertNotEqual(missing_csrf.status_code, 200)
        self.logout()
        anonymous = self.url_open(endpoint, data={
            'csrf_token': bootstrap.json()['csrf_token'], 'payload': payload,
        }, allow_redirects=False)
        self.assertNotEqual(anonymous.status_code, 200)

    def test_member_candidates_route_scopes_company_and_session(self):
        company = self.env.company
        password = 'test-only-%s' % uuid4().hex
        member = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat HTTP caller', 'login': 'bchat-http-caller-%s' % uuid4().hex,
            'password': password, 'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        candidate = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat HTTP candidate', 'login': 'bchat-http-candidate-%s' % uuid4().hex,
            'company_id': company.id, 'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        foreign_company = self.env['res.company'].create({'name': 'BChat HTTP foreign company'})
        self.authenticate(member.login, password)
        listed = self.url_open(
            '/bchat/api/v2/member-candidates?company_id=%s&q=BChat%%20HTTP%%20candidate' % company.id,
            allow_redirects=False)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()['users'], [
            {'user_id': candidate.id, 'name': candidate.name},
        ])
        denied = self.url_open(
            '/bchat/api/v2/member-candidates?company_id=%s&q=' % foreign_company.id,
            allow_redirects=False)
        self.assertEqual(denied.status_code, 403)
        self.logout()
        anonymous = self.url_open(
            '/bchat/api/v2/member-candidates?company_id=%s&q=' % company.id,
            allow_redirects=False)
        self.assertNotEqual(anonymous.status_code, 200)
