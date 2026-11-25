"""Synthetic offline acceptance only; never part of the production addon."""
import logging
import os
import base64
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests.common import tagged
from odoo.addons.l10n_sa_edi.tests.common import TestSaEdiCommon
from odoo.addons.baseer_pos_global_discount.tests import test_global_discount as gd_tests

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestNativeDiscountAcceptance(TestSaEdiCommon):
    def _order(self, **kwargs):
        order = gd_tests.TestGlobalDiscount._order(self, **kwargs)
        for base in order._gd_tax_base_lines(order.lines):
            detail = base['tax_details']
            base['record'].write({'price_subtotal': detail['total_excluded_currency'],
                                  'price_subtotal_incl': detail['total_included_currency']})
        return order
    _refund = gd_tests.TestGlobalDiscount._refund
    _combo_order = gd_tests.TestGlobalDiscount._combo_order
    _combo_refund = gd_tests.TestGlobalDiscount._combo_refund

    def setUp(self):
        super().setUp()
        self.env.user.sudo().write({'group_ids': [Command.link(self.env.ref('point_of_sale.group_pos_manager').id)]})
        self.network_deny = patch('requests.sessions.Session.request', side_effect=AssertionError('NETWORK_FORBIDDEN_IN_SYNTHETIC_ACCEPTANCE'))
        self.network_mock = self.network_deny.start()
        self.addCleanup(self.network_deny.stop)
        # Only the outbound EDI worker boundary is paused. Native posting,
        # payment reconciliation, tax allocations and XML are not mocked.
        self.send_pause = patch.object(type(self.env['account.edi.document']), '_process_documents_web_services', return_value=None)
        self.send_pause.start()
        self.addCleanup(self.send_pause.stop)
        self.tax = self.tax_15
        self.tax.price_include_override = 'tax_excluded'
        self.product = self.env['product.product'].create({
            'name': 'Synthetic acceptance service', 'type': 'service',
            'available_in_pos': True, 'list_price': 100,
            'taxes_id': [Command.set(self.tax.ids)],
            'property_account_income_id': self.company_data['default_account_revenue'].id,
        })
        self.config = self.env['pos.config'].create({
            'name': 'Synthetic isolated discount register',
            'invoice_journal_id': self.customer_invoice_journal.id,
            'baseer_zatca_phase2_enabled': True,
            'baseer_global_discount_account_id': self.company_data['default_account_revenue'].id,
        })
        self.config.action_baseer_setup_native_discount()
        self.config.write({'baseer_global_discount_enabled': True, 'baseer_fixed_discount_enabled': True, 'baseer_fixed_discount_allowed': 'managers'})
        self.config.discount_product_id.property_account_income_id = self.company_data['default_account_revenue']
        self.env['pos.session'].create({'config_id': self.config.id, 'state': 'opened'})
        self.payment_method = self.config.payment_method_ids[:1]
        if not self.payment_method:
            self.payment_method = self.env['pos.payment.method'].create({
                'name': 'Synthetic customer account', 'split_transactions': True,
                'receivable_account_id': self.company_data['default_account_receivable'].id,
            })
            self.config.payment_method_ids = [Command.link(self.payment_method.id)]

    def _apply(self, order, value, kind):
        tax = self.env['account.tax']
        bases = order._gd_tax_base_lines(order.lines)
        for base in bases:
            detail = base['tax_details']
            base['record'].write({'price_subtotal': detail['total_excluded_currency'],
                                  'price_subtotal_incl': detail['total_included_currency']})
        for base in tax._prepare_global_discount_lines(bases, order.company_id, kind, float(value)):
            detail = base['tax_details']
            self.env['pos.order.line'].create({
                'order_id': order.id, 'uuid': str(uuid4()),
                'product_id': self.config.discount_product_id.id,
                'qty': base['quantity'], 'price_unit': base['price_unit'],
                'tax_ids': [Command.set(base['tax_ids'].ids)],
                'price_subtotal': detail['total_excluded_currency'],
                'price_subtotal_incl': detail['total_included_currency'],
                'extra_tax_data': tax._export_base_line_extra_tax_data(base),
                'baseer_discount_kind': kind, 'baseer_discount_input': float(value),
                'baseer_discount_approved_by_user_id': self.env.user.id,
            })
        order._compute_prices()
        self._sync_native_draft(order)

    def test_historical_invoice_report_and_refund_guard(self):
        order = self._order()
        order.write({'partner_id': self.partner_sa_simplified.id, 'to_invoice': True})
        order.write({'state': 'paid'})
        source = order.lines.ensure_one()
        legacy_product = self.config.discount_product_id.copy({'name': 'Historical allowance'})
        allowance = self.env['pos.order.line'].sudo().create({
            'order_id': order.id, 'product_id': legacy_product.id, 'qty': 1,
            'price_unit': -10, 'price_subtotal': -10, 'price_subtotal_incl': -11.5,
            'tax_ids': [Command.set(self.tax.ids)], 'baseer_global_discount_line': True,
            'baseer_global_discount_source_id': source.id,
        })
        order.sudo().write({'baseer_global_discount_locked': True,
                            'baseer_global_discount_kind': 'fixed',
                            'baseer_global_discount_value': 11.5,
                            'baseer_global_discount_gross': 11.5})
        order._compute_prices()
        order._generate_pos_order_invoice()
        self.assertEqual(order.account_move.state, 'posted')
        self.assertAlmostEqual(order.account_move.amount_total, 103.5, places=2)
        self.env.flush_all()
        rows = self.env['report.pos.order'].search([('order_id', '=', order.id)])
        self.assertEqual(rows.ids, source.ids)
        self.assertAlmostEqual(sum(rows.mapped('baseer_invoice_discount')), 10)
        self.assertEqual(allowance.baseer_global_discount_source_id, source)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._refund(order, 1)

    def _sale(self, kind='fixed', value='20', price=100, qty=1):
        order = self._order(price=price, qty=qty)
        order.write({'partner_id': self.partner_sa_simplified.id, 'to_invoice': True})
        self._apply(order, value, kind)
        return order

    def _pay_actual(self, order):
        self.env['pos.make.payment'].with_context(
            active_id=order.id, active_ids=order.ids, generate_pdf=False,
        ).create({'payment_method_id': self.payment_method.id, 'amount': order.amount_total}).check()
        self.assertEqual(order.state, 'done')
        move = order.account_move
        self.assertTrue(move)
        self.assertEqual(move.state, 'posted')
        self.assertAlmostEqual(sum(move.line_ids.mapped('balance')), 0, places=2)
        self.assertAlmostEqual(move.amount_total, abs(order.amount_total), places=2)
        self.assertAlmostEqual(move.amount_tax, abs(order.amount_tax), places=2)
        income = move.line_ids.filtered(lambda line: line.account_id.account_type in ('income', 'income_other'))
        self.assertAlmostEqual(-sum(income.mapped('balance')),
                               order.amount_total - order.amount_tax, places=2)
        self.assertTrue(move.edi_document_ids.filtered(lambda d: d.edi_format_id.code == 'sa_zatca'))
        self.network_mock.assert_not_called()
        return move

    def _xml(self, order, move):
        move._l10n_sa_generate_unsigned_data()
        xml = self.env['account.edi.format']._l10n_sa_generate_zatca_template(move)
        self.assertIsInstance(xml, str, str(xml))
        root = etree.fromstring(xml.encode())

        def amount(path):
            values = root.xpath(path)
            self.assertEqual(len(values), 1, path)
            return Decimal(values[0])

        self.assertEqual(amount("/*/*[local-name()='LegalMonetaryTotal']/*[local-name()='TaxInclusiveAmount']/text()"), Decimal(str(move.amount_total)).quantize(Decimal('.01')))
        for tax_total in root.xpath("/*/*[local-name()='TaxTotal']/*[local-name()='TaxAmount']/text()"):
            self.assertEqual(Decimal(tax_total), Decimal(str(move.amount_tax)).quantize(Decimal('.01')))
        allowances = root.xpath("/*/*[local-name()='AllowanceCharge']")
        self.assertTrue(allowances)
        expected_base = abs(sum(move.invoice_line_ids.filtered(lambda l: l.price_subtotal < 0).mapped('price_subtotal')))
        xml_base = sum(Decimal(a.xpath("./*[local-name()='Amount']/text()")[0]) for a in allowances)
        self.assertEqual(xml_base, Decimal(str(round(expected_base, 2))).quantize(Decimal('.01')))
        for a in allowances:
            self.assertEqual(a.xpath("./*[local-name()='ChargeIndicator']/text()"), ['false'])
            self.assertEqual(a.xpath("./*[local-name()='AllowanceChargeReasonCode']/text()"), ['95'])
            self.assertEqual(len(a.xpath("./*[local-name()='TaxCategory']")), 1)
        if move.move_type == 'out_refund':
            self.assertEqual(root.xpath("/*/*[local-name()='InvoiceTypeCode']/text()"), ['381'])
            self.assertTrue(root.xpath("/*/*[local-name()='BillingReference']"))
            self.assertEqual(move.reversed_entry_id, order.refunded_order_id.account_move)
        qr = base64.b64decode(move.l10n_sa_qr_code_str)
        qr_tags = {}
        cursor = 0
        while cursor < len(qr):
            tag, size = qr[cursor], qr[cursor + 1]
            cursor += 2
            qr_tags[tag] = qr[cursor:cursor + size]
            cursor += size
        self.assertEqual(Decimal(qr_tags[4].decode()), Decimal(str(move.amount_total)).quantize(Decimal('.01')))
        self.assertEqual(Decimal(qr_tags[5].decode()), Decimal(str(move.amount_tax)).quantize(Decimal('.01')))
        self.assertEqual(set(qr_tags), set(range(1, 10)))
        self.network_mock.assert_not_called()
        evidence = Path(os.environ.get('BASEER_ACCEPTANCE_EVIDENCE_DIR', '/var/lib/odoo/acceptance-evidence'))
        evidence.mkdir(parents=True, exist_ok=True)
        filename = self._testMethodName + '-' + move.move_type + '-' + str(move.id)
        (evidence / (filename + '.xml')).write_text(xml)
        (evidence / (filename + '.json')).write_text(json.dumps({
            'synthetic_offline_fixture': True, 'authority_accepted': False,
            'case': self._testMethodName, 'move_type': move.move_type,
            'gross': str(move.amount_total), 'tax': str(move.amount_tax),
            'state': move.state, 'balanced': abs(sum(move.line_ids.mapped('balance'))) < .005,
            'credit_reference_matches_original': bool(move.reversed_entry_id == order.refunded_order_id.account_move) if move.move_type == 'out_refund' else None,
            'allowance_count': len(allowances), 'qr_tags': sorted(qr_tags),
            'network_request_count': self.network_mock.call_count,
            'xml_sha256': hashlib.sha256(xml.encode()).hexdigest(),
        }, indent=2) + '\n')
        _logger.info('GD_NATIVE_XML_PASS type=%s gross=%.2f tax=%.2f allowances=%d balanced=True qr9=True network_calls=0', move.move_type, move.amount_total, move.amount_tax, len(allowances))
        return root

    def _refund_actual(self, order, qty):
        source = order.lines.filtered(lambda line: line.product_id != self.config.discount_product_id).ensure_one()
        refund = self._native_share_refund(order, [(source, qty)])
        refund.write({'partner_id': order.partner_id.id, 'to_invoice': True})
        move = self._pay_actual(refund)
        self._xml(refund, move)
        return refund

    def test_native_percent_invoice_and_full_credit(self):
        sale = self._sale('percent', '10')
        move = self._pay_actual(sale)
        self.assertAlmostEqual(move.amount_total, 103.50, places=2)
        self.assertAlmostEqual(move.amount_tax, 13.50, places=2)
        self._xml(sale, move)
        refund = self._refund_actual(sale, 1)
        self.assertAlmostEqual(refund.amount_total, -103.50, places=2)

    def test_native_fixed_invoice_and_full_credit(self):
        sale = self._sale('fixed', '20')
        move = self._pay_actual(sale)
        self.assertAlmostEqual(move.amount_total, 95, places=2)
        self.assertAlmostEqual(move.amount_tax, 12.39, places=2)
        self._xml(sale, move)
        refund = self._refund_actual(sale, 1)
        self.assertAlmostEqual(refund.amount_total, -95, places=2)

    def test_native_partial_last_cent_reconciles(self):
        sale = self._sale('fixed', '0.97', price=1, qty=3)
        move = self._pay_actual(sale)
        self._xml(sale, move)
        refunds = self.env['pos.order']
        for _ in range(3):
            refunds |= self._refund_actual(sale, 1)
        self.assertAlmostEqual(sum(refunds.mapped('amount_total')), -sale.amount_total, places=2)
        self.assertAlmostEqual(sum(refunds.mapped('amount_tax')), -sale.amount_tax, places=2)
        self.assertAlmostEqual(sum(refunds.lines.mapped('baseer_discount_share_incl')), .97, places=2)

    def test_native_mixed_15_zero_categories(self):
        zero = self.tax.copy({'name': 'Synthetic explicit zero', 'amount': 0, 'l10n_sa_exemption_reason_code': 'VATEX-SA-32'})
        sale = self._order()
        sale.write({'partner_id': self.partner_sa_simplified.id, 'to_invoice': True})
        self.env['pos.order.line'].create({
            'order_id': sale.id, 'product_id': self.product.id, 'qty': 1, 'price_unit': 100,
            'price_subtotal': 100, 'price_subtotal_incl': 100, 'tax_ids': [Command.set(zero.ids)],
        })
        sale._compute_prices()
        self._apply(sale, '20', 'fixed')
        move = self._pay_actual(sale)
        root = self._xml(sale, move)
        self.assertAlmostEqual(move.amount_total, 195, places=2)
        self.assertEqual(set(root.xpath("/*/*[local-name()='AllowanceCharge']/*[local-name()='TaxCategory']/*[local-name()='Percent']/text()")), {'15.0', '0.0'})

    def test_native_combo_fixed_invoice_and_full_group_credit(self):
        sale, parent = self._combo_order(ordinary=True)
        sale.write({'partner_id': self.partner_sa_simplified.id, 'to_invoice': True})
        self._apply(sale, '20', 'fixed')
        move = self._pay_actual(sale)
        self.assertAlmostEqual(move.amount_total, 152.50, places=2)
        self.assertAlmostEqual(move.amount_tax, 19.89, places=2)
        self.assertEqual(len(move.invoice_line_ids.filtered(lambda line: line.display_type == 'line_section')), 1)
        self._xml(sale, move)
        refund = self._native_share_refund(sale, [(line, line.qty) for line in sale.lines if line.product_id != self.config.discount_product_id and line != parent])
        refund.write({'partner_id': sale.partner_id.id, 'to_invoice': True})
        credit = self._pay_actual(refund)
        self._xml(refund, credit)
        self.assertAlmostEqual(refund.amount_total, -sale.amount_total, places=2)
        self.assertAlmostEqual(refund.amount_tax, -sale.amount_tax, places=2)

    def test_native_combo_percentage_mixed_tax_invoice_and_credit(self):
        zero = self.tax.copy({'name': 'Synthetic combo explicit zero', 'amount': 0,
                              'l10n_sa_exemption_reason_code': 'VATEX-SA-32'})
        sale, parent = self._combo_order(ordinary=True, child_b_tax=zero)
        sale.write({'partner_id': self.partner_sa_simplified.id, 'to_invoice': True})
        self._apply(sale, '10', 'percent')
        move = self._pay_actual(sale)
        self.assertAlmostEqual(move.amount_total, 149.85, places=2)
        self.assertAlmostEqual(move.amount_tax, 14.85, places=2)
        root = self._xml(sale, move)
        self.assertEqual(set(root.xpath("/*/*[local-name()='AllowanceCharge']/*[local-name()='TaxCategory']/*[local-name()='Percent']/text()")), {'15.0', '0.0'})
        refund = self._native_share_refund(sale, [(line, line.qty) for line in sale.lines if line.product_id != self.config.discount_product_id and line != parent])
        refund.write({'partner_id': sale.partner_id.id, 'to_invoice': True})
        self._xml(refund, self._pay_actual(refund))
        self.assertAlmostEqual(refund.amount_total, -149.85, places=2)

    def test_native_combo_repeated_partial_group_credits_reconcile(self):
        sale, parent = self._combo_order(parent_qty=3)
        sale.write({'partner_id': self.partner_sa_simplified.id, 'to_invoice': True})
        self._apply(sale, '0.97', 'fixed')
        self._xml(sale, self._pay_actual(sale))
        # Return the sold group even after a catalog choice is retired.
        parent.product_id.combo_ids = parent.product_id.combo_ids[:1]
        refunds = self.env['pos.order']
        for _index in range(3):
            refund = self._native_share_refund(sale, [(line, line.qty / 3) for line in parent.combo_line_ids])
            refund.write({'partner_id': sale.partner_id.id, 'to_invoice': True})
            self._xml(refund, self._pay_actual(refund))
            refunds |= refund
        self.assertAlmostEqual(sum(refunds.mapped('amount_total')), -sale.amount_total, places=2)
        self.assertAlmostEqual(sum(refunds.mapped('amount_tax')), -sale.amount_tax, places=2)
        self.assertAlmostEqual(sum(refunds.lines.mapped('baseer_discount_share_incl')), .97, places=2)

    def _sync_native_draft(self, order):
        """Send the same line fields as the POS, including manual tax data."""
        payload = {
            'uuid': order.uuid, 'session_id': order.session_id.id,
            'company_id': order.company_id.id, 'user_id': self.env.uid,
            'partner_id': self.partner_sa_simplified.id, 'state': 'draft',
            'is_refund': order.is_refund, 'to_invoice': True,
            'l10n_sa_reason': order.l10n_sa_reason,
            'date_order': fields.Datetime.now(),
            'amount_total': order.amount_total, 'amount_tax': order.amount_tax,
            'amount_paid': 0, 'amount_return': 0, 'payment_ids': [],
            'lines': [Command.update(line.id, {
                'uuid': line.uuid, 'product_id': line.product_id.id, 'qty': line.qty,
                'price_unit': line.price_unit, 'discount': line.discount,
                'tax_ids': line.tax_ids.ids, 'price_subtotal': line.price_subtotal,
                'price_subtotal_incl': line.price_subtotal_incl,
                'extra_tax_data': line.extra_tax_data,
                'refunded_orderline_id': line.refunded_orderline_id.id or False,
                'baseer_discount_kind': line.baseer_discount_kind,
                'baseer_discount_input': line.baseer_discount_input,
                'baseer_discount_approved_by_user_id': line.baseer_discount_approved_by_user_id.id or False,
                'baseer_discount_share_excl': line.baseer_discount_share_excl,
                'baseer_discount_share_incl': line.baseer_discount_share_incl,
            }) for line in order.lines],
        }
        self.env['pos.order'].with_context(generate_pdf=False).sync_from_ui([payload])
        return order

    def _native_fixed_mixed_sale(self):
        self.config.action_baseer_setup_native_discount()
        self.config.write({'baseer_fixed_discount_enabled': True, 'baseer_fixed_discount_allowed': 'managers'})
        zero = self.tax.copy({'name': 'Native acceptance zero', 'amount': 0,
                              'l10n_sa_exemption_reason_code': 'VATEX-SA-32'})
        sale = self._order(price=100, qty=3)
        sale.write({'partner_id': self.partner_sa_simplified.id, 'to_invoice': True})
        self.env['pos.order.line'].create({
            'order_id': sale.id, 'uuid': str(uuid4()), 'product_id': self.product.id,
            'qty': 1, 'price_unit': 100, 'price_subtotal': 100,
            'price_subtotal_incl': 100, 'tax_ids': [Command.set(zero.ids)],
        })
        sale._compute_prices()
        tax_model = self.env['account.tax']
        bases = sale._gd_tax_base_lines(sale.lines)
        for base in tax_model._prepare_global_discount_lines(bases, sale.company_id, 'fixed', 44.5):
            detail = base['tax_details']
            self.env['pos.order.line'].create({
                'order_id': sale.id, 'uuid': str(uuid4()), 'product_id': self.config.discount_product_id.id,
                'qty': base['quantity'], 'price_unit': base['price_unit'],
                'tax_ids': [Command.set(base['tax_ids'].ids)],
                'price_subtotal': detail['total_excluded_currency'],
                'price_subtotal_incl': detail['total_included_currency'],
                'extra_tax_data': tax_model._export_base_line_extra_tax_data(base),
                'baseer_discount_kind': 'fixed', 'baseer_discount_input': 44.5,
                'baseer_discount_approved_by_user_id': self.env.user.id,
            })
        sale._compute_prices()
        self._sync_native_draft(sale)
        return sale

    def _native_share_refund(self, sale, quantities):
        """Mirror refundShare and baseerBuildRefundDiscount for each tax group."""
        refund = self.env['pos.order'].create({
            'session_id': sale.session_id.id, 'company_id': sale.company_id.id,
            'partner_id': sale.partner_id.id, 'to_invoice': True, 'is_refund': True,
            'l10n_sa_reason': 'BR-KSA-17-reason-4',
            'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
        })
        currency = sale.currency_id
        tax_model = self.env['account.tax']
        for source, quantity in quantities:
            previous = source.refund_orderline_ids.filtered(lambda line: line.order_id.state != 'cancel')
            final = sum(abs(line.qty) for line in previous) + quantity >= abs(source.qty) - 1e-8
            shares = {}
            for field in ('baseer_discount_share_excl', 'baseer_discount_share_incl'):
                shares[field] = currency.round(
                    -source[field] - sum(previous.mapped(field)) if final
                    else -source[field] * quantity / abs(source.qty))
            self.env['pos.order.line'].create({
                'order_id': refund.id, 'uuid': str(uuid4()), 'product_id': source.product_id.id,
                'qty': -quantity, 'price_unit': source.price_unit, 'discount': source.discount,
                'price_subtotal': 0, 'price_subtotal_incl': 0,
                'tax_ids': [Command.set(source.tax_ids.ids)], 'refunded_orderline_id': source.id,
                **shares,
            })
            excl, incl = shares['baseer_discount_share_excl'], shares['baseer_discount_share_incl']
            discount = self.env['pos.order.line'].create({
                'order_id': refund.id, 'uuid': str(uuid4()), 'product_id': self.config.discount_product_id.id,
                'qty': -1, 'price_unit': -excl, 'price_subtotal': excl,
                'price_subtotal_incl': incl, 'tax_ids': [Command.set(source.tax_ids.ids)],
            })
            base = refund._gd_tax_base_lines(discount)[0]
            details = base['tax_details']
            delta = -excl - details['total_excluded_currency'] - details['delta_total_excluded_currency']
            details['delta_total_excluded_currency'] += delta
            details['delta_total_excluded'] += delta
            if details['taxes_data']:
                tax_detail = details['taxes_data'][0]
                adjustment = -incl + excl - tax_detail['tax_amount_currency']
                tax_detail['tax_amount_currency'] += adjustment
                tax_detail['tax_amount'] += adjustment
            tax_model._fix_base_lines_tax_details_on_manual_tax_amounts([base], refund.company_id)
            discount.extra_tax_data = tax_model._export_base_line_extra_tax_data(base)
        refund._compute_prices()
        self._sync_native_draft(refund)
        return refund

    def _allowance_total(self, root):
        return sum(Decimal(value) for value in root.xpath(
            "/*/*[local-name()='AllowanceCharge']/*[local-name()='Amount']/text()"))

    def test_new_native_fixed_mixed_invoice(self):
        sale = self._native_fixed_mixed_sale()
        move = self._pay_actual(sale)
        root = self._xml(sale, move)
        discounts = sale.lines.filtered(lambda line: line.product_id == self.config.discount_product_id)
        self.assertEqual(len(discounts), 2)
        self.assertEqual(len(root.xpath("/*/*[local-name()='AllowanceCharge']")), 2)
        self.assertEqual(set(root.xpath("/*/*[local-name()='AllowanceCharge']/*[local-name()='TaxCategory']/*[local-name()='Percent']/text()")), {'15.0', '0.0'})
        self.assertEqual(self._allowance_total(root), Decimal(str(round(-sum(discounts.mapped('price_subtotal')), 2))).quantize(Decimal('.01')))
        self.assertAlmostEqual(move.amount_total, sale.amount_total, places=2)

    def test_new_native_fixed_three_partial_credits(self):
        sale = self._native_fixed_mixed_sale()
        self._xml(sale, self._pay_actual(sale))
        source = sale.lines.filtered(lambda line: line.qty == 3).ensure_one()
        allowances = Decimal('0')
        for _ in range(3):
            refund = self._native_share_refund(sale, [(source, 1)])
            credit = self._pay_actual(refund)
            root = self._xml(refund, credit)
            self.assertEqual(root.xpath("/*/*[local-name()='ID']/text()"), [credit.name])
            self.assertEqual(root.xpath("/*/*[local-name()='BillingReference']/*[local-name()='InvoiceDocumentReference']/*[local-name()='ID']/text()"), [sale.account_move.name])
            self.assertAlmostEqual(credit.amount_total, -refund.amount_total, places=2)
            self.assertAlmostEqual(credit.amount_tax, -refund.amount_tax, places=2)
            allowances += self._allowance_total(root)
        self.assertEqual(allowances, Decimal(str(-source.baseer_discount_share_excl)).quantize(Decimal('.01')))

    def test_new_native_fixed_full_credit(self):
        sale = self._native_fixed_mixed_sale()
        invoice = self._pay_actual(sale)
        self._xml(sale, invoice)
        sources = sale.lines.filtered(lambda line: line.product_id != self.config.discount_product_id)
        refund = self._native_share_refund(sale, [(line, line.qty) for line in sources])
        credit = self._pay_actual(refund)
        self._xml(refund, credit)
        self.assertAlmostEqual(credit.amount_total, invoice.amount_total, places=2)
        self.assertAlmostEqual(credit.amount_total, -refund.amount_total, places=2)
