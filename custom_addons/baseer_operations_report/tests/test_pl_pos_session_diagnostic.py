"""Diagnose P&L attribution against native closed sessions; synthetic only."""

from decimal import Decimal
import logging
from uuid import uuid4
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tests.common import TransactionCase, tagged

from . import test_operations, test_pos_evidence


_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'pl_pos_session_diagnostic')
class TestPLPosSessionDiagnostic(TransactionCase):
    _account = test_operations.TestOperationsGrossCalculator._account
    _journal = test_operations.TestOperationsGrossCalculator._journal
    _tax = test_operations.TestOperationsGrossCalculator._tax
    _empty_native_pos_order = test_operations.TestOperationsGrossCalculator._empty_native_pos_order
    _native_global_rounding_order = test_operations.TestOperationsGrossCalculator._native_global_rounding_order
    _empty_order_payment = test_operations.TestOperationsGrossCalculator._empty_order_payment
    _empty_native_reader = test_operations.TestOperationsGrossCalculator._empty_native_reader
    _order = test_pos_evidence.TestOperationsPosEvidence._order
    _close = test_pos_evidence.TestOperationsPosEvidence._close

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.partner_id.tz = 'UTC'
        self.report = self.env['baseer.operations.report']
        self.receivable = self._account('956101', 'asset_receivable', True)
        self.payable = self._account('956102', 'liability_payable', True)
        self.income = self._account('956103', 'income')
        self.tax_account = self._account('956104', 'liability_current')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Synthetic P&L session diagnostic',
            'property_account_receivable_id': self.receivable.id,
            'property_account_payable_id': self.payable.id,
        })
        self.sale_journal = self._journal('sale', 'PSD')
        self.tax = self._tax('sale', self.tax_account)
        self.tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).account_id = self.tax_account

    def _observe_session(self, order):
        session = self._close(order)
        move = session.move_id
        self.assertFalse(order.account_move)
        self.assertEqual(order.session_id.move_id, move)
        posted = -sum((Decimal(str(line.balance)) for line in move.line_ids
                       if line.account_id == self.income), Decimal('0'))
        source = sum((Decimal(str(line.price_subtotal)) for line in order.lines), Decimal('0'))
        payments = sum((Decimal(str(payment.amount)) for payment in order.payment_ids), Decimal('0'))
        self.assertEqual(payments, Decimal(str(order.amount_total)))
        secured = self._empty_native_reader()
        report = secured.env['baseer.profit.loss.report']
        visible = report.env['pos.order'].search([
            ('id', '=', order.id), ('session_id.move_id', '=', move.id),
            ('account_move', '=', False), ('state', 'in', ('paid', 'done', 'invoiced')),
        ])
        self.assertEqual(visible.ids, order.ids)
        census = report._channel_child_ids(visible)
        self.assertEqual(census['lines'][order.id], set(order.lines.ids))
        self.assertEqual(census['payments'][order.id], set(order.payment_ids.ids))
        prepared = report._native_channel_accounts(visible, census['lines'])
        self.assertTrue(all(prepared[line.id].id == self.income.id for line in order.lines))
        allocation = report._revenue_channels(
            self.company, Domain('move_id', '=', move.id) & Domain('account_id', '=', self.income.id),
        )[self.income.id]
        self.assertEqual(sum((value for _name, value in allocation.values()), Decimal('0')), posted)
        _logger.info('PL_POS_SYNTHETIC_DIAGNOSTIC posted=%s source=%s difference=%s '
                     'order_total=%s payment_total=%s channels=%s',
                     posted, source, posted - source, order.amount_total, payments, sorted(allocation))
        return posted, source, allocation, order.payment_ids.payment_method_id

    def test_closed_session_taxed_exact_source(self):
        order = self._order(taxed=True)
        posted, source, allocation, method = self._observe_session(order)
        self.assertEqual(posted, Decimal('100'))
        self.assertEqual(source, posted)
        self.assertEqual(allocation['payment_%s' % method.id][1], posted)
        self.assertNotIn('unallocated', allocation)

    def test_closed_session_native_global_rounding_vector(self):
        order = self._native_global_rounding_order()
        order.date_order = fields.Datetime.now()
        self._empty_order_payment(order).amount = .09
        posted, source, allocation, method = self._observe_session(order)
        rounding = Decimal(str(self.company.currency_id.rounding))
        # Source/ledger parity is assessed before accepting channel attribution.
        if abs(posted - source) <= rounding:
            self.assertEqual(allocation['payment_%s' % method.id][1], posted)
            self.assertNotIn('unallocated', allocation)
        else:
            self.assertEqual(allocation['unallocated'][1], posted)

    def test_repeated_tax_included_rounding_needs_native_accounting_base(self):
        """Two synthetic orders reproduce a session mismatch over one cent."""
        self.company.tax_calculation_rounding_method = 'round_globally'
        self.tax.price_include_override = 'tax_included'
        bank = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.assertTrue(bank)
        clearing = self._account('956141', 'asset_current', True)
        original_method = self.env['pos.payment.method'].with_company(self.company).create({
            'name': 'Synthetic first bank method', 'company_id': self.company.id,
            'journal_id': bank.id, 'receivable_account_id': self.receivable.id,
            'outstanding_account_id': clearing.id,
        })
        second_method = original_method.copy({'name': 'Synthetic second bank method'})
        config = self.env['pos.config'].with_company(self.company).create({
            'name': 'Synthetic mixed payment diagnostic', 'company_id': self.company.id,
            'journal_id': self.sale_journal.id, 'invoice_journal_id': self.sale_journal.id,
            'payment_method_ids': [Command.set((original_method | second_method).ids)],
        })
        session = self.env['pos.session'].create({'config_id': config.id})
        session.set_opening_control(0, 'Synthetic payment allocation regression')
        first = self._empty_native_pos_order(session)
        product = self.env['product.product'].with_company(self.company).create({
            'name': 'Synthetic inclusive rounding', 'type': 'service',
            'available_in_pos': True, 'property_account_income_id': self.income.id,
            'taxes_id': [Command.set(self.tax.ids)],
        })
        orders = first | self._empty_native_pos_order(first.session_id)
        for order in orders:
            order.write({
                'date_order': fields.Datetime.now(),
                'amount_total': .08, 'amount_tax': .01, 'amount_paid': .08,
                'lines': [Command.create({
                    'product_id': product.id, 'uuid': str(uuid4()), 'qty': 1,
                    'price_unit': .02, 'price_subtotal': .02,
                    'price_subtotal_incl': .02, 'full_product_name': product.display_name,
                    'tax_ids': [Command.set(self.tax.ids)],
                }) for _ in range(4)],
            })
            payment = self._empty_order_payment(order)
            payment.amount = .08
            if order != first:
                payment.payment_method_id = second_method
        session = self._close(first)
        move = session.move_id
        posted = -sum((Decimal(str(line.balance)) for line in move.line_ids
                       if line.account_id == self.income), Decimal('0'))
        displayed_net = sum((Decimal(str(line.price_subtotal)) for line in orders.lines), Decimal('0'))
        self.assertEqual(displayed_net, Decimal('.16'))
        self.assertEqual(posted, Decimal('.14'))
        self.assertGreater(abs(posted - displayed_net), Decimal(str(self.company.currency_id.rounding)))
        secured = self._empty_native_reader()
        report = secured.env['baseer.profit.loss.report']
        channels = report._revenue_channels(
            self.company, Domain('move_id', '=', move.id) & Domain('account_id', '=', self.income.id),
        )[self.income.id]
        self.assertEqual(sum((value for _name, value in channels.values()), Decimal('0')), posted)
        self.assertEqual(channels['payment_%s' % original_method.id][1], Decimal('.07'))
        self.assertEqual(channels['payment_%s' % second_method.id][1], Decimal('.07'))
        self.assertNotIn('unallocated', channels)
        # Corrupt only the observed order tax, not the posted session move;
        # a changed historical tax header must not be attributed by inference.
        with patch.object(type(orders), 'amount_tax', .02):
            rejected = report._revenue_channels(
                self.company, Domain('move_id', '=', move.id) & Domain('account_id', '=', self.income.id),
            )[self.income.id]
        self.assertEqual(rejected['unallocated'][1], posted)
        self.assertNotIn('payment_%s' % original_method.id, rejected)
        self.assertNotIn('payment_%s' % second_method.id, rejected)

    def test_closed_session_administrative_correction_has_one_ledger_source_per_order(self):
        bank = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.assertTrue(bank)
        first_method = self.env['pos.payment.method'].with_company(self.company).create({
            'name': 'Synthetic original tender', 'company_id': self.company.id,
            'journal_id': bank.id, 'receivable_account_id': self.receivable.id,
            'outstanding_account_id': self._account('956141', 'asset_current', True).id,
        })
        second_method = first_method.copy({'name': 'Synthetic corrected tender'})
        config = self.env['pos.config'].with_company(self.company).create({
            'name': 'Synthetic administrative correction', 'company_id': self.company.id,
            'journal_id': self.sale_journal.id, 'invoice_journal_id': self.sale_journal.id,
            'payment_method_ids': [Command.set((first_method | second_method).ids)],
        })
        session = self.env['pos.session'].create({'config_id': config.id})
        session.set_opening_control(0, 'Synthetic administrative correction')
        remaining = self._order(session, amount=100, taxed=True)
        remaining.payment_ids.payment_method_id = first_method
        corrected = self._order(session, amount=40, taxed=True)
        corrected.payment_ids.payment_method_id = second_method
        move = self._close(remaining).move_id
        income = move.line_ids.filtered(lambda line: line.account_id == self.income)
        tax = move.line_ids.filtered('tax_line_id')
        self.assertEqual(sum(income.mapped('balance')), -140)
        self.assertEqual(sum(tax.mapped('balance')), -21)
        move.button_draft()
        marker_name = 'Synthetic POS closing difference'
        move.with_context(check_move_validity=False).write({'line_ids': [
            Command.update(income.id, {'credit': 100, 'amount_currency': -100}),
            Command.update(tax.id, {'credit': 15, 'amount_currency': -15, 'tax_base_amount': 100}),
            Command.create({
                'account_id': self.receivable.id, 'partner_id': self.partner.id,
                'name': marker_name, 'credit': 46,
            }),
        ]})
        move.action_post()
        marker = move.line_ids.filtered(lambda line: line.name == marker_name)
        correction_date = fields.Date.add(move.date, months=1)
        ref = 'POS-%s-ADMIN-CORRECTION-%s' % (
            corrected.id, correction_date.strftime('%Y%m%d'),
        )
        counterpart_name = '%s / reverse ONLY original closing difference%s' % (ref, marker.id)
        correction = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': move.journal_id.id, 'date': correction_date,
            'ref': ref, 'line_ids': [
                Command.create({
                    'account_id': self.receivable.id, 'partner_id': self.partner.id,
                    'name': counterpart_name, 'debit': 46,
                }),
                Command.create({
                    'account_id': self.income.id, 'name': 'Synthetic sales correction', 'credit': 40,
                }),
                Command.create({
                    'account_id': self.tax_account.id, 'name': 'Synthetic tax correction',
                    'tax_repartition_line_id': tax.tax_repartition_line_id.id,
                    'tax_base_amount': 40, 'credit': 6,
                }),
            ],
        })
        correction.action_post()
        counterpart = correction.line_ids.filtered(lambda line: line.name == counterpart_name)
        report = self._empty_native_reader().env['baseer.profit.loss.report']

        def channels(source, provenance=None):
            scope = Domain('move_id', 'in', source.ids) & Domain('account_id', '=', self.income.id)
            return {key: amount for key, (_name, amount) in report._revenue_channels(
                self.company, scope, provenance=provenance,
            )[self.income.id].items()}

        self.assertEqual(channels(move | correction), {'unallocated': Decimal('140.00')})
        (marker | counterpart).reconcile()
        self.assertTrue(marker.full_reconcile_id)
        self.assertEqual(marker.full_reconcile_id, counterpart.full_reconcile_id)
        first_key = 'payment_%s' % first_method.id
        second_key = 'payment_%s' % second_method.id
        evidence = []
        self.assertEqual(channels(move, evidence), {first_key: Decimal('100.00')})
        self.assertEqual(channels(correction, evidence), {second_key: Decimal('40.00')})
        self.assertEqual(channels(move | correction), {
            first_key: Decimal('100.00'), second_key: Decimal('40.00'),
        })
        self.assertEqual({(item['move_id'], item['channel_key'], item['value']) for item in evidence}, {
            (move.id, first_key, Decimal('100.00')), (correction.id, second_key, Decimal('40.00')),
        })
        for source, channel, net in (
            (move, first_key, '100.00'),
            (correction, second_key, '40.00'),
        ):
            filters = {'company_id': self.company.id, 'date_from': str(source.date),
                       'date_to': str(source.date), 'journal_ids': [source.journal_id.id],
                       'tax_inclusive': False}
            data = report.get_accounts(filters, 'income')
            row = next(row for row in data['accounts'] if row['id'] == self.income.id)
            self.assertEqual(row['amount'], net)
            self.assertEqual([(item['key'], item['amounts']['current']['amount'])
                              for item in row['channels']], [(channel, net)])
            # The synthetic correction has a tax line but no tax on its base;
            # the inclusive report must refuse that unproven allocation.
            filters['tax_inclusive'] = True
            if source == correction:
                with self.assertRaises(ValidationError):
                    report.get_accounts(filters, 'income')
            else:
                row = next(row for row in report.get_accounts(filters, 'income')['accounts']
                           if row['id'] == self.income.id)
                self.assertEqual(row['amount'], '115.00')
                self.assertEqual([(item['key'], item['amounts']['current']['amount'])
                                  for item in row['channels']], [(channel, '115.00')])
        duplicate = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': correction.journal_id.id,
            'date': correction.date, 'ref': ref,
        })
        self.assertEqual(channels(move | correction), {'unallocated': Decimal('140.00')})
        duplicate.unlink()
        rule = self.env['ir.rule'].create({
            'name': 'Hide the synthetic administrative correction',
            'model_id': self.env['ir.model']._get('account.move').id,
            'domain_force': f"[('id', '!=', {correction.id})]",
        })
        try:
            report.env.invalidate_all()
            self.assertEqual(channels(move), {'unallocated': Decimal('100.00')})
        finally:
            rule.unlink()
        counterpart.name = '%s / reverse ONLY original closing difference%s' % (ref, income.id)
        self.assertEqual(channels(move | correction), {'unallocated': Decimal('140.00')})
