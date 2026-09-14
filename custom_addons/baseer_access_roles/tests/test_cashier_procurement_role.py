from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class CashierProcurementRoleCase(TransactionCase):
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
