from unittest.mock import patch

from odoo import Command, api
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class PurchaseExpenseDashboardCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company_a = self.env.company
        self.company_b = self.env['res.company'].create({
            'name': 'Supplier dashboard company B',
            'currency_id': self.company_a.currency_id.id,
        })
        self.base_group = self.env.ref('base.group_user')
        self.owner_group = self.env.ref('baseer_access_roles.group_owner')
        self.cashier_group = self.env.ref('baseer_access_roles.group_cashier')
        self.account_group = self.env.ref('account.group_account_invoice')
        self.dashboard = self.env['spreadsheet.dashboard'].sudo().create({
            'name': 'Supplier dashboard test',
            'dashboard_group_id': self.env.ref(
                'spreadsheet_dashboard.spreadsheet_dashboard_group_finance'
            ).id,
            'baseer_dashboard_kind': 'supplier_bills',
            'is_published': True,
            'company_ids': [Command.set([self.company_a.id])],
            'group_ids': [Command.set([self.owner_group.id, self.account_group.id])],
        })

    def _user(self, name, role, companies=None):
        companies = companies or self.company_a
        return self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': name,
            'login': name.lower().replace(' ', '_'),
            'company_id': self.company_a.id,
            'company_ids': [Command.set(companies.ids)],
            'baseer_access_role': role,
        })

    def _as_user(self, user, company=None):
        context = dict(self.env.context, allowed_company_ids=[(company or self.company_a).id])
        user_env = api.Environment(self.env.cr, user.id, context)
        return user_env['spreadsheet.dashboard'].browse(self.dashboard.id)

    def test_ped_t01_signed_bill_and_refund_use_native_amounts_and_exact_detail_domain(self):
        """The dashboard aggregates native signed fields; it never recreates bills."""
        owner = self._user('Supplier dashboard owner', 'owner')
        partner = self.env['res.partner'].create({'name': 'Dashboard supplier'})
        grouped = [
            [{'amount_total_signed:sum': -75, 'amount_residual_signed:sum': -60}],
            [{'amount_total_signed:sum': -75, 'amount_residual_signed:sum': -60}],
            [{'commercial_partner_id': (partner.id, partner.name), 'amount_total_signed:sum': -75}],
        ]
        Move = self.env['account.move']
        with patch.object(type(Move), 'formatted_read_group', side_effect=grouped), patch.object(
            type(Move), 'search_count', side_effect=[2, 1],
        ):
            payload = self._as_user(owner).get_baseer_supplier_bill_metrics({'native': {
                'type': 'range', 'from': '2026-09-01', 'to': '2026-09-30',
            }})
        self.assertEqual(payload['cards']['count']['value'], 2)
        self.assertEqual(payload['cards']['total']['value'], '75.00')
        self.assertEqual(payload['cards']['residual']['value'], '60.00')
        self.assertEqual(payload['cards']['paid']['value'], '15.00')
        self.assertEqual(payload['timeline'][0]['height_percent'], '100.00')
        self.assertEqual(payload['vendors'][0]['total']['value'], '75.00')
        self.assertEqual(payload['foreign_currency_count'], 1)
        self.assertIn(('company_id', '=', self.company_a.id), payload['source_action']['domain'])
        self.assertIn(('currency_id', '=', self.company_a.currency_id.id), payload['source_action']['domain'])
        self.assertIn(('move_type', 'in', ('in_invoice', 'in_refund')), payload['source_action']['domain'])

    def test_ped_t02_cashier_is_denied_and_company_scope_cannot_be_forged(self):
        cashier = self._user('Supplier dashboard cashier', 'cashier')
        with self.assertRaises(AccessError):
            self._as_user(cashier).get_baseer_supplier_bill_metrics({'native': None})

        owner = self._user('Supplier dashboard scoped owner', 'owner', self.company_a | self.company_b)
        with self.assertRaises(AccessError):
            self._as_user(owner, self.company_b).get_baseer_supplier_bill_metrics({'native': None})

    def test_ped_t03_period_is_bounded_before_any_source_read(self):
        owner = self._user('Supplier dashboard period owner', 'owner')
        with self.assertRaises(ValidationError):
            self._as_user(owner).get_baseer_supplier_bill_metrics({'native': {
                'type': 'range', 'from': '2025-01-01', 'to': '2026-01-02',
            }})
