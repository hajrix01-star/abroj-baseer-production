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

    def test_native_paid_order_invoice_after_closing_and_refund_keep_one_origin(self):
        """Exercise native POS posting, not hand-made paid/invoiced order links."""
        company = self.env.company
        accounts = self.env['account.account'].with_company(company)

        def account(code, kind, reconcile=False):
            return accounts.create({
                'code': code, 'name': f'POS origin {code}',
                'account_type': kind, 'reconcile': reconcile,
                'company_ids': [Command.set(company.ids)],
            })

        original_income = account('957101', 'income')
        mapped_income = account('957102', 'income')
        tax_due = account('957103', 'liability_current')
        receivable = account('957104', 'asset_receivable', reconcile=True)
        clearing = account('957105', 'asset_current')
        partner = self.env['res.partner'].with_company(company).create({
            'name': 'POS origin source partner',
            'property_account_receivable_id': receivable.id,
        })
        tax = self.env['account.tax'].with_company(company).create({
            'name': 'POS origin VAT 15%', 'company_id': company.id,
            'type_tax_use': 'sale', 'amount_type': 'percent', 'amount': 15,
        })
        tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).write({'account_id': tax_due.id})
        fiscal_position = self.env['account.fiscal.position'].with_company(company).create({
            'name': 'POS source income remap', 'company_id': company.id,
            'account_ids': [Command.create({
                'account_src_id': original_income.id,
                'account_dest_id': mapped_income.id,
            })],
        })
        product = self.env['product.product'].with_company(company).create({
            'name': 'POS source taxed service', 'type': 'service',
            'available_in_pos': True, 'list_price': 100,
            'property_account_income_id': original_income.id,
            'taxes_id': [Command.set(tax.ids)],
        })
        sale_journal = self.env['account.journal'].with_company(company).create({
            'name': 'POS source sales', 'code': 'OPS',
            'type': 'sale', 'company_id': company.id,
        })
        bank_journal = self.env['account.journal'].with_company(company).search([
            ('company_id', '=', company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.assertTrue(bank_journal)
        method = self.env['pos.payment.method'].with_company(company).create({
            'name': 'POS source bank', 'company_id': company.id,
            'journal_id': bank_journal.id,
            'receivable_account_id': receivable.id,
            'outstanding_account_id': clearing.id,
        })
        config = self.env['pos.config'].with_company(company).create({
            'name': 'POS origin source', 'company_id': company.id,
            'journal_id': sale_journal.id,
            'invoice_journal_id': sale_journal.id,
            'payment_method_ids': [Command.set(method.ids)],
        })
        config.open_ui()
        session = config.current_session_id
        session.set_opening_control(0, 'POS origin source test')
        payload = {
            'uuid': str(uuid4()), 'session_id': session.id,
            'company_id': company.id, 'partner_id': partner.id,
            'fiscal_position_id': fiscal_position.id,
            'state': 'paid', 'source': 'pos', 'to_invoice': False,
            'amount_total': 115, 'amount_tax': 15,
            'amount_paid': 115, 'amount_return': 0,
            'lines': [Command.create({
                'product_id': product.id, 'uuid': str(uuid4()),
                'qty': 1, 'price_unit': 100,
                'price_subtotal': 100, 'price_subtotal_incl': 115,
                'tax_ids': [Command.set(tax.ids)],
                'full_product_name': product.display_name,
            })],
            'payment_ids': [Command.create({
                'payment_method_id': method.id, 'amount': 115,
                'payment_date': fields.Datetime.now(),
            })],
        }
        order_id = self.env['pos.order'].with_company(company)._process_order(payload, False)
        order = self.env['pos.order'].browse(order_id)
        self.assertEqual(order.state, 'paid')
        self.assertEqual(order.source, 'pos')
        self.assertFalse(order.account_move)
        self.assertEqual(self._money(order.amount_total), Decimal('115.00'))
        self.assertEqual(self._money(order.amount_tax), Decimal('15.00'))
        self.assertEqual(self._money(order.lines.price_subtotal), Decimal('100.00'))
        self.assertEqual(self._money(order.lines.price_subtotal_incl), Decimal('115.00'))
        self.assertEqual(order.lines._prepare_base_line_for_taxes_computation()['account_id'],
                         mapped_income)

        session.action_pos_session_closing_control()
        self.assertEqual(session.state, 'closed')
        self.assertEqual(session.move_id.state, 'posted')
        session_income = sum(session.move_id.line_ids.filtered(
            lambda line: line.account_id == mapped_income,
        ).mapped('balance'))
        self.assertEqual(self._money(session_income), Decimal('-100.00'))
        self.assertFalse(session.move_id.line_ids.filtered(
            lambda line: line.account_id == original_income,
        ))

        order.with_context(generate_pdf=False).action_pos_order_invoice()
        invoice = order.account_move
        self.assertEqual((invoice.state, invoice.move_type), ('posted', 'out_invoice'))
        self.assertIn(order, invoice.pos_order_ids)
        self.assertEqual(self._money(invoice.amount_total), Decimal('115.00'))
        invoice_income = sum(invoice.line_ids.filtered(
            lambda line: line.account_id == mapped_income,
        ).mapped('balance'))
        reversal = self.env['account.move'].search([
            ('reversed_pos_order_id', '=', order.id), ('state', '=', 'posted'),
        ])
        self.assertEqual(len(reversal), 1)
        reversal_income = sum(reversal.line_ids.filtered(
            lambda line: line.account_id == mapped_income,
        ).mapped('balance'))
        self.assertEqual(self._money(invoice_income), Decimal('-100.00'))
        self.assertEqual(self._money(reversal_income), Decimal('100.00'))
        self.assertEqual(self._money(session_income + invoice_income + reversal_income),
                         Decimal('-100.00'))
        # Session move + linked invoice are not two sales. The native reversal
        # removes the first origin from the ledger when invoicing happens later.

        config.open_ui()
        refund_session = config.current_session_id
        refund_session.set_opening_control(0, 'POS origin refund test')
        refund = order._refund()
        self.assertEqual(refund.state, 'draft')
        self.assertEqual(refund.lines.refunded_orderline_id, order.lines)
        self.assertEqual(self._money(refund.lines.price_subtotal_incl),
                         Decimal('-115.00'))
        self.assertEqual(self._money(refund.amount_total), Decimal('-115.00'))
        self.env['pos.payment'].with_company(company).create({
            'pos_order_id': refund.id, 'payment_method_id': method.id,
            'amount': -115,
        })
        refund._compute_prices()
        refund.action_pos_order_paid()
        refund.with_context(generate_pdf=False).action_pos_order_invoice()
        self.assertTrue(refund.is_refund)
        self.assertEqual((refund.account_move.state, refund.account_move.move_type),
                         ('posted', 'out_refund'))
        self.assertIn(refund, refund.account_move.pos_order_ids)
        self.assertEqual(self._money(refund.account_move.amount_total),
                         Decimal('115.00'))
        self.assertNotEqual(refund.id, order.id)
        self.assertEqual(len(order | refund), 2)

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
