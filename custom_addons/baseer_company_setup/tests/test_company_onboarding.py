from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class CompanyOnboardingCase(TransactionCase):

    def _new_company(self, **values):
        values.setdefault('name', 'Onboarding company %s' % self._testMethodName)
        company = self.env['res.company'].create(values)
        self.env.cr.flush()
        return company

    def _assert_no_financial_documents(self, company):
        self.assertFalse(self.env['account.move'].search([('company_id', '=', company.id)]))
        self.assertFalse(self.env['account.payment'].search([('company_id', '=', company.id)]))

    def test_opening_setup_is_company_scoped_and_read_only(self):
        company = self._new_company()
        other = self._new_company(name='Other onboarding company %s' % self._testMethodName)
        action = company.action_baseer_open_onboarding()
        self.assertEqual(action['res_model'], 'baseer.company.onboarding')
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wizard.company_id, company)
        self.assertEqual(wizard.accounting_state, 'ready')
        # When the employee-service module is present, the unified setup
        # remains under review until its foundational analytic rules exist.
        self.assertEqual(wizard.state, 'review')
        self._assert_no_financial_documents(company)
        self._assert_no_financial_documents(other)

    def test_setup_blocks_explicit_non_saudi_company_without_writing(self):
        company = self._new_company(
            country_id=self.env.ref('base.us').id,
            currency_id=self.env.ref('base.USD').id,
        )
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wizard.accounting_state, 'blocked')
        self._assert_no_financial_documents(company)

    def test_non_erp_manager_cannot_open_company_setup(self):
        company = self._new_company()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Onboarding regular user',
            'login': 'onboarding_regular_' + self._testMethodName,
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, self.env.company.ids)],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            company.with_user(user).action_baseer_open_onboarding()

    def test_staged_navigation_and_review_are_read_only(self):
        company = self._new_company()
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wizard.setup_step, 'foundation')
        self.assertIn('الأساس السعودي', wizard.plan_preview)
        wizard.action_next_step()
        self.assertEqual(wizard.setup_step, 'sales')
        wizard.action_next_step()
        self.assertEqual(wizard.setup_step, 'operations')
        wizard.action_next_step()
        self.assertEqual(wizard.setup_step, 'review')
        wizard.action_previous_step()
        self.assertEqual(wizard.setup_step, 'operations')
        self._assert_no_financial_documents(company)

    def test_readiness_requires_active_starter_journals(self):
        company = self._new_company()
        bank = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('type', '=', 'bank'), ('active', '=', True),
        ], limit=1)
        self.assertTrue(bank)
        bank.active = False
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wizard.accounting_state, 'missing')
        self._assert_no_financial_documents(company)

    def test_setup_preview_reads_target_company_when_another_company_is_active(self):
        company = self._new_company()
        other = self._new_company(name='Other active company %s' % self._testMethodName)
        manager = self.env.ref('base.user_admin')
        action = company.with_user(manager).with_context(
            allowed_company_ids=[company.id, other.id]
        ).action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].with_user(manager).browse(action['res_id'])
        self.assertIn('الأساس السعودي', wizard.plan_preview)
        self._assert_no_financial_documents(company)

    def test_erp_manager_can_open_an_assigned_company_when_another_company_is_active(self):
        target = self._new_company()
        active = self._new_company(name='Active onboarding company %s' % self._testMethodName)
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Multi-company onboarding manager',
            'login': 'multicompany_onboarding_' + self._testMethodName,
            'company_id': active.id,
            'company_ids': [(6, 0, [target.id, active.id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('base.group_erp_manager').id,
            ])],
        })
        action = target.with_user(manager).with_context(
            allowed_company_ids=[active.id]
        ).action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].with_user(manager).browse(action['res_id'])
        self.assertEqual(wizard.company_id, target)
        self._assert_no_financial_documents(target)

    def test_erp_manager_cannot_open_or_apply_setup_for_another_company(self):
        company = self._new_company()
        allowed_company = self._new_company(name='Allowed company %s' % self._testMethodName)
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Restricted onboarding manager',
            'login': 'restricted_onboarding_' + self._testMethodName,
            'company_id': allowed_company.id,
            'company_ids': [(6, 0, allowed_company.ids)],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('base.group_erp_manager').id,
            ])],
        })
        restricted_company = company.with_user(manager).with_context(
            allowed_company_ids=[allowed_company.id]
        )
        with self.assertRaises(AccessError):
            restricted_company.action_baseer_open_onboarding()
        self._assert_no_financial_documents(company)
