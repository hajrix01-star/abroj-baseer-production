"""Batch reads retain financial results, source membership and reader ACLs."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal
import re
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.baseer_profit_loss_report.models.profit_loss import SECTION_KEYS

from . import test_pos_evidence


@tagged('post_install', '-at_install', 'operations_read_batches')
class TestOperationsReadBatches(TransactionCase):
    # Compose fixture builders, without inheriting the other test methods.
    _account = test_pos_evidence.TestOperationsPosEvidence._account
    _journal = test_pos_evidence.TestOperationsPosEvidence._journal
    _tax = test_pos_evidence.TestOperationsPosEvidence._tax
    _empty_native_pos_order = test_pos_evidence.TestOperationsPosEvidence._empty_native_pos_order
    _native_global_rounding_order = test_pos_evidence.TestOperationsPosEvidence._native_global_rounding_order
    _empty_order_payment = test_pos_evidence.TestOperationsPosEvidence._empty_order_payment
    _empty_native_reader = test_pos_evidence.TestOperationsPosEvidence._empty_native_reader
    _order = test_pos_evidence.TestOperationsPosEvidence._order
    _close = test_pos_evidence.TestOperationsPosEvidence._close
    _pl = test_pos_evidence.TestOperationsPosEvidence._pl

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.partner_id.tz = 'UTC'
        self.report = self.env['baseer.operations.report']
        self.receivable = self._account('956101', 'asset_receivable', True)
        self.payable = self._account('956102', 'liability_payable', True)
        self.income = self._account('956103', 'income')
        self.other_income = self._account('956104', 'income_other')
        self.tax_account = self._account('956105', 'liability_current')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Batch read synthetic partner',
            'property_account_receivable_id': self.receivable.id,
            'property_account_payable_id': self.payable.id,
        })
        self.sale_journal = self._journal('sale', 'BRS')
        self.tax = self._tax('sale', self.tax_account)
        self.tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).account_id = self.tax_account

    def _mixed_orders(self):
        rounded = self._native_global_rounding_order()
        rounded.date_order = fields.Datetime.now()
        self._empty_order_payment(rounded).amount = .09
        regular = self._order(rounded.session_id, taxed=True)
        return rounded | regular

    def _amounts(self, orders, report=None, scalar=False):
        selected_report = self.report if report is None else report
        visible = selected_report.env['pos.order'].browse(orders.ids)
        sections = {key: {} for key in SECTION_KEYS}
        excluded = Counter()
        if scalar:
            for order in visible:
                selected_report._pos_amounts(order, self.company, sections, excluded)
        else:
            selected_report._pos_amounts(visible, self.company, sections, excluded)
        return sections, excluded

    def _rows(self, sections):
        today = fields.Date.today()
        return self.report._rows(sections, self.company, today, today, [])

    def test_singleton_and_batch_preserve_global_rounding_events_and_fingerprints(self):
        orders = self._mixed_orders()
        scalar, scalar_excluded = self._amounts(orders, scalar=True)
        batch, batch_excluded = self._amounts(orders)
        self.assertEqual(batch, scalar)
        self.assertEqual(batch_excluded, scalar_excluded)
        self.assertEqual(batch_excluded['native_pos_tax_rounding'], 2)
        entry = batch['income'][self.income.id]
        self.assertEqual(entry['raw'], Decimal('115.09'))
        self.assertEqual(entry['count'], 5)
        self.assertEqual({event['source_id'] for event in entry['events']}, set(orders.ids))
        self.assertEqual(self._rows(batch), self._rows(scalar))
        mapping = self.report._pos_lines_batch(orders)
        self.assertEqual(set(mapping), set(orders.ids))
        for order in orders:
            self.assertEqual(mapping[order.id], order.lines)

    def test_scalar_and_bulk_recording_preserve_signed_totals_and_acl(self):
        orders = self._mixed_orders()
        original, _excluded = self._amounts(orders)
        events = original['income'][self.income.id]['events']
        entries = [('income', self.income, event['amount'], 'pos', event)
                   for event in events]
        # Aggregation also retains a signed adjustment and a second account.
        entries.extend([
            ('income', self.income, Decimal('-2'), 'pos', events[0]),
            ('income_other', self.other_income, Decimal('3'), 'pos', events[-1]),
        ])
        scalar = {key: {} for key in SECTION_KEYS}
        bulk = {key: {} for key in SECTION_KEYS}
        for section, account, amount, source, event in entries:
            self.report._record(scalar, section, account, amount, source, event)
        self.report._record_many(bulk, entries)
        self.assertEqual(bulk, scalar)
        self.assertEqual(bulk['income'][self.income.id]['raw'], Decimal('113.09'))
        self.assertEqual(bulk['income_other'][self.other_income.id]['raw'], Decimal('3'))
        self.assertEqual(self._rows(bulk), self._rows(scalar))
        secured = self._empty_native_reader()
        checked = {key: {} for key in SECTION_KEYS}
        secured._record_many(checked, entries)
        self.assertEqual(checked, bulk)
        rule = self.env['ir.rule'].create({
            'name': 'Hide one account from synthetic bulk aggregation',
            'model_id': self.env['ir.model']._get('account.account').id,
            'domain_force': f"[('id', '!=', {self.other_income.id})]",
        })
        try:
            secured.env.invalidate_all()
            self.assertTrue(secured.env['account.account'].search([('id', '=', self.income.id)]))
            self.assertFalse(secured.env['account.account'].search([('id', '=', self.other_income.id)]))
            with self.assertRaises(AccessError):
                secured._record_many({key: {} for key in SECTION_KEYS}, entries)
        finally:
            rule.unlink()

    def test_hidden_batch_parent_or_child_and_old_session_witness_fail_closed(self):
        orders = self._mixed_orders()
        old, visible = orders
        old.date_order = fields.Datetime.now() - timedelta(days=1)
        session = self._close(visible)
        secured = self._empty_native_reader()
        expected, _excluded = self._amounts(orders)
        checked, _excluded = self._amounts(orders, report=secured)
        self.assertEqual(checked, expected)
        candidates = secured.env['account.move.line'].browse(self._pl(session.move_id).ids)
        self.assertEqual(secured._proven_pos_secondary_lines(
            self.company, candidates,
        ), set(candidates.ids))
        self.assertLess(old.date_order.date(), fields.Date.today())
        for model, hidden in (('pos.order.line', old.lines[:1]), ('pos.order', old)):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide one synthetic batch parent or child',
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': f"[('id', '!=', {hidden.id})]",
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', hidden.id)]))
                    self.assertTrue(secured.env['pos.order'].search([('id', '=', visible.id)]))
                    self.assertEqual(len(secured.env['pos.order.line'].search([
                        ('order_id', '=', visible.id),
                    ])), 1)
                    singleton, _excluded = self._amounts(visible, report=secured)
                    self.assertEqual(singleton['income'][self.income.id]['raw'], Decimal('115'))
                    with self.assertRaises(AccessError):
                        self._amounts(orders, report=secured)
                    # Session proof must still read the previous day's source.
                    with self.assertRaises(AccessError):
                        secured._proven_pos_secondary_lines(self.company, candidates)
                finally:
                    rule.unlink()

    def test_separate_calls_read_changed_source_and_context_cannot_bypass(self):
        orders = self._mixed_orders()
        original, _excluded = self._amounts(orders)
        original_rows = self._rows(original)
        regular = orders[-1]
        line = regular.lines
        line.write({
            'price_unit': 200, 'price_subtotal': 200, 'price_subtotal_incl': 230,
        })
        regular.write({'amount_total': 230, 'amount_tax': 30, 'amount_paid': 230})
        regular.payment_ids.amount = 230
        changed, _excluded = self._amounts(orders)
        self.assertEqual(changed['income'][self.income.id]['raw'], Decimal('230.09'))
        self.assertNotEqual(self._rows(changed), original_rows)
        line.price_subtotal_incl = 230.01
        with self.assertRaises(AccessError):
            self._amounts(orders)
        injected = self.report.with_context(
            baseer_operations_batch_verified=True,
            baseer_operations_pos_lines_by_order={str(order.id): [] for order in orders},
            baseer_operations_read_batch=orders.ids,
        )
        with self.assertRaises(AccessError):
            self._amounts(orders, report=injected)
        line.price_subtotal_incl = 230
        restored, _excluded = self._amounts(orders)
        self.assertEqual(restored, changed)

    def test_closed_vector_union_rejects_one_hidden_account_or_repartition(self):
        orders = self._mixed_orders()
        rounded, regular = orders
        distinct_tax = self.tax.copy({'name': 'Synthetic batch second-order VAT'})
        regular.lines.tax_ids = distinct_tax
        regular.lines.product_id.property_account_income_id = self.other_income
        session = self._close(regular)
        tax_repartition = distinct_tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        )
        self.assertEqual(len(tax_repartition), 1)
        secured = self._empty_native_reader()
        visible_session = secured.env['pos.session'].browse(session.id)
        vector = secured._pos_expected_vector(visible_session, self.company)
        self.assertTrue(vector)
        candidates = secured.env['account.move.line'].browse(self._pl(session.move_id).ids)
        self.assertEqual(secured._proven_pos_secondary_lines(
            self.company, candidates,
        ), set(candidates.ids))
        for model, hidden in (
                ('account.account', self.other_income),
                ('account.tax.repartition.line', tax_repartition)):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide one target in the synthetic native vector union',
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': f"[('id', '!=', {hidden.id})]",
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', hidden.id)]))
                    control, _excluded = self._amounts(rounded, report=secured)
                    self.assertEqual(control['income'][self.income.id]['raw'], Decimal('.09'))
                    with self.assertRaises(AccessError):
                        secured._pos_expected_vector(visible_session, self.company)
                    with self.assertRaises(AccessError):
                        secured._proven_pos_secondary_lines(self.company, candidates)
                finally:
                    rule.unlink()

    def test_parent_line_pair_witness_rejects_compensated_parent_swap(self):
        left = self._order(taxed=True)
        right = self._order(left.session_id, taxed=True)
        orders = left | right
        expected = {(order.id, order.lines.id) for order in orders}
        swapped = {(left.id, right.lines.id), (right.id, left.lines.id)}
        self.assertNotEqual(swapped, expected)
        self.assertEqual({line for _parent, line in swapped},
                         {line for _parent, line in expected})
        mapping = self.report._pos_lines_batch(orders)
        self.assertEqual(mapping[left.id], left.lines)
        self.assertEqual(mapping[right.id], right.lines)
        cursor_type = type(self.env.cr)
        original_execute = cursor_type.execute
        original_fetchall = self.env.cr.fetchall
        state = {'pair_query': False, 'injected': False}

        def witnessed_execute(cursor, query, *args, **kwargs):
            sql = re.sub(r'\s+', ' ', str(getattr(query, 'code', query)).replace(
                '"', '').lower()).strip()
            result = original_execute(cursor, query, *args, **kwargs)
            if cursor is self.env.cr:
                state['pair_query'] = sql.startswith(
                    'select order_id, id from pos_order_line where order_id',
                )
            return result

        def swapped_fetchall():
            rows = original_fetchall()
            if state['pair_query']:
                state['pair_query'] = False
                self.assertEqual(set(rows), expected)
                state['injected'] = True
                return sorted(swapped)
            return rows

        # Inject only the read-only SQL witness returned to the guard. The
        # native source relations and both line IDs remain unchanged in ORM.
        with patch.object(cursor_type, 'execute', new=witnessed_execute), \
                patch.object(self.env.cr, 'fetchall', new=swapped_fetchall):
            with self.assertRaises(AccessError):
                self.report._pos_lines_batch(orders)
        self.assertTrue(state['injected'], 'The raw parent/line witness was not exercised')
        mapping = self.report._pos_lines_batch(orders)
        self.assertEqual(mapping[left.id], left.lines)
        self.assertEqual(mapping[right.id], right.lines)

    def test_sale_vector_allows_hidden_unused_refund_repartition(self):
        orders = self._mixed_orders()
        session = self._close(orders[-1])
        unused = self.tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        )
        self.assertEqual(len(unused), 1)
        self.assertFalse(orders.filtered('is_refund'))
        secured = self._empty_native_reader()
        visible_session = secured.env['pos.session'].browse(session.id)
        expected = secured._pos_expected_vector(visible_session, self.company)
        self.assertTrue(expected)
        candidates = secured.env['account.move.line'].browse(self._pl(session.move_id).ids)
        self.assertEqual(secured._proven_pos_secondary_lines(
            self.company, candidates,
        ), set(candidates.ids))
        rule = self.env['ir.rule'].create({
            'name': 'Hide unused synthetic refund repartition from a sale session',
            'model_id': self.env['ir.model']._get('account.tax.repartition.line').id,
            'domain_force': f"[('id', '!=', {unused.id})]",
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['account.tax.repartition.line'].search([
                ('id', '=', unused.id),
            ]))
            self.assertEqual(secured._pos_expected_vector(visible_session, self.company), expected)
            self.assertEqual(secured._proven_pos_secondary_lines(
                self.company, candidates,
            ), set(candidates.ids))
        finally:
            rule.unlink()

    def test_fiscal_position_mapped_tax_repartition_is_required_evidence(self):
        orders = self._mixed_orders()
        rounded, mapped_order = orders
        mapped_tax = self.tax.copy({'name': 'Synthetic fiscal-position mapped VAT'})
        fiscal_position = self.env['account.fiscal.position'].with_company(self.company).create({
            'name': 'Synthetic batch fiscal-position tax map',
            'company_id': self.company.id,
            'tax_ids': [Command.create({
                'tax_src_id': self.tax.id, 'tax_dest_id': mapped_tax.id,
            })],
        })
        mapped_order.fiscal_position_id = fiscal_position
        self.assertNotIn(mapped_tax, mapped_order.lines.tax_ids)
        self.assertEqual(mapped_order.lines.tax_ids_after_fiscal_position, mapped_tax)
        session = self._close(mapped_order)
        required = mapped_tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        )
        self.assertEqual(len(required), 1)
        secured = self._empty_native_reader()
        visible_session = secured.env['pos.session'].browse(session.id)
        self.assertTrue(secured._pos_expected_vector(visible_session, self.company))
        candidates = secured.env['account.move.line'].browse(self._pl(session.move_id).ids)
        self.assertEqual(secured._proven_pos_secondary_lines(
            self.company, candidates,
        ), set(candidates.ids))
        rule = self.env['ir.rule'].create({
            'name': 'Hide a required synthetic mapped-tax repartition',
            'model_id': self.env['ir.model']._get('account.tax.repartition.line').id,
            'domain_force': f"[('id', '!=', {required.id})]",
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['account.tax.repartition.line'].search([
                ('id', '=', required.id),
            ]))
            control, _excluded = self._amounts(rounded, report=secured)
            self.assertEqual(control['income'][self.income.id]['raw'], Decimal('.09'))
            with self.assertRaises(AccessError):
                secured._pos_expected_vector(visible_session, self.company)
            with self.assertRaises(AccessError):
                secured._proven_pos_secondary_lines(self.company, candidates)
        finally:
            rule.unlink()

    def _membership_queries(self, orders):
        counts = Counter()
        cursor_type = type(self.env.cr)
        original_execute = cursor_type.execute
        tax_relation = self.env['pos.order.line']._fields['tax_ids'].relation.lower()

        def counted_execute(cursor, query, *args, **kwargs):
            sql = getattr(query, 'code', query)
            if isinstance(sql, bytes):
                sql = sql.decode()
            sql = re.sub(r'\s+', ' ', str(sql).replace('"', '').lower()).strip()
            if sql.startswith('select'):
                # Count the raw membership witnesses, not ORM field loads or
                # all queries in a financial request. Every query still runs.
                if (re.search(r'\bfrom pos_order_line\b', sql)
                        and re.search(r'\bwhere order_id\s*(?:=|in\b)', sql)):
                    counts['line_membership'] += 1
                if re.search(r'\bfrom ' + re.escape(tax_relation) + r'\b', sql):
                    counts['tax_membership'] += 1
            return original_execute(cursor, query, *args, **kwargs)

        with patch.object(cursor_type, 'execute', new=counted_execute):
            self._amounts(orders)
        return counts

    def test_line_and_tax_membership_queries_do_not_scale_per_order(self):
        self.company.tax_calculation_rounding_method = 'round_globally'
        first = self._order(taxed=True)
        orders = first
        for _index in range(7):
            orders |= self._order(first.session_id, taxed=True)
        # Warm native ORM fields for all sources equally. The explicit SQL
        # membership guards must execute again on both fresh financial calls.
        self._amounts(orders)
        small = self._membership_queries(orders[:2])
        large = self._membership_queries(orders)
        for kind in ('line_membership', 'tax_membership'):
            with self.subTest(kind=kind):
                self.assertGreater(small[kind], 0, 'Membership guard was not observed')
                self.assertGreater(large[kind], 0, 'Fresh call skipped its membership guard')
                self.assertLessEqual(large[kind], small[kind] + 1)
