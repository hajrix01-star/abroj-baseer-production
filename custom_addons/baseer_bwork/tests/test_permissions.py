"""Core permission gates, compatibility and content-free revocation hints."""

from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..models.user_permissions import _CORE_SWITCHES


@tagged('post_install', '-at_install', 'baseer_bwork')
class BWorkPermissionCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref('base.user_admin')
        cls.company = cls.admin.company_id
        cls.member = cls.env['res.users'].with_context(no_reset_password=True).create({
            # Explicitly authorized fixture, not the fresh-install default.
            **{name: True for name in _CORE_SWITCHES},
            'name': 'BWork permission member',
            'login': 'bwork-permission-%s' % uuid4().hex,
            'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })
        cls.portal = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BWork permission portal',
            'login': 'bwork-permission-portal-%s' % uuid4().hex,
            'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_portal').id])],
        })
        cls.service = cls.env['baseer.bwork.service'].with_user(cls.member)

    def test_new_internal_account_is_closed_without_an_explicit_grant(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BWork default closed', 'login': 'bwork-closed-' + uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set(self.env.ref('base.group_user').ids)],
        })
        self.assertTrue(user._is_internal())
        self.assertTrue(all(user[name] is False for name in _CORE_SWITCHES))
        service = self.env['baseer.bwork.service'].with_user(user)
        rights = service._v2_bootstrap()['permissions']
        for name in ('chat_view', 'chat_send', 'media', 'group_create', 'group_manage',
                     'task_view', 'task_manage', 'room_admin'):
            self.assertIs(rights[name], False, name)
        for read in (service._v2_rooms, service._v2_tasks):
            with self.assertRaises(AccessError):
                read()
        revision = user.bwork_permission_revision
        administrative_user = user.with_user(self.admin)
        self.assertFalse(administrative_user.env.su)
        administrative_user.write({'bwork_chat_view': True, 'bwork_chat_send': True})
        rights = service._v2_bootstrap()['permissions']
        self.assertTrue(rights['chat_view'])
        self.assertTrue(rights['chat_send'])
        self.assertFalse(rights['task_view'])
        self.assertGreater(user.bwork_permission_revision, revision)
        self.assertEqual(service._v2_rooms()['rooms'], [])

    def test_ordinary_user_cannot_enable_own_closed_switches(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BWork no self grant', 'login': 'bwork-no-self-' + uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set(self.env.ref('base.group_user').ids)],
        })
        with self.assertRaises(AccessError):
            user.with_user(user).write({'bwork_chat_view': True})
        self.assertFalse(user.bwork_chat_view)

    def test_bootstrap_adds_permissions_without_changing_legacy_capabilities(self):
        bootstrap = self.service._v2_bootstrap()
        self.assertEqual(bootstrap['permissions']['version'], 1)
        self.assertTrue(bootstrap['permissions']['chat_view'])
        self.assertTrue(bootstrap['permissions']['chat_send'])
        self.assertTrue(bootstrap['permissions']['task_manage'])
        self.assertTrue(bootstrap['capabilities']['rooms'])
        self.assertFalse(bootstrap['capabilities']['tasks'])
        self.assertFalse(self.portal._bwork_effective_permissions()['chat_view'])
        self.assertFalse(self.portal.bwork_chat_view)

    def test_chat_revocation_blocks_reads_but_not_bootstrap_or_permission_hint(self):
        start = self.service._v2_bootstrap()['permissions']['revision']
        self.member.write({'bwork_chat_view': False})
        bootstrap = self.service._v2_bootstrap()
        self.assertFalse(bootstrap['permissions']['chat_view'])
        self.assertFalse(bootstrap['permissions']['chat_send'])
        self.assertGreater(bootstrap['permissions']['revision'], start)
        with self.assertRaises(AccessError):
            self.service._v2_rooms()
        with self.assertRaises(AccessError):
            self.service._v2_history(1)
        with self.assertRaises(AccessError):
            self.service._v2_change_snapshot('rooms', watermark=0)
        legacy = self.service._v2_changes(after=0)
        self.assertNotIn('permissions', [row['kind'] for row in legacy['changes']])
        changes = self.service._v2_changes(after=0, include_permissions=True)
        self.assertIn('permissions', [row['kind'] for row in changes['changes']])
        self.assertTrue(all(set(row) == {'seq', 'kind'} for row in changes['changes']
                            if row['kind'] == 'permissions'))

    def test_write_switches_are_independent_and_server_enforced(self):
        self.member.write({'bwork_chat_send': False, 'bwork_media': False,
                           'bwork_task_manage': False, 'bwork_group_create': False})
        rights = self.service._v2_bootstrap()['permissions']
        self.assertTrue(rights['chat_view'])
        self.assertTrue(rights['task_view'])
        self.assertFalse(rights['chat_send'])
        self.assertFalse(rights['media'])
        self.assertFalse(rights['task_manage'])
        self.assertFalse(rights['group_create'])
        with self.assertRaises(AccessError):
            self.service._v2_send(1, {})
        with self.assertRaises(AccessError):
            self.service._v2_upload_scope(1, {})
        with self.assertRaises(AccessError):
            self.service._v2_task_create({})
        with self.assertRaises(AccessError):
            self.service._v2_group_create({})
        # Read remains available (no room/task exists for this account).
        self.assertEqual(self.service._v2_rooms()['rooms'], [])

    def test_task_revocation_blocks_snapshot_and_list(self):
        self.member.write({'bwork_task_view': False})
        with self.assertRaises(AccessError):
            self.service._v2_tasks()
        with self.assertRaises(AccessError):
            self.service._v2_change_snapshot('tasks', watermark=0)

    def test_company_scope_change_notifies_cache_purge(self):
        company = self.env['res.company'].create({'name': 'BWork permissions second company'})
        before = self.service._v2_bootstrap()['permissions']['revision']
        self.member.write({'company_ids': [Command.link(company.id)]})
        self.assertGreater(self.service._v2_bootstrap()['permissions']['revision'], before)
        hints = self.service._v2_changes(after=0, include_permissions=True)['changes']
        self.assertIn('permissions', [hint['kind'] for hint in hints])

    def test_room_admin_requires_original_group_and_admin_identity(self):
        room_group = self.env.ref('baseer_bwork.group_bwork_manager')
        self.assertFalse(self.member._bwork_effective_permissions()['room_admin'])
        self.admin.write({'group_ids': [Command.link(room_group.id)]})
        self.assertTrue(self.admin._bwork_effective_permissions()['room_admin'])
        with self.assertRaises(AccessError):
            self.member.write({'bwork_manage_rooms': True})

    def test_user_view_has_one_core_permissions_group(self):
        view = self.env.ref('baseer_bwork.view_users_form_bwork_capabilities')
        self.assertIn('name="bwork_capabilities"', view.arch_db)
