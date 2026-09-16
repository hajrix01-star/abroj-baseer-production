from datetime import date
from decimal import Decimal
from unittest.mock import patch

from odoo import Command, api
from odoo.addons.baseer_purchase_expense_dashboard.models.dashboard import (
    PurchaseExpenseDashboard,
    _ratio,
)
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
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

    def test_ped_t01_payload_keeps_gross_cards_and_server_owned_gross_ratios(self):
        """The UI receives rounded values only; it does not own money or ratio arithmetic."""
        owner = self._user('Supplier dashboard owner', 'owner')
        partner = self.env['res.partner'].create({'name': 'Dashboard supplier'})
        timeline = [{'key': '2026-09', 'label': '09/2026', 'total': {'value': '75.00', 'display': '75.00'}, 'paid': {'value': '15.00', 'display': '15.00'}}]
        vendors = [{'id': partner.id, 'name': partner.name, 'total': {'value': '50.00', 'display': '50.00'}, 'sales_ratio': {'available': True, 'value': '25.00', 'display': '25.00'}}]
        categories = [{'id': False, 'name': 'Unclassified', 'total': {'value': '30.00', 'display': '30.00'}, 'sales_ratio': {'available': True, 'value': '15.00', 'display': '15.00'}}]
        Move = self.env['account.move']
        with patch.object(PurchaseExpenseDashboard, '_baseer_purchase_totals', return_value=(Decimal('75.00'), Decimal('60.00'), Decimal('15.00'), 2)), patch.object(
            PurchaseExpenseDashboard, '_baseer_monthly_movement', return_value=timeline,
        ), patch.object(PurchaseExpenseDashboard, '_baseer_approved_pos_gross_sales', return_value=Decimal('200.00')), patch.object(
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
        ), patch.object(PurchaseExpenseDashboard, '_baseer_approved_pos_gross_sales', return_value=Decimal('100.00')) as aggregate, patch.object(
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

    def _native_fixture(self):
        self.company_a.currency_id = self.env.ref('base.SAR')
        self.spend_plan = self.env.ref('baseer_native_spend.spend_plan')
        self.subplan = self.env['account.analytic.plan'].create({
            'name': 'Dashboard utilities', 'parent_id': self.spend_plan.id,
        })
        self.leaves = self.env['account.analytic.account'].create([
            {'name': name, 'plan_id': self.subplan.id, 'company_id': False}
            for name in ('Electricity', 'Water')
        ])
        self.expense = self.env['account.account'].create({
            'name': 'Dashboard expense', 'code': 'NBD600', 'account_type': 'expense',
            'company_ids': [Command.set(self.company_a.ids)],
        })
        payable = self.env['account.account'].create({
            'name': 'Dashboard payable', 'code': 'NBD210', 'account_type': 'liability_payable',
            'company_ids': [Command.set(self.company_a.ids)],
        })
        self.journal = self.env['account.journal'].create({
            'name': 'Dashboard purchases', 'code': 'NBDP', 'type': 'purchase',
            'company_id': self.company_a.id,
        })
        self.partner = self.env['res.partner'].create({
            'name': 'Native dashboard supplier', 'property_account_payable_id': payable.id,
        })
        self.tax = self.env['account.tax'].create({
            'name': 'Dashboard VAT 15%', 'amount': 15, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': self.company_a.id,
        })
        self.company_a._baseer_ensure_spend_applicability()

    def _native_bill(self, amount=100, distribution=None, move_type='in_invoice', tax=True):
        move = self.env['account.move'].create({
            'company_id': self.company_a.id, 'move_type': move_type,
            'partner_id': self.partner.id, 'journal_id': self.journal.id,
            'invoice_date': '2099-09-15',
            'invoice_line_ids': [Command.create({
                'name': 'Native no-product expense', 'quantity': 1, 'price_unit': amount,
                'account_id': self.expense.id,
                'tax_ids': [Command.set(self.tax.ids if tax else [])],
                'analytic_distribution': distribution if distribution is not None else {str(self.leaves[0].id): 100},
            })],
        })
        move.action_post()
        self.assertEqual(move.state, 'posted')
        return move

    def _native_rows(self, sales=Decimal('200.00')):
        return self.dashboard._baseer_category_rows(
            self.company_a, self.company_a.currency_id,
            date(2099, 9, 1), date(2099, 9, 30), sales,
        )

    def _historical_distribution(self, move, distribution):
        # TransactionCase-only fixture: model an already-posted legacy distribution
        # without weakening the production posting guard or updating real history.
        import json
        line = move.invoice_line_ids.filtered(lambda item: item.display_type == 'product')
        line.flush_recordset(['analytic_distribution'])
        self.env.cr.execute(
            'UPDATE account_move_line SET analytic_distribution = %s::jsonb WHERE id = %s',
            [json.dumps(distribution) if distribution is not None else None, line.id],
        )
        line.invalidate_recordset(['analytic_distribution'])

    def test_ped_t06_native_categories_keep_no_product_vat_refunds_and_archived_leaves(self):
        """Replaces snapshot T06: the stored native allocation is the reporting authority."""
        self._native_fixture()
        self._native_bill(100)
        self._native_bill(20, move_type='in_refund')
        self.leaves[0].active = False
        rows = self._native_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], self.subplan.id)
        self.assertEqual(rows[0]['total']['value'], '92.00')
        self.assertEqual(rows[0]['sales_ratio']['display'], '46.00')
        self.assertEqual(rows[0]['children'][0]['id'], self.leaves[0].id)
        self.assertEqual(rows[0]['children'][0]['total']['value'], '92.00')
        timeline = self.dashboard._baseer_monthly_movement(
            self.company_a, self.company_a.currency_id, date(2099, 8, 1), date(2099, 9, 30),
        )
        self.assertEqual(timeline[1]['total']['value'], '92.00')

    def test_ped_t07_joint_dimensions_do_not_double_spend(self):
        self._native_fixture()
        other_plan = self.env['account.analytic.plan'].create({'name': 'Dashboard unrelated dimension'})
        other = self.env['account.analytic.account'].create([
            {'name': name, 'plan_id': other_plan.id, 'company_id': False}
            for name in ('Location X', 'Location Y')
        ])
        a, b = self.leaves.ids
        x, y = other.ids
        self._native_bill(100, {f'{a},{x}': 30, f'{a},{y}': 20, f'{b},{x}': 50})
        rows = self._native_rows()
        self.assertEqual(rows[0]['total']['value'], '115.00')
        self.assertEqual({child['id']: child['total']['value'] for child in rows[0]['children']}, {a: '57.50', b: '57.50'})

    def test_ped_t08_legacy_missing_partial_and_malformed_preserve_gross(self):
        self._native_fixture()
        a, b = self.leaves.ids
        distributions = [None, {}, {str(a): 60}, {str(a): 120}, {f'{a},{b}': 100}, {str(a): 60, str(b): 60}]
        for distribution in distributions:
            move = self._native_bill(100, tax=False)
            self._historical_distribution(move, distribution)
        rows = self._native_rows(sales=Decimal('0'))
        classified = next(row for row in rows if row['id'])
        unclassified = next(row for row in rows if not row['id'])
        self.assertEqual(classified['total']['value'], '60.00')
        self.assertEqual(unclassified['total']['value'], '540.00')
        self.assertEqual(sum(Decimal(row['total']['value']) for row in rows), Decimal('600.00'))
        self.assertTrue(all(not row['sales_ratio']['available'] for row in rows))

    def test_ped_t09_currency_rounding_is_conservative_and_refund_symmetric(self):
        self._native_fixture()
        a, b = self.leaves.ids
        self._native_bill(.01, {str(a): 50, str(b): 50}, tax=False)
        rows = self._native_rows()
        self.assertEqual(rows[0]['total']['value'], '0.01')
        self.assertEqual(sum(Decimal(child['total']['value']) for child in rows[0]['children']), Decimal('.01'))
        self._native_bill(.01, {str(a): 50, str(b): 50}, move_type='in_refund', tax=False)
        rows = self._native_rows()
        self.assertEqual(rows[0]['total']['value'], '0.00')
        self.assertTrue(all(Decimal(child['total']['value']) == 0 for child in rows[0]['children']))

    def test_ped_t10_native_metadata_company_scope_and_root_hierarchy(self):
        self._native_fixture()
        foreign = self.env['account.analytic.account'].create({
            'name': 'Foreign confidential leaf', 'plan_id': self.subplan.id, 'company_id': self.company_b.id,
        })
        root_leaf = self.env['account.analytic.account'].create({
            'name': 'Root leaf', 'plan_id': self.spend_plan.id, 'company_id': False,
        })
        self._native_bill(50, {str(root_leaf.id): 100}, tax=False)
        legacy = self._native_bill(25, tax=False)
        self._historical_distribution(legacy, {str(foreign.id): 100})
        owner = self._user('Native dashboard single company', 'owner')
        rows = self._as_user(owner)._baseer_category_rows(
            self.company_a, self.company_a.currency_id, date(2099, 9, 1), date(2099, 9, 30), Decimal('100'),
        )
        self.assertNotIn('Foreign confidential leaf', str(rows))
        self.assertEqual(next(row for row in rows if row['id'] == self.spend_plan.id)['total']['value'], '50.00')
        self.assertEqual(next(row for row in rows if not row['id'])['total']['value'], '25.00')
        accountant = self._user('Native dashboard ordinary accountant', None, groups=(self.account_group,))
        account_rows = self._as_user(accountant)._baseer_category_rows(
            self.company_a, self.company_a.currency_id, date(2099, 9, 1), date(2099, 9, 30), Decimal('100'),
        )
        self.assertEqual(account_rows, rows)

    def test_ped_t11_allocator_handles_unknown_dimensions_and_invalid_percentages(self):
        from odoo.addons.baseer_purchase_expense_dashboard.models.dashboard import _allocate_spend, _spend_percentages
        self.assertEqual(_spend_percentages({'9': 100}, {1, 2}), {False: Decimal('100')})
        self.assertEqual(_spend_percentages({'1': 30, '1,9': 30}, {1, 2}), {1: Decimal('60'), False: Decimal('40')})
        for distribution in (
            {'1': 'NaN'}, {'1': -1}, {'1': 60, '2': 60}, {'1,2': 100},
            {'1,1': 50}, {'١': 100}, {'+1': 100}, {' 1': 100}, {'1,': 100},
        ):
            self.assertEqual(_spend_percentages(distribution, {1, 2}), {False: Decimal('100')})
        shares = {1: Decimal('33.33'), 2: Decimal('33.33'), False: Decimal('33.34')}
        allocated = _allocate_spend(Decimal('.01'), shares, self.company_a.currency_id)
        self.assertEqual(sum(allocated.values()), Decimal('.01'))

    def test_ped_t12_global_vat_rounding_reconciles_to_native_bill_gross(self):
        self._native_fixture()
        self.company_a.tax_calculation_rounding_method = 'round_globally'
        a, b = self.leaves.ids
        move = self.env['account.move'].create({
            'company_id': self.company_a.id, 'move_type': 'in_invoice',
            'partner_id': self.partner.id, 'journal_id': self.journal.id,
            'invoice_date': '2099-09-15',
            'invoice_line_ids': [Command.create({
                'name': 'Global VAT rounding source', 'quantity': 1, 'price_unit': .05,
                'account_id': self.expense.id, 'tax_ids': [Command.set(self.tax.ids)],
                'analytic_distribution': {str(a): 50, str(b): 50},
            }) for _ in range(3)],
        })
        move.action_post()
        self.assertEqual(move.state, 'posted')
        self.assertAlmostEqual(move.amount_total, .17)
        rows = self._native_rows()
        expected = -Decimal(str(move.amount_total_signed))
        self.assertEqual(sum(Decimal(row['total']['value']) for row in rows), expected)
        self.assertEqual(sum(Decimal(child['total']['value']) for row in rows for child in row['children']), expected)
        owner = self._user('Dashboard partially visible invoice', 'owner')
        hidden = move.invoice_line_ids.filtered(lambda line: line.display_type == 'product')[0]
        restriction = self.env['ir.rule'].create({
            'name': 'Dashboard test one hidden bill line',
            'model_id': self.env['ir.model']._get_id('account.move.line'),
            'domain_force': repr([('id', '!=', hidden.id)]),
        })
        limited = self._as_user(owner)._baseer_category_rows(
            self.company_a, self.company_a.currency_id, date(2099, 9, 1), date(2099, 9, 30), Decimal('100'),
        )
        # Two visible gross lines are .06 each; do not top them up to the hidden
        # full invoice's .17 or reveal the excluded line through reconciliation.
        self.assertEqual(sum(Decimal(row['total']['value']) for row in limited), Decimal('.12'))
        restriction.unlink()
        refund = move.copy({'move_type': 'in_refund', 'invoice_date': '2099-09-15'})
        refund.action_post()
        self.assertEqual(refund.state, 'posted')
        self.assertAlmostEqual(refund.amount_total, .17)
        net_rows = self._native_rows()
        self.assertEqual(sum(Decimal(row['total']['value']) for row in net_rows), Decimal('0'))
        self.assertTrue(all(Decimal(child['total']['value']) == 0 for row in net_rows for child in row['children']))

    def test_ped_t13_move_record_rules_also_protect_category_sources(self):
        self._native_fixture()
        a, b = self.leaves.ids
        self.leaves[1].name = 'Hidden supplier expense category'
        visible = self._native_bill(40, {str(a): 100}, tax=False)
        hidden = self._native_bill(731, {str(b): 100}, tax=False)
        owner = self._user('Dashboard restricted bill reader', 'owner')
        self.env['ir.rule'].create({
            'name': 'Dashboard test hide one bill independently of its lines',
            'model_id': self.env['ir.model']._get_id('account.move'),
            'domain_force': repr([('id', '!=', hidden.id)]),
        })
        dashboard = self._as_user(owner)
        # This explicitly reproduces the independent record-rule mismatch:
        # source lines remain readable while the source bill is unavailable.
        self.assertTrue(dashboard.env['account.move.line'].search_count([
            ('id', 'in', hidden.invoice_line_ids.ids),
        ]))
        self.assertFalse(dashboard.env['account.move'].search_count([('id', '=', hidden.id)]))
        payload = dashboard.get_baseer_supplier_bill_metrics({'native': {
            'type': 'range', 'from': '2099-09-01', 'to': '2099-09-30',
        }})
        self.assertEqual(payload['cards']['count']['value'], 1)
        self.assertEqual(Decimal(payload['cards']['total']['value']), Decimal(str(visible.amount_total)))
        self.assertEqual(
            sum(Decimal(row['total']['value']) for row in payload['categories']),
            Decimal(payload['cards']['total']['value']),
        )
        self.assertNotIn('Hidden supplier expense category', str(payload['categories']))
        self.assertNotIn('731', str(payload['categories']))
