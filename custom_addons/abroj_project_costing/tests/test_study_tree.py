from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAbrojStudyTree(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Study tree test company',
            'abroj_project_costing_enabled': True,
        })
        cls.category = cls.env['abroj.cost.category'].with_company(cls.company).create({
            'name': 'كهرباء',
            'company_id': cls.company.id,
        })
        cls.other_company = cls.env['res.company'].create({
            'name': 'Study tree other company',
            'abroj_project_costing_enabled': True,
        })

    def _project(self, name='مشروع الشجرة'):
        return self.env['abroj.cost.project'].with_company(self.company).create({
            'name': name,
            'company_id': self.company.id,
            'agreement_amount': 10000,
        })

    def _section(self, project, name, parent=False):
        return self.env['abroj.cost.plan.line'].with_company(self.company).create({
            'project_id': project.id,
            'parent_id': parent.id if parent else False,
            'node_kind': 'section',
            'name': name,
            'quantity': 0,
        })

    def _item(self, project, name, parent=False, amount=0):
        return self.env['abroj.cost.plan.line'].with_company(self.company).create({
            'project_id': project.id,
            'parent_id': parent.id if parent else False,
            'node_kind': 'item',
            'category_id': self.category.id,
            'name': name,
            'pricing_method': 'lump_sum',
            'lump_sum_cost': amount,
        })

    def test_three_level_rollup_counts_each_leaf_once(self):
        project = self._project()
        kitchen = self._section(project, 'المطبخ')
        electrical = self._section(project, 'كهرباء المطبخ', kitchen)
        leaf = self._item(project, 'تمديدات المطبخ', electrical, 200)
        actual = self.env['abroj.cost.actual.line'].with_company(self.company).create({
            'project_id': project.id,
            'plan_line_id': leaf.id,
            'category_id': self.category.id,
            'name': 'فاتورة تمديدات',
            'amount': 230,
        })
        self.assertEqual(leaf.estimated_total, 200)
        self.assertEqual(electrical.estimated_total, 200)
        self.assertEqual(kitchen.estimated_total, 200)
        self.assertEqual(project.estimated_total, 200)
        self.assertEqual(kitchen.actual_total, 230)
        self.assertEqual(project.actual_total, 230)
        self.assertEqual(actual.plan_line_id, leaf)

    def test_sections_cannot_be_priced_or_receive_actual_costs(self):
        project = self._project()
        section = self._section(project, 'الصالة')
        with self.assertRaises(ValidationError):
            section.write({'category_id': self.category.id})
        with self.assertRaises(ValidationError):
            self.env['abroj.cost.actual.line'].with_company(self.company).create({
                'project_id': project.id,
                'plan_line_id': section.id,
                'category_id': self.category.id,
                'name': 'فاتورة غير صحيحة',
                'amount': 1,
            })

    def test_leaf_cannot_receive_children_or_cross_project_parent(self):
        project = self._project()
        leaf = self._item(project, 'بند رئيسي', amount=100)
        with self.assertRaises(ValidationError):
            self._item(project, 'ابن غير صالح', leaf, 10)
        other_project = self._project('مشروع آخر')
        other_section = self._section(other_project, 'قسم آخر')
        with self.assertRaises(ValidationError):
            self._item(project, 'عبر مشروع', other_section, 10)

    def test_existing_flat_item_remains_a_root_leaf(self):
        project = self._project()
        legacy = self._item(project, 'بند قديم', amount=150)
        self.assertEqual(legacy.node_kind, 'item')
        self.assertFalse(legacy.parent_id)
        self.assertEqual(project.estimated_total, 150)
