from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class SalesSummaryOnboardingCase(TransactionCase):

    def _new_company(self):
        company = self.env['res.company'].create({
            'name': 'Summary onboarding %s' % self._testMethodName,
        })
        self.env.cr.flush()
        return company

    def _assert_no_financial_documents(self, company):
        self.assertFalse(self.env['account.move'].search([('company_id', '=', company.id)]))
        self.assertFalse(self.env['account.payment'].search([('company_id', '=', company.id)]))
        self.assertFalse(self.env['pos.session'].search([('company_id', '=', company.id)]))

    def test_summary_methods_are_opt_in_and_additive(self):
        company = self._new_company()
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wizard.sales_summary_state, 'not_selected')
        self.assertFalse(self.env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', True)]))
        wizard.write({
            'sales_mode': 'summary',
            'setup_summary_cash': True,
            'setup_summary_bank': True,
        })
        wizard.action_apply_selected()
        config = self.env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
        self.assertTrue(config)
        self.assertEqual(set(config.payment_method_ids.mapped('name')), {'نقدي | Cash', 'بنك | Bank'})
        wizard.setup_summary_jahez = True
        wizard.action_apply_selected()
        self.assertEqual(set(config.payment_method_ids.mapped('name')), {
            'نقدي | Cash', 'بنك | Bank', 'جاهز | Jahez'})
        # A fresh wizard reads the configuration it is about to extend; it
        # must not present an existing company as "no sales".
        action = company.action_baseer_open_onboarding()
        reopened = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(reopened.sales_mode, 'summary')
        self.assertTrue(reopened.setup_summary_cash)
        self.assertTrue(reopened.setup_summary_bank)
        self.assertTrue(reopened.setup_summary_jahez)
        self.assertFalse(reopened.setup_summary_hungerstation)
        self._assert_no_financial_documents(company)

    def test_selected_platforms_get_independent_journals(self):
        company = self._new_company()
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.write({
            'sales_mode': 'summary',
            'setup_summary_hungerstation': True,
            'setup_summary_keeta': True,
            'setup_summary_jahez': True,
        })
        wizard.action_apply_selected()
        config = self.env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
        expected = {
            'هنقرستيشن | HungerStation': ('HUNG', '101008', '102110'),
            'كيتا | Keeta': ('KEET', '101007', '102111'),
            'جاهز | Jahez': ('JAHZ', '101009', '102112'),
        }
        methods = config.with_company(company).payment_method_ids.filtered(
            lambda method: method.baseer_category_id.kind == 'platform')
        self.assertEqual(len(methods), len(expected))
        self.assertEqual(len(methods.mapped('journal_id')), len(expected))
        for method in methods:
            journal_code, liquidity_code, clearing_code = expected[method.name]
            self.assertEqual(method.journal_id.code, journal_code)
            liquidity = method.journal_id.with_company(company).default_account_id
            self.assertEqual(liquidity.code, liquidity_code)
            self.assertEqual(liquidity.account_type, 'asset_cash')
            self.assertEqual(method.outstanding_account_id.code, clearing_code)
            self.assertEqual(method.outstanding_account_id.account_type, 'asset_current')
            self.assertTrue(method.outstanding_account_id.reconcile)

        wizard.action_apply_selected()
        self.assertEqual(len(config.payment_method_ids.filtered(
            lambda method: method.baseer_category_id.kind == 'platform')), len(expected))
        self._assert_no_financial_documents(company)

    def test_native_direct_pos_can_start_without_a_financial_document(self):
        company = self._new_company()
        config = self.env['pos.config'].with_context(
            allowed_company_ids=[company.id]
        ).with_company(company).create({
            'name': 'Direct POS %s' % self._testMethodName,
            'company_id': company.id,
        })
        self.assertTrue(config)
        self.assertFalse(config.baseer_summary_only)
        self._assert_no_financial_documents(company)

    def test_direct_pos_is_explicit_and_does_not_create_sales_summaries(self):
        company = self._new_company()
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.sales_mode = 'direct_pos'
        wizard.action_apply_selected()
        self.assertTrue(self.env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', False),
        ], limit=1))
        self.assertFalse(self.env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', True),
        ]))
        self._assert_no_financial_documents(company)

    def test_onboarding_refresh_works_from_another_active_company(self):
        """Readiness is internal and must not depend on the manager's current company."""
        company = self._new_company()
        wizard = self.env[company.action_baseer_open_onboarding()['res_model']].browse(
            company.action_baseer_open_onboarding()['res_id']
        )
        wizard.write({'sales_mode': 'summary', 'setup_summary_cash': True})
        wizard.action_apply_selected()
        manager = self.env.ref('base.user_admin')
        action = company.with_user(manager).with_context(
            allowed_company_ids=[company.id, self.env.company.id]
        ).with_company(self.env.company).action_baseer_open_onboarding()
        refreshed = self.env[action['res_model']].with_user(manager).browse(action['res_id'])
        refreshed.sales_mode = 'summary'
        refreshed.action_refresh()
        self.assertEqual(refreshed.sales_summary_state, 'ready')
