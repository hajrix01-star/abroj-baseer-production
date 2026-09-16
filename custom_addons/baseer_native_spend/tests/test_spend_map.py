from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.baseer_native_spend.models.spend_map import (
    BaseerSpendMapRun,
    _ACTIVE_CATALOG_VERSION_PARAM,
)


@tagged('post_install', '-at_install')
class SpendMapPreviewCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.plan = cls.env.ref('baseer_native_spend.spend_plan')
        cls.subplan = cls.env['account.analytic.plan'].create({
            'name': 'MAP Test root', 'parent_id': cls.plan.id,
        })
        cls.leaf_a = cls.env['account.analytic.account'].create({
            'name': 'MAP Test A', 'plan_id': cls.subplan.id, 'company_id': False,
        })
        cls.leaf_b = cls.env['account.analytic.account'].create({
            'name': 'MAP Test B', 'plan_id': cls.subplan.id, 'company_id': False,
        })

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            _ACTIVE_CATALOG_VERSION_PARAM, 'noorix-v1',
        )
        self.tag_a = self.env['res.partner.category'].create({'name': 'MAP tag A %s' % self._testMethodName})
        self.tag_b = self.env['res.partner.category'].create({'name': 'MAP tag B %s' % self._testMethodName})
        self.supplier = self.env['res.partner'].create({
            'name': 'MAP supplier %s' % self._testMethodName, 'supplier_rank': 1,
            'category_id': [Command.set(self.tag_a.ids)],
        })
        self.category = self.env['product.category'].create({'name': 'MAP category %s' % self._testMethodName})
        self.product = self.env['product.product'].create({
            'name': 'MAP product %s' % self._testMethodName, 'type': 'service', 'categ_id': self.category.id,
        })

    def rule(self, kind, leaf, approve=True, **values):
        selector = {
            'partner': 'partner_id',
            'partner_tag': 'partner_tag_id',
            'product': 'product_id',
            'product_category': 'product_category_id',
        }[kind]
        defaults = {
            'selector_kind': kind,
            'analytic_account_id': leaf.id,
            selector: values.pop(selector, {
                'partner_id': self.supplier.id,
                'partner_tag_id': self.tag_a.id,
                'product_id': self.product.id,
                'product_category_id': self.category.id,
            }[selector]),
        }
        defaults.update(values)
        record = self.env['baseer.spend.map.rule'].create(defaults)
        if approve:
            record.action_approve()
        return record

    def readiness_run(self):
        return self.env['baseer.spend.map.run'].create({
            'name': 'MAP preview', 'company_id': self.company.id,
        })

    def test_active_catalog_parameter_controls_new_rules_and_previews(self):
        self.env['ir.config_parameter'].sudo().set_param(
            _ACTIVE_CATALOG_VERSION_PARAM, 'baseer-v2',
        )
        rule = self.rule('partner_tag', self.leaf_a)
        run = self.readiness_run()
        self.assertEqual(rule.catalog_version, 'baseer-v2')
        self.assertEqual(run.catalog_version, 'baseer-v2')

    def test_same_scope_selector_is_rejected_even_when_destination_matches(self):
        self.rule('partner_tag', self.leaf_a)
        with self.assertRaises(ValidationError):
            self.rule('partner_tag', self.leaf_a)

    def test_company_override_has_its_own_natural_key(self):
        shared = self.rule('partner_tag', self.leaf_a)
        override = self.rule('partner_tag', self.leaf_b, company_id=self.company.id)
        self.assertNotEqual(shared.natural_key, override.natural_key)
        outcome = self.readiness_run()._baseer_evaluate_context(partner=self.supplier)
        self.assertEqual(outcome['outcome'], 'resolved')
        self.assertEqual(outcome['selected_analytic_account_id'], self.leaf_b.id)

    def test_run_uses_only_its_catalog_version(self):
        self.rule('partner_tag', self.leaf_a, catalog_version='noorix-v2')
        run = self.readiness_run()
        outcome = run._baseer_evaluate_context(partner=self.supplier)
        self.assertEqual(outcome['outcome'], 'unmapped')
        self.assertFalse(outcome['candidate_rule_ids'][0][2])

    def test_catalog_versions_preserve_old_rule_and_allow_same_selector(self):
        old = self.rule('partner_tag', self.leaf_a, catalog_version='noorix-v1')
        old.action_retire()
        new = self.rule('partner_tag', self.leaf_b, catalog_version='noorix-v2')
        self.assertNotEqual(old.natural_key, new.natural_key)
        self.assertEqual(self.readiness_run()._baseer_evaluate_context(partner=self.supplier)['outcome'], 'unmapped')
        v2 = self.readiness_run()
        v2.catalog_version = 'noorix-v2'
        self.assertEqual(v2._baseer_evaluate_context(partner=self.supplier)['selected_analytic_account_id'], self.leaf_b.id)

    def test_multiple_tags_with_different_leaves_are_ambiguous(self):
        self.supplier.category_id = self.tag_a | self.tag_b
        self.rule('partner_tag', self.leaf_a)
        self.rule('partner_tag', self.leaf_b, partner_tag_id=self.tag_b.id)
        outcome = self.readiness_run()._baseer_evaluate_context(partner=self.supplier)
        self.assertEqual(outcome['outcome'], 'ambiguous')

    def test_multiple_tags_with_same_leaf_resolve(self):
        self.supplier.category_id = self.tag_a | self.tag_b
        self.rule('partner_tag', self.leaf_a)
        self.rule('partner_tag', self.leaf_a, partner_tag_id=self.tag_b.id)
        outcome = self.readiness_run()._baseer_evaluate_context(partner=self.supplier)
        self.assertEqual(outcome['outcome'], 'resolved')
        self.assertEqual(outcome['selected_analytic_account_id'], self.leaf_a.id)

    def test_product_has_priority_over_vendor_tag(self):
        self.rule('partner_tag', self.leaf_a)
        self.rule('product', self.leaf_b)
        outcome = self.readiness_run()._baseer_evaluate_context(partner=self.supplier, product=self.product)
        self.assertEqual(outcome['outcome'], 'resolved')
        self.assertEqual(outcome['selected_analytic_account_id'], self.leaf_b.id)

    def test_preview_captures_actual_supplier_product_relationship(self):
        self.env['product.supplierinfo'].create({
            'partner_id': self.supplier.id,
            'product_tmpl_id': self.product.product_tmpl_id.id,
        })
        self.rule('partner_tag', self.leaf_a)
        self.rule('product', self.leaf_b)
        values = self.readiness_run()._baseer_preview_values()
        pair = next(value for value in values if value.get('context_kind') == 'supplier_product'
                    and value.get('partner_id') == self.supplier.id
                    and value.get('product_id') == self.product.id)
        self.assertEqual(pair['selected_analytic_account_id'], self.leaf_b.id)
        self.assertEqual(pair['outcome'], 'resolved')
        self.assertEqual(pair['evidence_json']['relationship_sources'][0]['kind'], 'supplierinfo')
        self.assertTrue(pair['evidence_hash'])

    def test_untagged_vendor_uses_explicit_vendor_rule_only(self):
        untagged = self.env['res.partner'].create({'name': 'MAP untagged', 'supplier_rank': 1})
        self.rule('partner', self.leaf_a, partner_id=untagged.id)
        outcome = self.readiness_run()._baseer_evaluate_context(partner=untagged)
        self.assertEqual(outcome['outcome'], 'resolved')
        self.assertEqual(outcome['selected_analytic_account_id'], self.leaf_a.id)

    def test_untagged_vendor_uses_explicit_product_rule_only(self):
        untagged = self.env['res.partner'].create({'name': 'MAP untagged product', 'supplier_rank': 1})
        self.rule('product', self.leaf_a)
        outcome = self.readiness_run()._baseer_evaluate_context(partner=untagged, product=self.product)
        self.assertEqual(outcome['outcome'], 'resolved')
        self.assertEqual(outcome['selected_analytic_account_id'], self.leaf_a.id)

    def test_untagged_vendor_without_explicit_rule_is_unmapped(self):
        untagged = self.env['res.partner'].create({'name': 'MAP untagged absent', 'supplier_rank': 1})
        outcome = self.readiness_run()._baseer_evaluate_context(partner=untagged)
        self.assertEqual(outcome['outcome'], 'unmapped')

    def test_run_becomes_stale_after_supplier_tag_changes(self):
        run = self.readiness_run()
        run.action_generate_preview()
        self.supplier.category_id = self.tag_a | self.tag_b
        run.action_check_stale()
        self.assertEqual(run.state, 'stale')
        self.assertTrue(run.freshness_check_ids.is_stale)

    def test_run_becomes_stale_after_supplier_product_relationship_changes(self):
        run = self.readiness_run()
        run.action_generate_preview()
        self.env['product.supplierinfo'].create({
            'partner_id': self.supplier.id,
            'product_tmpl_id': self.product.product_tmpl_id.id,
        })
        run.action_check_stale()
        self.assertEqual(run.state, 'stale')
        self.assertTrue(run.freshness_check_ids.is_stale)

    def test_stale_check_never_changes_approved_run(self):
        run = self.readiness_run()
        run.action_generate_preview()
        super(BaseerSpendMapRun, run).write({
            'state': 'approved', 'approved_by_id': self.env.user.id,
        })
        before = (run.state, run.is_stale, run.stale_at, run.write_date)
        self.supplier.category_id = self.tag_a | self.tag_b
        run.action_check_stale()
        run.invalidate_recordset()
        self.assertEqual((run.state, run.is_stale, run.stale_at, run.write_date), before)
        self.assertTrue(run.freshness_check_ids[:1].is_stale)

    def test_context_flag_cannot_modify_evidence_or_approved_run(self):
        run = self.readiness_run()
        with self.assertRaises(AccessError):
            run.with_context(_baseer_spend_map_system_write=True).write({'state': 'ready'})
        with self.assertRaises(AccessError):
            self.env['baseer.spend.map.preview.line'].with_context(
                _baseer_spend_map_system_write=True
            ).create({'run_id': run.id, 'context_kind': 'coverage_gap', 'outcome': 'coverage_gap'})

    def test_context_flag_cannot_modify_approved_rule(self):
        rule = self.rule('partner_tag', self.leaf_a)
        with self.assertRaises(AccessError):
            rule.with_context(_baseer_spend_map_system_write=True).write({'note': 'forged'})

    def test_approved_rule_cannot_be_changed_or_removed(self):
        rule = self.rule('partner_tag', self.leaf_a)
        with self.assertRaises(AccessError):
            rule.write({'note': 'changed'})
        with self.assertRaises(AccessError):
            rule.unlink()

    def test_cashier_cannot_create_or_approve_map_evidence(self):
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MAP cashier', 'login': 'map_cashier', 'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.env['baseer.spend.map.run'].with_user(cashier).create({
                'name': 'not allowed', 'company_id': self.company.id,
            })

    def test_manager_cannot_read_another_company_readiness_run(self):
        other_company = self.env['res.company'].create({'name': 'MAP other company'})
        foreign_run = self.env['baseer.spend.map.run'].create({
            'name': 'foreign', 'company_id': other_company.id,
        })
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MAP one-company manager', 'login': 'map_manager',
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_manager').id,
            ])],
        })
        visible = self.env['baseer.spend.map.run'].with_user(manager).with_context(
            allowed_company_ids=self.company.ids,
        ).search([])
        self.assertNotIn(foreign_run, visible)

    def test_one_company_manager_cannot_create_shared_rule(self):
        other_company = self.env['res.company'].create({'name': 'MAP scope other company'})
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MAP scoped manager', 'login': 'map_scoped_manager',
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_manager').id,
            ])],
        })
        with self.assertRaises(AccessError):
            self.env['baseer.spend.map.rule'].with_user(manager).create({
                'selector_kind': 'partner_tag', 'partner_tag_id': self.tag_a.id,
                'analytic_account_id': self.leaf_a.id,
            })

    def test_shared_rule_cannot_reference_company_specific_selector(self):
        other_company = self.env['res.company'].create({'name': 'MAP selector other company'})
        scoped_supplier = self.env['res.partner'].create({
            'name': 'MAP scoped supplier', 'supplier_rank': 1, 'company_id': other_company.id,
        })
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.rule('partner', self.leaf_a, partner_id=scoped_supplier.id)

    def test_other_company_supplierinfo_is_not_previewed_or_hashed(self):
        other_company = self.env['res.company'].create({'name': 'MAP supplierinfo other company'})
        info = self.env['product.supplierinfo'].create({
            'partner_id': self.supplier.id,
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'company_id': other_company.id,
        })
        run = self.readiness_run()
        before = run._baseer_snapshot_hash()
        values = run._baseer_preview_values()
        self.assertFalse(any(value.get('context_kind') == 'supplier_product'
                             and value.get('partner_id') == self.supplier.id
                             and value.get('product_id') == self.product.id for value in values))
        info.price = 99
        self.assertEqual(before, run._baseer_snapshot_hash())

    def test_preview_does_not_write_native_distribution_models(self):
        native = self.env['account.analytic.distribution.model'].create({
            'company_id': False,
            'partner_id': self.supplier.id,
            'analytic_distribution': {str(self.leaf_a.id): 100},
        })
        values = self.readiness_run()._baseer_preview_values()
        native.invalidate_recordset(['write_date', 'analytic_distribution'])
        self.assertTrue(values)
        self.assertEqual(native.analytic_distribution, {str(self.leaf_a.id): 100})

    def test_draft_rule_blocks_readiness_until_approved(self):
        self.rule('partner_tag', self.leaf_a, approve=False)
        outcome = self.readiness_run()._baseer_evaluate_context(partner=self.supplier)
        self.assertEqual(outcome['outcome'], 'reconcile')
