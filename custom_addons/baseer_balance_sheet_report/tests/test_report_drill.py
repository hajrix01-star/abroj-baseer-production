from decimal import Decimal

from odoo.exceptions import AccessError
from odoo.tests.common import tagged
from odoo.addons.baseer_general_ledger_report.tests.test_report_drill import DrillFixture


@tagged('post_install', '-at_install', 'reports_unified_drill')
class TestBalanceDrill(DrillFixture):
    report_model = 'baseer.balance.sheet.report'

    def test_fixed_dispatch_roundtrip(self):
        engine = self.env['baseer.report.drill'].with_user(self.reader).sudo(False).with_context(allowed_company_ids=self.company.ids)
        result = engine.get_drilldown('balance_sheet', self.filters, {'kind': 'account', 'account_id': self.cash.id, 'section': 'assets'}, 1)
        action = engine.open_source('balance_sheet', self.filters, result['rows'][0]['source'])
        self.assertEqual((action['res_model'], action['res_id']), ('account.move', self.prior.id))

    def test_sections_equation_and_signed_accounts_match_authoritative_report(self):
        report = self.secured._build_pdf_report(self.filters)
        for key, value in report['equation'].items():
            result = self.secured._get_drilldown(self.filters, {'kind': 'equation', 'equation': key})
            self.assertEqual(result['value'], value)
            self.assertEqual(sum((self.amount(row['cells']['amount']) for row in result['rows']), Decimal(0)), self.amount(value))
        for section in report['sections']:
            result = self.secured._get_drilldown(self.filters, {'kind': 'section', 'section': section['key']})
            self.assertEqual(result['value'], section['amount'])
            for row in result['rows']:
                detail = self.secured._get_drilldown(self.filters, row['drill'])
                self.assertEqual(detail['value'], row['cells']['amount'])
                self.assertEqual(sum((self.amount(entry['cells']['amount']) for entry in detail['rows']), Decimal(0)),
                                 self.amount(detail['value']))
        income = self.secured._get_drilldown(self.filters, {'kind': 'account', 'section': 'current_result', 'account_id': self.income.id})
        self.assertEqual(income['value'], '50.00')
        self.assertNotIn(self.prior.line_ids.filtered(lambda line: line.account_id == self.income).id, self.source_ids(income))

    def test_appropriation_bridge_and_section_membership(self):
        allocation = self._entry('2047-01-02', self.unaffected, 100, 0, self.equity)
        result = self.secured._get_drilldown(self.filters, {'kind': 'section', 'section': 'brought_forward'})
        self.assertEqual(result['value'], '0.00')
        self.assertEqual(result['total_count'], 2)
        selector = {'kind': 'account', 'section': 'brought_forward', 'account_id': self.unaffected.id}
        detail = self.secured._get_drilldown(self.filters, selector)
        self.assertEqual(detail['value'], '-100.00')
        self.assertEqual(self.secured._open_drill_source(self.filters, detail['rows'][0]['source'])['res_id'], allocation.id)
        with self.assertRaises(AccessError):
            self.secured._get_drilldown(self.filters, dict(selector, section='assets'))

    def test_security_malformed_source_and_complete_source_cap(self):
        self.check_boundaries({'kind': 'account', 'section': 'assets', 'account_id': self.cash.id})
