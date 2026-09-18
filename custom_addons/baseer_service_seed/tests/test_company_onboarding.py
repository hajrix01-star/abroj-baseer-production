from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class EmployeeServiceOnboardingCase(TransactionCase):

    def _new_company(self):
        company = self.env['res.company'].create({
            'name': 'Employee services onboarding %s' % self._testMethodName,
        })
        self.env.cr.flush()
        return company

    def _assert_no_financial_documents(self, company):
        self.assertFalse(self.env['account.move'].search([('company_id', '=', company.id)]))
        self.assertFalse(self.env['account.payment'].search([('company_id', '=', company.id)]))

    def test_employee_services_are_foundational_with_core_setup_and_create_no_financial_documents(self):
        company = self._new_company()
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wizard.employee_services_state, 'missing')
        self.assertTrue(wizard.setup_employee_services)
        # The hidden compatibility field cannot opt a Saudi company out of the
        # foundational service/analytic preparation when core setup is applied.
        wizard.setup_employee_services = False
        wizard.action_apply_selected()
        self.assertEqual(wizard.employee_services_state, 'ready')
        self.assertTrue(all(line['state'] == 'ready' for line in company._baseer_hr_service_analytic_status()))
        self._assert_no_financial_documents(company)

    def test_readiness_refresh_works_when_active_company_is_different(self):
        """The setup window must not fail while the manager is in another company."""
        company = self._new_company()
        wizard = self.env[company.action_baseer_open_onboarding()['res_model']].browse(
            company.action_baseer_open_onboarding()['res_id']
        )
        wizard.setup_employee_services = True
        wizard.action_apply_selected()

        other_company = self.env.company
        # Match the operational path: an ERP/accounting manager working in a
        # different active company opens the target company's setup window.
        manager = self.env.ref('base.user_admin')
        action = company.with_user(manager).with_context(
            allowed_company_ids=[company.id, other_company.id]
        ).with_company(other_company).action_baseer_open_onboarding()
        refreshed = self.env[action['res_model']].with_user(manager).browse(action['res_id'])
        self.assertEqual(refreshed.employee_services_state, 'ready')

    def test_missing_chart_does_not_disable_core_setup(self):
        """A dependent service card cannot block the prerequisite core card."""
        company = self._new_company()
        company.chart_template = False
        wizard = self.env[company.action_baseer_open_onboarding()['res_model']].browse(
            company.action_baseer_open_onboarding()['res_id']
        )
        self.assertEqual(wizard.accounting_state, 'missing')
        self.assertEqual(wizard.employee_services_state, 'blocked')
        self.assertEqual(wizard.state, 'review')
        self._assert_no_financial_documents(company)
