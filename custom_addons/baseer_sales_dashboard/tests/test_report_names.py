from odoo.tests.common import TransactionCase
from ..models.report_names import report_name


class ReportNamesCase(TransactionCase):
    def test_language_and_order(self):
        for source, ar, en in (
            ('نقدي | Cash', 'نقدي', 'Cash'),
            ('HungerStation | هنقرستيشن', 'هنقرستيشن', 'HungerStation'),
            ('دوحة المستهلك | dohat almostahlik', 'دوحة المستهلك', 'dohat almostahlik'),
            ('فرع 2 | Branch 2', 'فرع 2', 'Branch 2'),
        ):
            self.assertEqual(report_name(source, 'ar_001'), ar)
            self.assertEqual(report_name(source, 'en_US'), en)

    def test_ambiguous_and_single_labels_are_preserved(self):
        for source in (False, '', 'ARZ', 'المعلم الشامي', 'A | B', 'نقدي | بنك',
                       'فرع | Branch | Detail', 'نقدي | '):
            for lang in ('ar_001', 'en_US'):
                self.assertEqual(report_name(source, lang), source)

    def test_company_response_changes_only_display_name(self):
        company = self.env.company
        source = 'شركة الاختبار | Test Company'
        company.name = source
        dashboard = self.env.ref('baseer_sales_dashboard.dashboard_executive_center')
        for lang, expected in (('ar_001', 'شركة الاختبار'), ('en_US', 'Test Company')):
            options = dashboard.with_context(lang=lang).get_baseer_executive_companies()
            row = next(row for row in options['companies'] if row['id'] == company.id)
            self.assertEqual(row['name'], expected)
        self.assertEqual(company.name, source)
