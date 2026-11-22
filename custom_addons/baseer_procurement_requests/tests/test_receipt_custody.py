from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from .test_representative_petty_cash import RepresentativePettyCashCase


@tagged('post_install', '-at_install')
class ReceiptCustodyCase(TransactionCase):
    """Rollback-only checks for the separated receipt and custody workflows."""
    def setUp(self):
        super().setUp()
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_accountant')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_manager')
        self.env.user.group_ids |= self.env.ref('base.group_erp_manager')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_cashier')
        self.company = self.env.company
        self.company.currency_id = self.env.ref('base.SAR')
        self.company.currency_id.active = True
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
            'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set([self.bank_journal.id])],
        })

    def _request(self):
        request = RepresentativePettyCashCase._request(self)
        # Simulate a request created before the list-only field existed.
        self.env.cr.execute('UPDATE baseer_procurement_request SET list_only=false WHERE id=%s', [request.id])
        request.invalidate_recordset(['list_only'])
        return request
    _sent_request = RepresentativePettyCashCase._sent_request

    def _cashier(self):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Receipt custody branch manager', 'login': 'receipt-custody-%s' % uuid4(),
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('baseer_procurement_requests.group_procurement_cashier').id])],
        })

    def _rows(self, request):
        return [{'line_id': request.line_ids.id, 'actual_qty': '3.00', 'actual_price': '4.00'}]

    def test_receipt_without_funding_or_config(self):
        request = self._sent_request().with_user(self._cashier())
        self.company.sudo().write({
            'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.clear()],
        })
        models = ('account.move', 'baseer.procurement.representative.advance')
        before = {name: self.env[name].sudo().search_count([]) for name in models}
        self.assertEqual(request.prepare_receipt_custody(request.id), {'required': False})
        request.confirm_actual_from_catalog(request.id, self._rows(request))
        request.invalidate_recordset()
        self.assertEqual(request.state, 'purchased')
        self.assertFalse(request.receipt_custody_confirmed)
        for name in models:
            self.assertEqual(self.env[name].sudo().search_count([]), before[name])
        request.action_confirm_actual_purchase()
        for name in models:
            self.assertEqual(self.env[name].sudo().search_count([]), before[name])

    def test_old_funding_payload_rejected_without_effect(self):
        request = self._sent_request()
        before = {name: self.env[name].sudo().search_count([]) for name in (
            'account.move', 'baseer.procurement.representative.advance')}
        for payload in ({'snapshot': 'old'}, {'amount': '27.50', 'payment_journal_id': self.bank_journal.id}):
            with self.assertRaisesRegex(ValidationError, 'Reload the page'):
                request.confirm_actual_from_catalog(request.id, self._rows(request), payload)
        self.assertEqual(request.state, 'sent')
        for name, count in before.items():
            self.assertEqual(self.env[name].sudo().search_count([]), count)

    def test_historical_funding_remains_linked_after_receipt(self):
        request = self._sent_request()
        model = self.env['baseer.procurement.representative.advance']
        token = str(uuid4())
        funding_id = model.submit_funding(request.id, self.bank_journal.id, self.representative.id,
                                         31, token, fields.Date.context_today(self))
        funding = model.browse(funding_id)
        move_id = funding.move_id.id
        request.confirm_actual_from_catalog(request.id, self._rows(request))
        self.assertEqual(request._receipt_custody_fundings().ids, [funding_id])
        self.assertEqual(funding.move_id.id, move_id)
        self.assertEqual(model.submit_funding(request.id, self.bank_journal.id, self.representative.id,
                                              31, token, fields.Date.context_today(self)), funding_id)
        self.assertEqual(request.action_open_receipt_custody()['params']['representative_id'], self.representative.id)

    def test_historical_marker_is_still_protected(self):
        request = self._sent_request()
        for proof in (True, 'proof', {}):
            with self.assertRaises(AccessError):
                request.sudo().with_context(_baseer_receipt_custody_proof=proof).write({'receipt_custody_confirmed': True})
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.request'].create({'receipt_custody_confirmed': False})
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.request'].with_context(default_receipt_custody_confirmed=True).create({})

    def test_receipt_context_rejects_unauthorized_or_other_company(self):
        request = self._sent_request()
        outsider = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Unprivileged internal user', 'login': 'receipt-outsider-%s' % uuid4(),
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            request.with_user(outsider).prepare_receipt_custody(request.id)
        other = self.env['res.company'].create({'name': 'Receipt other company'})
        with self.assertRaises(AccessError):
            request.with_context(allowed_company_ids=[other.id, self.company.id]).prepare_receipt_custody(request.id)
