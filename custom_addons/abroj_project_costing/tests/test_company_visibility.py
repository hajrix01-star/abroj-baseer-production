from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCompanyVisibility(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enabled_company = cls.env['res.company'].create({
            'name': 'Costing enabled test company',
            'abroj_project_costing_enabled': True,
        })
        cls.disabled_company = cls.env['res.company'].create({
            'name': 'Costing disabled test company',
            'abroj_project_costing_enabled': False,
        })
        cls.manager = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Costing multi-company manager',
            'login': 'costing.multi.company.manager',
            'company_id': cls.enabled_company.id,
            'company_ids': [Command.set((cls.enabled_company | cls.disabled_company).ids)],
            'group_ids': [Command.set([cls.env.ref('abroj_project_costing.group_abroj_cost_manager').id])],
        })
        cls.admin = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Costing multi-company administrator',
            'login': 'costing.multi.company.admin',
            'company_id': cls.enabled_company.id,
            'company_ids': [Command.set((cls.enabled_company | cls.disabled_company).ids)],
            'group_ids': [Command.set([
                cls.env.ref('base.group_system').id,
                cls.env.ref('abroj_project_costing.group_abroj_cost_manager').id,
            ])],
        })
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Costing multi-company project owner',
            'login': 'costing.multi.company.owner',
            'company_id': cls.enabled_company.id,
            'company_ids': [Command.set((cls.enabled_company | cls.disabled_company).ids)],
            'group_ids': [Command.set([cls.env.ref('abroj_project_costing.group_abroj_cost_user').id])],
        })
        Project = cls.env['abroj.cost.project'].sudo()
        cls.enabled_project = Project.create({
            'name': 'Enabled company project',
            'company_id': cls.enabled_company.id,
            'owner_id': cls.user.id,
            'agreement_amount': 1000,
        })
        cls.disabled_project = Project.create({
            'name': 'Disabled company historical project',
            'company_id': cls.disabled_company.id,
            'agreement_amount': 1000,
        })
        cls.disabled_receipt = cls.env['abroj.cost.receipt'].sudo().create({
            'project_id': cls.disabled_project.id,
            'amount': 100,
        })
        category = cls.env['abroj.cost.category'].sudo().search([
            ('company_id', '=', cls.disabled_company.id),
        ], limit=1)
        product = cls.env['product.template'].create({'name': 'Costing import boundary product'})
        cls.disabled_import = cls.env['abroj.cost.material.import.wizard'].sudo().create({
            'company_id': cls.disabled_company.id,
            'category_id': category.id,
            'product_ids': [Command.set(product.ids)],
        })

    def _as_manager(self, company, model):
        return self.env[model].with_user(self.manager).with_context(
            allowed_company_ids=[company.id, self.enabled_company.id, self.disabled_company.id]
        )

    def test_disabled_company_blocks_direct_project_and_child_access(self):
        Project = self._as_manager(self.disabled_company, 'abroj.cost.project')
        Receipt = self._as_manager(self.disabled_company, 'abroj.cost.receipt')
        self.assertEqual(Project.search_count([('id', '=', self.disabled_project.id)]), 0)
        self.assertEqual(Receipt.search_count([('id', '=', self.disabled_receipt.id)]), 0)
        with self.assertRaises(AccessError):
            Project.browse(self.disabled_project.id).read(['name'])
        with self.assertRaises(AccessError):
            Receipt.browse(self.disabled_receipt.id).read(['name'])

    def test_other_allowed_company_does_not_expand_selected_company(self):
        Project = self._as_manager(self.enabled_company, 'abroj.cost.project')
        self.assertEqual(Project.search_count([('id', '=', self.enabled_project.id)]), 1)
        self.assertEqual(Project.search_count([('id', '=', self.disabled_project.id)]), 0)
        with self.assertRaises(AccessError):
            Project.browse(self.disabled_project.id).write({'location': 'forbidden'})
        self.assertFalse(self.disabled_project.sudo().location)

    def test_administrator_cannot_bypass_disabled_company_by_url(self):
        Project = self.env['abroj.cost.project'].with_user(self.admin).with_context(
            allowed_company_ids=[self.disabled_company.id, self.enabled_company.id],
        )
        with self.assertRaises(AccessError):
            Project.browse(self.disabled_project.id).read(['name'])

    def test_regular_owner_can_work_only_in_enabled_company(self):
        Project = self.env['abroj.cost.project'].with_user(self.user).with_context(
            allowed_company_ids=[self.enabled_company.id, self.disabled_company.id],
        )
        self.assertEqual(Project.search_count([('id', '=', self.enabled_project.id)]), 1)
        self.assertTrue(Project.browse(self.enabled_project.id).read(['name']))
        created = Project.create({'name': 'Owner project', 'agreement_amount': 100})
        self.assertEqual(created.company_id.id, self.enabled_company.id)
        disabled_scope = Project.with_context(
            allowed_company_ids=[self.disabled_company.id, self.enabled_company.id],
        )
        self.assertEqual(disabled_scope.search_count([('id', '=', self.enabled_project.id)]), 0)

    def test_disabled_company_cannot_create_and_reenable_restores_old_records(self):
        Project = self._as_manager(self.disabled_company, 'abroj.cost.project')
        with self.assertRaises(AccessError):
            Project.default_get(['name', 'company_id'])
        with self.assertRaises(AccessError):
            Project.create({
                'name': 'Must not be created',
                'company_id': self.disabled_company.id,
                'agreement_amount': 100,
            })
        self.disabled_company.sudo().abroj_project_costing_enabled = True
        self.assertEqual(Project.search_count([('id', '=', self.disabled_project.id)]), 1)

    def test_disabled_company_material_import_is_not_a_bypass(self):
        Category = self._as_manager(self.disabled_company, 'abroj.cost.category')
        Wizard = self._as_manager(self.disabled_company, 'abroj.cost.material.import.wizard')
        with self.assertRaises(AccessError):
            Category.create({'name': 'Forbidden category', 'company_id': self.disabled_company.id})
        with self.assertRaises(AccessError):
            Wizard.browse(self.disabled_import.id).read(['company_id'])
