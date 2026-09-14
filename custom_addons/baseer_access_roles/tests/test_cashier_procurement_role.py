from uuid import uuid4

from odoo import Command
from odoo.tests.common import TransactionCase


class CashierProcurementRoleCase(TransactionCase):
    def test_cpr_t01_cashier_role_inherits_only_procurement_cashier_capability(self):
        """The role reaches the existing guarded workflow, never manager/finance groups."""
        company = self.env.company
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Cashier procurement role',
            'login': 'cashier-procurement-%s' % uuid4().hex,
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'baseer_access_role': 'cashier',
        })

        self.assertTrue(cashier.has_group('baseer_access_roles.group_cashier'))
        self.assertTrue(cashier.has_group(
            'baseer_procurement_requests.group_procurement_cashier'
        ))
        self.assertTrue(cashier.has_group(
            'baseer_procurement_requests.group_procurement_user'
        ))
        self.assertFalse(cashier.has_group(
            'baseer_procurement_requests.group_procurement_manager'
        ))
        self.assertFalse(cashier.has_group(
            'baseer_procurement_requests.group_procurement_accountant'
        ))
        self.assertFalse(cashier.has_group('account.group_account_invoice'))
