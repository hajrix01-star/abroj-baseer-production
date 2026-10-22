"""Fresh financial proof reuse and scalar-equivalent payment attribution."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal
import re
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.baseer_profit_loss_report.models.profit_loss import SECTION_KEYS
from odoo.addons.baseer_profit_loss_report.models.revenue_channels import UNALLOCATED

from . import test_read_batches


@tagged('post_install', '-at_install', 'operations_dedup')
class TestOperationsDedup(TransactionCase):
    _account = test_read_batches.TestOperationsReadBatches._account
    _journal = test_read_batches.TestOperationsReadBatches._journal
    _tax = test_read_batches.TestOperationsReadBatches._tax
    _native_global_rounding_order = test_read_batches.TestOperationsReadBatches._native_global_rounding_order
    _empty_order_payment = test_read_batches.TestOperationsReadBatches._empty_order_payment
    _empty_native_reader = test_read_batches.TestOperationsReadBatches._empty_native_reader
    _order = test_read_batches.TestOperationsReadBatches._order
    _close = test_read_batches.TestOperationsReadBatches._close
    _pl = test_read_batches.TestOperationsReadBatches._pl
    _amounts = test_read_batches.TestOperationsReadBatches._amounts
    _mixed_orders = test_read_batches.TestOperationsReadBatches._mixed_orders

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.partner_id.tz = 'UTC'
        self.report = self.env['baseer.operations.report']
        self.receivable = self._account('955101', 'asset_receivable', True)
        self.payable = self._account('955102', 'liability_payable', True)
        self.income = self._account('955103', 'income')
        self.other_income = self._account('955104', 'income_other')
        self.tax_account = self._account('955105', 'liability_current')
        self.cash = self._account('955106', 'asset_cash')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Dedup synthetic partner',
            'property_account_receivable_id': self.receivable.id,
            'property_account_payable_id': self.payable.id,
        })
        self.sale_journal = self._journal('sale', 'DDS')
        self.tax = self._tax('sale', self.tax_account)
        self.tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).account_id = self.tax_account

    def _empty_native_pos_order(self, session=None):
        if session is None:
            bank = self.env['account.journal'].search([
                ('company_id', '=', self.company.id), ('type', '=', 'bank'),
            ], limit=1)
            self.assertTrue(bank)
            clearing = self._account('955141', 'asset_current', True)
            bank_method = self.env['pos.payment.method'].with_company(self.company).create({
                'name': 'Dedup synthetic bank', 'company_id': self.company.id,
                'journal_id': bank.id, 'receivable_account_id': self.receivable.id,
                'outstanding_account_id': clearing.id, 'sequence': 1,
            })
            cash_method = self._cash_method()
            # Native POS freezes payment configuration once a session opens.
            # Configure both real methods first, then use its normal opening.
            config = self.env['pos.config'].with_company(self.company).create({
                'name': 'Dedup synthetic POS', 'company_id': self.company.id,
                'journal_id': self.sale_journal.id,
                'invoice_journal_id': self.sale_journal.id, 'cash_control': False,
                'payment_method_ids': [Command.set((bank_method | cash_method).ids)],
            })
            session = self.env['pos.session'].create({'config_id': config.id})
            session.set_opening_control(0, 'Dedup synthetic opening')
        return test_read_batches.TestOperationsReadBatches._empty_native_pos_order(self, session)

    def _cash_method(self, session=None):
        if session is not None:
            method = session.config_id.payment_method_ids.filtered(
                lambda row: row.journal_id.type == 'cash',
            )
            self.assertEqual(len(method), 1)
            return method
        journal = self._journal('cash', 'DDC')
        journal.default_account_id = self.cash
        method = self.env['pos.payment.method'].with_company(self.company).create({
            'name': 'Dedup synthetic cash', 'company_id': self.company.id,
            'journal_id': journal.id, 'receivable_account_id': self.receivable.id,
            'sequence': 2,
        })
        return method

    def _payment(self, order, method, amount):
        return self.env['pos.payment'].create({
            'pos_order_id': order.id, 'payment_method_id': method.id, 'amount': amount,
        })

    def _entry(self, orders, report=None):
        sections, _excluded = self._amounts(orders, report=report)
        return sections['income'][self.income.id]

    def _scalar_channels(self, entry, report=None):
        """Original per-event attribution through the unchanged shared reader."""
        selected = self.report if report is None else report
        pl = selected.env['baseer.profit.loss.report']
        channels = {}
        for event in entry['events']:
            amount = Decimal(str(event['amount']))
            allocation = {UNALLOCATED: ('', amount)}
            if event['line_model'] == 'pos.order.line':
                try:
                    line = selected.env['pos.order.line'].browse(event['line_id']).exists()
                    line.check_access('read')
                    if line and line.order_id.company_id == self.company:
                        allocation = pl._order_channels(line.order_id, amount, self.company)
                except AccessError:
                    pass
            for key, (name, value) in allocation.items():
                previous = channels.get(key, (name, Decimal('0')))
                channels[key] = (name, previous[1] + value)
        return [{
            'key': key, 'name': name or pl._unallocated_channel_label(),
            'amount': pl._format_money(value, self.company.currency_id),
            'negative': value < 0,
        } for key, (name, value) in sorted(channels.items())]

    def _channel_cases(self):
        rounded = self._native_global_rounding_order()
        rounded.date_order = fields.Datetime.now()
        original = self._empty_order_payment(rounded)
        original.amount = .05
        session = rounded.session_id
        bank = original.payment_method_id
        cash = self._cash_method(session)
        self._payment(rounded, cash, .04)
        cash_order = self._order(session)
        cash_order.payment_ids.payment_method_id = cash
        split = self._order(session)
        split.payment_ids.write({'payment_method_id': cash.id, 'amount': 40})
        self._payment(split, bank, 60)
        change = self._order(session)
        change.payment_ids.write({'payment_method_id': cash.id, 'amount': 120})
        self._payment(change, cash, -20)
        change.amount_return = 20
        refund = cash_order._refund()
        refund.date_order = fields.Datetime.now()
        self._payment(refund, cash, -100)
        refund._compute_prices()
        refund.action_pos_order_paid()
        return {
            'cash': (cash_order, {cash.id: Decimal('100')}),
            'split': (split, {cash.id: Decimal('40'), bank.id: Decimal('60')}),
            'change': (change, {cash.id: Decimal('100')}),
            'refund': (refund, {cash.id: Decimal('-100')}),
            'rounding': (rounded, {cash.id: Decimal('.04'), bank.id: Decimal('.05')}),
        }

    def test_batched_channels_match_scalar_cash_split_change_refund_and_rounding(self):
        cases = self._channel_cases()
        all_orders = self.env['pos.order']
        for label, (order, expected) in cases.items():
            with self.subTest(case=label):
                all_orders |= order
                entry = self._entry(order)
                channels = self.report._entry_channels(entry, self.company)
                self.assertEqual(channels, self._scalar_channels(entry))
                self.assertEqual({row['key']: Decimal(row['amount']) for row in channels}, {
                    'payment_%s' % method: amount for method, amount in expected.items()
                })
                self.assertEqual(sum((Decimal(row['amount']) for row in channels), Decimal('0')),
                                 entry['raw'])
        combined = self._entry(all_orders)
        self.assertEqual(self.report._entry_channels(combined, self.company),
                         self._scalar_channels(combined))

    def test_period_proof_does_not_hide_unproven_previous_day_session_source(self):
        orders = self._mixed_orders()
        old, current = orders
        old.date_order = fields.Datetime.now() - timedelta(days=1)
        session = self._close(current)
        secured = self._empty_native_reader()
        period_sources = secured.env['pos.order'].browse(current.id)
        proven = secured._pos_amounts(
            period_sources, self.company, {key: {} for key in SECTION_KEYS}, Counter(),
        )
        self.assertEqual(proven, period_sources)
        self.assertIs(proven.env, secured.env)
        self.assertNotIn(old.id, proven.ids)
        visible_session = secured.env['pos.session'].browse(session.id)
        vector = secured._pos_expected_vector(visible_session, self.company)
        self.assertEqual(secured._pos_expected_vector(
            visible_session, self.company, proven_orders=proven,
        ), vector)
        candidates = secured.env['account.move.line'].browse(self._pl(session.move_id).ids)
        self.assertEqual(secured._proven_pos_secondary_lines(
            self.company, candidates, proven_orders=proven,
        ), set(candidates.ids))
        rule = self.env['ir.rule'].create({
            'name': 'Hide an unproven previous-day session source',
            'model_id': self.env['ir.model']._get('pos.order.line').id,
            'domain_force': f"[('id', '!=', {old.lines[:1].id})]",
        })
        try:
            secured.env.invalidate_all()
            self.assertTrue(secured.env['pos.order.line'].search([
                ('order_id', '=', current.id),
            ]))
            with self.assertRaises(AccessError):
                secured._pos_expected_vector(visible_session, self.company, proven_orders=proven)
            with self.assertRaises(AccessError):
                secured._proven_pos_secondary_lines(self.company, candidates, proven_orders=proven)
        finally:
            rule.unlink()

    def test_fresh_channel_calls_read_payment_changes_and_ignore_context_claims(self):
        order = self._order()
        bank = order.payment_ids.payment_method_id
        cash = self._cash_method(order.session_id)
        order.payment_ids.payment_method_id = cash
        entry = self._entry(order)
        first = self.report._entry_channels(entry, self.company)
        self.assertEqual(first[0]['key'], 'payment_%s' % cash.id)
        order.payment_ids.payment_method_id = bank
        changed = self.report._entry_channels(entry, self.company)
        self.assertEqual(changed, self._scalar_channels(entry))
        self.assertNotEqual(changed, first)
        self.assertEqual(changed[0]['key'], 'payment_%s' % bank.id)
        order.payment_ids.amount = 99
        injected = self.report.with_context(
            baseer_operations_proven_orders=order.ids,
            baseer_operations_channel_batch=first,
            baseer_operations_batch_verified=True,
        )
        current = injected._entry_channels(entry, self.company)
        self.assertEqual(current, self._scalar_channels(entry, report=injected))
        self.assertEqual([(row['key'], row['amount']) for row in current], [(UNALLOCATED, '100.00')])
        order.payment_ids.amount = 100
        self.assertEqual(self.report._entry_channels(entry, self.company), changed)

    def test_hidden_payment_keeps_scalar_fallback_for_other_visible_order(self):
        cash_order = self._order()
        bank_order = self._order(cash_order.session_id)
        bank = bank_order.payment_ids.payment_method_id
        cash = self._cash_method(cash_order.session_id)
        cash_order.payment_ids.payment_method_id = cash
        entry = self._entry(cash_order | bank_order)
        secured = self._empty_native_reader()
        self.assertEqual(secured._entry_channels(entry, self.company),
                         self._scalar_channels(entry, report=secured))
        hidden = cash_order.payment_ids
        rule = self.env['ir.rule'].create({
            'name': 'Hide one synthetic channel payment',
            'model_id': self.env['ir.model']._get('pos.payment').id,
            'domain_force': f"[('id', '!=', {hidden.id})]",
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['pos.payment'].search([('id', '=', hidden.id)]))
            channels = secured._entry_channels(entry, self.company)
            self.assertEqual(channels, self._scalar_channels(entry, report=secured))
            self.assertEqual({row['key']: Decimal(row['amount']) for row in channels}, {
                UNALLOCATED: Decimal('100'), 'payment_%s' % bank.id: Decimal('100'),
            })
        finally:
            rule.unlink()

    def test_channel_payment_membership_query_count_is_constant_for_more_events(self):
        first = self._order()
        orders = first
        for _index in range(7):
            orders |= self._order(first.session_id)
        small = self._entry(orders[:2])
        large = self._entry(orders)
        self.report._entry_channels(large, self.company)
        cursor_type = type(self.env.cr)
        original_execute = cursor_type.execute

        def query_count(entry):
            queries = []

            def counted_execute(cursor, query, *args, **kwargs):
                sql = re.sub(r'\s+', ' ', str(getattr(query, 'code', query)).replace(
                    '"', '').lower()).strip()
                if (sql.startswith('select') and 'from pos_payment where pos_order_id' in sql):
                    queries.append(sql)
                return original_execute(cursor, query, *args, **kwargs)

            with patch.object(cursor_type, 'execute', new=counted_execute):
                actual = self.report._entry_channels(entry, self.company)
            self.assertEqual(actual, self._scalar_channels(entry))
            return len(queries)

        small_count = query_count(small)
        large_count = query_count(large)
        self.assertGreater(small_count, 0, 'Raw payment membership proof was not observed')
        self.assertGreater(large_count, 0, 'Fresh call skipped payment membership proof')
        self.assertEqual(large_count, small_count)
