from pathlib import Path
from xml.etree import ElementTree

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFinancialDashboard(TransactionCase):
    def test_financial_dashboard_is_a_distinct_finance_dashboard(self):
        dashboard = self.env.ref('baseer_financial_dashboard.dashboard_financial_performance')
        self.assertEqual(dashboard.baseer_dashboard_kind, 'financial_dashboard')
        self.assertEqual(
            dashboard.dashboard_group_id,
            self.env.ref('spreadsheet_dashboard.spreadsheet_dashboard_group_finance'),
        )

    def test_dashboard_contract_keeps_reports_and_tabs_separate(self):
        module = Path(__file__).resolve().parents[1]
        manifest = (module / '__manifest__.py').read_text(encoding='utf-8')
        template = ElementTree.parse(module / 'static/src/financial_dashboard.xml')
        source = (module / 'static/src/financial_dashboard.js').read_text(encoding='utf-8')
        self.assertIn("'baseer_profit_loss_report'", manifest)
        self.assertIn("'baseer_operations_report'", manifest)
        self.assertIn('role="tablist"', (module / 'static/src/financial_dashboard.xml').read_text(encoding='utf-8'))
        self.assertIn('role="tabpanel"', (module / 'static/src/financial_dashboard.xml').read_text(encoding='utf-8'))
        self.assertEqual(template.getroot().tag, 'templates')
        self.assertIn('IsolatedFinancialProfitLoss', source)
        self.assertIn('SalesPaymentsDashboard', source)
        self.assertIn('t-component="activeComponent"', (module / 'static/src/financial_dashboard.xml').read_text(encoding='utf-8'))

    def test_sales_payments_dashboard_is_a_presentation_only_extension(self):
        module = Path(__file__).resolve().parents[1]
        source = (module / 'static/src/financial_sales_payments.js').read_text(encoding='utf-8')
        template = (module / 'static/src/financial_dashboard.xml').read_text(encoding='utf-8')
        self.assertIn('extends BaseerOperationsPreview', source)
        self.assertNotIn('orm.call', source)
        self.assertIn('t-inherit="baseer_operations_report.Preview"', template)
        self.assertIn('t-inherit-mode="primary"', template)
        self.assertIn('t-set="salesDashboardData"', template)
        self.assertNotIn('t-set="dashboard"', template)
        self.assertIn('data-owner-row', template)
        self.assertIn('hasUnclassifiedOutflows', template)

    def test_dashboard_integration_preserves_existing_dashboard_boundaries(self):
        module = Path(__file__).resolve().parents[1]
        integration = (module / 'static/src/financial_dashboard.xml').read_text(encoding='utf-8')
        # Finance guards wrap rather than overwrite the shared nodes. This
        # survives later extension replacement regardless of asset order.
        # Five replacements protect the shared dashboard nodes; the sixth is
        # the primary-inherited sales canvas used only by this dashboard.
        self.assertEqual(integration.count('position="replace"'), 6)
        self.assertEqual(integration.count('<t t-if="!isBaseerFinancialDashboard">'), 5)
        self.assertEqual(integration.count('!isBaseerProcurementOperationsDashboard'), 5)

    def test_projection_matches_report_without_overriding_it(self):
        company = self.env.company
        account_model = self.env['account.account'].with_company(company)
        income = account_model.search([('company_ids', 'in', company.id), ('account_type', '=', 'income')], limit=1)
        other = account_model.search([('company_ids', 'in', company.id), ('account_type', '=', 'income_other')], limit=1)
        expense = account_model.search([('company_ids', 'in', company.id), ('account_type', '=', 'expense')], limit=1)
        balance = account_model.search([('company_ids', 'in', company.id), ('account_type', '=', 'asset_current'), ('reconcile', '=', False)], limit=1)
        journal = self.env['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'general')], limit=1)
        self.assertTrue(income and other and expense and balance and journal)
        for account, amount in ((income, 120), (income, -20), (other, 7), (expense, -30)):
            credit = max(amount, 0)
            debit = max(-amount, 0)
            move = self.env['account.move'].with_company(company).create({
                'date': '2041-05-10', 'journal_id': journal.id, 'move_type': 'entry',
                'line_ids': [
                    Command.create({'name': 'P&L', 'account_id': account.id, 'debit': debit, 'credit': credit}),
                    Command.create({'name': 'balance', 'account_id': balance.id, 'debit': credit, 'credit': debit}),
                ],
            })
            move._post(soft=False)
        filters = {'company_id': company.id, 'date_from': '2041-01-01', 'date_to': '2041-12-31', 'journal_ids': []}
        report = self.env['baseer.profit.loss.report'].get_report(filters)
        result = self.env['baseer.financial.dashboard.report'].get_dashboard_report(filters)
        self.assertEqual(result['rows'], report['rows'])
        self.assertEqual(result['gross_profit'], report['gross_profit'])
        self.assertEqual(result['net_profit'], report['net_profit'])
        self.assertEqual(self.env['baseer.profit.loss.report'].get_report(filters), report)
        cards = {item['key']: item for item in result['dashboard']['cards']}
        self.assertEqual(cards['income']['value']['amount'], '100.00')
        self.assertEqual(cards['gross_margin']['value']['display'], '100.00%')
        self.assertEqual(cards['expense']['value']['amount'], '30.00')
        self.assertEqual(cards['net_income']['value']['amount'], '77.00')
        self.assertEqual(result['dashboard']['waterfall'][3]['amount']['amount'], '7.00')
        empty = self.env['baseer.financial.dashboard.report'].get_dashboard_report({**filters, 'date_from': '2042-01-01', 'date_to': '2042-12-31'})
        self.assertFalse(next(item for item in empty['dashboard']['cards'] if item['key'] == 'gross_margin')['value']['available'])

    def test_projection_rejects_unauthorized_user_and_company(self):
        company = self.env.company
        user = self.env['res.users'].create({
            'name': 'Dashboard employee', 'login': 'isolated-dashboard-employee',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': company.id, 'company_ids': [Command.set(company.ids)],
        })
        filters = {'company_id': company.id, 'date_from': '2041-01-01', 'date_to': '2041-12-31', 'journal_ids': []}
        with self.assertRaises(AccessError):
            self.env['baseer.financial.dashboard.report'].with_user(user).get_dashboard_report(filters)
        foreign = self.env['res.company'].create({'name': 'Dashboard forbidden company'})
        with self.assertRaises(AccessError):
            self.env['baseer.financial.dashboard.report'].with_context(allowed_company_ids=company.ids).get_dashboard_report({**filters, 'company_id': foreign.id})
        journal = self.env['account.journal'].with_company(foreign).create({
            'name': 'Foreign dashboard journal', 'code': 'FDJ', 'type': 'general', 'company_id': foreign.id,
        })
        with self.assertRaises(AccessError):
            self.env['baseer.financial.dashboard.report'].get_dashboard_report({**filters, 'journal_ids': [journal.id]})
