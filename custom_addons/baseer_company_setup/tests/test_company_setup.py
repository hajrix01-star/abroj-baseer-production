from odoo.exceptions import AccessError
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

    def test_empty_root_create_lifecycle_defaults_to_saudi_chart_and_seed_once(self):
        company = self._new_company()
        # `flush()` runs the same precommit callback that a real create/commit
        # cycle runs, without committing any QA test fixture.
        self.env.cr.flush()
        company.invalidate_recordset()
        self.assertEqual(company.country_id, self.saudi)
        self.assertEqual(company.currency_id, self.sar)
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
        untouched = self._new_company(name='Saudi untouched %s' % self._testMethodName)
        company.write({'country_id': False})
        action = company.action_baseer_initialize_saudi_accounting()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(company.country_id, self.saudi)
        self.assertEqual(company.currency_id, self.sar)
        self.assertEqual(company.chart_template, 'sa')
        self._assert_no_financial_documents(company)
        self.assertFalse(untouched.chart_template)
        self._assert_no_financial_documents(untouched)

    def test_non_erp_manager_cannot_create_or_initialize_company_accounting(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Company setup unprivileged',
            'login': 'company_setup_unprivileged_' + self._testMethodName,
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, self.env.company.ids)],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.env['res.company'].with_user(user).create({
                'name': 'Unprivileged company ' + self._testMethodName,
            })

    def test_targeted_saudi_action_requires_erp_manager(self):
        company = self._new_company()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Company setup no ERP manager',
            'login': 'company_setup_no_erp_' + self._testMethodName,
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, self.env.company.ids)],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            company.with_user(user).action_baseer_initialize_saudi_accounting()
