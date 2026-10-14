"""Independent BChat order grants are administrative, durable and server-side."""

from pathlib import Path
from runpy import run_path
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'bchat_user_permissions')
class BChatUserPermissionsCase(TransactionCase):
    def setUp(self):
        super().setUp()
        if 'baseer_access_role' not in self.env['res.users']._fields:
            self.skipTest('BChat order permissions require Baseer access roles')
        self.admin = self.env.ref('base.user_admin')
        self.company = self.env.company
        self.employee = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat permissions employee',
            'login': 'bchat-permissions-%s' % uuid4().hex,
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'baseer_access_role': 'pos_cashier',
        })
        self.service = self.env['baseer.bchat.service'].with_user(self.employee)

    def _grant(self, **flags):
        self.employee.with_user(self.admin).write(flags)

    def test_create_and_receive_are_independent(self):
        with self.assertRaises(AccessError):
            self.service._v2_order_options()
        self._grant(bchat_order_view=True, bchat_order_create=True)
        options = self.service._v2_order_options()
        self.assertEqual((options['can_view'], options['can_create'], options['can_receive']),
                         (True, True, False))
        self.assertEqual(options['access'], 'viewer')
        self.assertEqual(
            tuple(self.service._v2_bootstrap()['permissions'][key] for key in (
                'order_view', 'order_create', 'order_receive',
            )), (True, True, False),
        )
        self.service._v2_order_options(self.company.id)
        with self.assertRaises(AccessError):
            self.service._v2_receipts(self.company.id)
        self._grant(bchat_order_create=False, bchat_order_receive=True)
        options = self.service._v2_order_options()
        self.assertEqual((options['can_view'], options['can_create'], options['can_receive']),
                         (True, False, True))
        with self.assertRaises(AccessError):
            self.service._v2_order_options(self.company.id)
        self.service._v2_receipts(self.company.id)
        self._grant(bchat_order_create=True)
        self.assertEqual(self.service._v2_order_options()['access'], 'operator')
        self.assertTrue(self.employee.sudo().bchat_can_order)

    def test_legacy_group_cannot_authorize_and_role_change_does_not_erase_grants(self):
        group = self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator')
        self.employee.write({'group_ids': [Command.link(group.id)]})
        with self.assertRaises(AccessError):
            self.service._v2_order_options()
        self._grant(bchat_order_view=True, bchat_order_create=True,
                    bchat_order_receive=True)
        previous = self.employee.sudo().bchat_permission_revision
        self.employee.write({'baseer_access_role': 'accountant'})
        self.employee.invalidate_recordset(['bchat_permission_revision'])
        self.assertGreater(self.employee.sudo().bchat_permission_revision, previous)
        self.assertTrue(self.employee.sudo().bchat_order_create)
        self.assertTrue(self.employee.sudo().bchat_order_receive)
        options = self.service._v2_order_options()
        self.assertEqual((options['can_view'], options['can_create'], options['can_receive']),
                         (True, False, False))
        self.employee.write({'baseer_access_role': 'cashier'})
        self.assertEqual(self.service._v2_order_options()['access'], 'operator')
        self.assertNotIn(group, self.employee.group_ids)

    def test_admin_only_and_no_hidden_view_grant(self):
        with self.assertRaises(AccessError):
            self.employee.with_user(self.employee).write({'bchat_order_view': True})
        with self.env.cr.savepoint(), self.assertRaises(ValidationError):
            self._grant(bchat_order_create=True)
        self._grant(bchat_order_view=True, bchat_order_create=True)
        with self.env.cr.savepoint(), self.assertRaises(ValidationError):
            self._grant(bchat_order_view=False)
        self._grant(bchat_order_view=False, bchat_order_create=False)
        with self.assertRaises(AccessError):
            self.service._v2_order_options()

    def test_revocation_increments_permission_revision_and_emits_hint(self):
        self._grant(bchat_order_view=True)
        previous = self.employee.sudo().bchat_permission_revision
        cursor = self.service._v2_changes(0, 10, include_permissions=True)['watermark']
        self._grant(bchat_order_view=False)
        self.employee.invalidate_recordset(['bchat_permission_revision'])
        self.assertGreater(self.employee.sudo().bchat_permission_revision, previous)
        changes = self.service._v2_changes(cursor, 10, include_permissions=True)
        self.assertIn('permissions', [row['kind'] for row in changes['changes']])

    def test_existing_rights_seed_once_and_new_users_default_closed(self):
        owner = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat owner before migration', 'login': 'bchat-owner-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'baseer_access_role': 'owner',
        })
        group = self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator')
        owner.write({'group_ids': [Command.link(group.id)]})
        self.employee.write({'group_ids': [Command.link(group.id)]})
        path = (Path(__file__).resolve().parents[1] / 'migrations' /
                '19.0.1.0.2' / 'post-migration.py')
        marker = 'baseer_bchat_procurement.order_permissions_seed_19_0_1_0_2'
        settings = self.env['ir.config_parameter'].sudo()
        settings.set_param(marker, '')
        self.assertTrue(path.name.startswith('post-'))
        run_path(str(path))['migrate'](self.env.cr, '19.0.1.0.0')
        self.assertTrue(owner.sudo().bchat_order_view)
        self.assertFalse(owner.sudo().bchat_order_create)
        self.assertFalse(owner.sudo().bchat_order_receive)
        self.assertTrue(self.employee.sudo().bchat_order_view)
        self.assertTrue(self.employee.sudo().bchat_order_create)
        self.assertTrue(self.employee.sudo().bchat_order_receive)
        self._grant(bchat_order_view=False, bchat_order_create=False,
                    bchat_order_receive=False)
        run_path(str(path))['migrate'](self.env.cr, '19.0.1.0.1')
        self.assertFalse(self.employee.sudo().bchat_order_view)
        fresh = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat owner after migration',
            'login': 'bchat-new-owner-%s' % uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'baseer_access_role': 'owner',
        })
        self.assertFalse(fresh.sudo().bchat_order_view)

    def test_native_user_form_contains_separate_order_options(self):
        view = self.env['res.users'].with_user(self.admin).get_view(
            view_id=self.env.ref('base.view_users_form').id, view_type='form',
        )
        for field in ('bchat_order_view', 'bchat_order_create', 'bchat_order_receive'):
            self.assertIn(field, view['arch'])
