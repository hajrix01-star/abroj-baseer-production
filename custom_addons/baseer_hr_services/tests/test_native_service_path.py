from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class EmployeeServiceNativePathCase(TransactionCase):
    """Employee services must use native products, never category maps."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env.user.group_ids |= (
            cls.env.ref('hr.group_hr_manager') | cls.env.ref('account.group_account_invoice')
        )
        Account = cls.env['account.account']
        cls.expense = Account.create({
            'name': 'HRN native permits expense', 'code': 'HRN901',
            'account_type': 'expense', 'company_ids': [Command.set(cls.company.ids)],
        })
        cls.visa_expense = Account.create({
            'name': 'HRN native visas expense', 'code': 'HRN902',
            'account_type': 'expense', 'company_ids': [Command.set(cls.company.ids)],
        })
        cls.payable = Account.create({
            'name': 'HRN payable', 'code': 'HRN903', 'account_type': 'liability_payable',
            'reconcile': True, 'company_ids': [Command.set(cls.company.ids)],
        })
        cls.category = cls.env['product.category'].create({'name': 'HRN native services'})
        cls.iqama_product = cls._seed_product('iqama_renewal', cls.expense)
        cls.visa_product = cls._seed_product('visa', cls.visa_expense)
        cls.provider = cls.env['res.partner'].create({
            'name': 'HRN provider', 'supplier_rank': 1,
            'property_account_payable_id': cls.payable.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'HRN employee', 'company_id': cls.company.id,
        })
        cls.journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'purchase'), ('active', '=', True),
        ], order='sequence,id', limit=1)
        if not cls.journal:
            cls.env['account.journal'].create({
                'name': 'HRN Purchases', 'code': 'HRNP', 'type': 'purchase',
                'company_id': cls.company.id, 'sequence': -100,
            })

    @classmethod
    def _seed_product(cls, service_type, expense):
        xmlid = f'baseer_service_seed.product_{service_type}_company_{cls.company.id}'
        product = cls.env.ref(xmlid, raise_if_not_found=False)
        if not product:
            product = cls.env['product.product'].create({
                'name': 'HRN ' + service_type, 'type': 'service', 'company_id': cls.company.id,
                'categ_id': cls.category.id, 'purchase_ok': True, 'sale_ok': False,
            })
            cls.env['ir.model.data'].create({
                'module': 'baseer_service_seed', 'name': xmlid.rsplit('.', 1)[1],
                'model': 'product.product', 'res_id': product.id, 'noupdate': True,
            })
        product.write({'active': True, 'purchase_ok': True,
                       'property_account_expense_id': expense.id})
        return product

    def _service(self, service_type='iqama_renewal', amount=100, partner=None):
        values = {}
        if service_type == 'visa':
            values['visa_type'] = 'issue'
        return self.env['baseer.hr.service'].create({
            'employee_id': self.employee.id, 'service_type': service_type,
            'partner_id': (partner or self.provider).id, 'gross_amount': amount,
            'invoice_date': '2026-09-16', 'issue_date': '2026-09-16',
        } | values)

    def test_service_uses_native_product_account_without_category_map(self):
        self.assertNotIn('category_map_id', self.env['baseer.hr.service']._fields)
        service = self._service()
        service.action_approve()
        bill = service.bill_id
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.invoice_line_ids.product_id, self.iqama_product)
        self.assertEqual(bill.invoice_line_ids.account_id, self.expense)
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        if root:
            selected = self.env['account.analytic.account'].browse([
                int(account_id) for key in bill.invoice_line_ids.analytic_distribution
                for account_id in key.split(',')
            ]).exists()
            self.assertTrue(selected)
            self.assertTrue(all(account.root_plan_id == root for account in selected))
        self.assertEqual((bill.amount_untaxed, bill.amount_tax, bill.amount_total), (100, 0, 100))

    def test_same_provider_uses_service_type_product_not_supplier_history(self):
        first = self._service()
        first.action_approve()
        second = self._service('visa')
        second.action_approve()
        self.assertEqual(first.bill_id.invoice_line_ids.account_id, self.expense)
        self.assertEqual(second.bill_id.invoice_line_ids.product_id, self.visa_product)
        self.assertEqual(second.bill_id.invoice_line_ids.account_id, self.visa_expense)

    def test_supplier_models_recompute_native_analytics_without_changing_expense(self):
        """Odoo's native supplier models own the analytic dimension."""
        root = self.env.ref('baseer_native_spend.spend_plan')
        plan = self.env['account.analytic.plan'].create({
            'name': 'HRN native supplier analytics', 'parent_id': root.id,
        })
        analytic_a = self.env['account.analytic.account'].create({
            'name': 'HRN supplier A analytics', 'plan_id': plan.id, 'company_id': False,
        })
        analytic_b = self.env['account.analytic.account'].create({
            'name': 'HRN supplier B analytics', 'plan_id': plan.id, 'company_id': False,
        })
        provider_a = self.env['res.partner'].create({
            'name': 'HRN supplier A', 'supplier_rank': 1,
            'property_account_payable_id': self.payable.id,
        })
        provider_b = self.env['res.partner'].create({
            'name': 'HRN supplier B', 'supplier_rank': 1,
            'property_account_payable_id': self.payable.id,
        })
        Distribution = self.env['account.analytic.distribution.model']
        Distribution.create({
            'company_id': self.company.id, 'product_id': self.iqama_product.id,
            'partner_id': provider_a.id, 'sequence': 1,
            'analytic_distribution': {str(analytic_a.id): 100},
        })
        Distribution.create({
            'company_id': self.company.id, 'product_id': self.iqama_product.id,
            'partner_id': provider_b.id, 'sequence': 1,
            'analytic_distribution': {str(analytic_b.id): 100},
        })

        first = self._service(partner=provider_a)
        first.action_approve()
        second = self._service(partner=provider_b)
        second.action_approve()

        self.assertEqual(first.bill_id.invoice_line_ids.account_id, self.expense)
        self.assertEqual(second.bill_id.invoice_line_ids.account_id, self.expense)
        self.assertEqual(first.bill_id.invoice_line_ids.analytic_distribution,
                         {str(analytic_a.id): 100.0})
        self.assertEqual(second.bill_id.invoice_line_ids.analytic_distribution,
                         {str(analytic_b.id): 100.0})

    def test_vat_uses_native_product_path_and_reconciles_totals(self):
        tax = self.env['account.tax'].create({
            'name': 'HRN VAT 15%', 'company_id': self.company.id,
            'type_tax_use': 'purchase', 'amount_type': 'percent', 'amount': 15,
        })
        self.company.account_purchase_tax_id = tax
        service = self._service(amount=115)
        service.write({'vat_enabled': True})
        service.action_approve()
        self.assertEqual((service.net_amount, service.tax_amount, service.gross_amount), (100, 15, 115))
        self.assertEqual((service.bill_id.amount_untaxed, service.bill_id.amount_tax,
                          service.bill_id.amount_total), (100, 15, 115))

    def test_invalid_native_product_account_blocks_approval_atomically(self):
        invalid = self.env['account.account'].create({
            'name': 'HRN invalid asset account', 'code': 'HRN904',
            'account_type': 'asset_current', 'company_ids': [Command.set(self.company.ids)],
        })
        self.iqama_product.property_account_expense_id = invalid
        service = self._service()
        with self.assertRaises(ValidationError):
            service.action_approve()
        self.assertFalse(service.bill_id)
        self.assertEqual(service.state, 'draft')

    def test_non_service_product_blocks_draft_before_any_bill(self):
        self.iqama_product.type = 'consu'
        with self.assertRaises(ValidationError):
            self._service()
        self.assertFalse(self.env['account.move'].search([
            ('baseer_hr_service_id', '!=', False), ('company_id', '=', self.company.id),
        ]))

    def test_missing_native_service_product_blocks_without_bill(self):
        self.env['ir.model.data'].search([
            ('module', '=', 'baseer_service_seed'),
            ('name', '=', f'product_iqama_renewal_company_{self.company.id}'),
        ]).unlink()
        with self.assertRaises(ValidationError):
            self._service()
        self.assertFalse(self.env['account.move'].search([
            ('baseer_hr_service_id', '!=', False), ('company_id', '=', self.company.id),
        ]))
