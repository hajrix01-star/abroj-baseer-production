"""BChat checkboxes must be real, narrow Odoo capabilities."""

from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'bchat_user_permissions')
class BChatUserPermissionsCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.admin = self.env.ref('base.user_admin')
        self.company = self.env.company
        self.employee = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat permissions employee',
            'login': 'bchat-permissions-%s' % uuid4().hex,
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.target = self.employee.with_user(self.admin)

    def test_order_checkbox_grants_and_revokes_real_group(self):
        group = self.env.ref('baseer_bchat_procurement.group_bchat_procurement_operator')
        self.assertFalse(self.employee.bchat_can_order)
        self.target.write({'bchat_can_order': True})
        self.assertIn(group, self.employee.group_ids)
        self.assertTrue(self.employee.bchat_can_order)
        self.target.write({'bchat_can_order': False})
        self.assertNotIn(group, self.employee.group_ids)

    def test_non_admin_cannot_write_computed_checkbox(self):
        with self.assertRaises(AccessError):
            self.employee.with_user(self.employee).write({'bchat_can_order': True})
        self.assertFalse(self.employee.bchat_can_order)

    def test_room_manager_only_admin_even_with_group(self):
        group = self.env.ref('baseer_bchat.group_bchat_manager')
        self.assertFalse(self.employee.bchat_room_admin_eligible)
        with self.assertRaises(AccessError):
            self.target.write({'bchat_manage_rooms': True})
        self.assertNotIn(group, self.employee.group_ids)
        # A group grant through the generic Access Rights screen must not
        # bypass the service's account identity check.
        group.with_user(self.admin).write({'user_ids': [Command.link(self.employee.id)]})
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.employee)._require_room_manager()
        self.assertTrue(self.admin.bchat_room_admin_eligible)

    def test_role_preset_keeps_individual_order_grant(self):
        if 'baseer_access_role' not in self.employee._fields:
            self.skipTest('Baseer role presets are not installed')
        self.target.write({'bchat_can_order': True})
        self.target.write({'baseer_access_role': 'cashier'})
        self.assertTrue(self.employee.bchat_can_order)
        self.target.write({'baseer_access_role': 'pos_cashier'})
        self.assertTrue(self.employee.bchat_can_order)
        self.target.write({'baseer_access_role': 'accountant'})
        self.assertFalse(self.employee.bchat_can_order)
        with self.assertRaises(ValidationError):
            self.target.write({'bchat_can_order': True})

    def test_manager_checkbox_roundtrip(self):
        group = self.env.ref('baseer_bchat.group_bchat_manager')
        self.admin.with_user(self.admin).write({'bchat_manage_rooms': True})
        self.assertIn(group, self.admin.group_ids)
        if 'baseer_access_role' in self.admin._fields:
            self.admin.with_user(self.admin).write({'baseer_access_role': 'owner'})
            self.assertIn(group, self.admin.group_ids)
        self.env['baseer.bchat.service'].with_user(self.admin)._require_room_manager()
        self.admin.with_user(self.admin).write({'bchat_manage_rooms': False})
        self.assertNotIn(group, self.admin.group_ids)

    def test_native_user_form_contains_both_capabilities(self):
        view = self.env['res.users'].with_user(self.admin).get_view(
            view_id=self.env.ref('base.view_users_form').id, view_type='form',
        )
        self.assertIn('bchat_can_order', view['arch'])
        self.assertIn('bchat_manage_rooms', view['arch'])
