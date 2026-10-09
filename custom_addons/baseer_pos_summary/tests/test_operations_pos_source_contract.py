"""Native POS source evidence for the proposed gross operations report.

These fixtures characterize original orders, not an operations calculator.
The Baseer summary test deliberately uses its real approval/correction path;
it does not fabricate protected order, accounting or correction links.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

from odoo import Command, fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOperationsPosNativeSourceContract(TransactionCase):

    @staticmethod
    def _money(value):
        return Decimal(str(value)).quantize(Decimal('0.01'))

    def test_ordinary_order_line_gross_refund_and_status_are_distinct(self):
        company = self.env.company
        tax = self.env['account.tax'].with_company(company).create({
            'name': 'Operations native POS VAT 15%',
            'company_id': company.id, 'type_tax_use': 'sale',
            'amount_type': 'percent', 'amount': 15,
        })
        product = self.env['product.product'].with_company(company).create({
            'name': 'Operations native POS service', 'type': 'service',
            'available_in_pos': True, 'list_price': 100,
            'taxes_id': [Command.set(tax.ids)],
        })
        config = self.env['pos.config'].with_company(company).create({
            'name': 'Operations ordinary POS', 'company_id': company.id,
        })
        session = self.env['pos.session'].with_company(company).create({
            'config_id': config.id,
        })

        def order(state, qty, is_refund=False):
            result = self.env['pos.order'].with_company(company).create({
                'session_id': session.id, 'company_id': company.id,
                'state': state, 'source': 'pos', 'is_refund': is_refund,
                'to_invoice': False,
                'amount_total': 0, 'amount_tax': 0,
                'amount_paid': 0, 'amount_return': 0,
                'lines': [Command.create({
                    'product_id': product.id,
                    'tax_ids': [Command.set(tax.ids)],
                    'uuid': str(uuid4()), 'qty': qty, 'price_unit': 100,
                    'price_subtotal': 100 * qty,
                    'price_subtotal_incl': 115 * qty,
                    'full_product_name': product.display_name,
                })],
            })
            result._compute_prices()
            return result

        draft = order('draft', 1)
        paid = order('paid', 1)
        done = order('done', 1)
        cancelled = order('cancel', 1)
        refund = order('done', -1, is_refund=True)
        for candidate in (draft, paid, done, cancelled):
            self.assertEqual(self._money(candidate.lines.price_subtotal),
                             Decimal('100.00'))
            self.assertEqual(self._money(candidate.lines.price_subtotal_incl),
                             Decimal('115.00'))
            self.assertEqual(self._money(candidate.amount_tax), Decimal('15.00'))
            self.assertEqual(self._money(candidate.amount_total), Decimal('115.00'))
            self.assertEqual(candidate.source, 'pos')
            self.assertEqual(candidate.session_id, session)
            self.assertFalse(candidate.account_move)
        self.assertEqual(self._money(refund.lines.price_subtotal_incl),
                         Decimal('-115.00'))
        self.assertEqual(self._money(refund.amount_tax), Decimal('-15.00'))
        self.assertEqual(self._money(refund.amount_total), Decimal('-115.00'))
        self.assertTrue(refund.is_refund)
        self.assertEqual({row.id for row in (draft | paid | done | cancelled | refund)
                          if row.state in ('paid', 'done')},
                         {paid.id, done.id, refund.id})
        # The same amount on a draft or cancelled order is not a second sale;
        # source state and original order ID are both required.

    def test_approved_summary_uses_business_day_one_order_and_correction_links(self):
        # Reuse the existing onboarding path, which creates a Saudi/SAR chart,
        # a dedicated summary register and a separate platform clearing method.
        company = self.env['res.company'].create({
            'name': 'Operations POS summary source company',
        })
        wizard_action = company.action_baseer_open_onboarding()
        wizard = self.env[wizard_action['res_model']].browse(wizard_action['res_id'])
        wizard.write({'sales_mode': 'summary', 'setup_summary_jahez': True})
        wizard.action_apply_selected()
        scoped = self.env['baseer.pos.summary'].with_context(
            allowed_company_ids=[company.id],
        ).with_company(company)
        config = scoped.env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', True),
        ], limit=1)
        self.assertTrue(config)
        platform = config.payment_method_ids.filtered(
            lambda method: method.baseer_category_id.kind == 'platform',
        )
        self.assertEqual(len(platform), 1)
        self.assertEqual(platform.journal_id.type, 'bank')
        # Odoo labels a method with a bank journal as ``bank`` even when
        # Baseer routes it to a deferred platform receivable.  Native
        # ``pay_later`` cannot be inferred from this allocation.
        self.assertEqual(platform.type, 'bank')
        self.assertEqual(platform.outstanding_account_id.account_type,
                         'asset_current')
        business_day = fields.Date.context_today(scoped) - timedelta(days=1)
        summary = scoped.create({
            'company_id': company.id, 'config_id': config.id,
            'business_date': business_day, 'period_scope': 'all',
            'day_schedule': 'all', 'customer_count': 1,
            'allocation_ids': [Command.create({
                'payment_method_id': platform.id, 'amount': 115,
            })],
        })
        self.assertEqual(summary.state, 'draft')
        self.assertFalse(summary.order_id)
        summary.action_approve()
        order, session = summary.order_id, summary.session_id
        self.assertEqual(summary.state, 'approved')
        self.assertTrue(order and session)
        self.assertEqual(session.order_ids, order)
        self.assertEqual((order.baseer_summary_id, session.baseer_summary_id),
                         (summary, summary))
        self.assertEqual((order.source, order.state, order.to_invoice),
                         ('baseer_summary', 'done', False))
        self.assertFalse(order.account_move)
        self.assertEqual(order.date_order, datetime.combine(business_day, time(9, 0)))
        self.assertEqual(session.move_id.state, 'posted')
        self.assertEqual(session.move_id.date, business_day)
        self.assertEqual(self._money(order.lines.price_subtotal_incl),
                         Decimal('115.00'))
        self.assertEqual(self._money(order.amount_total), Decimal('115.00'))
        self.assertEqual(self._money(summary.amount_gross), Decimal('115.00'))
        self.assertEqual(summary.allocation_ids.pos_payment_id.pos_order_id, order)
        self.assertEqual(summary.allocation_ids.payment_method_id, platform)
        # A platform allocation has an outstanding current-asset clearing
        # account.  Its bank-typed POS payment alone does not prove receipt.
        self.assertNotEqual(platform.outstanding_account_id.account_type,
                            'asset_cash')

        original_order_id = order.id
        original_session_move_id = session.move_id.id
        summary._correct_summary('Operations source correction')
        replacement = summary.replacement_id
        self.assertEqual(summary.state, 'cancelled')
        self.assertTrue(replacement)
        self.assertEqual(replacement.replaces_id, summary)
        self.assertEqual(replacement.state, 'draft')
        self.assertEqual(replacement.business_date, business_day)
        self.assertFalse(replacement.order_id)
        self.assertEqual(summary.order_id.id, original_order_id)
        self.assertEqual(summary.order_id.state, 'cancel')
        self.assertEqual(summary.session_id.move_id.id, original_session_move_id)
        self.assertEqual(summary.reversal_move_ids.reversed_entry_id,
                         summary._native_moves())
        self.assertTrue(all(move.state == 'posted'
                            for move in summary.reversal_move_ids))
