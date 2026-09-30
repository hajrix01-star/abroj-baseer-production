from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAbrojMemberPermissions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Costing member permissions company',
            'abroj_project_costing_enabled': True,
        })
        user_group = cls.env.ref('abroj_project_costing.group_abroj_cost_user')
        manager_group = cls.env.ref('abroj_project_costing.group_abroj_cost_manager')

        def make_user(role, group=user_group):
            return cls.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Costing permissions %s' % role,
                'login': 'costing.permissions.%s' % role,
                'company_id': cls.company.id,
                'company_ids': [Command.set(cls.company.ids)],
                'group_ids': [Command.set(group.ids)],
            })

        cls.owner = make_user('owner')
        cls.viewer = make_user('viewer')
        cls.editor = make_user('editor')
        cls.manager = make_user('manager', manager_group)
        cls.category = cls.env['abroj.cost.category'].with_company(cls.company).create({
            'name': 'Member permissions category',
            'company_id': cls.company.id,
        })
        owner_env = cls.env(
            user=cls.owner,
            context=dict(cls.env.context, allowed_company_ids=cls.company.ids),
        )
        cls.project = owner_env['abroj.cost.project'].create({
            'name': 'Project with viewer and editor',
            'agreement_amount': 10000,
        })
        cls.memberships = {}
        for user, access_level in (
            (cls.viewer, 'view'), (cls.editor, 'edit'), (cls.manager, 'view'),
        ):
            cls.memberships[user.id] = owner_env['abroj.cost.project.member'].create({
                'project_id': cls.project.id,
                'user_id': user.id,
                'access_level': access_level,
            })
        cls.children = {}
        cls.child_values = {
            'abroj.cost.plan.line': {
                'project_id': cls.project.id,
                'name': 'Permission study item',
                'category_id': cls.category.id,
                'pricing_method': 'lump_sum',
                'lump_sum_cost': 100,
            },
            'abroj.cost.actual.line': {
                'project_id': cls.project.id,
                'name': 'Permission actual cost',
                'category_id': cls.category.id,
                'is_unplanned': True,
                'amount': 50,
            },
            'abroj.cost.receipt': {'project_id': cls.project.id, 'amount': 100},
            'abroj.cost.progress.stage': {
                'project_id': cls.project.id,
                'name': 'Permission stage',
                'planned_start_date': '2026-10-01',
                'planned_duration_days': 1,
            },
        }
        cls.child_updates = {
            'abroj.cost.plan.line': {'lump_sum_cost': 125},
            'abroj.cost.actual.line': {'amount': 75},
            'abroj.cost.receipt': {'amount': 125},
            'abroj.cost.progress.stage': {'planned_duration_days': 2},
        }
        for model, values in cls.child_values.items():
            cls.children[model] = owner_env[model].create(dict(values))
        cls.amendment = owner_env['abroj.cost.agreement.amendment'].create({
            'project_id': cls.project.id,
            'new_amount': 11000,
            'reason': 'Owner-only amendment',
        })

    def _as_user(self, user, model):
        return self.env[model].with_user(user).with_context(
            allowed_company_ids=self.company.ids,
        )

    def test_view_member_can_read_project_and_children(self):
        self.assertTrue(self.project.with_user(self.viewer).read(['name']))
        for model, child in self.children.items():
            with self.subTest(model=model):
                Model = self._as_user(self.viewer, model)
                self.assertEqual(Model.search_count([('id', '=', child.id)]), 1)
                self.assertTrue(Model.browse(child.id).read(['project_id']))

    def test_view_member_cannot_write_even_when_another_member_can_edit(self):
        for model, child in self.children.items():
            with self.subTest(model=model):
                field = next(iter(self.child_updates[model]))
                before = child[field]
                with self.assertRaises(AccessError), self.cr.savepoint():
                    self._as_user(self.viewer, model).browse(child.id).write(
                        self.child_updates[model],
                    )
                self.assertEqual(child[field], before)

    def test_view_member_cannot_create_children(self):
        for model, values in self.child_values.items():
            with self.subTest(model=model):
                Model = self._as_user(self.owner, model)
                before = Model.search_count([('project_id', '=', self.project.id)])
                with self.assertRaises(AccessError), self.cr.savepoint():
                    self._as_user(self.viewer, model).create(dict(values))
                self.assertEqual(
                    Model.search_count([('project_id', '=', self.project.id)]), before,
                )

    def test_edit_member_can_update_children_and_add_operational_records(self):
        with self.assertRaises(AccessError):
            self._as_user(self.editor, 'abroj.cost.project.member').browse(
                self.memberships[self.editor.id].id,
            ).read(['user_id', 'access_level'])
        for model, child in self.children.items():
            with self.subTest(model=model):
                Model = self._as_user(self.editor, model)
                self.assertTrue(Model.browse(child.id).write(self.child_updates[model]))
                if model != 'abroj.cost.plan.line':
                    created = Model.create(dict(self.child_values[model]))
                    self.assertEqual(created.project_id.id, self.project.id)

    def test_edit_member_still_cannot_change_project_or_plan_structure(self):
        with self.assertRaises(AccessError), self.cr.savepoint():
            self._as_user(self.editor, 'abroj.cost.project').browse(self.project.id).write({
                'location': 'Editor cannot change project',
            })
        Plan = self._as_user(self.editor, 'abroj.cost.plan.line')
        with self.assertRaises(AccessError), self.cr.savepoint():
            Plan.create(dict(self.child_values['abroj.cost.plan.line']))
        with self.assertRaises(AccessError), self.cr.savepoint():
            Plan.browse(self.children['abroj.cost.plan.line'].id).write({'parent_id': False})

    def test_members_cannot_escalate_access_or_modify_agreement(self):
        for user in (self.viewer, self.editor):
            with self.subTest(user=user.login):
                Member = self._as_user(user, 'abroj.cost.project.member')
                with self.assertRaises(AccessError), self.cr.savepoint():
                    Member.browse(self.memberships[user.id].id).write({'access_level': 'edit'})
                with self.assertRaises(AccessError), self.cr.savepoint():
                    self._as_user(user, 'abroj.cost.project').browse(self.project.id).write({
                        'member_ids': [Command.update(self.memberships[user.id].id, {
                            'access_level': 'edit',
                        })],
                    })
                Amendment = self._as_user(user, 'abroj.cost.agreement.amendment')
                with self.assertRaises(AccessError), self.cr.savepoint():
                    Amendment.browse(self.amendment.id).write({'new_amount': 12000})
                with self.assertRaises(AccessError), self.cr.savepoint():
                    Amendment.create({
                        'project_id': self.project.id,
                        'new_amount': 12000,
                        'reason': 'Member cannot amend agreement',
                    })
        self.assertEqual(self.memberships[self.viewer.id].access_level, 'view')
        self.assertEqual(self.amendment.new_amount, 11000)

    def test_owner_can_update_and_create_all_children(self):
        self.assertTrue(self._as_user(self.owner, 'abroj.cost.project').browse(
            self.project.id,
        ).write({'location': 'Owner project change'}))
        for model, child in self.children.items():
            with self.subTest(model=model):
                Model = self._as_user(self.owner, model)
                self.assertTrue(Model.browse(child.id).write(self.child_updates[model]))
                self.assertEqual(
                    Model.create(dict(self.child_values[model])).project_id.id,
                    self.project.id,
                )

    def test_owner_downgrade_revokes_editor_write_access(self):
        self.memberships[self.editor.id].write({'access_level': 'view'})
        Receipt = self._as_user(self.editor, 'abroj.cost.receipt')
        receipt = Receipt.browse(self.children['abroj.cost.receipt'].id)
        self.assertTrue(receipt.read(['amount']))
        with self.assertRaises(AccessError), self.cr.savepoint():
            receipt.write({'amount': 125})
        with self.assertRaises(AccessError), self.cr.savepoint():
            Receipt.create(dict(self.child_values['abroj.cost.receipt']))

    def test_manager_preserves_assigned_scope_and_existing_operations(self):
        for model, child in self.children.items():
            with self.subTest(model=model):
                Model = self._as_user(self.manager, model)
                self.assertTrue(Model.browse(child.id).write(self.child_updates[model]))
                created = Model.create(dict(self.child_values[model]))
                self.assertEqual(created.project_id.id, self.project.id)
                self.assertTrue(created.unlink())
        Project = self._as_user(self.owner, 'abroj.cost.project')
        unrelated = Project.create({'name': 'Unassigned project', 'agreement_amount': 1000})
        for model, values in self.child_values.items():
            with self.subTest(unassigned_model=model):
                values = dict(values, project_id=unrelated.id)
                child = self._as_user(self.owner, model).create(dict(values))
                Model = self._as_user(self.manager, model)
                self.assertEqual(Model.search_count([('id', '=', child.id)]), 0)
                with self.assertRaises(AccessError), self.cr.savepoint():
                    Model.browse(child.id).read(['project_id'])
                with self.assertRaises(AccessError), self.cr.savepoint():
                    Model.browse(child.id).write(self.child_updates[model])
                with self.assertRaises(AccessError), self.cr.savepoint():
                    Model.create(dict(values))
                with self.assertRaises(AccessError), self.cr.savepoint():
                    Model.browse(child.id).unlink()
