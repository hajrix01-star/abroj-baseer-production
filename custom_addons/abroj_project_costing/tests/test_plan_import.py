import base64
from io import BytesIO

from openpyxl import Workbook, load_workbook

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAbrojCostPlanImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Plan import test company',
            'abroj_project_costing_enabled': True,
        })
        cls.category = cls.env['abroj.cost.category'].with_company(cls.company).create({
            'name': 'التشطيبات',
            'company_id': cls.company.id,
        })

    def _project(self):
        return self.env['abroj.cost.project'].with_company(self.company).create({
            'name': 'Plan import test project',
            'company_id': self.company.id,
            'agreement_amount': 10000,
        })

    def _wizard(self, project, rows):
        content = '\n'.join([
            'category,name,pricing_method,quantity,material_unit_cost,auxiliary_unit_cost,labor_unit_cost,inclusive_unit_cost,lump_sum_cost,notes',
            *rows,
        ]).encode()
        return self.env['abroj.cost.plan.import.wizard'].with_company(self.company).create({
            'project_id': project.id,
            'company_id': self.company.id,
            'import_file': base64.b64encode(content),
            'import_filename': 'plan.csv',
        })

    def test_csv_import_creates_only_plan_lines(self):
        project = self._project()
        material_count_before = self.env['abroj.cost.material'].search_count([
            ('company_id', '=', self.company.id),
        ])
        wizard = self._wizard(project, [
            'التشطيبات,بند مقطوعية,lump_sum,1,0,0,0,0,1500,ملاحظة',
            'التشطيبات,بند تفصيلي,detailed,2,100,25,50,0,0,',
        ])
        action = wizard.action_import_plan()
        lines = project.plan_line_ids.sorted('sequence')
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].pricing_method, 'lump_sum')
        self.assertEqual(lines[0].estimated_total, 1500)
        self.assertEqual(lines[1].estimated_total, 350)
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(self.env['abroj.cost.material'].search_count([
            ('company_id', '=', self.company.id),
        ]), material_count_before)

    def test_xlsx_import_creates_plan_lines(self):
        project = self._project()
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'بنود الدراسة'
        sheet.append([
            'category', 'name', 'pricing_method', 'quantity',
            'material_unit_cost', 'auxiliary_unit_cost', 'labor_unit_cost',
            'inclusive_unit_cost', 'lump_sum_cost', 'notes',
        ])
        sheet.append(['التشطيبات', 'بند Excel', 'supply_install', 2, 0, 0, 0, 375, 0, ''])
        content = BytesIO()
        workbook.save(content)
        wizard = self.env['abroj.cost.plan.import.wizard'].with_company(self.company).create({
            'project_id': project.id,
            'company_id': self.company.id,
            'import_file': base64.b64encode(content.getvalue()),
            'import_filename': 'plan.xlsx',
        })
        wizard.action_import_plan()
        self.assertEqual(project.plan_line_ids.estimated_total, 750)

    def test_invalid_row_does_not_create_partial_plan(self):
        project = self._project()
        wizard = self._wizard(project, [
            'التشطيبات,بند صحيح,lump_sum,1,0,0,0,0,1500,',
            'فئة غير موجودة,بند مرفوض,lump_sum,1,0,0,0,0,900,',
        ])
        with self.assertRaises(UserError):
            wizard.action_import_plan()
        self.assertFalse(project.plan_line_ids)

    def test_import_rejects_existing_plan_to_prevent_duplicates(self):
        project = self._project()
        self.env['abroj.cost.plan.line'].with_company(self.company).create({
            'project_id': project.id,
            'category_id': self.category.id,
            'name': 'بند موجود',
            'pricing_method': 'lump_sum',
            'lump_sum_cost': 10,
        })
        wizard = self._wizard(project, [
            'التشطيبات,بند جديد,lump_sum,1,0,0,0,0,1500,',
        ])
        with self.assertRaises(UserError):
            wizard.action_import_plan()
        self.assertEqual(len(project.plan_line_ids), 1)

    def test_import_rechecks_plan_after_validation(self):
        """A later import must see a plan created after its file was read."""
        project = self._project()
        wizard = self._wizard(project, [
            'التشطيبات,بند متأخر,lump_sum,1,0,0,0,0,1500,',
        ])
        wizard._validated_values()
        self.env['abroj.cost.plan.line'].with_company(self.company).create({
            'project_id': project.id,
            'category_id': self.category.id,
            'name': 'بند استيراد آخر',
            'pricing_method': 'lump_sum',
            'lump_sum_cost': 10,
        })
        with self.assertRaises(UserError):
            wizard._lock_empty_project_plan()
        self.assertEqual(len(project.plan_line_ids), 1)

    def test_csv_rejects_row_501_before_import(self):
        project = self._project()
        wizard = self._wizard(project, [
            'التشطيبات,بند %s,lump_sum,1,0,0,0,0,1,' % index
            for index in range(1, 502)
        ])
        with self.assertRaises(ValidationError):
            wizard.action_import_plan()
        self.assertFalse(project.plan_line_ids)

    def test_export_returns_download_action(self):
        project = self._project()
        self.env['abroj.cost.plan.line'].with_company(self.company).create({
            'project_id': project.id,
            'category_id': self.category.id,
            'name': 'بند للتصدير',
            'pricing_method': 'lump_sum',
            'lump_sum_cost': 1500,
        })
        action = project.action_export_plan()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('download=true', action['url'])

    def test_export_escapes_spreadsheet_formula_text(self):
        project = self._project()
        self.env['abroj.cost.plan.line'].with_company(self.company).create({
            'project_id': project.id,
            'category_id': self.category.id,
            'name': '=2+2',
            'pricing_method': 'lump_sum',
            'lump_sum_cost': 1500,
            'notes': '@unsafe',
        })
        wizard = self.env['abroj.cost.plan.import.wizard'].with_company(self.company).create({
            'project_id': project.id,
            'company_id': self.company.id,
        })
        wizard.action_export_plan()
        workbook = load_workbook(BytesIO(base64.b64decode(wizard.export_file)), data_only=False)
        sheet = workbook['بنود الدراسة']
        self.assertEqual(sheet['B2'].data_type, 's')
        self.assertEqual(sheet['B2'].value, "'=2+2")
        self.assertEqual(sheet['J2'].value, "'@unsafe")
