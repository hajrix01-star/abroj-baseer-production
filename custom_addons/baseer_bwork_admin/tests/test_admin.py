"""Isolated ORM/HTTP evidence; reporting calls use ordinary UID2, never sudo."""
import base64
import json
import importlib.util
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.baseer_bchat.models.media import _MEDIA_TOKEN
from .. import contracts


@tagged('post_install', '-at_install')
class BWorkAdminCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other = cls.env['res.company'].create({'name': 'Admin second company'})
        cls.foreign = cls.env['res.company'].create({'name': 'Admin foreign company'})
        cls.admin = cls.env.ref('base.user_admin')
        cls.admin.write({'group_ids': [Command.link(cls.env.ref('baseer_bchat.group_bchat_manager').id)],
                         'company_ids': [Command.link(cls.other.id)]})
        cls.ordinary = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Non-admin manager', 'login': 'admin-contract-' + uuid4().hex,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id,
                                      cls.env.ref('baseer_bchat.group_bchat_manager').id])],
        })
        cls.room = cls.env['baseer.bchat.room'].with_user(cls.admin).with_company(cls.company).create({
            'name': 'Metadata room', 'company_id': cls.company.id})
        cls.member = cls.env['baseer.bchat.membership'].with_user(cls.admin).with_company(cls.company).create({
            'room_id': cls.room.id, 'user_id': cls.ordinary.id})

    def service(self, user=None, companies=None):
        return self.env['baseer.bwork.admin.service'].with_user(user or self.admin).with_context(
            allowed_company_ids=(companies or self.company).ids)

    def test_authority_rejects_group_only_sudo_and_foreign_current_scope(self):
        data = self.service().snapshot(self.company.ids)
        self.assertTrue(data['complete'])
        self.assertFalse(self.service().env.su)
        for service, ids in (
                (self.service(self.ordinary), self.company.ids),
                (self.service().sudo(), self.company.ids),
                (self.service(), self.foreign.ids),
                (self.service(), self.other.ids)):
            with self.assertRaises(AccessError):
                service.snapshot(ids)
        self.assertEqual(self.service(companies=self.company | self.other).snapshot(
            (self.company | self.other).ids)['company_ids'], sorted((self.company | self.other).ids))

    def test_bounded_inputs_and_pages(self):
        for ids in ([], [True], [self.company.id, self.company.id], list(range(1, 12))):
            with self.assertRaises(ValidationError):
                self.service().snapshot(ids)
        for kwargs in ({'limit': 201}, {'offset': -1}, {'limit': True}, {'offset': 100001}):
            with self.assertRaises(ValidationError):
                self.service().rooms(self.company.ids, **kwargs)
        page = self.service().rooms(self.company.ids, limit=1)
        self.assertEqual(page['items'][0]['id'], self.room.id)
        self.assertEqual(page['limit'], 1)
        self.assertEqual(self.service().members(self.company.ids)['items'][0]['id'], self.member.id)

    def test_cap_is_global_and_never_returns_partial_headline(self):
        # One room plus one membership, not one independent cap per table.
        with patch.object(contracts, 'MAX_SOURCE_ROWS', 1):
            data = self.service().snapshot(self.company.ids)
        self.assertEqual(data['status'], 'limit_exceeded')
        self.assertFalse(data['complete'])
        self.assertIsNone(data['totals'])
        self.assertEqual(data['companies'], [])

    def test_distinct_logical_attachment_bytes_warning_and_retention(self):
        attachment = self.env['ir.attachment'].create({
            'name': 'Logical fixture', 'datas': base64.b64encode(b'x' * 1234), 'mimetype': 'application/octet-stream'})
        for _index in range(2):
            self.env['baseer.bchat.media']._create_verified({
                'room_id': self.room.id, 'company_id': self.company.id,
                'membership_id': self.member.id, 'author_user_id': self.ordinary.id,
                'upload_uuid': str(uuid4()), 'kind': 'file', 'mime': 'application/octet-stream',
                'size_bytes': 1234, 'sha256': 'a' * 64, 'name': 'Metadata only',
                'state': 'attached', 'attachment_id': attachment.id,
                'thumbnail_attachment_id': attachment.id,
            }, _MEDIA_TOKEN)
        before = self.env['baseer.bchat.media'].sudo().search_count([('room_id', '=', self.room.id)])
        data = self.service().snapshot(self.company.ids)
        row = data['companies'][0]
        self.assertEqual(row['logical_bytes'], 1234)
        self.assertEqual(row['logical_mib'], '0.00')
        self.assertEqual(row['warning_status'], 'disabled')
        self.assertEqual(row['media']['attached'], 2)
        self.assertEqual(data['linked_retention'], 'preserve_all')
        self.assertTrue(attachment.exists())
        self.assertEqual(self.env['baseer.bchat.media'].sudo().search_count([('room_id', '=', self.room.id)]), before)
        with patch.object(contracts, 'MAX_SOURCE_ROWS', 4):
            self.assertFalse(self.service().snapshot(self.company.ids)['complete'], 'Attachment reference also consumes capacity')

    def test_configuration_requires_effective_admin_and_system_and_valid_integers(self):
        model = self.env['baseer.bwork.admin.policy'].with_user(self.admin).with_context(allowed_company_ids=self.company.ids)
        policy = model.create({'company_id': self.company.id, 'warning_mib': 0})
        self.assertEqual(policy.warning_mib, 0)
        for value in (-1, True, contracts.MAX_WARNING_MIB + 1):
            with self.assertRaises(ValidationError):
                policy.write({'warning_mib': value})
        policy.write({'warning_mib': 1})
        self.assertEqual(self.service().snapshot(self.company.ids)['companies'][0]['warning_mib'], 1)
        policy.invalidate_recordset()
        exported = policy.export_data(['warning_mib'])['datas']
        self.assertEqual(len(exported), 1)
        self.assertEqual(str(exported[0][0]), '1')
        with self.assertRaises(AccessError):
            policy.with_user(self.ordinary).write({'warning_mib': 2})
        with self.assertRaises(AccessError):
            policy.unlink()
        # Preserve Odoo's native last-active-administrator invariant. This
        # disposable fixture is not the policy reader or a BWork room admin.
        system_group = self.env.ref('base.group_system')
        fallback_admin = self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': 'Isolated policy system administrator', 'login': 'policy-system-' + uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id, system_group.id])],
            'active': True,
        })
        self.assertTrue(fallback_admin.active)
        self.assertTrue(fallback_admin.has_group('base.group_system'))
        self.assertFalse(fallback_admin._bchat_effective_permissions()['room_admin'])
        # Keep actual room-admin authority but remove the additional config grant.
        self.admin.sudo().write({'group_ids': [Command.unlink(system_group.id)]})
        self.assertFalse(self.admin.has_group('base.group_system'))
        self.assertTrue(self.admin._bchat_effective_permissions()['room_admin'])
        with self.assertRaises(AccessError):
            policy.write({'warning_mib': 2})
        self.assertEqual(policy.warning_mib, 1)

    def test_console_actions_guard_direct_rpc_and_readonly_views(self):
        model = self.env['baseer.bwork.admin.console'].with_user(self.admin).with_context(allowed_company_ids=self.company.ids)
        # Opening the native form calls onchange on virtual many2many records,
        # not create/read on a persisted console. Cover the actual failing RPC
        # and changing companies, with the existing effective authority intact.
        fields_spec = {name: {} for name in (
            'company_ids', 'status', 'rooms_count', 'members_count',
            'logical_storage', 'storage_details', 'operations')}
        both = self.company | self.other
        for language in ('en_US', 'ar_001'):
            opening = model.with_context(allowed_company_ids=both.ids, lang=language)
            for selected in (self.company, self.other, both):
                result = opening.onchange({'company_ids': [Command.set(selected.ids)]}, [], fields_spec)
                values = result['value']
                self.assertIsInstance(values['operations'], str)
                self.assertNotIn('\nFalse\n', values['operations'])
                for company in selected:
                    self.assertIn(company.name, values['operations'].splitlines())
                    self.assertIn(company.name + ':', values['storage_details'])
                for company in both - selected:
                    self.assertNotIn(company.name, values['operations'].splitlines())
            for selected in (self.foreign,):
                with self.assertRaises(AccessError):
                    opening.onchange({'company_ids': [Command.set(selected.ids)]}, [], fields_spec)
        with self.assertRaises(AccessError):
            model.with_user(self.ordinary).onchange(
                {'company_ids': [Command.set(self.company.ids)]}, [], fields_spec)
        with self.assertRaises(AccessError):
            model.sudo().onchange({'company_ids': [Command.set(self.company.ids)]}, [], fields_spec)
        console = model.create({'company_ids': [Command.set(self.company.ids)]})
        self.assertEqual(console.rooms_count, '1')
        for method in ('action_rooms', 'action_members'):
            action = getattr(console, method)()
            self.assertEqual(action['limit'], 80)
            self.assertFalse(action['context']['edit'])
            form = self.env['ir.ui.view'].browse(action['views'][1][0])
            self.assertIn('edit="0"', form.arch_db)
            with self.assertRaises(AccessError):
                getattr(console.with_user(self.ordinary), method)()
        with self.assertRaises(AccessError):
            console.with_user(self.ordinary).read(['operations'])
        with self.assertRaises(AccessError):
            console.sudo().read(['operations'])
        with self.assertRaises(AccessError):
            model.sudo().search([])
        policy = self.env['baseer.bwork.admin.policy'].with_user(self.admin).with_context(
            allowed_company_ids=self.company.ids).create({'company_id': self.company.id, 'warning_mib': 0})
        attachment = self.env['ir.attachment'].create({'name': 'Vacuum content sentinel', 'datas': base64.b64encode(b'preserve')})
        message = self.env['baseer.bchat.service'].with_user(self.ordinary)._v2_send(self.room.id, {
            'api_version': 2, 'membership_id': self.member.id, 'client_uuid': str(uuid4()), 'text': 'Preserved content',
        })
        fresh = model.create({'company_ids': [Command.set(self.company.ids)]})
        self.env.cr.execute('UPDATE baseer_bwork_admin_console SET write_date = %s WHERE id = %s',
                            [self.env.cr.now() - timedelta(hours=2), console.id])
        with patch.object(type(model), '_transient_max_hours', 1.0), patch.object(type(model), '_transient_max_count', 0):
            # The actual inherited native vacuum must run, not a mocked guard
            # or manual deletion helper. Only its old-ID selection is adapted.
            model.sudo()._transient_vacuum()
        self.env.cr.execute('SELECT id FROM baseer_bwork_admin_console WHERE id = ANY(%s)', [[console.id, fresh.id]])
        self.assertEqual(self.env.cr.fetchall(), [(fresh.id,)])
        self.assertTrue(policy.exists())
        self.assertTrue(attachment.exists())
        self.assertTrue(self.room.exists())
        self.assertTrue(self.member.exists())
        self.assertTrue(self.env['baseer.bchat.message'].sudo().browse(message['message_id']).exists())
        with self.assertRaises(AccessError):
            policy.sudo().read(['warning_mib'])

    def test_upgrade_repairs_only_obsolete_root_menu_translations(self):
        path = Path(__file__).resolve().parents[2] / 'baseer_bchat/migrations/19.0.0.4.17/post-migrate.py'
        spec = importlib.util.spec_from_file_location('bwork_menu_upgrade', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        menu = self.env.ref('baseer_bchat.menu_bchat_root')
        other = self.env.ref('baseer_bchat.menu_bchat_rooms')
        self.env['ir.ui.menu'].flush_model(['name'])
        original_other = other.with_context(lang='en_US').name
        fixture = {'en_US': 'BWork', 'ar_001': 'BChat', 'ar_SY': 'BChat',
                   'fr_FR': 'BChat', 'ar_EG': 'Custom Arabic title'}
        self.env.cr.execute('UPDATE ir_ui_menu SET name = %s::jsonb WHERE id = %s',
                            [json.dumps(fixture), menu.id])
        for _attempt in range(2):
            migration.migrate(self.env.cr, '19.0.0.4.16')
            self.env.cr.execute('SELECT name FROM ir_ui_menu WHERE id = %s', [menu.id])
            self.assertEqual(self.env.cr.fetchone()[0], {
                'en_US': 'BWork', 'ar_001': 'بيورك', 'ar_SY': 'بيورك',
                'fr_FR': 'BWork', 'ar_EG': 'Custom Arabic title'})
        self.env['ir.ui.menu'].invalidate_model(['name'])
        self.assertEqual(other.with_context(lang='en_US').name, original_other)
        self.assertEqual(self.env.ref('baseer_bchat.menu_bchat_root').id, menu.id)

    def test_no_private_acl_or_provider_secret_readiness_claim(self):
        for model in ('baseer.bchat.media', 'baseer.bchat.push.device', 'baseer.bchat.push.event',
                      'baseer.bchat.mobile.upload.grant', 'baseer.bchat.message'):
            self.assertFalse(self.env[model].with_user(self.admin).has_access('read'))
        with patch.object(type(self.env['baseer.bchat.push.event']), '_fcm_config', side_effect=AssertionError('No secret inspection')):
            data = self.service().snapshot(self.company.ids)
        self.assertEqual(data['provider_readiness'], 'unverified')
        self.assertEqual(len(data['crons']), 4)
        self.assertNotIn('last_success', json.dumps(data))

    def test_cached_console_web_read_export_and_scope_change_fail_closed(self):
        model = self.env['baseer.bwork.admin.console'].with_user(self.admin).with_context(
            allowed_company_ids=(self.company | self.other).ids)
        console = model.create({'company_ids': [Command.set(self.other.ids)]})
        self.assertTrue(console.read(['company_ids', 'operations']))
        scoped = console.with_context(allowed_company_ids=self.company.ids)
        for callback in (
                lambda: scoped.web_read({'company_ids': {}, 'operations': {}}),
                lambda: scoped.export_data(['company_ids', 'operations']),
                lambda: scoped.fetch(['company_ids', 'operations']),
                lambda: scoped.check_access('read')):
            with self.assertRaises(AccessError):
                callback()
        self.assertFalse(scoped.search([('id', '=', console.id)]))
        self.assertFalse(scoped.search_read([('id', '=', console.id)], ['company_ids']))
        self.assertFalse(scoped.read_group([('id', '=', console.id)], ['id:count'], ['create_uid']))
        self.admin.sudo().write({'company_ids': [Command.unlink(self.other.id)]})
        with self.assertRaises(AccessError):
            console.with_context(allowed_company_ids=self.company.ids).read(['operations'])

    def test_invalid_console_scope_rejected_before_mutation_and_missing_media_no_totals(self):
        model = self.env['baseer.bwork.admin.console'].with_user(self.admin).with_context(allowed_company_ids=self.company.ids)
        console = model.create({'company_ids': [Command.set(self.company.ids)]})
        with self.assertRaises(AccessError):
            console.write({'company_ids': [Command.set(self.other.ids)]})
        self.assertEqual(console.company_ids, self.company)
        self.env['baseer.bchat.media']._create_verified({
            'room_id': self.room.id, 'company_id': self.company.id,
            'membership_id': self.member.id, 'author_user_id': self.ordinary.id,
            'upload_uuid': str(uuid4()), 'kind': 'file', 'mime': 'application/octet-stream',
            'size_bytes': 123, 'sha256': 'b' * 64, 'name': 'Missing metadata', 'state': 'staged',
        }, _MEDIA_TOKEN)
        data = self.service().snapshot(self.company.ids)
        self.assertEqual(data['status'], 'integrity_error')
        self.assertEqual(data['integrity']['missing_attachment_rows'], 1)
        self.assertIsNone(data['totals'])


@tagged('post_install', '-at_install')
class BWorkAdminHttpCase(HttpCase):
    def _rpc(self, ids):
        return self.url_open('/web/dataset/call_kw/baseer.bwork.admin.service/snapshot',
            headers={'Content-Type': 'application/json'}, data=json.dumps({
                'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                'params': {'model': 'baseer.bwork.admin.service', 'method': 'snapshot',
                           'args': [ids], 'kwargs': {'context': {'allowed_company_ids': ids}}},
            })).json()

    def test_authenticated_native_rpc_and_ordinary_denial(self):
        admin = self.env.ref('base.user_admin')
        password = 'admin-isolated-' + uuid4().hex
        admin.write({'password': password, 'group_ids': [Command.link(
            self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        self.authenticate(admin.login, password)
        self.assertTrue(self._rpc(self.env.company.ids)['result']['complete'])
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'HTTP nonadmin', 'login': 'admin-http-' + uuid4().hex, 'password': password,
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.authenticate(user.login, password)
        self.assertIn('error', self._rpc(self.env.company.ids))

    def test_unauthenticated_rpc_has_no_metadata(self):
        response = self._rpc(self.env.company.ids)
        self.assertIn('error', response)
        self.assertNotIn('result', response)
