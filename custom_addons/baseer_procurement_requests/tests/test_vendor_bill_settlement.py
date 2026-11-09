import importlib.util
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.vendor_bill_settlement import AGENT_TAG


@tagged('post_install', '-at_install')
class VendorBillCustodySettlementCase(TransactionCase):
    """Existing vendor bills settle against PCUST or RPC without new funding."""

    def setUp(self):
        super().setUp()
        if self._testMethodName == 'test_zz_concurrent_same_reference_settles_once':
            # The committed race uses its own cursor. Do not lock the admin
            # user from this test transaction.
            return
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_accountant')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_manager')
        self.env.user.group_ids |= self.env.ref('account.group_account_invoice')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_cashier')
        sar = self.env.ref('base.SAR', raise_if_not_found=False)
        if sar and not sar.active:
            sar.active = True
        self.company = self.env['res.company'].create({
            'name': 'VBS %s' % uuid4().hex[:8],
            'currency_id': (sar or self.env.company.currency_id).id,
        })
        self.env.user.company_ids |= self.company
        self.env = self.env(context={**self.env.context, 'allowed_company_ids': [self.company.id]})
        self.company = self.company.with_env(self.env)
        Account = self.env['account.account']
        self.custody_account = Account.create({
            'name': 'VBS petty cash', 'code': 'VBS001', 'account_type': 'asset_receivable',
            'reconcile': True, 'company_ids': [Command.set(self.company.ids)],
        })
        self.rpc_account = Account.create({
            'name': 'VBS representative petty cash', 'code': 'VBS002', 'account_type': 'asset_current',
            'reconcile': True, 'company_ids': [Command.set(self.company.ids)],
        })
        self.cash_account = Account.create({
            'name': 'VBS cash', 'code': 'VBS003', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.bank_account = Account.create({
            'name': 'VBS bank', 'code': 'VBS005', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.expense = Account.create({
            'name': 'VBS expense', 'code': 'VBS004', 'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.payable = Account.create({
            'name': 'VBS payable', 'code': 'VBS210', 'account_type': 'liability_payable',
            'reconcile': True, 'company_ids': [Command.set(self.company.ids)],
        })
        Journal = self.env['account.journal']
        self.custody_journal = Journal.create({
            'name': 'VBS petty cash', 'code': 'VPCU', 'type': 'general', 'company_id': self.company.id,
        })
        self.rpc_journal = Journal.create({
            'name': 'VBS representative petty cash', 'code': 'VRPC', 'type': 'general', 'company_id': self.company.id,
        })
        self.cash_journal = Journal.create({
            'name': 'VBS cash', 'code': 'VCSH', 'type': 'cash', 'company_id': self.company.id,
            'default_account_id': self.cash_account.id,
        })
        self.bank_journal = Journal.create({
            'name': 'VBS bank', 'code': 'VBNK', 'type': 'bank', 'company_id': self.company.id,
            'default_account_id': self.bank_account.id,
        })
        self.purchase_journal = Journal.create({
            'name': 'VBS purchases', 'code': 'VPUR', 'type': 'purchase', 'company_id': self.company.id,
            'default_account_id': self.expense.id,
        })
        self.representative = self.env['res.partner'].with_company(self.company).create({
            'name': 'VBS representative', 'company_id': self.company.id, 'is_purchase_representative': True,
        })
        self.supplier = self.env['res.partner'].with_company(self.company).create({
            'name': 'VBS supplier', 'company_id': self.company.id, 'supplier_rank': 1,
        })
        self.supplier.with_company(self.company).property_account_payable_id = self.payable
        self.warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.warehouse:
            self.warehouse = self.env['stock.warehouse'].create({
                'name': 'VBS warehouse', 'code': 'V%s' % str(self.company.id)[-3:], 'company_id': self.company.id,
            })
        category = self.env['product.category'].create({'name': 'VBS category'})
        product = self.env['product.product'].create({
            'name': 'VBS product', 'company_id': self.company.id, 'categ_id': category.id,
        })
        self.option = self.env['baseer.procurement.purchase.option'].create({
            'name': 'Unit', 'company_id': self.company.id, 'product_id': product.id, 'uom_id': product.uom_id.id,
        })
        self.today = fields.Date.context_today(self)

    def _configure_pcust(self):
        self.company.write({
            'baseer_procurement_custody_account_id': self.custody_account.id,
            'baseer_procurement_custody_journal_id': self.custody_journal.id,
        })

    def _configure_rpc(self):
        self.company.write({
            'baseer_procurement_representative_petty_cash_account_id': self.rpc_account.id,
            'baseer_procurement_representative_petty_cash_journal_id': self.rpc_journal.id,
            'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set(self.bank_journal.ids)],
        })

    def _fund_pcust(self, amount, representative=None, pool=False):
        self._configure_pcust()
        representative = representative or self.representative
        values = {'company_id': self.company.id}
        if pool:
            values['is_company_pool'] = True
        else:
            values['representative_partner_id'] = representative.id
        custody = self.env['baseer.procurement.custody'].create(values)
        event_values = {
            'custody_id': custody.id, 'event_type': 'funding', 'amount': amount,
            'cash_journal_id': self.cash_journal.id, 'reference': 'VBS funding %s' % amount,
            'representative_partner_id': representative.id,
        }
        if pool:
            # Final receipt confirmation now requires an existing representative
            # advance. The pool funding below is still the petty-cash source.
            self._configure_rpc()
            request = self._request(representative)
            request.action_mark_sent()
            self.env['baseer.procurement.representative.advance'].submit_funding(
                request.id, self.bank_journal.id, representative.id, amount, str(uuid4()), self.today,
            )
            request.line_ids.manager_received_qty = 1
            request.action_confirm_manager_receipt()
            request.line_ids.write({'actual_qty': 1, 'actual_price': amount})
            request.action_confirm_actual_purchase()
            event_values['procurement_request_id'] = request.id
        event = self.env['baseer.procurement.custody.event'].create(event_values)
        event.action_post()
        return custody, event

    def _request(self, representative=None):
        return self.env['baseer.procurement.request'].create({
            'company_id': self.company.id,
            'warehouse_id': self.warehouse.id,
            'representative_partner_id': (representative or self.representative).id,
            'line_ids': [Command.create({
                'option_id': self.option.id, 'requested_qty': 1, 'requested_price': 1,
            })],
        })

    def _fund_rpc(self, amount, movement_date=None, representative=None):
        self._configure_rpc()
        representative = representative or self.representative
        request = self._request(representative)
        request.action_mark_sent()
        advance_id = self.env['baseer.procurement.representative.advance'].submit_funding(
            request.id, self.bank_journal.id, representative.id, amount, str(uuid4()),
            movement_date or self.today,
        )
        return self.env['baseer.procurement.representative.advance'].browse(advance_id)

    def _bill(self, amount, ref='', currency=None, move_type='in_invoice', post=False):
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': move_type,
            'company_id': self.company.id,
            'partner_id': self.supplier.id,
            'journal_id': self.purchase_journal.id,
            'invoice_date': self.today,
            'ref': ref or 'VBS-%s' % uuid4().hex[:8],
            'currency_id': (currency or self.company.currency_id).id,
            'invoice_line_ids': [Command.create({
                'name': 'Existing supplier invoice',
                'quantity': 1,
                'price_unit': amount,
                'account_id': self.expense.id,
                'tax_ids': [Command.clear()],
            })],
        })
        if post:
            bill.action_post()
        return bill

    def _model(self, user=None):
        model = self.env['baseer.procurement.vendor.bill.settlement'].with_company(self.company)
        if user:
            model = model.with_user(user)
        return model

    def _settle(self, bill, key=None, representative=None, user=None, custody=None, agent=False):
        representative = representative or self.representative
        key = key or 'vbs-%s' % uuid4().hex
        model = self._model(user)
        if agent:
            return model.settle_agent_vendor_bill(bill.id, representative.id, key)
        if custody:
            return model.action_settle_existing_vendor_bill(bill.id, representative.id, key, custody.id)
        return model.action_settle_existing_vendor_bill(bill.id, representative.id, key)

    def _user(self, login, groups):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': '%s-%s' % (login, uuid4().hex[:8]),
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set(groups)],
        })

    def _counts(self):
        company = self.company.id
        def count(model, domain):
            return self.env[model].search_count(domain) if model in self.env else 0
        return {
            'bills': count('account.move', [('company_id', '=', company), ('move_type', '=', 'in_invoice')]),
            'payments': count('account.payment', [('company_id', '=', company)]),
            'orders': count('purchase.order', [('company_id', '=', company)]),
            'pickings': count('stock.picking', [('company_id', '=', company)]),
            'events': count('baseer.procurement.custody.event', [('company_id', '=', company)]),
            'advances': count('baseer.procurement.representative.advance', [('company_id', '=', company)]),
        }

    def test_pcust_settles_posted_and_draft_bills_without_new_documents(self):
        custody, funding = self._fund_pcust(100)
        funding_snapshot = [(line.id, line.debit, line.credit, line.account_id.id) for line in funding.move_id.line_ids]
        posted = self._bill(40, post=True)
        expense_line = posted.invoice_line_ids
        expense_debit = expense_line.debit
        counts = self._counts()
        preflight = self._model().preflight_existing_vendor_bill(posted.id, self.representative.id, 'pcust-posted')
        self.assertFalse(preflight['already_settled'])
        self.assertEqual(preflight['mechanism'], 'pcust')
        self.assertEqual(preflight['custody_remaining'], 100)
        self.assertEqual(preflight['custody_remaining_after'], 60)
        self.assertEqual(self._counts(), counts)
        result = self._settle(posted, key='pcust-posted')
        self.assertEqual(result['mechanism'], 'pcust')
        self.assertEqual(result['bill_state'], 'posted')
        self.assertEqual(result['bill_payment_state'], 'paid')
        self.assertEqual(result['reconciliation_state'], 'reconciled')
        self.assertFalse(result['already_settled'])
        self.assertEqual(result['account_id'], self.custody_account.id)
        self.assertEqual(result['journal_id'], self.custody_journal.id)
        self.assertEqual(result['custody_remaining'], 60)
        self.assertEqual(custody.balance, 60)
        self.assertEqual(custody.settled_amount, 40)
        move = self.env['account.move'].browse(result['settlement_move_id'])
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.journal_id, self.custody_journal)
        self.assertFalse(move.line_ids.filtered(lambda line: line.account_id.account_type in ('asset_cash', 'expense')))
        credit = move.line_ids.filtered(lambda line: line.credit)
        debit = move.line_ids.filtered(lambda line: line.debit)
        self.assertEqual(credit.partner_id, self.representative)
        self.assertEqual(credit.account_id, self.custody_account)
        self.assertEqual(credit.baseer_procurement_custody_id, custody)
        self.assertEqual(debit.partner_id, self.supplier)
        self.assertEqual(debit.account_id.account_type, 'liability_payable')
        self.assertEqual(expense_line.debit, expense_debit)
        self.assertEqual(funding.move_id.state, 'posted')
        self.assertEqual(
            [(line.id, line.debit, line.credit, line.account_id.id) for line in funding.move_id.line_ids],
            funding_snapshot,
        )
        after = self._counts()
        self.assertEqual(after['bills'], counts['bills'])
        self.assertEqual(after['payments'], counts['payments'])
        self.assertEqual(after['orders'], counts['orders'])
        self.assertEqual(after['events'], counts['events'])
        self.assertEqual(after['advances'], counts['advances'])
        monthly = self.env['baseer.procurement.custody.monthly.statement'].search([('custody_id', '=', custody.id)])
        self.assertEqual(monthly.settled_amount, 40)
        self.assertEqual(monthly.closing_balance, 60)
        settlement = self.env['baseer.procurement.custody.settlement'].browse(result['custody_settlement_id'])
        with self.assertRaises(UserError):
            settlement.action_reverse()
        draft = self._bill(15)
        self.assertEqual(draft.state, 'draft')
        draft_result = self._settle(draft, key='pcust-draft')
        draft.invalidate_recordset()
        self.assertEqual(draft.state, 'posted')
        self.assertEqual(draft.payment_state, 'paid')
        self.assertEqual(draft_result['custody_remaining'], 45)
        self.assertEqual(custody.balance, 45)
        self.assertEqual(self._counts()['bills'], counts['bills'] + 1)

    def test_preflight_failure_and_mid_settlement_failure_leave_the_draft_unposted(self):
        custody, _funding = self._fund_pcust(10)
        bill = self._bill(25)
        with self.assertRaises(UserError):
            self._model().preflight_existing_vendor_bill(bill.id, self.representative.id, 'too-large')
        bill.invalidate_recordset()
        self.assertEqual(bill.state, 'draft')
        self.assertEqual(custody.balance, 10)
        with self.assertRaises(UserError):
            self._settle(bill, key='too-large')
        bill.invalidate_recordset()
        self.assertEqual(bill.state, 'draft')
        self.assertEqual(custody.balance, 10)
        self.assertFalse(self.env['account.move'].search([
            ('company_id', '=', self.company.id), ('journal_id', '=', self.custody_journal.id), ('move_type', '=', 'entry'),
            ('ref', 'ilike', 'Existing'),
        ]).filtered(lambda move: move != _funding.move_id))
        payable_bill = self._bill(5)
        with patch.object(type(self._model()), '_store', side_effect=UserError('forced settlement failure')):
            with self.assertRaises(UserError):
                self._settle(payable_bill, key='rollback')
        payable_bill.invalidate_recordset()
        custody.invalidate_recordset(['balance', 'settled_amount'])
        self.assertEqual(payable_bill.state, 'draft')
        self.assertEqual(custody.balance, 10)
        self.assertFalse(self._model().search([('vendor_bill_id', '=', payable_bill.id)]))

    def test_rpc_splits_one_bill_across_existing_advances(self):
        first = self._fund_rpc(40, self.today - timedelta(days=2))
        second = self._fund_rpc(25, self.today - timedelta(days=1))
        Advance = self.env['baseer.procurement.representative.advance']
        self.assertEqual(Advance._baseer_representative_available_amount(self.company, self.representative), Decimal('65.00'))
        bill = self._bill(50, post=True)
        counts = self._counts()
        result = self._settle(bill, key='rpc-split')
        self.assertEqual(result['mechanism'], 'rpc')
        self.assertEqual(result['bill_payment_state'], 'paid')
        self.assertEqual(result['reconciliation_state'], 'reconciled')
        self.assertEqual(result['account_id'], self.rpc_account.id)
        self.assertEqual(result['journal_id'], self.rpc_journal.id)
        self.assertEqual(result['advance_allocations'], [
            {'advance_id': first.id, 'amount': 40.0},
            {'advance_id': second.id, 'amount': 10.0},
        ])
        self.assertEqual(result['custody_remaining'], 15)
        first.invalidate_recordset(['remaining_amount', 'settled_amount'])
        second.invalidate_recordset(['remaining_amount', 'settled_amount'])
        self.assertEqual(first.remaining_amount, 0)
        self.assertEqual(second.remaining_amount, 15)
        self.assertEqual(
            Advance._baseer_representative_available_amount(self.company, self.representative),
            Decimal('15.00'),
        )
        move = self.env['account.move'].browse(result['settlement_move_id'])
        self.assertFalse(move.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_cash'))
        self.assertEqual(len(move.line_ids.filtered(lambda line: line.credit)), 2)
        self.assertTrue(all(line.partner_id == self.representative for line in move.line_ids.filtered('credit')))
        self.assertFalse(self.env['baseer.procurement.custody.settlement'].search([('vendor_bill_id', '=', bill.id)]))
        after = self._counts()
        self.assertEqual(after['advances'], counts['advances'])
        self.assertEqual(after['bills'], counts['bills'])
        self.assertEqual(after['payments'], counts['payments'])
        self.assertEqual(after['orders'], counts['orders'])
        dashboard = Advance.dashboard_data(self.representative.id)
        self.assertEqual(dashboard['summary']['available'], 15)
        open_ids = {row['id']: row['remaining'] for row in dashboard['open_fundings']}
        self.assertNotIn(first.id, open_ids)
        self.assertEqual(open_ids[second.id], 15)
        partial = self._bill(10, post=True)
        partial_result = self._settle(partial, key='rpc-partial')
        self.assertEqual(partial_result['advance_allocations'], [{'advance_id': second.id, 'amount': 10.0}])
        self.assertEqual(second.remaining_amount, 5)
        self.assertEqual(Advance._baseer_representative_available_amount(self.company, self.representative), Decimal('5.00'))

    def test_mechanism_selection_never_mixes_pcust_and_rpc(self):
        custody, _funding = self._fund_pcust(20)
        advance = self._fund_rpc(80)
        bill = self._bill(15, post=True)
        result = self._settle(bill, key='pcust-wins')
        self.assertEqual(result['mechanism'], 'pcust')
        self.assertEqual(custody.balance, 5)
        self.assertEqual(advance.remaining_amount, 80)
        short = self._bill(10)
        with self.assertRaises(UserError):
            self._settle(short, key='no-top-up')
        short.invalidate_recordset()
        self.assertEqual(short.state, 'draft')
        self.assertEqual(custody.balance, 5)
        self.assertEqual(advance.remaining_amount, 80)
        empty = self.env['baseer.procurement.custody'].create({
            'company_id': self.company.id, 'representative_partner_id': self.representative.id,
        })
        # A second open custody for the same representative is ambiguous.
        with self.assertRaises(UserError):
            self._settle(self._bill(1), key='ambiguous')
        empty.action_close()
        other = self.env['res.partner'].with_company(self.company).create({
            'name': 'VBS other representative', 'company_id': self.company.id, 'is_purchase_representative': True,
        })
        other_custody, _other_funding = self._fund_pcust(30, representative=other)
        # The original representative still has an open custody, so RPC is not used.
        self.assertEqual(custody.representative_partner_id, self.representative)
        self.assertEqual(other_custody.balance, 30)
        closed_company = self.env['res.company'].create({
            'name': 'VBS closed %s' % uuid4().hex[:6], 'currency_id': self.company.currency_id.id,
        })
        self.env.user.company_ids |= closed_company
        third = self.env['res.partner'].with_company(self.company).create({
            'name': 'VBS third representative', 'company_id': self.company.id, 'is_purchase_representative': True,
        })
        unfunded = self.env['baseer.procurement.custody'].create({
            'company_id': self.company.id, 'representative_partner_id': third.id,
        })
        unfunded.action_close()
        self._configure_rpc()
        request = self._request(third)
        request.action_mark_sent()
        advance_id = self.env['baseer.procurement.representative.advance'].submit_funding(
            request.id, self.bank_journal.id, third.id, 30, str(uuid4()), self.today,
        )
        third_bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice', 'company_id': self.company.id, 'partner_id': self.supplier.id,
            'journal_id': self.purchase_journal.id, 'invoice_date': self.today, 'ref': 'VBS-third',
            'currency_id': self.company.currency_id.id,
            'invoice_line_ids': [Command.create({
                'name': 'Third invoice', 'quantity': 1, 'price_unit': 12, 'account_id': self.expense.id,
                'tax_ids': [Command.clear()],
            })],
        })
        third_result = self._settle(third_bill, key='closed-uses-rpc', representative=third)
        self.assertEqual(third_result['mechanism'], 'rpc')
        self.assertEqual(unfunded.state, 'closed')
        self.assertEqual(
            self.env['baseer.procurement.representative.advance'].browse(advance_id).remaining_amount, 18,
        )
        self.company.write({
            'baseer_procurement_custody_account_id': False,
            'baseer_procurement_custody_journal_id': False,
            'baseer_procurement_representative_petty_cash_account_id': False,
            'baseer_procurement_representative_petty_cash_journal_id': False,
        })
        bare = self.env['res.partner'].with_company(self.company).create({
            'name': 'VBS bare representative', 'company_id': self.company.id, 'is_purchase_representative': True,
        })
        with self.assertRaises(UserError):
            self._settle(self._bill(5), key='missing-mapping', representative=bare)
        self._configure_rpc()
        with self.assertRaises(UserError):
            self._settle(self._bill(5), key='no-open-funding', representative=bare)
        self.assertFalse(closed_company.baseer_procurement_custody_account_id)

    def test_company_pool_settles_the_representative_balance(self):
        custody, funding = self._fund_pcust(80, pool=True)
        self.assertTrue(custody.is_company_pool)
        bill = self._bill(30, post=True)
        result = self._settle(bill, key='pool')
        self.assertEqual(result['mechanism'], 'pcust')
        self.assertEqual(result['custody_id'], custody.id)
        self.assertEqual(custody._representative_balance(self.representative), 50)
        self.assertEqual(funding.move_id.state, 'posted')
        self.assertEqual(funding.amount, 80)

    def test_ineligible_bills_representatives_and_companies_are_rejected(self):
        custody, _funding = self._fund_pcust(50)
        cancelled = self._bill(10)
        cancelled.button_cancel()
        refund = self._bill(10, move_type='in_refund')
        zero = self._bill(0)
        foreign = self.env['res.currency'].with_context(active_test=False).search([
            ('id', '!=', self.company.currency_id.id),
        ], limit=1)
        self.assertTrue(foreign)
        foreign.active = True
        foreign_bill = self._bill(10, currency=foreign)
        paid = self._bill(10, post=True)
        payable = paid.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        payment = self.env['account.move'].create({
            'move_type': 'entry', 'company_id': self.company.id, 'journal_id': self.cash_journal.id,
            'date': self.today,
            'line_ids': [
                Command.create({'name': 'prepaid', 'account_id': payable.account_id.id, 'partner_id': self.supplier.id, 'debit': 10}),
                Command.create({'name': 'prepaid', 'account_id': self.cash_account.id, 'credit': 10}),
            ],
        })
        payment.action_post()
        (payable | payment.line_ids.filtered(lambda line: line.account_id == payable.account_id)).reconcile()
        partial = self._bill(10, post=True)
        partial_payable = partial.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        partial_payment = self.env['account.move'].create({
            'move_type': 'entry', 'company_id': self.company.id, 'journal_id': self.cash_journal.id,
            'date': self.today,
            'line_ids': [
                Command.create({'name': 'partial', 'account_id': partial_payable.account_id.id, 'partner_id': self.supplier.id, 'debit': 4}),
                Command.create({'name': 'partial', 'account_id': self.cash_account.id, 'credit': 4}),
            ],
        })
        partial_payment.action_post()
        (partial_payable | partial_payment.line_ids.filtered(lambda line: line.account_id == partial_payable.account_id)).reconcile()
        other_company = self.env['res.company'].create({
            'name': 'VBS other %s' % uuid4().hex[:6], 'currency_id': self.company.currency_id.id,
        })
        self.env.user.company_ids |= other_company
        home_bill = self._bill(10)
        inactive = self.env['res.partner'].with_company(self.company).create({
            'name': 'VBS inactive', 'company_id': self.company.id, 'is_purchase_representative': True,
        })
        inactive.active = False
        plain = self.env['res.partner'].create({'name': 'VBS plain contact', 'company_id': self.company.id})
        cases = [
            (cancelled, self.representative, ValidationError),
            (refund, self.representative, ValidationError),
            (zero, self.representative, ValidationError),
            (foreign_bill, self.representative, ValidationError),
            (paid, self.representative, UserError),
            (partial, self.representative, UserError),
        ]
        for bill, representative, error in cases:
            with self.subTest(bill=bill.ref, error=error.__name__):
                with self.assertRaises(error):
                    self._settle(bill, representative=representative)
        with self.assertRaises(ValidationError):
            self._settle(self._bill(5), representative=inactive)
        with self.assertRaises(ValidationError):
            self._settle(self._bill(5), representative=plain)
        other_model = self.env['baseer.procurement.vendor.bill.settlement'].with_company(other_company).with_context(
            allowed_company_ids=[other_company.id],
        )
        with self.assertRaises(ValidationError):
            other_model.action_settle_existing_vendor_bill(home_bill.id, self.representative.id, 'other-company')
        negative = self._bill(-5)
        with self.assertRaises(ValidationError):
            self._settle(negative)
        wrong_custody, _wrong_funding = self._fund_pcust(10, representative=self.env['res.partner'].with_company(self.company).create({
            'name': 'VBS custody owner', 'company_id': self.company.id, 'is_purchase_representative': True,
        }))
        with self.assertRaises(ValidationError):
            self._settle(self._bill(5), custody=wrong_custody)
        self.assertEqual(custody.balance, 50)
        with self.assertRaises(ValidationError):
            self._model().action_settle_existing_vendor_bill(self._bill(5).id, self.representative.id, '')
        with self.assertRaises(ValidationError):
            self._model().action_settle_existing_vendor_bill(self._bill(5).id, self.representative.id, 'x' * 129)

    def test_retry_is_exact_once(self):
        custody, _funding = self._fund_pcust(40)
        bill = self._bill(12, post=True)
        other = self._bill(8, post=True)
        first = self._settle(bill, key='same-key')
        second = self._settle(bill, key='same-key')
        self.assertEqual(second['settlement_id'], first['settlement_id'])
        self.assertEqual(second['settlement_move_id'], first['settlement_move_id'])
        self.assertTrue(second['already_settled'])
        self.assertEqual(custody.balance, 28)
        self.assertEqual(self.env['account.move'].search_count([
            ('company_id', '=', self.company.id), ('id', '=', first['settlement_move_id']),
        ]), 1)
        with self.assertRaises(UserError):
            self._settle(bill, key='different-key')
        with self.assertRaises(UserError):
            self._settle(other, key='same-key')
        self.assertEqual(custody.balance, 28)
        self.assertEqual(other.payment_state, 'not_paid')

    def test_agent_tag_restricts_the_automated_entrypoint_only(self):
        self._fund_pcust(30)
        accountant = self._user('vbs-accountant', [
            self.env.ref('base.group_user').id,
            self.env.ref('baseer_procurement_requests.group_procurement_accountant').id,
            self.env.ref('account.group_account_invoice').id,
        ])
        agent = self._user('vbs-agent', [
            self.env.ref('base.group_user').id,
            self.env.ref('baseer_procurement_requests.group_procurement_invoice_agent').id,
        ])
        self.assertFalse(agent.has_group('baseer_procurement_requests.group_procurement_accountant'))
        self.assertFalse(accountant.has_group('baseer_procurement_requests.group_procurement_invoice_agent'))
        tagged = self._bill(9, ref='Supplier 1 - %s' % AGENT_TAG)
        plain = self._bill(6, ref='Ordinary supplier invoice')
        with self.assertRaises(AccessError):
            self._settle(tagged, user=accountant, agent=True)
        with self.assertRaises(AccessError):
            self._settle(plain, user=agent)
        with self.assertRaises(ValidationError):
            self._settle(plain, user=agent, agent=True, key='agent-plain')
        human = self._settle(plain, user=accountant, key='human-plain')
        self.assertEqual(human['entrypoint'], 'human')
        self.assertFalse(human['agent_tag'])
        self.assertEqual(plain.payment_state, 'paid')
        agent_result = self._settle(tagged, user=agent, agent=True, key='agent-tagged')
        self.assertEqual(agent_result['entrypoint'], 'agent')
        self.assertEqual(agent_result['agent_tag'], AGENT_TAG)
        self.assertEqual(tagged.payment_state, 'paid')
        request = self._request()
        request.action_mark_sent()
        self._configure_rpc()
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.representative.advance'].with_user(agent).submit_funding(
                request.id, self.bank_journal.id, self.representative.id, 5, str(uuid4()), self.today,
            )
        batch = self.env['baseer.purchase.batch'].create({'company_id': self.company.id})
        with self.assertRaises(AccessError):
            batch.with_user(agent).action_approve()
        self.assertEqual(batch.state, 'draft')

    def test_direct_writes_and_upgrade_do_not_create_financial_records(self):
        custody, funding = self._fund_pcust(20)
        bill = self._bill(5)
        before_moves = self.env['account.move'].search_count([])
        before_partners = self.env['res.partner'].search_count([])
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.vendor.bill.settlement'].sudo().create({
                'company_id': self.company.id, 'vendor_bill_id': bill.id,
                'representative_partner_id': self.representative.id, 'mechanism': 'pcust',
                'move_id': funding.move_id.id, 'account_id': self.custody_account.id,
                'journal_id': self.custody_journal.id, 'amount': 5, 'idempotency_key': 'forged',
                'entrypoint': 'human',
            })
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.custody.settlement'].sudo().create({
                'company_id': self.company.id, 'custody_id': custody.id, 'vendor_bill_id': bill.id,
                'move_id': funding.move_id.id, 'amount': 5,
            })
        with self.assertRaises(ValidationError):
            self.env['baseer.procurement.custody.settlement'].sudo().with_context(
                baseer_vendor_bill_settlement_internal=True,
            ).create({
                'company_id': self.company.id, 'custody_id': custody.id,
                'move_id': funding.move_id.id, 'amount': 5,
            })
        migration_path = Path(__file__).resolve().parents[1] / 'migrations' / '19.0.14.0.32' / 'post-migration.py'
        source = migration_path.read_text()
        self.assertNotIn('account.move', source)
        self.assertNotIn('res.partner', source)
        self.assertNotIn('settle_', source)
        spec = importlib.util.spec_from_file_location('vendor_bill_settlement_migration', migration_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.14.0.32')
        self.assertEqual(self.env['account.move'].search_count([]), before_moves)
        self.assertEqual(self.env['res.partner'].search_count([]), before_partners)
        self.assertEqual(bill.state, 'draft')
        self.assertEqual(custody.balance, 20)

    def test_zz_concurrent_same_reference_settles_once(self):
        import logging
        import os
        from odoo import SUPERUSER_ID, api, sql_db
        logger = logging.getLogger(__name__)
        if os.environ.get('BASEER_VENDOR_BILL_SETTLEMENT_CONCURRENCY') != '1':
            logger.info('Vendor-bill settlement race not requested outside disposable CI')
            return
        self.assertEqual(
            self.env.cr.dbname, 'baseer_procurement_route_ci',
            'Committed concurrency fixtures are permitted only in the disposable CI database',
        )
        db = sql_db.db_connect(self.env.cr.dbname)
        owned = uuid4().hex[:10]
        with db.cursor() as setup_cr:
            setup_cr.execute("SET LOCAL lock_timeout = '15s'")
            setup_cr.execute("SET LOCAL statement_timeout = '60s'")
            setup = api.Environment(setup_cr, SUPERUSER_ID, {})
            # Reuse the installed company. Creating another company writes
            # currency rates and commits a report-cache bump that collides
            # with the still-open install transaction.
            company = setup.company
            groups = [setup.ref(name).id for name in (
                'baseer_procurement_requests.group_procurement_accountant',
                'account.group_account_invoice',
            )]
            actor = setup['res.users'].with_context(no_reset_password=True).create({
                'name': 'VBS race %s' % owned, 'login': 'vbs-race-%s' % owned,
                'company_id': company.id, 'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set(groups)],
            })
            env = api.Environment(setup_cr, SUPERUSER_ID, {'allowed_company_ids': [company.id]})
            account = env['account.account']
            suffix = owned[:4].upper()
            custody_account = account.create({
                'name': 'VBS race custody %s' % owned, 'code': 'RC%s' % suffix, 'account_type': 'asset_receivable',
                'reconcile': True, 'company_ids': [Command.set(company.ids)],
            })
            cash_account = account.create({
                'name': 'VBS race cash %s' % owned, 'code': 'RH%s' % suffix, 'account_type': 'asset_cash',
                'company_ids': [Command.set(company.ids)],
            })
            expense = account.create({
                'name': 'VBS race expense %s' % owned, 'code': 'RE%s' % suffix, 'account_type': 'expense',
                'company_ids': [Command.set(company.ids)],
            })
            payable = account.create({
                'name': 'VBS race payable %s' % owned, 'code': 'RP%s' % suffix, 'account_type': 'liability_payable',
                'reconcile': True, 'company_ids': [Command.set(company.ids)],
            })
            journal = env['account.journal']
            custody_journal = journal.create({
                'name': 'VBS race custody %s' % owned, 'code': 'C%s' % suffix, 'type': 'general', 'company_id': company.id,
            })
            cash_journal = journal.create({
                'name': 'VBS race cash %s' % owned, 'code': 'H%s' % suffix, 'type': 'cash', 'company_id': company.id,
                'default_account_id': cash_account.id,
            })
            purchase_journal = journal.create({
                'name': 'VBS race purchases %s' % owned, 'code': 'P%s' % suffix, 'type': 'purchase', 'company_id': company.id,
                'default_account_id': expense.id,
            })
            company.write({
                'baseer_procurement_custody_account_id': custody_account.id,
                'baseer_procurement_custody_journal_id': custody_journal.id,
            })
            representative = env['res.partner'].with_company(company).create({
                'name': 'VBS race representative %s' % owned, 'company_id': company.id,
                'is_purchase_representative': True,
            })
            supplier = env['res.partner'].with_company(company).create({
                'name': 'VBS race supplier %s' % owned, 'company_id': company.id, 'supplier_rank': 1,
            })
            supplier.property_account_payable_id = payable
            custody = env['baseer.procurement.custody'].create({
                'company_id': company.id, 'representative_partner_id': representative.id,
            })
            actor_env = api.Environment(setup_cr, actor.id, {'allowed_company_ids': [company.id]})
            event = actor_env['baseer.procurement.custody.event'].create({
                'custody_id': custody.id, 'event_type': 'funding', 'amount': 100,
                'cash_journal_id': cash_journal.id, 'representative_partner_id': representative.id,
                'reference': 'VBS race funding',
            })
            event.action_post()
            bill = env['account.move'].with_company(company).create({
                'move_type': 'in_invoice', 'company_id': company.id, 'partner_id': supplier.id,
                'journal_id': purchase_journal.id, 'invoice_date': fields.Date.context_today(env['account.move']),
                'ref': 'VBS race %s' % owned, 'currency_id': company.currency_id.id,
                'invoice_line_ids': [Command.create({
                    'name': 'Race invoice', 'quantity': 1, 'price_unit': 40, 'account_id': expense.id,
                    'tax_ids': [Command.clear()],
                })],
            })
            funding_move_id = event.move_id.id
            company_id, actor_id, bill_id, representative_id, custody_id = (
                company.id, actor.id, bill.id, representative.id, custody.id,
            )
            setup_cr.commit()
        key = 'vbs-race-%s' % owned
        results = []

        def settle():
            with db.cursor() as cursor:
                cursor.execute("SET lock_timeout = '15s'")
                cursor.execute("SET statement_timeout = '45s'")
                raced = api.Environment(cursor, actor_id, {'allowed_company_ids': [company_id]})
                result = raced['baseer.procurement.vendor.bill.settlement'].with_company(
                    company_id,
                ).action_settle_existing_vendor_bill(bill_id, representative_id, key)
                results.append(result)
                cursor.commit()

        # Two committed transactions, the second starting only after the first
        # commits. The bill and idempotency locks make an overlapping retry
        # wait and then observe this same settlement instead of posting again.
        settle()
        settle()
        self.assertEqual(len(results), 2)
        self.assertTrue(results[1]['already_settled'])
        self.assertEqual(results[0]['settlement_id'], results[1]['settlement_id'])
        self.assertEqual(results[0]['settlement_move_id'], results[1]['settlement_move_id'])
        with db.cursor() as check_cr:
            check = api.Environment(check_cr, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
            stored = check['baseer.procurement.vendor.bill.settlement'].search([
                ('company_id', '=', company_id), ('idempotency_key', '=', key),
            ])
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored.vendor_bill_id.payment_state, 'paid')
            self.assertEqual(stored.custody_id.balance, 60)
            self.assertEqual(check['account.move'].browse(funding_move_id).state, 'posted')
            self.assertEqual(check['account.move'].search_count([
                ('company_id', '=', company_id), ('journal_id', '=', stored.journal_id.id), ('move_type', '=', 'entry'),
                ('id', '!=', funding_move_id),
            ]), 1)
            self.assertEqual(stored.custody_id.id, custody_id)
        logger.info('VENDOR_BILL_SETTLEMENT_CONCURRENCY_OK %s', owned)
