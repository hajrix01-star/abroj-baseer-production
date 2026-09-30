from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDashboardView(TransactionCase):
    def test_project_details_live_inside_first_overview_tab(self):
        view = self.env.ref('abroj_project_costing.view_abroj_project_form')
        form = etree.fromstring(view.arch_db.encode())
        sheet = form.find('sheet')
        notebook = sheet.find('notebook')
        self.assertIsNotNone(notebook)
        self.assertEqual(notebook[0].get('name'), 'overview')
        self.assertFalse(sheet.xpath('./group | ./div[@class="oe_title"]'))
        overview = notebook[0]
        for field_name in ('name', 'owner_id', 'customer_name', 'agreement_amount',
                           'estimated_total', 'actual_total', 'description', 'note'):
            self.assertTrue(overview.xpath('.//field[@name="%s"]' % field_name), field_name)

    def test_project_pdf_uses_its_company_and_compact_rows(self):
        report = self.env.ref('abroj_project_costing.report_project_costing')
        arch = report.get_combined_arch()
        self.assertIn('t-call="abroj_project_costing.abroj_independent_layout"', arch)
        self.assertNotIn('t-call="web.external_layout"', arch)
        self.assertIn('abroj-pairs', arch)
        self.assertIn('abroj-data', arch)
        layout = self.env.ref('abroj_project_costing.abroj_independent_layout').get_combined_arch()
        self.assertIn('t-set="company" t-value="doc.company_id"', layout)
        self.assertIn('abroj-print-title', layout)
        self.assertIn('abroj-print-header', layout)
        paperformat = self.env.ref('abroj_project_costing.paperformat_abroj_project_report')
        self.assertEqual(paperformat.margin_top, 14)
