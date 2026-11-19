"""Synthetic offline acceptance only; never part of the production addon."""
import logging
import base64
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from lxml import etree

from odoo import Command
from odoo.tests.common import tagged
from odoo.addons.l10n_sa_edi.tests.common import TestSaEdiCommon
from odoo.addons.baseer_pos_global_discount.tests import test_global_discount as gd_tests

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestNativeDiscountAcceptance(TestSaEdiCommon):
    _order = gd_tests.TestGlobalDiscount._order
    _apply = gd_tests.TestGlobalDiscount._apply
    _refund = gd_tests.TestGlobalDiscount._refund
    _prepare = gd_tests.TestGlobalDiscount._prepare
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
        self.config.action_baseer_setup_global_discount()
        self.config.baseer_global_discount_product_id.property_account_income_id = self.company_data['default_account_revenue']
        self.env['pos.session'].create({'config_id': self.config.id, 'state': 'opened'})
        self.payment_method = self.config.payment_method_ids[:1]
        if not self.payment_method:
            self.payment_method = self.env['pos.payment.method'].create({
                'name': 'Synthetic customer account', 'split_transactions': True,
                'receivable_account_id': self.company_data['default_account_receivable'].id,
            })
            self.config.payment_method_ids = [Command.link(self.payment_method.id)]

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
        sign = -1 if order.is_refund else 1
        # This is the native POS cash-report orientation, not just a balanced
        # move: the original POS lines must prove the same net and gross.
        self.assertAlmostEqual(sign * sum(order.lines.mapped('price_subtotal')),
                               order.amount_total - order.amount_tax, places=2)
        self.assertAlmostEqual(sign * sum(order.lines.mapped('price_subtotal_incl')),
                               order.amount_total, places=2)
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
        evidence = Path('/var/lib/odoo/acceptance-evidence')
        evidence.mkdir(exist_ok=True)
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
        refund = self._refund(order, qty)
        refund.write({'partner_id': order.partner_id.id, 'to_invoice': True})
        self._prepare(refund)
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
        self.assertAlmostEqual(sum(refunds.mapped('baseer_global_discount_gross')), .97, places=2)

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
        refund = self._combo_refund(sale, parent, 1, ordinary=True)
        refund.write({'partner_id': sale.partner_id.id, 'to_invoice': True})
        self._prepare(refund)
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
        refund = self._combo_refund(sale, parent, 1, ordinary=True)
        refund.write({'partner_id': sale.partner_id.id, 'to_invoice': True})
        self._prepare(refund)
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
            refund = self._combo_refund(sale, parent, 1)
            refund.write({'partner_id': sale.partner_id.id, 'to_invoice': True})
            self._prepare(refund)
            self._xml(refund, self._pay_actual(refund))
            refunds |= refund
        self.assertAlmostEqual(sum(refunds.mapped('amount_total')), -sale.amount_total, places=2)
        self.assertAlmostEqual(sum(refunds.mapped('amount_tax')), -sale.amount_tax, places=2)
        self.assertAlmostEqual(sum(refunds.mapped('baseer_global_discount_gross')), .97, places=2)
