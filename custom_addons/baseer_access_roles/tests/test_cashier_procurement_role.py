from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase


class CashierProcurementRoleCase(TransactionCase):
    def test_cpr_t00_owner_preset_keeps_the_only_system_administrator(self):
        """Owner promotion must not demote the sole native administrator."""
        administrator = self.env.ref('base.user_admin')
        system_group = self.env.ref('base.group_system')
        owner_group = self.env.ref('baseer_access_roles.group_owner')

        self.assertIn(system_group, administrator.group_ids)
        administrator.write({'baseer_access_role': 'owner'})

        self.assertEqual(administrator.baseer_access_role, 'owner')
        self.assertIn(owner_group, administrator.group_ids)
        self.assertIn(system_group, administrator.group_ids)

    def test_cpr_t00a_owner_preset_inherits_all_procurement_capabilities(self):
        """The owner sees every custom procurement surface without limited-role isolation."""
        administrator = self.env.ref('base.user_admin')
        administrator.write({'baseer_access_role': 'owner'})

        for xmlid in (
            'baseer_procurement_requests.group_procurement_manager',
            'baseer_procurement_requests.group_procurement_accountant',
            'baseer_procurement_requests.group_procurement_cashier',
        ):
            self.assertTrue(administrator.has_group(xmlid))

        self.assertFalse(administrator.has_group('baseer_access_roles.group_accountant'))
        self.assertFalse(administrator.has_group('baseer_access_roles.group_cashier'))

    def _fixture(self, company, suffix):
        """Create the minimum company-local operational request fixture."""
        company_env = self.env(context={
            **self.env.context,
            'allowed_company_ids': [company.id],
        })
        warehouse = company_env['stock.warehouse'].search([
            ('company_id', '=', company.id),
        ], limit=1)
        self.assertTrue(warehouse)
        uom = company_env.ref('uom.product_uom_unit')
        category_values = {'name': 'Cashier role category %s' % suffix}
        if 'property_cost_method' in company_env['product.category']._fields:
            category_values['property_cost_method'] = 'standard'
        if 'property_valuation' in company_env['product.category']._fields:
            category_values['property_valuation'] = 'periodic'
        category = company_env['product.category'].create(category_values)
        product = company_env['product.product'].create({
            'name': 'Cashier role material %s' % suffix,
            'company_id': company.id,
            'categ_id': category.id,
            'uom_id': uom.id,
            'is_storable': False,
            'purchase_ok': True,
        })
        option = company_env['baseer.procurement.purchase.option'].create({
            'name': 'Piece',
            'company_id': company.id,
            'product_id': product.id,
            'uom_id': uom.id,
        })
        purchaser = company_env['hr.employee'].create({
            'name': 'Cashier role buyer %s' % suffix,
            'company_id': company.id,
        })
        return warehouse, option, purchaser

    def _new_request(self, request_model, company, warehouse, option, purchaser):
        return request_model.create({
            'company_id': company.id,
            'warehouse_id': warehouse.id,
            'purchaser_id': purchaser.id,
            'line_ids': [Command.create({
                'option_id': option.id,
                'requested_qty': 2,
                'requested_price': 4,
            })],
        })

    def test_cpr_t01_cashier_role_inherits_only_procurement_cashier_capability(self):
        """The role reaches the existing guarded workflow, never manager/finance groups."""
        company = self.env.company
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Cashier procurement role',
            'login': 'cashier-procurement-%s' % uuid4().hex,
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'baseer_access_role': 'cashier',
        })

        self.assertTrue(cashier.has_group('baseer_access_roles.group_cashier'))
        self.assertTrue(cashier.has_group(
            'baseer_procurement_requests.group_procurement_cashier'
        ))
        self.assertTrue(cashier.has_group(
            'baseer_procurement_requests.group_procurement_user'
        ))
        self.assertFalse(cashier.has_group(
            'baseer_procurement_requests.group_procurement_manager'
        ))
        self.assertFalse(cashier.has_group(
            'baseer_procurement_requests.group_procurement_accountant'
        ))
        self.assertFalse(cashier.has_group('account.group_account_invoice'))

        cashier.write({'baseer_access_role': False})
        self.assertFalse(cashier.has_group(
            'baseer_procurement_requests.group_procurement_cashier'
        ))

    def test_cpr_t01a_cashier_sees_only_curated_navigation(self):
        """BASSER replaces native roots when installed; otherwise preserve legacy paths."""
        company = self.env.company
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Cashier procurement navigation',
            'login': 'cashier-procurement-navigation-%s' % uuid4().hex,
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'baseer_access_role': 'cashier',
        })

        menu_model = self.env['ir.ui.menu'].with_user(cashier)
        visible = menu_model._visible_menu_ids()
        workspace_root = self.env.ref(
            'baseer_basser_workspace.menu_basser_root', raise_if_not_found=False,
        )
        if workspace_root and workspace_root.id in visible:
            for xmlid in (
                'stock.menu_stock_root',
                'baseer_procurement_requests.menu_procurement_root',
                'baseer_procurement_requests.menu_procurement_catalog',
                'baseer_procurement_requests.menu_procurement_requests',
            ):
                self.assertNotIn(self.env.ref(xmlid).id, visible)
            return

        # During the base role module's own upgrade the optional BASSER module
        # can be queued but not yet have loaded its menu data.  Its own suite
        # covers the workspace cards; this suite must only assert the cashier
        # never receives configuration-only native entries.
        for xmlid in (
            'baseer_procurement_requests.menu_procurement_options',
            'baseer_procurement_requests.menu_procurement_custody',
            'baseer_procurement_requests.menu_procurement_reports',
        ):
            self.assertNotIn(self.env.ref(xmlid).id, visible)

    def test_cpr_t02_role_can_receive_only_in_the_active_company(self):
        """A role cashier creates/receives in A but cannot mutate B via ORM."""
        company_a = self.env.company
        company_b = self.env['res.company'].create({
            'name': 'Cashier role second company',
            'currency_id': company_a.currency_id.id,
        })
        warehouse_a, option_a, purchaser_a = self._fixture(company_a, 'A')
        warehouse_b, option_b, purchaser_b = self._fixture(company_b, 'B')
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Cashier operational role',
            'login': 'cashier-operational-%s' % uuid4().hex,
            'company_id': company_a.id,
            'company_ids': [Command.set([company_a.id, company_b.id])],
            'baseer_access_role': 'cashier',
        })
        cashier_env = self.env['baseer.procurement.request'].with_user(cashier).with_context(
            allowed_company_ids=[company_a.id, company_b.id],
        )

        request_a = self._new_request(
            cashier_env, company_a, warehouse_a, option_a, purchaser_a,
        )
        self.assertEqual(request_a.requester_id, cashier)
        request_a.action_mark_sent()
        request_a.confirm_actual_from_catalog(request_a.id, [{
            'line_id': request_a.line_ids.id,
            'actual_qty': '2.00',
            'actual_price': '5.00',
        }])
        self.assertEqual(request_a.state, 'purchased')
        self.assertEqual(request_a.actual_confirmed_by_id, cashier)
        self.assertTrue(self.env['baseer.procurement.price.history'].search_count([
            ('request_id', '=', request_a.id),
        ]))

        with self.assertRaises(AccessError):
            request_a.with_user(cashier).with_context(
                allowed_company_ids=[company_a.id, company_b.id],
            ).write({
                'company_id': company_b.id,
                'warehouse_id': warehouse_b.id,
                'purchaser_id': purchaser_b.id,
            })
        self.assertEqual(request_a.company_id, company_a)

        self.env.user.company_ids |= company_b
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_manager'
        )
        manager_only_request = self._new_request(
            self.env['baseer.procurement.request'],
            company_a, warehouse_a, option_a, purchaser_a,
        )
        manager_only_request.action_mark_sent()
        with self.assertRaises(AccessError):
            manager_only_request.with_user(cashier).action_confirm_manager_receipt()
        self.assertFalse(self.env['account.move'].with_user(cashier).check_access_rights(
            'create', raise_exception=False,
        ))
        self.assertFalse(self.env['baseer.procurement.custody'].with_user(
            cashier
        ).check_access_rights('read', raise_exception=False))

        request_b = self._new_request(
            self.env['baseer.procurement.request'].with_context(
                allowed_company_ids=[company_b.id],
            ),
            company_b, warehouse_b, option_b, purchaser_b,
        )
        with self.assertRaises(AccessError):
            request_b.with_user(cashier).with_context(
                allowed_company_ids=[company_a.id, company_b.id],
            ).action_mark_sent()

        request_b.action_mark_sent()
        request_b.line_ids.manager_received_qty = 2
        request_b.action_confirm_manager_receipt()
        cashier_request_b = request_b.with_user(cashier).with_context(
            allowed_company_ids=[company_a.id, company_b.id],
        )
        with self.assertRaises(AccessError):
            cashier_request_b.line_ids.write({
                'actual_qty': 2,
                'actual_price': 5,
            })
        with self.assertRaises(AccessError):
            cashier_request_b.action_confirm_actual_purchase()
        self.assertEqual(request_b.state, 'received')


class CashierPurchaseBatchApprovalCase(TransactionCase):
    """Regression coverage for the optional, company-scoped self-approval path."""

    def setUp(self):
        super().setUp()
        sar = self.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', 'SAR')], limit=1,
        )
        self.assertTrue(sar, 'Cashier batch approval tests require SAR.')
        if not sar.active:
            sar.active = True
        self.company_a = self.env['res.company'].create({
            'name': 'Cashier batch approval A',
            'currency_id': sar.id,
        })
        self.env.user.company_ids |= self.company_a
        self.env = self.env(context={
            **self.env.context,
            'allowed_company_ids': [self.company_a.id],
        })
        self.env.user.group_ids |= self.env.ref('account.group_account_invoice')
        self.purchase_journal = self.env['account.journal'].create({
            'name': 'Cashier batch purchases %s' % uuid4().hex,
            'code': 'CBP%s' % uuid4().hex[:7].upper(),
            'type': 'purchase',
            'company_id': self.company_a.id,
        })
        self.owner = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Cashier batch owner',
            'login': 'cashier-batch-owner-%s' % uuid4().hex,
            'company_id': self.company_a.id,
            'company_ids': [Command.set(self.company_a.ids)],
            'baseer_access_role': 'owner',
        })
        self.expense_account = self.env['account.account'].create({
            'name': 'Cashier batch expense',
            'code': 'CBA%s' % uuid4().hex[:7].upper(),
            'account_type': 'expense',
            'company_ids': [Command.set(self.company_a.ids)],
        })
        self.purchase_journal.write({'default_account_id': self.expense_account.id, 'sequence': -100})
        self.payable_account = self.env['account.account'].create({
            'name': 'Cashier batch payable',
            'code': 'CBL%s' % uuid4().hex[:7].upper(),
            'account_type': 'liability_payable',
            'company_ids': [Command.set(self.company_a.ids)],
        })
        self.category = self.env['product.category'].create({
            'name': 'Cashier batch category %s' % uuid4().hex,
        })
        self.service = self.env['product.product'].create({
            'name': 'Cashier batch service %s' % uuid4().hex,
            'type': 'service',
            'categ_id': self.category.id,
            'property_account_expense_id': self.expense_account.id,
        })
        self.mapping_a = self.env['baseer.purchase.category.map'].create({
            'company_id': self.company_a.id,
            'category_id': self.category.id,
            'product_id': self.service.id,
        })
        self.supplier = self.env['res.partner'].create({
            'name': 'Cashier batch supplier %s' % uuid4().hex,
            'supplier_rank': 1,
            'property_account_payable_id': self.payable_account.id,
        })
        spend_plan = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        if spend_plan:
            analytic = self.env['account.analytic.account'].create({
                'name': 'Cashier batch native spend', 'plan_id': spend_plan.id,
                'company_id': self.company_a.id,
            })
            self.env['account.analytic.distribution.model'].create({
                'partner_id': self.supplier.id, 'company_id': self.company_a.id,
                'analytic_distribution': {str(analytic.id): 100},
            })

    def _cashier(self, company_ids=None):
        company_ids = company_ids or self.company_a
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Cashier batch %s' % uuid4().hex,
            'login': 'cashier-batch-%s' % uuid4().hex,
            'company_id': self.company_a.id,
            'company_ids': [Command.set(company_ids.ids)],
            'baseer_access_role': 'cashier',
        })

    def _draft_batch(self, cashier, company=None):
        company = company or self.company_a
        return self.env['baseer.purchase.batch'].with_user(cashier).with_context(
            allowed_company_ids=[company.id],
        ).create({
            'company_id': company.id,
            'line_ids': [Command.create({
                'partner_id': self.supplier.id,
                'supplier_ref': 'CBA-%s' % uuid4().hex,
                'entry_type': 'purchase',
                'gross_amount': 40,
                'is_credit': True,
            })],
        })

    def _enable_self_approval(self, company=None, enabled=True):
        company = company or self.company_a
        company.with_user(self.owner).write({
            'cashier_purchase_batch_approval_enabled': enabled,
        })

    def _assert_no_batch_documents(self, batch):
        batch.invalidate_recordset(['state', 'approved_by_id', 'line_ids'])
        self.assertEqual(batch.state, 'draft')
        self.assertFalse(batch.line_ids.move_id)
        self.assertFalse(self.env['baseer.purchase.batch.cashier.approval.audit'].sudo().search([
            ('batch_id', '=', batch.id),
        ]))

    def test_cbpa_t01_default_is_accountant_approval_and_policy_write_is_owner_only(self):
        cashier = self._cashier()
        batch = self._draft_batch(cashier)
        accountant = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Cashier batch accountant',
            'login': 'cashier-batch-accountant-%s' % uuid4().hex,
            'company_id': self.company_a.id,
            'company_ids': [Command.set(self.company_a.ids)],
            'baseer_access_role': 'accountant',
        })

        self.assertFalse(self.company_a.cashier_purchase_batch_approval_enabled)
        self.assertFalse(cashier.has_group('account.group_account_invoice'))
        self.assertFalse(
            self.env['baseer.purchase.batch.cashier.approval.audit'].with_user(
                accountant,
            ).check_access_rights('read', raise_exception=False),
        )
        with self.assertRaises(AccessError):
            self.company_a.with_user(cashier).write({
                'cashier_purchase_batch_approval_enabled': True,
            })
        with self.assertRaises(AccessError):
            batch.with_user(cashier).action_approve()
        self._assert_no_batch_documents(batch)

    def test_cbpa_t02_enabled_cashier_approves_only_own_active_company_batch_without_bill_access(self):
        cashier = self._cashier()
        batch = self._draft_batch(cashier)
        self._enable_self_approval()

        result = batch.with_user(cashier).action_approve()
        self.assertEqual(result, {'type': 'ir.actions.client', 'tag': 'reload'})
        batch.invalidate_recordset(['state', 'approved_by_id', 'line_ids'])
        self.assertEqual(batch.state, 'approved')
        self.assertEqual(batch.approved_by_id, cashier)
        self.assertTrue(batch.line_ids.move_id)
        self.assertFalse(batch.sudo().line_ids.move_id.invoice_line_ids.product_id)
        self.assertEqual(batch.sudo().line_ids.move_id.invoice_line_ids.account_id, self.expense_account)
        self.assertFalse(cashier.has_group('account.group_account_invoice'))
        with self.assertRaises(AccessError):
            batch.with_user(cashier).action_view_bills()
        audit = self.env['baseer.purchase.batch.cashier.approval.audit'].sudo().search([
            ('batch_id', '=', batch.id),
        ])
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.actor_user_id, cashier)
        self.assertEqual(audit.company_id, self.company_a)
        self.assertTrue(audit.execution_user_id)
        with self.assertRaises(AccessError):
            batch.with_user(cashier).action_approve()

    def test_cbpa_t03_rechecks_creator_company_and_policy_inside_the_locked_flow(self):
        cashier = self._cashier()
        other_cashier = self._cashier()
        other_batch = self._draft_batch(other_cashier)
        self._enable_self_approval()
        with self.assertRaises(AccessError):
            other_batch.with_user(cashier).action_approve()
        self._assert_no_batch_documents(other_batch)

        company_b = self.env['res.company'].create({
            'name': 'Cashier batch approval B',
            'currency_id': self.company_a.currency_id.id,
        })
        self.env.user.company_ids |= company_b
        self.owner.company_ids |= company_b
        cashier.company_ids |= company_b
        expense_b = self.env['account.account'].with_context(
            allowed_company_ids=[company_b.id],
        ).create({
            'name': 'Cashier batch expense B',
            'code': 'CBB%s' % uuid4().hex[:7].upper(),
            'account_type': 'expense',
            'company_ids': [Command.set(company_b.ids)],
        })
        category_b = self.env['product.category'].with_context(
            allowed_company_ids=[company_b.id],
        ).create({'name': 'Cashier batch category B %s' % uuid4().hex})
        service_b = self.env['product.product'].with_context(
            allowed_company_ids=[company_b.id],
        ).create({
            'name': 'Cashier batch service B %s' % uuid4().hex,
            'type': 'service',
            'categ_id': category_b.id,
            'property_account_expense_id': expense_b.id,
        })
        mapping_b = self.env['baseer.purchase.category.map'].with_context(
            allowed_company_ids=[company_b.id],
        ).create({
            'company_id': company_b.id,
            'category_id': category_b.id,
            'product_id': service_b.id,
        })
        batch_b = self._draft_batch(cashier, company_b)
        with self.assertRaises(AccessError):
            batch_b.with_user(cashier).with_context(
                allowed_company_ids=[self.company_a.id, company_b.id],
            ).action_approve()
        self._assert_no_batch_documents(batch_b)

        batch = self._draft_batch(cashier)
        actor = self.env['res.users'].sudo().browse(cashier.id)

        def disable_policy_then_check(locked_batch):
            locked_batch.company_id.with_user(self.owner).write({
                'cashier_purchase_batch_approval_enabled': False,
            })
            locked_batch._check_cashier_approval_policy_at_lock(actor)

        with self.assertRaises(AccessError):
            batch.sudo()._approve_as_actor(actor, disable_policy_then_check)
        self._assert_no_batch_documents(batch)

    def test_cbpa_t04_outer_savepoint_rolls_back_approval_and_audit_together(self):
        cashier = self._cashier()
        batch = self._draft_batch(cashier)
        self._enable_self_approval()
        actor = self.env['res.users'].sudo().browse(cashier.id)

        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                batch.sudo()._approve_as_actor(
                    actor,
                    lambda locked_batch: locked_batch._check_cashier_approval_policy_at_lock(actor),
                )
                self.env['baseer.purchase.batch.cashier.approval.audit'].sudo().create({
                    'batch_id': batch.id,
                    'company_id': self.company_a.id,
                    'actor_user_id': actor.id,
                    'execution_user_id': batch.sudo().env.user.id,
                    'approved_at': fields.Datetime.now(),
                })
                raise UserError('Forced outer approval rollback')
        self._assert_no_batch_documents(batch)
