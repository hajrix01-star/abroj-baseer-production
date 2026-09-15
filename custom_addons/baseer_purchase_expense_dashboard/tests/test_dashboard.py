from datetime import date
from decimal import Decimal
from unittest.mock import patch

from odoo import Command, api
from odoo.addons.baseer_purchase_expense_dashboard.models.dashboard import (
    PurchaseExpenseDashboard,
    _ratio,
)
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

    def _user(self, name, role, companies=None, groups=()):
        companies = companies or self.company_a
        values = {
            'name': name,
            'login': name.lower().replace(' ', '_'),
            'company_id': self.company_a.id,
            'company_ids': [Command.set(companies.ids)],
        }
        if role:
            values['baseer_access_role'] = role
        else:
            values['group_ids'] = [Command.set([self.base_group.id, *[group.id for group in groups]])]
        return self.env['res.users'].sudo().with_context(no_reset_password=True).create(values)

    def _as_user(self, user, company=None):
        context = dict(self.env.context, allowed_company_ids=[(company or self.company_a).id])
        user_env = api.Environment(self.env.cr, user.id, context)
        return user_env['spreadsheet.dashboard'].browse(self.dashboard.id)

    def test_ped_t01_payload_keeps_gross_cards_and_server_owned_net_ratios(self):
        """The UI receives rounded values only; it does not own money or ratio arithmetic."""
        owner = self._user('Supplier dashboard owner', 'owner')
        partner = self.env['res.partner'].create({'name': 'Dashboard supplier'})
        timeline = [{'key': '2026-09', 'label': '09/2026', 'total': {'value': '75.00', 'display': '75.00'}, 'paid': {'value': '15.00', 'display': '15.00'}}]
        vendors = [{'id': partner.id, 'name': partner.name, 'total': {'value': '50.00', 'display': '50.00'}, 'sales_ratio': {'available': True, 'value': '25.00', 'display': '25.00'}}]
        categories = [{'id': False, 'name': 'Unclassified', 'total': {'value': '30.00', 'display': '30.00'}, 'sales_ratio': {'available': True, 'value': '15.00', 'display': '15.00'}}]
        Move = self.env['account.move']
        with patch.object(PurchaseExpenseDashboard, '_baseer_purchase_totals', return_value=(Decimal('75.00'), Decimal('60.00'), Decimal('15.00'), 2)), patch.object(
            PurchaseExpenseDashboard, '_baseer_monthly_movement', return_value=timeline,
        ), patch.object(PurchaseExpenseDashboard, '_baseer_approved_pos_net_sales', return_value=Decimal('200.00')), patch.object(
            PurchaseExpenseDashboard, '_baseer_supplier_rows', return_value=vendors,
        ), patch.object(PurchaseExpenseDashboard, '_baseer_category_rows', return_value=categories), patch.object(
            type(Move), 'search_count', return_value=1,
        ):
            payload = self._as_user(owner).get_baseer_supplier_bill_metrics({'native': {
                'type': 'range', 'from': '2026-09-01', 'to': '2026-09-30',
            }})
        self.assertEqual(payload['cards']['count']['value'], 2)
        self.assertEqual(payload['cards']['total']['value'], '75.00')
        self.assertEqual(payload['cards']['residual']['value'], '60.00')
        self.assertEqual(payload['cards']['paid']['value'], '15.00')
        self.assertEqual(payload['vendors'][0]['sales_ratio']['display'], '25.00')
        self.assertEqual(payload['categories'][0]['name'], 'Unclassified')
        self.assertTrue(payload['ratios']['available'])
        self.assertIn(('company_id', '=', self.company_a.id), payload['source_action']['domain'])
        self.assertIn(('currency_id', '=', self.company_a.currency_id.id), payload['source_action']['domain'])
        self.assertIn(('move_type', 'in', ('in_invoice', 'in_refund')), payload['source_action']['domain'])

    def test_ped_t02_ratio_handles_refunds_and_missing_sales_without_client_fallback(self):
        self.assertEqual(_ratio(Decimal('30'), Decimal('200'))['display'], '15.00')
        self.assertEqual(_ratio(Decimal('-30'), Decimal('200'))['display'], '-15.00')
        unavailable = _ratio(Decimal('30'), Decimal('0'))
        self.assertFalse(unavailable['available'])
        self.assertEqual(unavailable['display'], '—')

    def test_ped_t03_cashier_is_denied_and_company_scope_cannot_be_forged(self):
        cashier = self._user('Supplier dashboard cashier', 'cashier')
        with self.assertRaises(AccessError):
            self._as_user(cashier).get_baseer_supplier_bill_metrics({'native': None})

        owner = self._user('Supplier dashboard scoped owner', 'owner', self.company_a | self.company_b)
        with self.assertRaises(AccessError):
            self._as_user(owner, self.company_b).get_baseer_supplier_bill_metrics({'native': None})

    def test_ped_t04_accountant_gets_only_bounded_sales_aggregate_without_pos_group(self):
        accountant = self._user('Supplier dashboard accountant', None, groups=(self.account_group,))
        self.assertFalse(accountant.has_group('point_of_sale.group_pos_user'))
        Move = self.env['account.move']
        with patch.object(PurchaseExpenseDashboard, '_baseer_purchase_totals', return_value=(Decimal('20.00'), Decimal('0.00'), Decimal('20.00'), 1)), patch.object(
            PurchaseExpenseDashboard, '_baseer_monthly_movement', return_value=[],
        ), patch.object(PurchaseExpenseDashboard, '_baseer_approved_pos_net_sales', return_value=Decimal('100.00')) as aggregate, patch.object(
            PurchaseExpenseDashboard, '_baseer_supplier_rows', return_value=[],
        ), patch.object(PurchaseExpenseDashboard, '_baseer_category_rows', return_value=[]), patch.object(
            type(Move), 'search_count', return_value=0,
        ):
            payload = self._as_user(accountant).get_baseer_supplier_bill_metrics({'native': None})
        aggregate.assert_called_once()
        self.assertTrue(payload['ratios']['available'])
        self.assertNotIn('sales_source_action', payload)
        self.assertNotIn('sales_documents', payload)

    def test_ped_t05_period_is_bounded_before_any_source_read(self):
        owner = self._user('Supplier dashboard period owner', 'owner')
        with self.assertRaises(ValidationError):
            self._as_user(owner).get_baseer_supplier_bill_metrics({'native': {
                'type': 'range', 'from': '2025-01-01', 'to': '2026-01-02',
            }})

    def test_ped_t06_native_product_categories_use_signed_net_lines_and_unclassified(self):
        """The category SQL covers native invoices, refunds and product-less expense lines."""
        partner = self.env['res.partner'].create({'name': 'Category dashboard supplier'})
        category = self.env['product.category'].create({'name': 'Dashboard category'})
        product = self.env['product.product'].create({'name': 'Dashboard material', 'categ_id': category.id})
        expense = self.env['account.account'].search([('account_type', '=', 'expense')], limit=1)
        journal = self.env['account.journal'].search([('type', '=', 'purchase'), ('company_id', '=', self.company_a.id)], limit=1)
        self.assertTrue(expense and journal)

        def post(move_type, amount, with_product=True):
            line = {
                'name': 'Dashboard line', 'quantity': 1, 'price_unit': amount,
                'account_id': expense.id,
            }
            if with_product:
                line['product_id'] = product.id
            move = self.env['account.move'].create({
                'move_type': move_type, 'partner_id': partner.id, 'journal_id': journal.id,
                'invoice_date': '2026-09-15', 'invoice_line_ids': [Command.create(line)],
            })
            move.action_post()

        post('in_invoice', 100)
        post('in_refund', 20)
        post('in_invoice', 10, with_product=False)
        with self.assertQueryCount(1):
            rows = self.dashboard.sudo()._baseer_category_rows(
                self.company_a, self.company_a.currency_id, date(2026, 9, 1), date(2026, 9, 30), Decimal('200.00'),
            )
        by_id = {row['id']: row for row in rows}
        by_name = {row['name']: row for row in rows}
        self.assertEqual(by_id[category.id]['total']['value'], '80.00')
        self.assertEqual(by_id[category.id]['sales_ratio']['display'], '40.00')
        self.assertEqual(by_name['Unclassified']['total']['value'], '10.00')
        with self.assertQueryCount(1):
            timeline = self.dashboard.sudo()._baseer_monthly_movement(
                self.company_a, self.company_a.currency_id, date(2026, 8, 1), date(2026, 9, 30),
            )
        self.assertEqual(len(timeline), 2)
        # The movement card is explicitly gross; the product category remains net.
        self.assertEqual(timeline[1]['total']['value'], '102.00')
