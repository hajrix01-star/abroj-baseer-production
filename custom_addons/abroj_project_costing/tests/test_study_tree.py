from odoo.exceptions import UserError, ValidationError
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
        cls.other_category = cls.env['abroj.cost.category'].with_company(cls.company).create({
            'name': 'سباكة',
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
        # Section values are normalized server-side, not rejected by the form.
        section.write({'category_id': self.category.id, 'material_unit_cost': 100})
        self.assertFalse(section.category_id)
        self.assertEqual(section.material_unit_cost, 0)
        self.assertEqual(section.estimated_total, 0)
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

    def test_tree_returns_saved_descriptions_without_changing_rollups(self):
        project = self._project()
        section = self._section(project, 'المطبخ')
        description = 'أعمال المطبخ كاملة\nالكهرباء والسباكة <حسب المخطط>'
        section.write({'description': description})
        leaf = self._item(project, 'تمديدات كهرباء', section, 200)
        leaf.write({'description': 'تمديد الكيبل داخل الجدار'})
        empty = self._section(project, 'الصالة')

        rows = {row['id']: row for row in project.get_study_tree_data()}
        self.assertEqual(rows[section.id]['description'], description)
        self.assertEqual(rows[leaf.id]['description'], leaf.description)
        self.assertFalse(rows[empty.id]['description'])
        self.assertEqual(rows[section.id]['estimated_total'], 200)
        self.assertEqual(project.estimated_total, 200)
        self.assertEqual(leaf.parent_id, section)

    def test_new_line_amounts_use_company_currency_before_project_default_resolves(self):
        draft_section = self.env['abroj.cost.plan.line'].with_company(self.company).new({
            'node_kind': 'section',
            'name': 'قسم جديد',
        })
        draft_item = self.env['abroj.cost.plan.line'].with_company(self.company).new({
            'node_kind': 'item',
            'name': 'بند جديد',
            'pricing_method': 'lump_sum',
            'lump_sum_cost': 125.25,
        })
        self.assertEqual(draft_section.estimated_total, 0.0)
        self.assertEqual(draft_item.estimated_total, 125.25)

    def test_parent_section_action_forces_an_aggregation_only_root(self):
        project = self._project()
        action = project.action_open_plan_section_form()
        self.assertEqual(action['name'], 'إنشاء البند الأب')
        self.assertEqual(action['target'], 'new')
        self.assertTrue(action['context']['abroj_create_root_section'])
        self.assertEqual(action['context']['default_node_kind'], 'section')
        self.assertEqual(
            action['view_id'],
            self.env.ref('abroj_project_costing.view_abroj_plan_section_form').id,
        )
        self.assertEqual(action['views'], [(action['view_id'], 'form')])
        section_view = self.env['ir.ui.view'].browse(action['view_id']).arch_db
        for field_name in ('parent_id', 'category_id', 'material_id', 'pricing_method', 'uom_type', 'quantity', 'supplier_id'):
            self.assertNotIn('name="%s"' % field_name, section_view)

        defaults = self.env['abroj.cost.plan.line'].with_company(self.company).with_context(
            abroj_create_root_section=True,
        ).default_get(['node_kind', 'parent_id', 'quantity'])
        self.assertEqual(defaults['node_kind'], 'section')
        self.assertFalse(defaults['parent_id'])
        self.assertEqual(defaults['quantity'], 0.0)

        section = self.env['abroj.cost.plan.line'].with_company(self.company).with_context(
            abroj_create_root_section=True,
        ).create({
            'project_id': project.id,
            'node_kind': 'item',
            'category_id': self.category.id,
            'name': 'قسم مثبت من الخادم',
            'pricing_method': 'lump_sum',
            'lump_sum_cost': 500,
        })
        self.assertEqual(section.node_kind, 'section')
        self.assertFalse(section.parent_id)
        self.assertFalse(section.category_id)
        self.assertEqual(section.estimated_total, 0.0)

        section.write({
            'quantity': 2,
            'material_unit_cost': 100,
            'lump_sum_cost': 500,
        })
        self.assertEqual(section.quantity, 0.0)
        self.assertEqual(section.material_unit_cost, 0.0)
        self.assertEqual(section.lump_sum_cost, 0.0)
        self.assertEqual(section.estimated_total, 0.0)

        section.write({
            'node_kind': 'item',
            'category_id': self.category.id,
            'lump_sum_cost': 500,
        })
        self.assertEqual(section.node_kind, 'section')
        self.assertFalse(section.category_id)
        self.assertEqual(section.lump_sum_cost, 0.0)

    def test_planned_actual_cost_must_keep_the_leaf_work_category(self):
        project = self._project()
        leaf = self._item(project, 'تمديدات كهرباء', amount=100)
        with self.assertRaises(ValidationError):
            self.env['abroj.cost.actual.line'].with_company(self.company).create({
                'project_id': project.id,
                'plan_line_id': leaf.id,
                'category_id': self.other_category.id,
                'name': 'فاتورة بفئة خاطئة',
                'amount': 100,
            })
        self.env['abroj.cost.actual.line'].with_company(self.company).create({
            'project_id': project.id,
            'is_unplanned': True,
            'category_id': self.other_category.id,
            'name': 'تكلفة غير مخططة',
            'amount': 100,
        })

    def test_planned_actual_cost_derives_required_data_from_leaf_on_create(self):
        project = self._project()
        leaf = self._item(project, 'تمديدات كهرباء', amount=100)
        actual = self.env['abroj.cost.actual.line'].with_company(self.company).create({
            'project_id': project.id,
            'plan_line_id': leaf.id,
            'amount': 125,
        })
        self.assertEqual(actual.category_id, self.category)
        self.assertEqual(actual.name, leaf.name)
        self.assertFalse(actual.is_unplanned)

    def test_section_reorder_updates_server_sequence_and_tree_numbers(self):
        project = self._project()
        kitchen = self._section(project, 'المطبخ')
        hall = self._section(project, 'الصالة')
        exterior = self._section(project, 'الواجهة')
        electrical = self._section(project, 'كهرباء المطبخ', kitchen)
        leaf = self._item(project, 'تمديدات كهرباء', electrical, 100)
        actual = self.env['abroj.cost.actual.line'].with_company(self.company).create({
            'project_id': project.id,
            'plan_line_id': leaf.id,
            'amount': 80,
        })

        rows = project.action_reorder_plan_section(exterior.id, kitchen.id)
        root_rows = [row for row in rows if not row['parent_id']]
        self.assertEqual([row['name'] for row in root_rows], ['المطبخ', 'الواجهة', 'الصالة'])
        self.assertEqual([row['tree_number'] for row in root_rows], ['1', '2', '3'])
        self.assertEqual(exterior.sequence, 20)
        self.assertEqual(actual.plan_line_id, leaf)
        self.assertEqual(project.actual_total, 80)

    def test_section_cannot_move_into_its_descendant_or_be_deleted_with_children(self):
        project = self._project()
        kitchen = self._section(project, 'المطبخ')
        electrical = self._section(project, 'كهرباء المطبخ', kitchen)
        branch = self._section(project, 'لوحة التوزيع', electrical)
        self._item(project, 'قاطع رئيسي', kitchen, 100)

        with self.assertRaises(ValidationError):
            project.action_reorder_plan_section(kitchen.id, branch.id)
        with self.assertRaises(UserError):
            project.action_delete_plan_node(kitchen.id)

        empty = self._section(project, 'قسم فارغ')
        project.action_delete_plan_node(empty.id)
        self.assertFalse(empty.exists())
