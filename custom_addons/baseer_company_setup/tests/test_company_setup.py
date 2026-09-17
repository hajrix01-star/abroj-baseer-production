from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class CompanySetupCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.saudi = cls.env.ref('base.sa')
        cls.sar = cls.env.ref('base.SAR')

    def _new_company(self, **values):
        values.setdefault('name', 'Saudi baseline %s' % self._testMethodName)
        return self.env['res.company'].create(values)

    def _assert_no_financial_documents(self, company):
        self.assertFalse(self.env['account.move'].search([('company_id', '=', company.id)]))
        self.assertFalse(self.env['account.payment'].search([('company_id', '=', company.id)]))

    def test_empty_root_defaults_to_saudi_chart_and_seed_once(self):
        company = self._new_company()
        self.assertEqual(company.country_id, self.saudi)
        self.assertEqual(company.currency_id, self.sar)
        company._baseer_prepare_accounting()
        self.assertEqual(company.chart_template, 'sa')
        self.assertTrue(company.baseer_salary_expense_id)
        self.assertTrue(company.baseer_salary_payable_id)
        self.assertTrue(company.baseer_payroll_journal_id)
        journal_ids = self.env['account.journal'].search([('company_id', '=', company.id)]).ids
        company._baseer_prepare_accounting()
        self.assertEqual(self.env['account.journal'].search([('company_id', '=', company.id)]).ids, journal_ids)
        self._assert_no_financial_documents(company)

    def test_explicit_localization_is_not_replaced(self):
        usa = self.env.ref('base.us')
        usd = self.env.ref('base.USD')
        company = self._new_company(country_id=usa.id, currency_id=usd.id)
        self.assertEqual(company.country_id, usa)
        self.assertEqual(company.currency_id, usd)
        company._baseer_prepare_accounting()
        self.assertFalse(company.chart_template)
        self._assert_no_financial_documents(company)

    def test_branch_keeps_shared_accounting_without_default_chart(self):
        company = self._new_company(parent_id=self.env.company.id)
        self.assertFalse(company.chart_template)
        company._baseer_prepare_accounting()
        self.assertFalse(company.chart_template)
        self._assert_no_financial_documents(company)

    def test_targeted_saudi_action_only_initializes_its_company(self):
        company = self._new_company()
        company.write({'country_id': False})
        action = company.action_baseer_initialize_saudi_accounting()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(company.country_id, self.saudi)
        self.assertEqual(company.currency_id, self.sar)
        self.assertEqual(company.chart_template, 'sa')
        self._assert_no_financial_documents(company)
