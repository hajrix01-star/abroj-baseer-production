from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase


class RepresentativePettyCashCase(TransactionCase):
    """Focused accounting and workflow checks for PRA-BUILD-1 only."""

    def setUp(self):
        super().setUp()
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_accountant')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_manager')
        self.company = self.env.company
        self.warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        category = self.env['product.category'].create({'name': 'Representative petty cash test category'})
        product = self.env['product.product'].create({
            'name': 'Representative petty cash test product', 'categ_id': category.id,
            'company_id': self.company.id,
        })
        self.option = self.env['baseer.procurement.purchase.option'].create({
            'name': 'Unit', 'company_id': self.company.id, 'product_id': product.id,
            'uom_id': product.uom_id.id,
        })
        self.representative = self.env['res.partner'].create({
            'name': 'Representative petty cash buyer', 'company_id': self.company.id,
        })
        self.representative.with_company(self.company).write({'is_purchase_representative': True})
        Account = self.env['account.account']
        self.petty_cash_account = Account.create({
            'name': 'Representative petty cash receivable', 'code': 'RPA701',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [Command.set(self.company.ids)],
        })
        cash_account = Account.create({
            'name': 'Representative petty cash bank', 'code': 'RPA702',
            'account_type': 'asset_cash', 'company_ids': [Command.set(self.company.ids)],
        })
        self.general_journal = self.env['account.journal'].create({
            'name': 'Representative petty cash entries', 'code': 'RPAG', 'type': 'general',
            'company_id': self.company.id,
        })
        self.bank_journal = self.env['account.journal'].create({
            'name': 'Representative petty cash bank', 'code': 'RPAB', 'type': 'bank',
            'company_id': self.company.id, 'default_account_id': cash_account.id,
        })
        self.company.write({
            'baseer_procurement_representative_petty_cash_account_id': self.petty_cash_account.id,
            'baseer_procurement_representative_petty_cash_journal_id': self.general_journal.id,
        })

    def _request(self):
        return self.env['baseer.procurement.request'].create({
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'representative_partner_id': self.representative.id,
            'line_ids': [Command.create({
                'option_id': self.option.id, 'requested_qty': 5, 'requested_price': 4,
            })],
        })

    def _sent_request(self):
        request = self._request()
        request.action_mark_sent()
        return request

    def test_funding_posts_once_and_is_immutable(self):
        request = self._sent_request()
        token = str(uuid4())
        Model = self.env['baseer.procurement.representative.advance']
        record_id = Model.submit_funding(request.id, self.bank_journal.id, self.representative.id, 20, token)
        self.assertEqual(record_id, Model.submit_funding(request.id, self.bank_journal.id, self.representative.id, 20, token))
        record = Model.browse(record_id)
        self.assertEqual(record.move_id.state, 'posted')
        self.assertEqual(record.amount, 20)
        line = record.move_id.line_ids.filtered(lambda row: row.account_id == self.petty_cash_account)
        self.assertEqual(line.baseer_representative_petty_cash_id, record)
        self.assertEqual(line.partner_id, self.representative)
        returned_id = Model.submit_return(record.id, self.bank_journal.id, 5, str(uuid4()))
        returned = Model.browse(returned_id)
        self.assertEqual(record.remaining_amount, 15)
        returned_line = returned.move_id.line_ids.filtered(lambda row: row.account_id == self.petty_cash_account)
        self.assertEqual(returned_line.baseer_representative_petty_cash_id, record)
        self.assertTrue(returned_line.matched_debit_ids)
        with self.assertRaises(ValidationError):
            Model.submit_return(record.id, self.bank_journal.id, 16, str(uuid4()))
        with self.assertRaises(UserError):
            record.write({'amount': 10})
        with self.assertRaises(UserError):
            record.move_id.button_draft()

    def test_funding_rejects_draft_request_and_wrong_destination(self):
        request = self._request()
        Model = self.env['baseer.procurement.representative.advance']
        with self.assertRaises(ValidationError):
            Model.submit_funding(request.id, self.bank_journal.id, self.representative.id, 20, str(uuid4()))
        request.action_mark_sent()
        other = self.env['res.partner'].create({'name': 'Other representative', 'company_id': self.company.id})
        other.with_company(self.company).write({'is_purchase_representative': True})
        with self.assertRaises(ValidationError):
            Model.submit_funding(request.id, self.bank_journal.id, other.id, 20, str(uuid4()))

    def test_external_reference_cannot_be_reused_for_a_payment_point(self):
        request = self._sent_request()
        Model = self.env['baseer.procurement.representative.advance']
        Model.submit_funding(
            request.id, self.bank_journal.id, self.representative.id, 20, str(uuid4()), False, 'BANK-REF-1',
        )
        with self.assertRaises(ValidationError):
            Model.submit_funding(
                request.id, self.bank_journal.id, self.representative.id, 20, str(uuid4()), False, 'BANK-REF-1',
            )

    def test_cashier_cannot_record_a_movement(self):
        request = self._sent_request()
        cashier = self.env['res.users'].create({
            'name': 'Representative petty cash cashier', 'login': 'representative-petty-cash-cashier',
            'groups_id': [Command.set([self.env.ref('baseer_procurement_requests.group_procurement_cashier').id])],
        })
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.representative.advance'].with_user(cashier).submit_funding(
                request.id, self.bank_journal.id, self.representative.id, 20, str(uuid4()),
            )
