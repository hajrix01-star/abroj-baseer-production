from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.baseer_service_seed.models.catalog import SERVICES
from odoo.addons.baseer_service_seed.models.company import HR_SERVICE_ANALYTIC_MAP


@tagged('post_install', '-at_install')
class HrServiceAnalyticsSeedCase(TransactionCase):
    """The 15 HR services get an Odoo-native, company-scoped 100% rule."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= (
            cls.env.ref('base.group_erp_manager')
            | cls.env.ref('account.group_account_manager')
            | cls.env.ref('account.group_account_invoice')
            | cls.env.ref('hr.group_hr_manager')
        )
        cls.company = cls.env['res.company'].create({
            'name': 'HRA seed QA', 'country_id': cls.env.ref('base.sa').id,
            'currency_id': cls.env.ref('base.SAR').id,
        })
        cls.company.action_baseer_initialize_saudi_accounting()
        cls.company._baseer_seed_services()
        cls.company._baseer_ensure_spend_applicability()
        cls.employee = cls.env['hr.employee'].with_company(cls.company).create({
            'name': 'HRA QA employee', 'company_id': cls.company.id,
        })
        cls.provider = cls.env.ref('baseer_service_seed.provider_passports')

    def _service(self, service_type, amount=100):
        values = {
            'company_id': self.company.id, 'employee_id': self.employee.id,
            'service_type': service_type, 'partner_id': self.provider.id,
            'gross_amount': amount, 'invoice_date': fields.Date.today(),
            'issue_date': fields.Date.today(), 'service_reference': 'HRA-%s' % service_type,
        }
        if service_type == 'visa':
            values['visa_type'] = 'issue'
        if service_type == 'other_employee':
            values['notes'] = 'HRA QA documented other employee service'
        return self.env['baseer.hr.service'].with_company(self.company).create(values)

    def test_all_employee_service_types_have_distinct_company_product_rules(self):
        statuses = self.company._baseer_hr_service_analytic_status()
        self.assertEqual(len(statuses), 15)
        self.assertTrue(all(line['state'] == 'ready' for line in statuses))
        models = []
        for service_type, _english, _arabic, _purpose in SERVICES[:15]:
            product = self.env.ref(
                'baseer_service_seed.product_%s_company_%s' % (service_type, self.company.id)
            )
            leaf = self.company._baseer_hr_analytic_leaf(HR_SERVICE_ANALYTIC_MAP[service_type])
            model = self.env.ref(
                'baseer_service_seed.hr_analytic_model_%s_company_%s' % (service_type, self.company.id)
            )
            self.assertEqual(model.company_id, self.company)
            self.assertEqual(model.product_id, product)
            self.assertEqual(model.analytic_distribution, {str(leaf.id): 100.0})
            models.append(model)
        self.assertEqual(len({model.id for model in models}), 15)

    def test_all_employee_service_types_post_with_native_analytics(self):
        for index, (service_type, _english, _arabic, _purpose) in enumerate(SERVICES[:15], start=1):
            with self.subTest(service_type=service_type):
                service = self._service(service_type, amount=100 + index)
                service.action_approve()
                self.assertEqual(service.state, 'approved')
                self.assertEqual(service.bill_id.state, 'posted')
                line = service.bill_id.invoice_line_ids
                leaf = self.company._baseer_hr_analytic_leaf(HR_SERVICE_ANALYTIC_MAP[service_type])
                self.assertEqual(line.analytic_distribution, {str(leaf.id): 100.0})
                self.assertAlmostEqual(sum(service.bill_id.line_ids.mapped('balance')), 0)

    def test_missing_rule_blocks_without_issuing_a_bill(self):
        service_type = 'iqama_renewal'
        model = self.env.ref(
            'baseer_service_seed.hr_analytic_model_%s_company_%s' % (service_type, self.company.id)
        )
        model.unlink()
        service = self._service(service_type)
        with self.assertRaises(ValidationError):
            service.action_approve()
        self.assertEqual(service.state, 'draft')
        self.assertFalse(service.bill_id)

    def test_readiness_fills_only_a_missing_native_product_expense_account(self):
        service_type = 'iqama_renewal'
        product = self.env.ref(
            'baseer_service_seed.product_%s_company_%s' % (service_type, self.company.id)
        )
        expected_account = self.company._baseer_service_account('permits')
        product.active = False
        product.with_company(self.company).property_account_expense_id = False

        status = {
            line['service_type']: line for line in self.company._baseer_hr_service_analytic_status()
        }
        self.assertEqual(status[service_type]['state'], 'missing')

        self.company._baseer_prepare_hr_service_analytics()
        self.assertEqual(
            product.with_company(self.company).property_account_expense_id,
            expected_account,
        )
        self.assertTrue(product.active)
        self.assertTrue(all(
            line['state'] == 'ready'
            for line in self.company._baseer_hr_service_analytic_status()
        ))

    def test_readiness_replaces_a_legacy_shared_product_without_rewriting_it(self):
        service_type = 'iqama_renewal'
        original = self.env.ref(
            'baseer_service_seed.product_%s_company_%s' % (service_type, self.company.id)
        )
        original.company_id = False

        status = {
            line['service_type']: line for line in self.company._baseer_hr_service_analytic_status()
        }
        self.assertEqual(status[service_type]['state'], 'missing')

        self.company._baseer_prepare_hr_service_analytics()
        reference = self.env['ir.model.data'].search([
            ('module', '=', 'baseer_service_seed'),
            ('name', '=', 'product_%s_company_%s' % (service_type, self.company.id)),
        ], limit=1)
        replacement = self.env['product.product'].browse(reference.res_id)
        self.assertNotEqual(replacement, original)
        self.assertFalse(original.company_id)
        self.assertEqual(replacement.company_id, self.company)
        self.assertTrue(replacement.active)
        self.assertEqual(
            replacement.with_company(self.company).property_account_expense_id,
            self.company._baseer_service_account('permits'),
        )
