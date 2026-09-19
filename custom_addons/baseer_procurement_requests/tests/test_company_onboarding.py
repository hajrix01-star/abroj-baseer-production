from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class ProcurementOnboardingCase(TransactionCase):

    def _new_company(self, name=None):
        company = self.env['res.company'].create({
            'name': name or 'Procurement onboarding %s' % self._testMethodName,
        })
        self.env.cr.flush()
        return company

    def _assert_no_operational_documents(self, company):
        self.assertFalse(self.env['account.move'].search([('company_id', '=', company.id)]))
        self.assertFalse(self.env['account.payment'].search([('company_id', '=', company.id)]))
        self.assertFalse(self.env['stock.move'].search([('company_id', '=', company.id)]))
        self.assertFalse(self.env['baseer.procurement.representative.advance'].search([
            ('company_id', '=', company.id),
        ]))

    def test_warehouse_and_representative_custody_are_explicit(self):
        company = self._new_company()
        # The Saudi seed prepares the shared account and general journal, but
        # never selects a funding point or creates a financial movement.
        self.assertTrue(company.baseer_procurement_representative_petty_cash_account_id)
        self.assertTrue(company.baseer_procurement_representative_petty_cash_journal_id)
        self.assertFalse(company.baseer_procurement_representative_petty_cash_payment_journal_ids)
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        # A new company may already have Odoo's native warehouse. The
        # onboarding window must show that fact and ask only for the missing
        # procurement default, rather than pretending no stock exists.
        self.assertEqual(wizard.procurement_stock_state, 'missing')
        self.assertEqual(wizard.procurement_stock_mode, 'single')
        self.assertEqual(wizard.representative_petty_cash_state, 'not_selected')
        payment_point = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('type', 'in', ('bank', 'cash')), ('active', '=', True),
        ], limit=1)
        self.assertTrue(payment_point)
        wizard.write({
            'procurement_stock_mode': 'single',
            'setup_main_warehouse': True,
            'setup_representative_petty_cash': True,
            'representative_petty_cash_payment_journal_ids': [Command.set(payment_point.ids)],
        })
        wizard.action_apply_selected()
        self.assertTrue(company.baseer_procurement_default_warehouse_id)
        self.assertTrue(company.baseer_procurement_representative_petty_cash_account_id)
        self.assertTrue(company.baseer_procurement_representative_petty_cash_journal_id)
        self.assertEqual(company.baseer_procurement_representative_petty_cash_payment_journal_ids, payment_point)
        self._assert_no_operational_documents(company)

    def test_reopening_prefills_existing_setup_and_adds_custody_payment_points(self):
        company = self._new_company()
        journals = self.env['account.journal'].search([
            ('company_id', '=', company.id), ('type', 'in', ('bank', 'cash')), ('active', '=', True),
        ])
        bank = journals.filtered(lambda journal: journal.type == 'bank')[:1]
        cash = journals.filtered(lambda journal: journal.type == 'cash')[:1]
        self.assertTrue(bank and cash)
        company.write({'baseer_procurement_representative_petty_cash_payment_journal_ids': [
            Command.set(bank.ids),
        ]})

        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertTrue(wizard.setup_representative_petty_cash)
        self.assertEqual(wizard.representative_petty_cash_payment_journal_ids, bank)

        # Selecting only cash in the window means "add cash"; it must never
        # silently remove the bank that was configured before opening it.
        wizard.write({
            'representative_petty_cash_payment_journal_ids': [Command.set(cash.ids)],
        })
        wizard.action_apply_selected()
        self.assertEqual(
            company.baseer_procurement_representative_petty_cash_payment_journal_ids,
            bank | cash,
        )

        reopened = self.env[company.action_baseer_open_onboarding()['res_model']].browse(
            company.action_baseer_open_onboarding()['res_id']
        )
        self.assertTrue(reopened.setup_representative_petty_cash)
        self.assertEqual(
            reopened.representative_petty_cash_payment_journal_ids,
            bank | cash,
        )
        self._assert_no_operational_documents(company)

    def test_reopening_prefills_single_default_procurement_warehouse(self):
        company = self._new_company()
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.write({
            'procurement_stock_mode': 'single',
            'setup_main_warehouse': True,
        })
        wizard.action_apply_selected()
        warehouse = company.baseer_procurement_default_warehouse_id
        self.assertTrue(warehouse)

        action = company.action_baseer_open_onboarding()
        reopened = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(reopened.procurement_stock_mode, 'single')
        self.assertEqual(reopened.procurement_warehouse_id, warehouse)
        self._assert_no_operational_documents(company)

    def test_current_representative_petty_cash_menu_is_not_legacy_custody(self):
        """New users must not land on the retired PCUST accounting flow."""
        current_menu = self.env.ref(
            'baseer_procurement_requests.menu_procurement_representative_petty_cash'
        )
        self.assertTrue(current_menu.active)
        self.assertEqual(current_menu.action._name, 'ir.actions.client')
        self.assertEqual(
            current_menu.action.tag,
            'baseer_procurement_requests.representative_petty_cash',
        )
        for xml_id in (
            'menu_procurement_custody',
            'menu_procurement_custody_monthly_statement',
            'menu_procurement_custody_period_close',
        ):
            self.assertFalse(
                self.env.ref('baseer_procurement_requests.%s' % xml_id).active
            )

    def test_preview_reads_target_company_petty_cash_from_another_active_company(self):
        company = self._new_company()
        other = self._new_company(name='Other procurement onboarding %s' % self._testMethodName)
        manager = self.env.ref('base.user_admin')
        action = company.with_user(manager).with_context(
            allowed_company_ids=[company.id, other.id]
        ).with_company(other).action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].with_user(manager).browse(action['res_id'])
        self.assertEqual(wizard.representative_petty_cash_state, 'not_selected')
        self._assert_no_operational_documents(company)
