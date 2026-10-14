"""Characterize native payment evidence before building a cash-events report.

This does not calculate receipts or payments.  In particular, a POS payment
allocated to an applications platform is not itself proof of bank collection.
"""

from datetime import timedelta
from decimal import Decimal

from odoo import Command, fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReceiptsPaymentsSourceContract(TransactionCase):

    def test_pos_cash_platform_allocation_and_later_bank_collection(self):
        company = self.env['res.company'].create({
            'name': 'Receipts source contract company',
        })
        action = company.action_baseer_open_onboarding()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.write({
            'sales_mode': 'summary',
            'setup_summary_cash': True,
            'setup_summary_jahez': True,
        })
        wizard.action_apply_selected()
        summaries = self.env['baseer.pos.summary'].with_context(
            allowed_company_ids=[company.id],
        ).with_company(company)
        config = summaries.env['pos.config'].search([
            ('company_id', '=', company.id),
            ('baseer_summary_only', '=', True),
        ], limit=1)
        self.assertTrue(config)
        cash = config.payment_method_ids.filtered(
            lambda method: method.baseer_category_id.kind == 'cash',
        )
        platform = config.payment_method_ids.filtered(
            lambda method: method.baseer_category_id.kind == 'platform',
        )
        self.assertEqual((len(cash), len(platform)), (1, 1))
        self.assertEqual(cash.journal_id.type, 'cash')
        self.assertEqual(platform.journal_id.type, 'bank')
        self.assertEqual(platform.type, 'bank')
        self.assertEqual(cash.journal_id.default_account_id.account_type,
                         'asset_cash')
        self.assertEqual(platform.outstanding_account_id.account_type,
                         'asset_current')

        business_day = fields.Date.context_today(summaries) - timedelta(days=1)
        summary = summaries.create({
            'company_id': company.id,
            'config_id': config.id,
            'business_date': business_day,
            'period_scope': 'all',
            'day_schedule': 'all',
            'customer_count': 1,
            'allocation_ids': [
                Command.create({'payment_method_id': cash.id, 'amount': 40}),
                Command.create({'payment_method_id': platform.id, 'amount': 75}),
            ],
        })
        summary.action_approve()
        order, session = summary.order_id, summary.session_id
        self.assertEqual((summary.state, order.state, session.state),
                         ('approved', 'done', 'closed'))
        self.assertEqual(session.order_ids, order)
        cash_allocation = summary.allocation_ids.filtered(
            lambda line: line.payment_method_id == cash,
        )
        platform_allocation = summary.allocation_ids.filtered(
            lambda line: line.payment_method_id == platform,
        )
        cash_payment = cash_allocation.pos_payment_id
        platform_payment = platform_allocation.pos_payment_id
        self.assertTrue(cash_payment and platform_payment)
        self.assertEqual(cash_payment.pos_order_id, order)
        self.assertEqual(platform_payment.pos_order_id, order)
        self.assertEqual(Decimal(str(cash_payment.amount)), Decimal('40.00'))
        self.assertEqual(Decimal(str(platform_payment.amount)), Decimal('75.00'))
        self.assertEqual(Decimal(str(order.amount_total)), Decimal('115.00'))
        self.assertNotEqual(cash_payment.id, platform_payment.id)
        # The platform allocation is represented by a current-asset claim,
        # not by an additional cash/bank liquidity receipt on the sale day.
        platform_claim = summary._native_moves().line_ids.filtered(
            lambda line: line.account_id == platform.outstanding_account_id
            and line.balance > 0,
        )
        claim_amount = sum((Decimal(str(line.balance))
                            for line in platform_claim), Decimal('0'))
        self.assertEqual(claim_amount, Decimal('75.00'))

        settlement_day = business_day + timedelta(days=1)
        collection = summaries.env['account.bank.statement.line'].create({
            'journal_id': platform.journal_id.id,
            'date': settlement_day,
            'payment_ref': 'External platform collection',
            'amount': 75,
            'counterpart_account_id': platform.outstanding_account_id.id,
        })
        self.assertEqual(collection.move_id.state, 'posted')
        self.assertEqual(collection.move_id.statement_line_id, collection)
        self.assertEqual(collection.date, settlement_day)
        bank_lines = collection.move_id.line_ids.filtered(
            lambda line: line.account_id == platform.journal_id.default_account_id,
        )
        clearing_lines = collection.move_id.line_ids.filtered(
            lambda line: line.account_id == platform.outstanding_account_id,
        )
        self.assertEqual(len(bank_lines), 1)
        self.assertEqual(len(clearing_lines), 1)
        self.assertEqual(Decimal(str(bank_lines.balance)), Decimal('75.00'))
        self.assertEqual(Decimal(str(clearing_lines.balance)), Decimal('-75.00'))
        self.assertEqual(session.order_ids, order)
        self.assertNotIn(collection.move_id, summary._native_moves())
        # The later bank entry offsets the original platform claim on the same
        # clearing account; the POS allocation itself was not a bank receipt.
        self.assertEqual(platform_claim.account_id, clearing_lines.account_id)
        self.assertEqual(claim_amount + Decimal(str(clearing_lines.balance)),
                         Decimal('0.00'))
