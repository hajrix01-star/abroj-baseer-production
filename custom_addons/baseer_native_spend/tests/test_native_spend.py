import logging
import time

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.baseer_native_spend.hooks import post_init_hook

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class NativeSpendCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.currency_id = cls.env.ref('base.SAR')
        cls.plan = cls.env.ref('baseer_native_spend.spend_plan')
        cls.expense = cls.env['account.account'].create({
            'name': 'NAF expense', 'code': 'NAF600', 'account_type': 'expense',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.payable = cls.env['account.account'].create({
            'name': 'NAF payable', 'code': 'NAF210', 'account_type': 'liability_payable',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.journal = cls.env['account.journal'].create({
            'name': 'NAF purchases', 'code': 'NAFP', 'type': 'purchase', 'company_id': cls.company.id,
            'sequence': -100, 'default_account_id': cls.expense.id,
        })
        cls.subplan = cls.env['account.analytic.plan'].create({'name': 'NAF Food', 'parent_id': cls.plan.id})
        cls.a = cls.env['account.analytic.account'].create({'name': 'NAF Chicken', 'plan_id': cls.subplan.id, 'company_id': False})
        cls.b = cls.env['account.analytic.account'].create({'name': 'NAF Vegetables', 'plan_id': cls.subplan.id, 'company_id': False})
        cls.tag_parent = cls.env['res.partner.category'].create({'name': 'NAF Food'})
        cls.tag_a = cls.env['res.partner.category'].create({'name': 'NAF chicken tag', 'parent_id': cls.tag_parent.id})
        cls.tag_b = cls.env['res.partner.category'].create({'name': 'NAF vegetables tag', 'parent_id': cls.tag_parent.id})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'NAF supplier', 'supplier_rank': 1, 'category_id': [Command.set(cls.tag_a.ids)],
            'property_account_payable_id': cls.payable.id,
        })
        cls.category = cls.env['product.category'].create({'name': 'NAF product category'})
        cls.product = cls.env['product.product'].create({
            'name': 'NAF service', 'type': 'service', 'categ_id': cls.category.id,
            'property_account_expense_id': cls.expense.id,
            'supplier_taxes_id': [Command.clear()],
        })
        cls.mapping = cls.env['baseer.purchase.category.map'].create({
            'company_id': cls.company.id, 'category_id': cls.category.id, 'product_id': cls.product.id,
        }) if 'baseer.purchase.category.map' in cls.env else None
        cls.model = cls.env['account.analytic.distribution.model'].create({
            'company_id': False, 'partner_category_id': cls.tag_a.id, 'sequence': 100,
            'analytic_distribution': {str(cls.a.id): 100},
        })
        cls.model_b = cls.env['account.analytic.distribution.model'].create({
            'company_id': False, 'partner_category_id': cls.tag_b.id, 'sequence': 100,
            'analytic_distribution': {str(cls.b.id): 100},
        })
        Rule = cls.env['baseer.spend.map.rule']
        for tag, account in ((cls.tag_a, cls.a), (cls.tag_b, cls.b)):
            Rule.create({
                'name': 'NAF approved %s' % tag.name,
                'selector_kind': 'partner_tag', 'partner_tag_id': tag.id,
                'analytic_account_id': account.id, 'catalog_version': 'NAF-v1',
            }).action_approve()
        # The normal suite exercises the protected, post-mapping state.  A
        # company is deliberately *not* made mandatory at installation: the
        # mapping wave must finish first.  See the dedicated test below.
        cls.applicability = cls.env['account.analytic.applicability'].create({
            'analytic_plan_id': cls.plan.id,
            'company_id': cls.company.id,
            'business_domain': 'bill',
            'applicability': 'mandatory',
        })

    def bill(self, product=False, move_type='in_invoice', lines=1, distribution=None):
        value = {'name': 'NAF source', 'account_id': self.expense.id, 'quantity': 1, 'price_unit': 100, 'tax_ids': [Command.clear()]}
        if product:
            value['product_id'] = product.id
        if distribution is not None:
            value['analytic_distribution'] = distribution
        return self.env['account.move'].create({
            'company_id': self.company.id, 'move_type': move_type, 'partner_id': self.supplier.id,
            'journal_id': self.journal.id, 'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create(dict(value)) for _ in range(lines)],
        })

    def rule(self, account, **values):
        return self.env['account.analytic.distribution.model'].create({
            'company_id': False, 'sequence': 10, 'analytic_distribution': {str(account.id): 100}, **values,
        })

    def assert_blocked(self, bill, direct=False):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            if direct:
                bill.with_context(validate_analytic=False)._post(soft=False)
            else:
                bill.with_context(validate_analytic=False).action_post()
        self.assertEqual(bill.state, 'draft')

    def test_no_product_bill_and_refund_native_balances(self):
        for kind, sign in [('in_invoice', -1), ('in_refund', 1)]:
            bill = self.bill(move_type=kind)
            self.assertEqual(bill.invoice_line_ids.analytic_distribution, {str(self.a.id): 100.0})
            bill.action_post()
            self.assertEqual(bill.state, 'posted')
            self.assertAlmostEqual(sum(bill.line_ids.mapped('balance')), 0)
            self.assertAlmostEqual(sum(bill.invoice_line_ids.analytic_line_ids.mapped('amount')), sign * 100)
            self.assertEqual(bill.amount_total, 100)

    def test_plain_and_background_missing_distribution_blocked(self):
        self.model.unlink()
        self.assert_blocked(self.bill())
        self.assert_blocked(self.bill(), direct=True)

    def test_partial_distribution_blocked_and_explicit_split_allowed(self):
        self.assert_blocked(self.bill(distribution={str(self.a.id): 70}))
        bill = self.bill(distribution={str(self.a.id): 60, str(self.b.id): 40})
        bill.action_post()
        self.assertEqual(len(bill.invoice_line_ids.analytic_line_ids), 2)

    def test_invalid_joint_keys_and_percentages_cannot_fake_complete_spend(self):
        distributions = [
            {f'{self.a.id},{self.a.id}': 50},
            {f'{self.a.id},{self.b.id}': 50},
            {str(self.a.id): 150, str(self.b.id): -50},
            {str(self.a.id): True},
        ]
        for distribution in distributions:
            with self.subTest(distribution=distribution):
                # Isolate create as native inverses may also reject malformed data.
                with self.assertRaises(ValidationError), self.env.cr.savepoint():
                    self.bill(distribution=distribution).action_post()

    def test_tag_ambiguity_does_not_guess(self):
        self.supplier.category_id = self.tag_a | self.tag_b
        self.rule(self.b, partner_category_id=self.tag_b.id)
        self.assertFalse(self.bill().invoice_line_ids.analytic_distribution)
        self.assert_blocked(self.bill())

    def test_two_tags_same_destination_not_ambiguous(self):
        self.supplier.category_id = self.tag_a | self.tag_b
        self.rule(self.a, partner_category_id=self.tag_b.id)
        bill = self.bill()
        self.assertEqual(bill.invoice_line_ids.analytic_distribution, {str(self.a.id): 100.0})
        bill.action_post()

    def test_product_category_resolves_ambiguous_supplier(self):
        self.supplier.category_id = self.tag_a | self.tag_b
        self.rule(self.b, partner_category_id=self.tag_b.id)
        self.rule(self.b, product_categ_id=self.category.id, sequence=200)
        bill = self.bill(product=self.product)
        self.assertEqual(bill.invoice_line_ids.analytic_distribution, {str(self.b.id): 100.0})
        bill.action_post()

    def test_company_override_and_other_analytic_dimension(self):
        other_plan = self.env.ref('analytic.analytic_plan_projects', raise_if_not_found=False)
        if not other_plan:
            other_plan = self.env['account.analytic.plan'].search([('id', '!=', self.plan.id), ('parent_id', '=', False)], limit=1)
        other = self.env['account.analytic.account'].create({'name': 'NAF separate dimension', 'plan_id': other_plan.id, 'company_id': False})
        self.rule(other, partner_id=self.supplier.id)
        self.rule(self.b, partner_category_id=self.tag_a.id, company_id=self.company.id, sequence=200)
        bill = self.bill()
        accounts = bill.invoice_line_ids.distribution_analytic_account_ids
        self.assertIn(self.b, accounts)
        self.assertIn(other, accounts)
        self.assertNotIn(self.a, accounts)
        bill.action_post()

    def test_mixed_invoice_classifies_each_line(self):
        self.rule(self.b, product_categ_id=self.category.id)
        bill = self.bill()
        bill.invoice_line_ids = [Command.create({'name': 'Product row', 'product_id': self.product.id, 'account_id': self.expense.id, 'price_unit': 200, 'quantity': 1, 'tax_ids': [Command.clear()]})]
        bill.action_post()
        self.assertEqual(len(bill.invoice_line_ids), 2)
        self.assertEqual(bill.amount_total, 300)
        self.assertEqual(set(bill.invoice_line_ids.distribution_analytic_account_ids.ids), {self.a.id, self.b.id})

    def batch(self, count=1, **row_values):
        if 'baseer.purchase.batch' not in self.env:
            self.skipTest('Baseer purchase batch integration is not installed.')
        return self.env['baseer.purchase.batch'].create({'line_ids': [Command.create({
            'partner_id': self.supplier.id, 'supplier_ref': f'NAF-{self._testMethodName}-{n}',
            'gross_amount': 100, 'is_credit': True,
            'invoice_date': fields.Date.today(),
            **row_values,
        }) for n in range(count)]})

    def test_batch_native_classification_and_idempotent_approval(self):
        self.rule(self.b, product_categ_id=self.category.id)
        batch = self.batch()
        self.assertFalse(batch.line_ids.category_map_id)
        batch.action_approve()
        self.assertEqual(batch.state, 'approved')
        self.assertFalse(batch.move_ids.invoice_line_ids.product_id)
        self.assertEqual(batch.move_ids.invoice_line_ids.account_id, self.expense)
        self.assertEqual(batch.move_ids.invoice_line_ids.analytic_distribution, {str(self.a.id): 100.0})
        self.assertEqual(batch.move_ids.amount_residual, 100)
        self.assertFalse(batch.line_ids.payment_id)
        ids = batch.move_ids.ids
        batch.action_approve()
        self.assertEqual(batch.move_ids.ids, ids)

    def test_batch_category_rpc_create_and_write_rejected(self):
        batch = self.batch()
        for value in (self.mapping.id, False):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    self.batch(category_map_id=value)
                with self.assertRaises(ValidationError):
                    batch.line_ids.write({'category_map_id': value})
        self.assertFalse(batch.line_ids.category_map_id)

    def test_batch_legacy_draft_keeps_category_but_posts_without_product(self):
        # Simulate the stored link that existed before this module upgrade.
        # Public write is intentionally forbidden; no migration rewrites it.
        from odoo.addons.baseer_purchase_batch.models.purchase_batch import BaseerPurchaseBatchLine

        batch = self.batch()
        super(BaseerPurchaseBatchLine, batch.line_ids).write({'category_map_id': self.mapping.id})
        self.mapping.active = False
        self.rule(self.b, product_categ_id=self.category.id)
        batch.line_ids.write({'gross_amount': 115})
        batch.action_approve()
        self.assertEqual(batch.line_ids.category_map_id, self.mapping)
        self.assertFalse(batch.move_ids.invoice_line_ids.product_id)
        self.assertEqual(batch.move_ids.invoice_line_ids.analytic_distribution, {str(self.a.id): 100.0})
        self.assertEqual(batch.move_ids.amount_total, 115)

    def test_batch_caller_defaults_and_legacy_copy_cannot_restore_category_links(self):
        from odoo.addons.baseer_purchase_batch.models.purchase_batch import BaseerPurchaseBatchLine

        batch = self.batch()
        bill = self.bill()
        row = self.env['baseer.purchase.batch.line'].with_context(
            default_category_map_id=self.mapping.id, default_move_id=bill.id,
        ).create({
            'batch_id': batch.id, 'partner_id': self.supplier.id,
            'supplier_ref': 'NAF-default-injection', 'gross_amount': 100, 'is_credit': True,
        })
        self.assertFalse(row.category_map_id)
        self.assertFalse(row.move_id)
        # Reproduce a pre-upgrade draft link, then exercise ordinary copy.
        super(BaseerPurchaseBatchLine, row).write({'category_map_id': self.mapping.id})
        copied = row.copy({'supplier_ref': 'NAF-copy-without-legacy-category'})
        self.assertFalse(copied.category_map_id)
        self.assertFalse(copied.move_id)
        self.assertEqual(row.category_map_id, self.mapping)

    def test_batch_native_supplier_history_overrides_journal_fallback(self):
        historical_account = self.expense.copy({'name': 'NAF historical expense', 'code': 'NAF601'})
        # Persisted history is necessary: native Odoo resolves this via SQL.
        historical_bill = self.bill()
        historical_bill.invoice_line_ids.account_id = historical_account
        historical_bill.action_post()
        self.env.flush_all()
        batch = self.batch()
        batch.action_approve()
        self.assertEqual(batch.move_ids.invoice_line_ids.account_id, historical_account)
        self.assertEqual(self.journal.default_account_id, self.expense)

    def test_batch_new_supplier_uses_native_journal_default(self):
        batch = self.batch()
        batch.action_approve()
        self.assertEqual(batch.move_ids.journal_id, self.journal)
        self.assertEqual(batch.move_ids.invoice_line_ids.account_id, self.expense)

    def test_batch_does_not_require_a_category_mapping_or_service_product(self):
        if self.mapping is None:
            self.skipTest('Baseer purchase batch integration is not installed.')
        self.mapping.unlink()
        self.product.active = False
        batch = self.batch()
        batch.action_approve()
        self.assertEqual(batch.move_ids.state, 'posted')
        self.assertFalse(batch.move_ids.invoice_line_ids.product_id)
        self.assertEqual(batch.move_ids.invoice_line_ids.account_id, self.expense)

    def test_batch_foreign_supplier_rejected_without_changing_draft(self):
        other_company = self.env['res.company'].create({'name': 'NAF foreign batch supplier company'})
        supplier = self.env['res.partner'].create({
            'name': 'NAF private foreign supplier', 'company_id': other_company.id,
        })
        batch = self.batch()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            batch.line_ids.partner_id = supplier
        self.assertEqual(batch.line_ids.partner_id, self.supplier)
        self.assertEqual(batch.state, 'draft')

    def test_batch_invalid_native_account_rolls_back(self):
        asset = self.env['account.account'].create({
            'name': 'NAF asset is not batch expense', 'code': 'NAF120',
            'account_type': 'asset_current', 'company_ids': [Command.set(self.company.ids)],
        })
        self.journal.default_account_id = asset
        batch = self.batch()
        with self.assertRaises(ValidationError):
            batch.action_approve()
        self.assertEqual(batch.state, 'draft')
        self.assertFalse(batch.line_ids.move_id)
        self.assertFalse(self.env['account.move'].search([('ref', '=', batch.line_ids.supplier_ref)]))

    def test_batch_missing_native_account_fails_before_persistence(self):
        self.journal.default_account_id = False
        batch = self.batch()
        # This supplier has no history and this invoice has no prior items;
        # removing only the selected journal default leaves no native account.
        with self.assertRaises(ValidationError):
            batch.action_approve()
        self.assertEqual(batch.state, 'draft')
        self.assertFalse(batch.line_ids.move_id)
        self.assertFalse(self.env['account.move'].search([('ref', '=', batch.line_ids.supplier_ref)]))

    def test_batch_supplier_change_uses_new_native_tag_distribution(self):
        supplier = self.env['res.partner'].create({
            'name': 'NAF replacement supplier', 'supplier_rank': 1,
            'category_id': [Command.set(self.tag_b.ids)],
            'property_account_payable_id': self.payable.id,
        })
        batch = self.batch()
        batch.line_ids.partner_id = supplier
        batch.action_approve()
        self.assertEqual(batch.move_ids.partner_id, supplier)
        self.assertEqual(batch.move_ids.invoice_line_ids.analytic_distribution, {str(self.b.id): 100.0})

    def test_batch_ambiguous_supplier_tags_block_approval(self):
        self.supplier.category_id = self.tag_a | self.tag_b
        batch = self.batch()
        with self.assertRaises(ValidationError):
            batch.action_approve()
        self.assertEqual(batch.state, 'draft')
        self.assertFalse(batch.move_ids)

    def test_batch_optional_spend_keeps_native_unclassified_workflow(self):
        self.env['account.analytic.applicability'].search([
            ('analytic_plan_id', '=', self.plan.id), ('company_id', '=', self.company.id),
            ('business_domain', '=', 'bill'),
        ]).write({'applicability': 'optional'})
        self.model.unlink()
        batch = self.batch()
        batch.action_approve()
        self.assertEqual(batch.move_ids.state, 'posted')
        self.assertFalse(batch.move_ids.invoice_line_ids.analytic_distribution)

    def test_batch_productless_vat_and_native_paid_reconciliation(self):
        tax = self.env['account.tax'].create({
            'name': 'NAF purchase VAT 15%', 'company_id': self.company.id,
            'type_tax_use': 'purchase', 'amount_type': 'percent', 'amount': 15,
        })
        self.company.account_purchase_tax_id = tax
        liquidity = self.env['account.account'].create({
            'name': 'NAF cash', 'code': 'NAF101', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        cash = self.env['account.journal'].create({
            'name': 'NAF cash payments', 'code': 'NAFC', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': liquidity.id,
        })
        method = cash.outbound_payment_method_line_ids.filtered(lambda item: item.code == 'manual')[:1]
        self.assertTrue(method, 'Native cash journal must expose manual outbound payments.')
        method.payment_account_id = liquidity
        batch = self.batch(gross_amount=115, vat_enabled=True, is_credit=False,
                           payment_method_line_id=method.id)
        self.assertEqual(batch.line_ids.net_amount, 100)
        self.assertEqual(batch.line_ids.tax_amount, 15)
        batch.action_approve()
        bill = batch.move_ids
        payment = batch.line_ids.payment_id
        self.assertFalse(bill.invoice_line_ids.product_id)
        self.assertEqual((bill.amount_untaxed, bill.amount_tax, bill.amount_total), (100, 15, 115))
        self.assertEqual(bill.payment_state, 'paid')
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.move_id.state, 'posted')
        cash_lines = payment.move_id.line_ids.filtered(lambda item: item.account_id == liquidity)
        self.assertEqual(sum(cash_lines.mapped('balance')), -115)
        bill_ids, payment_ids = bill.ids, payment.ids
        batch.action_approve()
        self.assertEqual(batch.move_ids.ids, bill_ids)
        self.assertEqual(batch.line_ids.payment_id.ids, payment_ids)

    def correction_owner(self):
        if 'baseer.financial.correction' not in self.env:
            self.skipTest('Financial correction integration is not installed.')
        owner = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'NAF correction owner', 'login': 'naf_correction_' + self._testMethodName,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'baseer_access_role': 'owner',
        })
        owner.group_ids |= self.env.ref('account.group_account_manager')
        return owner

    def test_productless_batch_correction_preserves_account_and_reclassifies_supplier(self):
        owner = self.correction_owner()
        tax = self.env['account.tax'].create({
            'name': 'NAF correction VAT 15%', 'company_id': self.company.id,
            'type_tax_use': 'purchase', 'amount_type': 'percent', 'amount': 15,
        })
        self.company.account_purchase_tax_id = tax
        batch = self.batch(2, gross_amount=115, vat_enabled=True)
        batch.action_approve()
        row, sibling = batch.line_ids.sorted('id')
        bill = row.move_id
        original_line_ids = bill.invoice_line_ids.ids
        original_dates = (bill.invoice_date, bill.date)
        supplier = self.env['res.partner'].create({
            'name': 'NAF corrected supplier', 'supplier_rank': 1,
            'category_id': [Command.set(self.tag_b.ids)],
            'property_account_payable_id': self.payable.id,
        })
        different_account = self.expense.copy({'name': 'NAF different supplier expense', 'code': 'NAF602'})
        history = self.bill()
        history.write({'partner_id': supplier.id, 'invoice_line_ids': [
            Command.update(history.invoice_line_ids.id, {'account_id': different_account.id}),
        ]})
        history.action_post()
        self.env.flush_all()
        # Changing this supplier normally chooses its different historical
        # expense account; a reviewed correction must preserve the source one.
        action = row.with_user(owner).action_baseer_correct_operation()
        wizard = self.env['baseer.financial.correction'].with_user(owner).browse(action['res_id'])
        wizard.write({'partner_id': supplier.id, 'gross_amount_input': '230.00',
                      'reason': 'Correct supplier and original invoice amount'})
        wizard.action_confirm()
        self.assertTrue(wizard.completed)
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.invoice_line_ids.ids, original_line_ids)
        self.assertEqual((bill.invoice_date, bill.date), original_dates)
        self.assertEqual(bill.invoice_line_ids.account_id, self.expense)
        self.assertNotEqual(bill.invoice_line_ids.account_id, different_account)
        self.assertFalse(bill.invoice_line_ids.product_id)
        self.assertFalse(row.category_map_id)
        self.assertEqual(bill.invoice_line_ids.analytic_distribution, {str(self.b.id): 100.0})
        self.assertEqual((bill.amount_untaxed, bill.amount_tax, bill.amount_total), (200, 30, 230))
        self.assertEqual((row.net_amount, row.tax_amount, row.gross_amount), (200, 30, 230))
        self.assertEqual(row.partner_id, supplier)
        self.assertEqual(sibling.partner_id, self.supplier)
        self.assertEqual(sibling.move_id.amount_total, 115)
        self.assertEqual(batch.amount_gross, 345)
        self.assertEqual(batch.state, 'approved')
        audit = wizard.audit_id
        self.assertEqual(audit.operation, 'edit')
        self.assertEqual(audit.batch_line_id, row)
        wizard.action_confirm()
        self.assertEqual(wizard.audit_id, audit)

    def test_productless_batch_cancellation_retains_history_and_excludes_totals(self):
        owner = self.correction_owner()
        batch = self.batch()
        batch.action_approve()
        row, bill = batch.line_ids, batch.move_ids
        document_ids, journal_item_ids = bill.ids, bill.line_ids.ids
        action = row.with_user(owner).action_baseer_cancel_operation()
        wizard = self.env['baseer.financial.correction'].with_user(owner).browse(action['res_id'])
        wizard.reason = 'Duplicate invoice entered in error'
        wizard.action_confirm()
        self.assertTrue(wizard.completed)
        self.assertEqual(wizard.audit_id.operation, 'cancel')
        self.assertEqual(bill.exists().ids, document_ids)
        self.assertEqual(bill.line_ids.ids, journal_item_ids)
        self.assertEqual(bill.state, 'cancel')
        self.assertFalse(bill.invoice_line_ids.product_id)
        self.assertTrue(row.baseer_cancelled)
        self.assertEqual(row.gross_amount, 100)
        self.assertEqual(row.move_id, bill)
        self.assertEqual(batch.amount_gross, 0)
        self.assertEqual(batch.state, 'approved')
        wizard.action_confirm()
        with self.assertRaises(UserError):
            row.with_user(owner).action_baseer_cancel_operation()

    def test_historical_product_batch_correction_retains_product_and_category(self):
        from odoo.addons.baseer_purchase_batch.models.purchase_batch import (
            BaseerPurchaseBatch, BaseerPurchaseBatchLine,
        )

        owner = self.correction_owner()
        self.rule(self.b, product_categ_id=self.category.id)
        batch = self.batch()
        row = batch.line_ids
        bill = self.bill(product=self.product)
        bill.ref = row.supplier_ref
        bill.action_post()
        # Privileged fixture setup reconstructs the original pre-upgrade
        # approval: a real posted product bill and its immutable batch links.
        # The public correction below must then use the current guarded API.
        super(BaseerPurchaseBatchLine, row).write({
            'category_map_id': self.mapping.id, 'move_id': bill.id,
            'net_amount': bill.amount_untaxed, 'tax_amount': bill.amount_tax,
        })
        super(BaseerPurchaseBatch, batch).write({
            'state': 'approved', 'approved_by_id': self.env.uid,
            'approved_at': fields.Datetime.now(),
        })
        action = row.with_user(owner).action_baseer_correct_operation()
        wizard = self.env['baseer.financial.correction'].with_user(owner).browse(action['res_id'])
        wizard.write({'gross_amount_input': '125.00', 'reason': 'Correct historical supplier bill total'})
        wizard.action_confirm()
        self.assertTrue(wizard.completed)
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.invoice_line_ids.product_id, self.product)
        self.assertEqual(bill.invoice_line_ids.account_id, self.expense)
        self.assertEqual(bill.invoice_line_ids.analytic_distribution, {str(self.b.id): 100.0})
        self.assertEqual(row.category_map_id, self.mapping)
        self.assertEqual(row.move_id, bill)
        self.assertEqual((row.gross_amount, bill.amount_total, batch.amount_gross), (125, 125, 125))
        self.assertEqual(wizard.audit_id.operation, 'edit')

    def test_transition_retires_parallel_snapshot_writes_without_deleting_history(self):
        if 'baseer.purchase.line.classification' not in self.env:
            self.skipTest('Legacy classifier is not installed.')
        if not hasattr(self.env['baseer.purchase.batch'], '_baseer_native_spend_is_authoritative'):
            self.skipTest('Native batch transition is not installed.')
        Snapshot = self.env['baseer.purchase.line.classification']
        Case = self.env['baseer.purchase.line.classification.case']
        counts = (Snapshot.search_count([]), Case.search_count([]))
        bill = self.bill()
        bill.action_post()
        batch = self.batch()
        batch.action_approve()
        self.assertTrue(bill.invoice_line_ids.analytic_line_ids)
        self.assertTrue(batch.move_ids.invoice_line_ids.analytic_line_ids)
        self.assertEqual(counts, (Snapshot.search_count([]), Case.search_count([])))
        run = self.env['baseer.purchase.historical.classification.run'].create({
            'company_id': self.company.id, 'date_from': fields.Date.today(), 'date_to': fields.Date.today(),
        })
        with self.assertRaises(ValidationError):
            run.action_apply()
        with self.assertRaises(ValidationError):
            Snapshot._baseer_capture_historical_lines(bill.invoice_line_ids, run)

    def test_batch_missing_distribution_rolls_back_entire_approval(self):
        batch = self.batch(2)
        blank_supplier = self.env['res.partner'].create({
            'name': 'NAF unclassified second supplier', 'supplier_rank': 1,
            'property_account_payable_id': self.payable.id,
        })
        batch.line_ids.sorted('id')[1].partner_id = blank_supplier
        # The first row can post; failure on the second must remove both bills.
        refs = batch.line_ids.mapped('supplier_ref')
        with self.assertRaises(ValidationError):
            batch.action_approve()
        self.assertEqual(batch.state, 'draft')
        self.assertFalse(batch.line_ids.move_id)
        self.assertFalse(batch.line_ids.payment_id)
        self.assertFalse(self.env['account.move'].search([('ref', 'in', refs)]))

    def test_new_company_provisioning_idempotency_preserves_manual_config(self):
        company = self.env['res.company'].create({'name': 'NAF new company', 'currency_id': self.env.ref('base.SAR').id})
        domain = [('analytic_plan_id', '=', self.plan.id), ('company_id', '=', company.id), ('business_domain', '=', 'bill')]
        records = self.env['account.analytic.applicability'].search(domain)
        # The shared vendor-tag template from setUpClass is already complete,
        # so later companies inherit the guard at creation.  There is no
        # per-company copying of distribution models to drift over time.
        self.assertEqual(len(records), 1)
        self.assertEqual(records.applicability, 'mandatory')
        company._baseer_ensure_spend_applicability()
        records = self.env['account.analytic.applicability'].search(domain)
        self.assertEqual(len(records), 1)
        self.assertEqual(records.applicability, 'mandatory')
        records.applicability = 'optional'
        company._baseer_ensure_spend_applicability()
        self.assertEqual(records.applicability, 'optional')

    def test_partial_or_invalid_shared_template_does_not_guard_new_company(self):
        self.model_b.analytic_distribution = {str(self.b.id): 50}
        company = self.env['res.company'].create({'name': 'NAF partial template company', 'currency_id': self.env.ref('base.SAR').id})
        records = self.env['account.analytic.applicability'].search([
            ('analytic_plan_id', '=', self.plan.id), ('company_id', '=', company.id),
            ('business_domain', '=', 'bill'),
        ])
        self.assertFalse(records)
        self.model_b.analytic_distribution = {str(self.b.id): 100}
        self.model_b.product_id = self.product.id
        company = self.env['res.company'].create({'name': 'NAF constrained template company', 'currency_id': self.env.ref('base.SAR').id})
        records = self.env['account.analytic.applicability'].search([
            ('analytic_plan_id', '=', self.plan.id), ('company_id', '=', company.id),
            ('business_domain', '=', 'bill'),
        ])
        self.assertFalse(records)

    def test_optional_or_missing_company_configuration_keeps_native_optional_workflow(self):
        applicability = self.env['account.analytic.applicability'].search([('analytic_plan_id', '=', self.plan.id), ('company_id', '=', self.company.id), ('business_domain', '=', 'bill')])
        applicability.write({'applicability': 'optional'})
        bill = self.bill(distribution={})
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        applicability.unlink()
        bill = self.bill(distribution={})
        bill.action_post()
        self.assertEqual(bill.state, 'posted')

    def test_missing_or_invalid_root_keeps_bridge_optional(self):
        """A stale XML id must never make the safe release block a bill."""
        self.env['account.analytic.applicability'].search([
            ('analytic_plan_id', '=', self.plan.id), ('company_id', '=', self.company.id),
            ('business_domain', '=', 'bill'),
        ]).unlink()
        external = self.env['ir.model.data'].search([
            ('module', '=', 'baseer_native_spend'), ('name', '=', 'spend_plan'),
        ], limit=1)
        external.write({'res_id': self.subplan.id})
        bill = self.bill(distribution={})
        bill.action_post()
        self.assertEqual(bill.state, 'posted')

    def test_post_init_repairs_bad_xmlid_without_mandatory_rule(self):
        """Reconciliation adopts the Arabic root and never enables a company."""
        self.applicability.unlink()
        external = self.env['ir.model.data'].search([
            ('module', '=', 'baseer_native_spend'), ('name', '=', 'spend_plan'),
        ], limit=1)
        external.write({'res_id': self.subplan.id})
        post_init_hook(self.env)
        external.invalidate_recordset(['res_id'])
        repaired = self.env['account.analytic.plan'].browse(external.res_id)
        self.assertFalse(repaired.parent_id)
        self.assertEqual(repaired.name, 'تصنيف الإنفاق')
        self.assertFalse(self.env['account.analytic.applicability'].search([
            ('analytic_plan_id', '=', repaired.id),
            ('company_id', '=', self.company.id),
            ('business_domain', '=', 'bill'),
        ]))

    def test_cashier_cannot_administer_native_templates(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'NAF cashier', 'login': 'naf_cashier', 'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.model.with_user(user).write({'sequence': 999})

    def test_shared_accounts_do_not_leak_other_company_lines(self):
        company_b = self.env['res.company'].create({'name': 'NAF isolation company'})
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'NAF single company', 'login': 'naf_single', 'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('account.group_account_manager').id])],
        })
        self.bill().action_post()
        other_line = self.env['account.analytic.line'].create({
            'name': 'NAF foreign line', 'company_id': company_b.id, 'amount': -999,
            self.plan._column_name(): self.a.id,
        })
        lines = self.env['account.analytic.line'].with_user(user).with_context(allowed_company_ids=self.company.ids).search([])
        self.assertNotIn(other_line, lines)
        with self.assertRaises(AccessError):
            other_line.with_user(user).read(['amount'])

    def test_fifty_row_batch_timing_and_balance(self):
        self.rule(self.b, product_categ_id=self.category.id)
        batch = self.batch(50)
        start = time.monotonic()
        batch.action_approve()
        elapsed = time.monotonic() - start
        self.assertEqual(len(batch.move_ids), 50)
        self.assertTrue(all(move.state == 'posted' for move in batch.move_ids))
        self.assertAlmostEqual(sum(batch.move_ids.line_ids.mapped('balance')), 0)
        _logger.info('NAF_CAPACITY_50_ROWS seconds=%.3f bills=%s', elapsed, len(batch.move_ids))

    def test_switch_supplier_clears_stale_automatic_spend(self):
        ambiguous = self.env['res.partner'].create({'name': 'NAF ambiguous new supplier', 'category_id': [Command.set((self.tag_a | self.tag_b).ids)]})
        blank = self.env['res.partner'].create({'name': 'NAF blank new supplier'})
        self.rule(self.b, partner_category_id=self.tag_b.id)
        for supplier in (ambiguous, blank):
            bill = self.bill()
            self.assertEqual(bill.invoice_line_ids.analytic_distribution, {str(self.a.id): 100.0})
            bill.partner_id = supplier
            self.assertFalse(bill.invoice_line_ids.analytic_distribution)
            self.assert_blocked(bill)
            bill.invoice_line_ids.analytic_distribution = {str(self.b.id): 100}
            bill.action_post()

    def test_inactive_or_foreign_accounts_blocked(self):
        other_company = self.env['res.company'].create({'name': 'NAF foreign distribution'})
        foreign = self.env['account.analytic.account'].create({'name': 'Foreign spend', 'plan_id': self.subplan.id, 'company_id': other_company.id})
        self.assert_blocked(self.bill(distribution={str(foreign.id): 100}))
        self.a.active = False
        self.assert_blocked(self.bill(distribution={str(self.a.id): 100}))

    def test_scheduled_post_cannot_bypass_classification(self):
        self.model.unlink()
        bill = self.bill()
        bill.date = fields.Date.add(fields.Date.today(), days=1)
        with self.assertRaises(ValidationError):
            bill.with_context(validate_analytic=False)._post(soft=True)

    def test_general_journal_entry_not_made_mandatory(self):
        journal = self.env['account.journal'].search([('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        entry = self.env['account.move'].create({'journal_id': journal.id, 'line_ids': [
            Command.create({'name': 'NAF general debit', 'account_id': self.expense.id, 'debit': 20}),
            Command.create({'name': 'NAF general credit', 'account_id': self.expense.id, 'credit': 20}),
        ]})
        entry.with_context(validate_analytic=True)._post(soft=False)
        self.assertEqual(entry.state, 'posted')
