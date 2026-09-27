from odoo.tests.common import TransactionCase
from decimal import Decimal
from ..models.report_names import report_name


class ReportNamesCase(TransactionCase):
    def test_category_ranks_and_rounding_do_not_change_with_language(self):
        buckets = {1: {'name': 'ألف | Zulu', 'kind': 'bank', 'sales': Decimal('1')},
                   2: {'name': 'باء | Alpha', 'kind': 'bank', 'sales': Decimal('1')},
                   3: {'name': 'تاء | Bravo', 'kind': 'bank', 'sales': Decimal('1')}}
        dashboard = self.env['spreadsheet.dashboard']
        results = [dashboard.with_context(lang=lang)._baseer_category_performance(
            buckets, Decimal('3'), True) for lang in ('ar_001', 'en_US')]
        for key in ('rows', 'chart_rows'):
            self.assertEqual([(r['category_id'], r['sales'], r['share']) for r in results[0][key]],
                             [(r['category_id'], r['sales'], r['share']) for r in results[1][key]])
        for key in ('highest', 'lowest'):
            self.assertEqual(results[0]['performance'][key]['category_id'], results[1]['performance'][key]['category_id'])
        self.assertEqual(results[0]['rows'][0]['name'], 'ألف')
        self.assertEqual(results[1]['rows'][0]['name'], 'Zulu')

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
        # LANG3 stores own-company Arabic officially when identity addon exists.
        self.assertEqual(company.name, 'شركة الاختبار' if 'baseer_name_ar' in company._fields else source)
