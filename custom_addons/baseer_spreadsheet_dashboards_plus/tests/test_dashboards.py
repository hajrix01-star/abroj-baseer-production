import json
from pathlib import Path
from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestSpreadsheetDashboards(TransactionCase):
    def test_snapshots_and_records(self):
        base = Path(__file__).resolve().parents[1] / 'data' / 'files'
        for name in ('accounting', 'purchase', 'warehouse'):
            snapshot = json.loads((base / (name + '.json')).read_text())
            self.assertEqual(len(snapshot['sheets']), 2)
            for pivot in snapshot['pivots'].values():
                model = self.env[pivot['model']]
                for measure in pivot['measures']:
                    self.assertTrue(measure['fieldName'] == '__count' or measure['fieldName'] in model._fields)
                for group in pivot['rows'] + pivot['columns']:
                    self.assertIn(group['fieldName'].split(':')[0], model._fields)
            for listing in snapshot['lists'].values():
                model = self.env[listing['model']]
                for field in listing['columns']:
                    self.assertIn(field, model._fields)
        for xmlid, group in [('accounting_overview', 'finance'), ('purchase_vendor_analysis', 'logistics'), ('warehouse_daily_operations', 'logistics')]:
            dashboard = self.env.ref('baseer_spreadsheet_dashboards_plus.' + xmlid)
            self.assertTrue(dashboard.is_published)
            self.assertEqual(dashboard.dashboard_group_id, self.env.ref('spreadsheet_dashboard.spreadsheet_dashboard_group_' + group))
            self.assertIn('snapshot', json.loads(dashboard._get_serialized_readonly_dashboard()))
