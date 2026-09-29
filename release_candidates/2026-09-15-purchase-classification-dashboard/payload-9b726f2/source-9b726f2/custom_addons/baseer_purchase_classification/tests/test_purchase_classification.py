from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class PurchaseClassificationCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.currency_id = cls.env.ref('base.SAR')
        cls.expense_account = cls.env['account.account'].create({
            'name': 'PCL expense', 'code': 'PCL600', 'account_type': 'expense',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.payable_account = cls.env['account.account'].create({
            'name': 'PCL payable', 'code': 'PCL210', 'account_type': 'liability_payable',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.journal = cls.env['account.journal'].create({
            'name': 'PCL purchases', 'code': 'PCLP', 'type': 'purchase', 'company_id': cls.company.id,
        })
        cls.food_parent = cls.env['product.category'].create({'name': 'PCL food parent'})
        cls.food_leaf = cls.env['product.category'].create({
            'name': 'PCL food leaf', 'parent_id': cls.food_parent.id,
        })
        cls.expense_parent = cls.env['product.category'].create({'name': 'PCL expense parent'})
        cls.expense_leaf = cls.env['product.category'].create({
            'name': 'PCL expense leaf', 'parent_id': cls.expense_parent.id,
        })
        cls.food_service = cls.env['product.product'].create({
            'name': 'PCL food service', 'type': 'service', 'categ_id': cls.food_leaf.id,
            'property_account_expense_id': cls.expense_account.id,
        })
        cls.expense_service = cls.env['product.product'].create({
            'name': 'PCL expense service', 'type': 'service', 'categ_id': cls.expense_leaf.id,
            'property_account_expense_id': cls.expense_account.id,
        })
        cls.food_map = cls.env['baseer.purchase.category.map'].create({
            'company_id': cls.company.id, 'category_id': cls.food_leaf.id, 'product_id': cls.food_service.id,
        })
        cls.expense_map = cls.env['baseer.purchase.category.map'].create({
            'company_id': cls.company.id, 'category_id': cls.expense_leaf.id, 'product_id': cls.expense_service.id,
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'PCL categorized supplier',
            'property_account_payable_id': cls.payable_account.id,
        })
        cls.untagged_supplier = cls.env['res.partner'].create({
            'name': 'PCL untagged supplier', 'property_account_payable_id': cls.payable_account.id,
        })
        cls.manager = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PCL Manager', 'login': 'pcl_manager', 'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_manager').id,
            ])],
        })
        cls.cashier = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PCL Cashier', 'login': 'pcl_cashier', 'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })
        cls.supplier.with_company(cls.company).write({
            'baseer_purchase_category_map_id': cls.food_map.id,
        })

    def _rule(self, *, target_kind='supplier_category', target_id=None, reporting_type='purchase', reporting_map=None):
        reporting_map = reporting_map or self.food_map
        values = {
            'company_id': self.company.id,
            'target_kind': target_kind,
            'reporting_category_map_id': reporting_map.id,
            'reporting_type': reporting_type,
        }
        if target_kind == 'supplier_category':
            values['supplier_category_map_id'] = target_id or self.food_map.id
        else:
            values['product_category_id'] = target_id or self.food_leaf.id
        return self.env['baseer.purchase.reporting.rule'].with_user(self.manager).create(values)

    def _posted_bill(self, supplier, *, product=False, amount=100, move_type='in_invoice'):
        values = {
            'name': 'PCL source line', 'quantity': 1, 'price_unit': amount,
            'account_id': self.expense_account.id,
        }
        if product:
            values['product_id'] = product.id
        move = self.env['account.move'].with_user(self.manager).create({
            'move_type': move_type, 'partner_id': supplier.id, 'journal_id': self.journal.id,
            'invoice_date': '2099-09-15', 'invoice_line_ids': [Command.create(values)],
        })
        before = {
            line.id: (line.move_id.state, line.balance, line.price_total, line.tax_ids.ids, line.product_id.id)
            for line in move.invoice_line_ids
        }
        move.action_post()
        line = move.invoice_line_ids.filtered(lambda item: item.display_type == 'product')
        after = {
            line.id: (line.move_id.state, line.balance, line.price_total, line.tax_ids.ids, line.product_id.id)
        }
        return move, line, before, after

    def test_supplier_rule_captures_immutable_purchase_snapshot_without_source_write(self):
        self._rule()
        _move, line, before, after = self._posted_bill(self.supplier)
        self.assertEqual(before[line.id][1:], after[line.id][1:])
        case = self.env['baseer.purchase.line.classification.case'].search([('source_line_id', '=', line.id)])
        self.assertEqual(len(case), 1)
        snapshot = case.current_snapshot_id
        self.assertEqual(snapshot.version, 1)
        self.assertEqual(snapshot.decision_source, 'supplier_rule')
        self.assertEqual(snapshot.leg_ids.reporting_type, 'purchase')
        self.assertEqual(snapshot.leg_ids.reporting_category_id, self.food_leaf)
        self.assertEqual(snapshot.leg_ids.reporting_parent_category_id, self.food_parent)
        self.assertEqual(snapshot.leg_ids.basis_points, 10000)
        with self.assertRaises(AccessError):
            snapshot.with_user(self.manager).write({'reason': 'changed'})
        with self.assertRaises(AccessError):
            snapshot.leg_ids.with_user(self.manager).unlink()

    def test_unmapped_or_ambiguous_supplier_is_explicitly_unclassified(self):
        _move, line, _before, _after = self._posted_bill(self.untagged_supplier)
        snapshot = self.env['baseer.purchase.line.classification.case'].search(
            [('source_line_id', '=', line.id)]
        ).current_snapshot_id
        self.assertEqual(snapshot.decision_source, 'unclassified')
        self.assertEqual(snapshot.leg_ids.reporting_type, 'unclassified')
        self.assertEqual(snapshot.leg_ids.basis_points, 10000)

    def test_explicit_product_rule_has_priority_over_supplier_rule(self):
        self._rule()
        product = self.expense_service
        product_rule = self._rule(
            target_kind='product_category', target_id=self.expense_leaf.id,
            reporting_type='expense', reporting_map=self.expense_map,
        )
        _move, line, _before, _after = self._posted_bill(self.supplier, product=product)
        snapshot = self.env['baseer.purchase.line.classification.case'].search(
            [('source_line_id', '=', line.id)]
        ).current_snapshot_id
        self.assertEqual(snapshot.decision_source, 'product_rule')
        self.assertEqual(snapshot.leg_ids.rule_id, product_rule)
        self.assertEqual(snapshot.leg_ids.reporting_type, 'expense')

    def test_refund_uses_a_separate_case_and_rule_configuration_is_manager_only(self):
        self._rule()
        _bill, bill_line, _before, _after = self._posted_bill(self.supplier)
        _refund, refund_line, _before, _after = self._posted_bill(self.supplier, amount=100, move_type='in_refund')
        bill_case = self.env['baseer.purchase.line.classification.case'].search([('source_line_id', '=', bill_line.id)])
        refund_case = self.env['baseer.purchase.line.classification.case'].search([('source_line_id', '=', refund_line.id)])
        self.assertNotEqual(bill_case, refund_case)
        self.assertEqual(refund_line.move_id.move_type, 'in_refund')
        with self.assertRaises(AccessError):
            self.env['baseer.purchase.reporting.rule'].with_user(self.cashier).create({
                'company_id': self.company.id, 'target_kind': 'supplier_category',
                'supplier_category_map_id': self.expense_map.id,
                'reporting_category_map_id': self.expense_map.id, 'reporting_type': 'expense',
            })

    def test_manager_cannot_create_or_move_a_rule_to_an_unavailable_company(self):
        company_b = self.env['res.company'].create({
            'name': 'PCL Company B', 'currency_id': self.env.ref('base.SAR').id,
        })
        account_b = self.env['account.account'].create({
            'name': 'PCL B expense', 'code': 'PCLB600', 'account_type': 'expense',
            'company_ids': [Command.set(company_b.ids)],
        })
        parent_b = self.env['product.category'].create({'name': 'PCL B parent'})
        category_b = self.env['product.category'].create({
            'name': 'PCL B child', 'parent_id': parent_b.id,
        })
        service_b = self.env['product.product'].with_company(company_b).create({
            'name': 'PCL B service', 'type': 'service', 'categ_id': category_b.id,
            'property_account_expense_id': account_b.id,
        })
        map_b = self.env['baseer.purchase.category.map'].with_company(company_b).create({
            'company_id': company_b.id, 'category_id': category_b.id, 'product_id': service_b.id,
        })
        manager_rules = self.env['baseer.purchase.reporting.rule'].with_user(
            self.manager
        ).with_context(allowed_company_ids=[self.company.id])
        with self.assertRaises(AccessError):
            manager_rules.create({
                'company_id': company_b.id, 'target_kind': 'supplier_category',
                'supplier_category_map_id': map_b.id, 'reporting_category_map_id': map_b.id,
                'reporting_type': 'purchase',
            })
        rule = self._rule()
        with self.assertRaises(AccessError):
            rule.with_user(self.manager).with_context(allowed_company_ids=[self.company.id]).write({
                'company_id': company_b.id, 'supplier_category_map_id': map_b.id,
                'reporting_category_map_id': map_b.id,
            })

