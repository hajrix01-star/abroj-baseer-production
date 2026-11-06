from pathlib import Path
from xml.etree import ElementTree

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
        self.assertIn('BaseerProfitLossReport', source)
        self.assertIn('BaseerOperationsPreview', source)
        self.assertIn('t-component="activeComponent"', (module / 'static/src/financial_dashboard.xml').read_text(encoding='utf-8'))

    def test_dashboard_integration_preserves_existing_dashboard_boundaries(self):
        module = Path(__file__).resolve().parents[1]
        integration = (module / 'static/src/financial_dashboard.xml').read_text(encoding='utf-8')
        # Finance guards wrap rather than overwrite the shared nodes. This
        # survives later extension replacement regardless of asset order.
        self.assertEqual(integration.count('position="replace"'), 5)
        self.assertEqual(integration.count('<t t-if="!isBaseerFinancialDashboard">'), 5)
        self.assertEqual(integration.count('!isBaseerProcurementOperationsDashboard'), 5)
