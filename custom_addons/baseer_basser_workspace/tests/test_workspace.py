from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class BasserWorkspaceCase(TransactionCase):
    def _user(self, role, company=None):
        company = company or self.env.company
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BASSER %s %s' % (role, uuid4().hex),
            'login': 'basser-%s-%s' % (role, uuid4().hex),
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'baseer_access_role': role,
        })

    def test_basser_t01_cashier_gets_only_seeded_shortcuts_and_native_actions(self):
        cashier = self._user('cashier')
        advance_menu = self.env.ref('baseer_access_roles.menu_pos_advance_entries')
        self.assertIn(
            advance_menu.id,
            self.env['ir.ui.menu'].with_user(cashier)._baseer_native_visible_menu_ids(),
        )
        self.assertTrue(self.env['baseer.advance.entry'].with_user(cashier).check_access_rights(
            'read', raise_exception=False,
        ))
        workspace = self.env['baseer.basser.workspace.section'].with_user(cashier).get_workspace()

        self.assertEqual(workspace['role'], 'cashier')
        self.assertFalse(workspace['can_manage'])
        item_ids = {item['id'] for section in workspace['sections'] for item in section['items']}
        expected = {
            self.env.ref('baseer_basser_workspace.workspace_item_cashier_new_procurement').id,
            self.env.ref('baseer_basser_workspace.workspace_item_cashier_procurement_requests').id,
            self.env.ref('baseer_basser_workspace.workspace_item_cashier_sales_summaries').id,
            self.env.ref('baseer_basser_workspace.workspace_item_cashier_advances').id,
            self.env.ref('baseer_basser_workspace.workspace_item_cashier_heat_calendar').id,
        }
        self.assertSetEqual(item_ids, expected)

        opened = self.env['baseer.basser.workspace.section'].with_user(cashier).open_workspace_item(
            self.env.ref('baseer_basser_workspace.workspace_item_cashier_procurement_requests').id,
        )
        self.assertEqual(
            opened['action_id'],
            self.env.ref('baseer_procurement_requests.action_procurement_request').id,
        )
        catalog_opened = self.env['baseer.basser.workspace.section'].with_user(cashier).open_workspace_item(
            self.env.ref('baseer_basser_workspace.workspace_item_cashier_new_procurement').id,
        )
        self.assertEqual(catalog_opened['action']['type'], 'ir.actions.client')
        self.assertEqual(catalog_opened['action']['tag'], 'baseer_procurement_requests.catalog')
        heat_calendar_opened = self.env['baseer.basser.workspace.section'].with_user(
            cashier
        ).open_workspace_item(
            self.env.ref('baseer_basser_workspace.workspace_item_cashier_heat_calendar').id,
        )
        self.assertEqual(heat_calendar_opened['action']['tag'], 'action_spreadsheet_dashboard')
        self.assertEqual(
            heat_calendar_opened['action']['params']['dashboard_id'],
            self.env.ref('baseer_sales_heat_calendar.dashboard_sales_heat_calendar').id,
        )
        self.assertFalse(cashier.has_group('base.group_system'))
        self.assertFalse(cashier.has_group(
            'baseer_sales_heat_calendar.group_heat_calendar_manager'
        ))
        with self.assertRaises(AccessError):
            self.env['baseer.heat.calendar.target'].with_user(cashier).check_access('create')
        with self.assertRaises(AccessError):
            self.env['baseer.official.occasion'].with_user(cashier).check_access('create')

    def test_basser_t01a_accountant_gets_custody_and_monthly_reconciliation(self):
        accountant = self._user('accountant')
        self.assertTrue(accountant.has_group(
            'baseer_procurement_requests.group_procurement_accountant'
        ))
        workspace = self.env['baseer.basser.workspace.section'].with_user(accountant).get_workspace()
        item_ids = {item['id'] for section in workspace['sections'] for item in section['items']}
        self.assertSetEqual(item_ids, {
            self.env.ref('baseer_basser_workspace.workspace_item_accountant_purchase_batches').id,
            self.env.ref('baseer_basser_workspace.workspace_item_accountant_advances').id,
            self.env.ref('baseer_basser_workspace.workspace_item_accountant_procurement_custody').id,
            self.env.ref(
                'baseer_basser_workspace.workspace_item_accountant_monthly_custody_reconciliation'
            ).id,
        })

    def test_basser_t02_configuration_cannot_expose_unapproved_or_server_actions(self):
        owner = self._user('owner')
        section = self.env.ref('baseer_basser_workspace.workspace_section_cashier_operations')
        item_model = self.env['baseer.basser.workspace.item'].with_user(owner)

        with self.assertRaises(ValidationError):
            item_model.create({
                'section_id': section.id,
                'name': 'Blocked manager catalogue',
                'menu_id': self.env.ref('baseer_procurement_requests.menu_procurement_options').id,
            })

        server_action = self.env['ir.actions.server'].create({
            'name': 'BASSER blocked server action',
            'model_id': self.env['ir.model']._get('baseer.procurement.request').id,
            'state': 'code',
            'code': 'action = {}',
        })
        policy_menu = self.env.ref('baseer_procurement_requests.menu_procurement_requests')
        policy_menu.write({'action': 'ir.actions.server,%s' % server_action.id})
        isolated_section = self.env['baseer.basser.workspace.section'].with_user(owner).create({
            'name': 'Server action validation',
            'role': 'cashier',
        })
        with self.assertRaises(ValidationError):
            item_model.create({
                'section_id': isolated_section.id,
                'name': 'Blocked server action',
                'menu_id': policy_menu.id,
            })

    def test_basser_t03_cashier_cannot_manage_and_forged_item_is_rejected(self):
        cashier = self._user('cashier')
        section_model = self.env['baseer.basser.workspace.section'].with_user(cashier)
        with self.assertRaises(AccessError):
            section_model.check_access('create')
        with self.assertRaises(AccessError):
            self.env['baseer.basser.workspace.item'].with_user(cashier).check_access('write')
        with self.assertRaises(AccessError):
            section_model.open_workspace_item(
                self.env.ref('baseer_basser_workspace.workspace_item_accountant_purchase_batches').id,
            )

    def test_basser_t04_company_scope_uses_server_active_company_only(self):
        company_a = self.env.company
        company_b = self.env['res.company'].create({
            'name': 'BASSER company B',
            'currency_id': company_a.currency_id.id,
        })
        cashier = self._user('cashier', company_a)

        forged = self.env['baseer.basser.workspace.section'].with_user(cashier).with_context(
            allowed_company_ids=[company_b.id],
        )
        with self.assertRaises(AccessError):
            forged.get_workspace()

        owner = self._user('owner', company_a)
        owner.company_ids |= company_b
        with self.assertRaises(ValidationError):
            self.env['baseer.basser.workspace.section'].with_user(owner).with_context(
                allowed_company_ids=[company_a.id],
            ).create({
                'name': 'Forbidden company scope',
                'role': 'cashier',
                'company_id': company_b.id,
            })

    def test_basser_t05_native_visibility_changes_with_role_and_policy_stays_bounded(self):
        cashier = self._user('cashier')
        menu_model = self.env['ir.ui.menu'].with_user(cashier)
        native_visible = menu_model._baseer_native_visible_menu_ids()
        request_menu = self.env.ref('baseer_procurement_requests.menu_procurement_requests')
        self.assertIn(request_menu.id, native_visible)

        cashier.write({'baseer_access_role': False})
        changed_visible = self.env['ir.ui.menu'].with_user(cashier)._baseer_native_visible_menu_ids()
        self.assertNotIn(request_menu.id, changed_visible)

        owner = self._user('owner')
        section_model = self.env['baseer.basser.workspace.section'].with_user(owner)
        item_model = self.env['baseer.basser.workspace.item'].with_user(owner)
        for sequence in range(1, 36):
            section = section_model.create({
                'name': 'Bounded cashier section %s' % sequence,
                'role': 'cashier',
                'sequence': 100 + sequence,
            })
            item_model.create({
                'section_id': section.id,
                'name': 'Bounded request %s' % sequence,
                'menu_id': request_menu.id,
            })
        section = section_model.create({
            'name': 'Over-limit cashier section',
            'role': 'cashier',
            'sequence': 200,
        })
        with self.assertRaises(ValidationError):
            item_model.create({
                'section_id': section.id,
                'name': 'Over-limit request',
                'menu_id': request_menu.id,
            })
