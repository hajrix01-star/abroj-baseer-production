from decimal import Decimal

from odoo.tests.common import tagged
from odoo.addons.baseer_general_ledger_report.tests.test_report_drill import DrillFixture


@tagged('post_install', '-at_install', 'reports_unified_drill')
class TestTrialDrill(DrillFixture):
    report_model = 'baseer.trial.balance.report'

    def test_fixed_dispatch_roundtrip(self):
        engine = self.env['baseer.report.drill'].with_user(self.reader).sudo(False).with_context(allowed_company_ids=self.company.ids)
        result = engine.get_drilldown('trial_balance', self.filters, {'kind': 'account', 'account_id': self.cash.id, 'measure': 'closing_debit'}, 1)
        action = engine.open_source('trial_balance', self.filters, result['rows'][0]['source'])
        self.assertEqual((action['res_model'], action['res_id']), ('account.move', self.prior.id))

    def test_all_six_sides_and_totals_preserve_net_side_values(self):
        report = self.secured._build_trial_balance(self.filters, full=True)
        for measure in ('opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit'):
            total = self.secured._get_drilldown(self.filters, {'kind': 'total', 'measure': measure})
            self.assertEqual(total['value'], report['total'][measure])
            self.assertEqual(sum((self.amount(row['cells']['amount']) for row in total['rows']), Decimal(0)),
                             self.amount(total['value']))
            for account in report['accounts']:
                detail = self.secured._get_drilldown(self.filters, {'kind': 'account', 'account_id': account['id'], 'measure': measure})
                self.assertEqual(detail['value'], account[measure])
        zero_side = self.secured._get_drilldown(self.filters, {'kind': 'account', 'account_id': self.cash.id, 'measure': 'closing_credit'})
        self.assertEqual(zero_side['value'], '0.00')
        self.assertTrue(zero_side['rows'])
        self.assertIn('net position', zero_side['basis'])
        self.assertEqual(sum((self.amount(row['cells']['amount']) for row in zero_side['rows']), Decimal(0)), Decimal(140))

    def test_brought_forward_side_is_classified_after_netting(self):
        self._entry('2046-12-30', self.expense, 25, 0, self.cash)
        result = self.secured._get_drilldown(self.filters, {'kind': 'rbf', 'measure': 'opening_credit'})
        self.assertEqual(result['value'], '75.00')
        self.assertEqual(sum((self.amount(row['cells']['amount']) for row in result['rows']), Decimal(0)), Decimal(-75))
        self.assertIn('after combining', result['basis'])
        for row in result['rows']:
            child = self.secured._get_drilldown(self.filters, row['drill'])
            self.assertEqual(child['value'], row['cells']['amount'])
            for entry in child['rows']:
                action = self.secured._open_drill_source(self.filters, entry['source'])
                self.assertEqual(action['res_model'], 'account.move')

    def test_security_malformed_source_and_complete_source_cap(self):
        self.check_boundaries({'kind': 'account', 'account_id': self.cash.id, 'measure': 'closing_debit'})
