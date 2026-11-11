"""Witness-bound dashboard coverage against native Odoo accounting facts."""

from decimal import Decimal
from collections import Counter
from io import BytesIO
import logging
from time import perf_counter
from unittest.mock import patch

from openpyxl import load_workbook

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.baseer_financial_dashboard.models import owner_coverage

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestIsolatedOwnerCoverage(TransactionCase):
    """The dashboard may prove more sources without weakening billing reports."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.accounts = self.env['account.account'].with_company(self.company)

        def account(code, kind, reconcile=False):
            return self.accounts.create({
                'code': code, 'name': 'Isolated owner ' + code,
                'account_type': kind, 'reconcile': reconcile,
                'company_ids': [Command.set(self.company.ids)],
            })

        self.payable = account('954901', 'liability_payable', True)
        self.expense = account('954902', 'expense')
        self.writeoff = account('954903', 'expense')
        self.receivable = account('954904', 'asset_current')
        self.cash2 = account('954905', 'asset_cash')
        self.cash3 = account('954906', 'asset_cash')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Isolated owner vendor',
            'property_account_payable_id': self.payable.id,
        })
        self.purchase = self.env['account.journal'].with_company(self.company).create({
            'name': 'Isolated owner purchase', 'code': 'IOP', 'type': 'purchase',
            'company_id': self.company.id,
        })
        self.general = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        self.bank = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.assertTrue(self.general and self.bank and self.bank.default_account_id)
        self.assertEqual(self.bank.default_account_id.account_type, 'asset_cash')
        self.method = self.bank.outbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id.code == 'manual',
        )[:1]
        self.assertTrue(self.method)
        self.method.payment_account_id = self.bank.default_account_id
        self.report = self.env['baseer.financial.dashboard.operations']
        self.billing = self.env['baseer.operations.report']
        self.filters = {
            'company_id': self.company.id, 'date_from': '2046-06-01',
            'date_to': '2046-06-30', 'journal_ids': [],
        }

    def _bill(self, amount):
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice', 'partner_id': self.partner.id,
            'journal_id': self.purchase.id, 'invoice_date': '2046-06-10',
            'invoice_line_ids': [Command.create({
                'name': 'Isolated owner bill', 'quantity': 1,
                'price_unit': amount, 'account_id': self.expense.id,
                'tax_ids': [Command.clear()],
            })],
        })
        bill.action_post()
        return bill

    def _payment_with_embedded_writeoff(self, bill_amount=1518, cash_amount=1517.96):
        bill = self._bill(bill_amount)
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id, 'payment_method_line_id': self.method.id,
            'amount': cash_amount, 'payment_date': '2046-06-12',
            'installments_mode': 'full', 'payment_difference_handling': 'reconcile',
            'writeoff_account_id': self.writeoff.id,
        })
        payment = wizard._create_payments()
        lines = payment.move_id.line_ids
        self.assertEqual(len(lines), 3)
        liquidity = lines.filtered(lambda line: line.account_id == self.bank.default_account_id)
        payable = lines.filtered(lambda line: line.account_id == self.payable)
        adjustment = lines.filtered(lambda line: line.account_id == self.writeoff)
        self.assertEqual((len(liquidity), len(payable), len(adjustment)), (1, 1, 1))
        self.assertEqual(Decimal(str(liquidity.balance)), -Decimal(str(cash_amount)))
        self.assertEqual(Decimal(str(payable.balance)), Decimal(str(bill_amount)))
        self.assertEqual(Decimal(str(adjustment.balance)), Decimal('-0.04'))
        self.assertEqual(len(payable.matched_credit_ids), 1)
        return bill, payment, liquidity, payable

    def _split_payment(self, extra_unsettled=0, adjustment_day='2046-06-12',
                       adjustment_account=None, bill_amount=3220):
        bill = self._bill(bill_amount)
        payment = self.env['account.payment'].with_company(self.company).create({
            'date': '2046-06-12', 'amount': bill_amount + 1 + extra_unsettled,
            'payment_type': 'outbound', 'partner_type': 'supplier',
            'partner_id': self.partner.id, 'journal_id': self.bank.id,
            'company_id': self.company.id, 'currency_id': self.company.currency_id.id,
            'payment_method_line_id': self.method.id,
        })
        payment.action_post()
        adjustment = self.env['account.move'].with_company(self.company).create({
            'date': adjustment_day, 'journal_id': self.general.id, 'move_type': 'entry',
            'line_ids': [
                Command.create({'name': 'Difference expense', 'account_id': (adjustment_account or self.writeoff).id,
                                'partner_id': self.partner.id, 'debit': 1}),
                Command.create({'name': 'Difference payable', 'account_id': self.payable.id,
                                'partner_id': self.partner.id, 'credit': 1}),
            ],
        })
        adjustment._post(soft=False)
        payable = payment.move_id.line_ids.filtered(lambda line: line.account_id == self.payable)
        bill_payable = bill.line_ids.filtered(lambda line: line.account_id == self.payable)
        adjustment_payable = adjustment.line_ids.filtered(lambda line: line.account_id == self.payable)
        (payable + bill_payable + adjustment_payable).reconcile()
        liquidity = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        )
        self.assertEqual((len(payable), len(liquidity)), (1, 1))
        self.assertEqual(len(payable.matched_credit_ids), 2)
        return bill, payment, adjustment, liquidity, payable

    def _cash(self, report=None):
        return (self.report if report is None else report)._owner_cash(
            self.company, '2046-06-01', '2046-06-30', [],
        )

    def _ordinary_payment(self, amount):
        bill = self._bill(amount)
        return self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id, 'payment_method_line_id': self.method.id,
            'amount': amount, 'payment_date': '2046-06-12',
            'installments_mode': 'full', 'payment_difference_handling': 'open',
        })._create_payments()

    def _assert_exact_cash(self, result, liquidity, amount, expected_count):
        self.assertTrue(result['coverage_complete'], result['excluded'])
        self.assertEqual(result['liquidity_totals'], {liquidity.id: amount})
        self.assertEqual(len(result['events']), expected_count)
        self.assertEqual({row['payment_line_id'] for row in result['events']}, {liquidity.id})
        self.assertEqual(sum((row['amount'] for row in result['events']), Decimal('0')), amount)
        self.assertTrue(all(row['classification'] == 'unconfirmed_bill_classification'
                            for row in result['events']))

    def test_embedded_writeoff_reports_actual_cash_once_and_preserves_billing(self):
        _bill, _payment, liquidity, _payable = self._payment_with_embedded_writeoff()
        before = self.billing.get_owner_snapshot(self.filters)
        self.assertFalse(before['complete'])
        result = self._cash()
        self._assert_exact_cash(result, liquidity, Decimal('1517.96'), 1)
        self.assertEqual(self.billing.get_owner_snapshot(self.filters), before)

    def test_split_writeoff_witness_reconciles_snapshot_details_and_export(self):
        _bill, _payment, _adjustment, liquidity, _payable = self._split_payment()
        self.assertFalse(self.billing.get_owner_snapshot(self.filters)['complete'])

        result = self._cash()
        self._assert_exact_cash(result, liquidity, Decimal('3221.00'), 2)
        self.assertEqual({row['amount'] for row in result['events']},
                         {Decimal('3220.00'), Decimal('1.00')})
        self.assertEqual(len({row['line_id'] for row in result['events']}), 2)
        snapshot = self.report.get_owner_snapshot(self.filters)
        self.assertTrue(snapshot['complete'])
        period = snapshot['periods'][0]
        total = next(row for row in period['totals'] if row['key'] == 'cash_total')
        self.assertEqual(total['amount'], '3,221.00')
        detail = self.report.get_owner_details(
            self.filters, 'total:cash_total', period['key'], period['revision'],
        )
        self.assertFalse(detail['changed'])
        self.assertEqual(detail['amount'], '3,221.00')
        self.assertEqual(sum((Decimal(row['amount'].replace(',', ''))
                              for row in detail['events']), Decimal('0')), Decimal('3221.00'))
        source = self.report.action_owner_source(
            self.filters, 'total:cash_total', period['key'], period['revision'],
            detail['events'][0]['event_key'],
        )
        self.assertEqual(source['target'], 'new')
        self.assertFalse(source['context']['edit'])
        document = self.report._get_export_document(self.filters)
        self.assertIn(Decimal('3221.00'), [
            cell for row in document['rows'] for cell in row['cells'].values()
            if isinstance(cell, Decimal)
        ])
        self.assertFalse(self.billing.get_owner_snapshot(self.filters)['complete'])

    def test_twenty_payments_six_candidates_measure_original_vs_isolated(self):
        # Representative of the observed volume, built in this test database:
        # fourteen already-supported payments, two inline write-offs, and four
        # split settlements.  This is not a production/concurrency benchmark.
        for amount in range(100, 114):
            self._ordinary_payment(amount)
        self._payment_with_embedded_writeoff()
        self._payment_with_embedded_writeoff(1519, 1518.96)
        for index in range(4):
            self._split_payment(bill_amount=3220 + index)

        def measure(report):
            self.env.flush_all()
            self.env.invalidate_all()
            before_queries = self.env.cr.sql_log_count
            started = perf_counter()
            result = self._cash(report)
            return result, self.env.cr.sql_log_count - before_queries, perf_counter() - started

        baseline, original_queries, original_seconds = measure(self.billing)
        isolated, isolated_queries, isolated_seconds = measure(self.report)
        self.assertFalse(baseline['coverage_complete'])
        self.assertEqual(baseline['excluded'].get('unsupported_native_payment'), 2)
        self.assertEqual(baseline['excluded'].get('unassigned_native_payment'), 4)
        self.assertTrue(isolated['coverage_complete'], isolated['excluded'])
        self.assertEqual(len(isolated['liquidity_totals']), 20)
        _logger.info(
            'ISOLATED_OWNER_20_6 original_queries=%s isolated_queries=%s '
            'original_seconds=%.3f isolated_seconds=%.3f',
            original_queries, isolated_queries, original_seconds, isolated_seconds,
        )

    def test_second_census_bound_accepts_n_and_fails_closed_at_n_plus_one(self):
        # Reduce the named bound in the isolated test only: this exercises the
        # exact <=N and >N branches without generating a thousand accounting
        # records.  The original source census retains its real production cap.
        self._payment_with_embedded_writeoff()
        self._payment_with_embedded_writeoff(1519, 1518.96)
        with patch.object(owner_coverage, 'NATIVE_PAYMENT_CENSUS_BATCH_SIZE', 2):
            at_limit = self._cash()
            self.assertTrue(at_limit['coverage_complete'], at_limit['excluded'])
            self.assertEqual(len(at_limit['liquidity_totals']), 2)
            self._ordinary_payment(42)
            beyond_limit = self._cash()
            self.assertFalse(beyond_limit['coverage_complete'])
            self.assertEqual(beyond_limit['excluded'].get('unsupported_native_payment'), 2)
            self.assertFalse(self.report.get_owner_snapshot(self.filters)['complete'])

    def test_incomplete_partial_and_unknown_receivable_remain_hidden(self):
        _bill, _payment, _adjustment, _liquidity, _payable = self._split_payment(extra_unsettled=1)
        result = self._cash()
        self.assertFalse(result['coverage_complete'])
        self.assertFalse(self.report.get_owner_snapshot(self.filters)['complete'])

    def test_adjustment_from_a_different_day_remains_incomplete(self):
        self._split_payment(adjustment_day='2046-06-13')
        result = self._cash()
        self.assertFalse(result['coverage_complete'])
        self.assertFalse(self.report.get_owner_snapshot(self.filters)['complete'])

    def test_adjustment_to_a_nonexpense_account_remains_incomplete(self):
        self._split_payment(adjustment_account=self.receivable)
        result = self._cash()
        self.assertFalse(result['coverage_complete'])
        self.assertFalse(self.report.get_owner_snapshot(self.filters)['complete'])

    def test_payment_already_claimed_by_another_family_is_not_counted_twice(self):
        _bill, payment, _adjustment, _liquidity, _payable = self._split_payment()
        sections = {key: {} for key in (
            'income', 'income_other', 'expense_direct_cost', 'expense',
            'expense_depreciation', 'expense_other',
        )}
        excluded = Counter()
        self.report._native_payment_outflows(
            self.company, '2046-06-01', '2046-06-30', [], sections, excluded,
            claimed_payment_ids=frozenset([payment.id]), read_facts={},
        )
        self.assertFalse(any(section for section in sections.values()))

    def test_reversed_settlement_is_not_admitted(self):
        _bill, _payment, adjustment, _liquidity, _payable = self._split_payment()
        self.assertTrue(self._cash()['coverage_complete'])
        reversal = adjustment._reverse_moves([{'date': '2046-06-12'}])
        self.assertTrue(reversal and adjustment.reversal_move_ids)
        try:
            result = self._cash()
        except AccessError:
            return
        self.assertFalse(result['coverage_complete'])

    def test_inconsistent_settlement_identity_is_never_accepted(self):
        _bill, _payment, adjustment, _liquidity, _payable = self._split_payment()
        self.assertTrue(self._cash()['coverage_complete'])
        line = adjustment.line_ids.filtered(lambda row: row.account_id == self.payable)
        self.assertEqual(len(line), 1)
        foreign_partner = self.env['res.partner'].create({'name': 'Foreign settlement partner'})
        foreign_company = self.env['res.company'].create({'name': 'Foreign settlement company'})
        foreign_currency = self.env['res.currency'].search([
            ('id', '!=', self.company.currency_id.id),
        ], limit=1)
        self.assertTrue(foreign_currency)
        # Test-only corruption simulates incomplete/cross-boundary evidence;
        # the production path never writes these journal lines.
        for field, alternate in (
                ('partner_id', foreign_partner.id),
                ('company_id', foreign_company.id),
                ('currency_id', foreign_currency.id)):
            original = line[field].id
            line.flush_recordset([field])
            try:
                self.env.cr.execute(
                    f'UPDATE account_move_line SET {field}=%s WHERE id=%s',
                    [alternate, line.id],
                )
                line.invalidate_recordset([field])
                try:
                    result = self._cash()
                except AccessError:
                    continue
                self.assertFalse(result['coverage_complete'], field)
            finally:
                self.env.cr.execute(
                    f'UPDATE account_move_line SET {field}=%s WHERE id=%s',
                    [original, line.id],
                )
                line.invalidate_recordset([field])

    def test_changed_reconciliation_invalidates_the_old_detail_revision(self):
        bill, _payment, adjustment, _liquidity, payable = self._split_payment()
        old = self.report.get_owner_snapshot(self.filters)
        self.assertTrue(old['complete'])
        period = old['periods'][0]
        old_ids = set(payable.matched_credit_ids.ids)
        payable.matched_credit_ids.unlink()
        counterparts = (bill.line_ids + adjustment.line_ids).filtered(
            lambda line: line.account_id == self.payable,
        )
        (payable + counterparts).reconcile()
        self.assertNotEqual(set(payable.matched_credit_ids.ids), old_ids)
        new = self.report.get_owner_snapshot(self.filters)
        self.assertTrue(new['complete'])
        self.assertNotEqual(new['periods'][0]['revision'], period['revision'])
        stale = self.report.get_owner_details(
            self.filters, 'total:cash_total', period['key'], period['revision'],
        )
        self.assertTrue(stale['changed'])

    def test_private_pdf_and_excel_export_bind_to_the_same_current_revision(self):
        self._split_payment()
        snapshot = self.report.get_owner_snapshot(self.filters)
        self.assertTrue(snapshot['complete'])
        revisions = [{'key': period['key'], 'revision': period['revision']}
                     for period in snapshot['periods']]
        exporter = self.env['baseer.financial.dashboard.export'].with_context(
            _financial_dashboard_export_revisions=revisions,
        )
        document = exporter._document('financial_dashboard_operations', self.filters)
        self.assertIn(Decimal('3221.00'), [
            cell for row in document['rows'] for cell in row['cells'].values()
            if isinstance(cell, Decimal)
        ])
        payload, mimetype, name = exporter._export(
            'financial_dashboard_operations', self.filters, 'xlsx',
        )
        self.assertIn('spreadsheetml.sheet', mimetype)
        self.assertTrue(name.endswith('.xlsx'))
        self.assertTrue(any(Decimal(str(cell.value)) == Decimal('3221.00')
                            for row in load_workbook(BytesIO(payload)).active.iter_rows()
                            for cell in row if isinstance(cell.value, (int, float))))
        action = self.report.action_print_owner(self.filters, revisions)
        self.assertEqual(action['report_name'],
                         'baseer_financial_dashboard.dashboard_owner_pdf_portrait')
        provider = self.env['report.baseer_financial_dashboard.dashboard_owner_pdf_portrait']
        values = provider._get_report_values([], {'filters': self.filters, 'revisions': revisions})
        cash = next(row for row in values['periods'][0]['totals'] if row['key'] == 'cash_total')
        self.assertEqual(cash['amount'], '3,221.00')

        with self.assertRaises(ValidationError):
            self.env['baseer.financial.dashboard.export']._document(
                'financial_dashboard_operations', self.filters,
            )
        with self.assertRaises(ValidationError):
            provider._get_report_values([], {'filters': self.filters})
        stale = [{'key': revisions[0]['key'], 'revision': '0' * 64}]
        with self.assertRaises(AccessError):
            self.env['baseer.financial.dashboard.export'].with_context(
                _financial_dashboard_export_revisions=stale,
            )._document('financial_dashboard_operations', self.filters)
        with self.assertRaises(AccessError):
            provider._get_report_values([], {'filters': self.filters, 'revisions': stale})
        with self.assertRaises(AccessError):
            self.report.action_print_owner(self.filters, stale)
        self.assertFalse(self.billing.get_owner_snapshot(self.filters)['complete'])

    def test_three_cash_lines_to_receivable_do_not_become_an_expense(self):
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2046-06-13', 'journal_id': self.general.id, 'move_type': 'entry',
            'line_ids': [
                Command.create({'name': 'Unknown receivable', 'account_id': self.receivable.id, 'debit': 60}),
                Command.create({'name': 'Cash A', 'account_id': self.bank.default_account_id.id, 'credit': 10}),
                Command.create({'name': 'Cash B', 'account_id': self.cash2.id, 'credit': 20}),
                Command.create({'name': 'Cash C', 'account_id': self.cash3.id, 'credit': 30}),
            ],
        })
        move._post(soft=False)
        result = self._cash()
        self.assertFalse(result['coverage_complete'])
        self.assertEqual(result['excluded'].get('unproven_liquidity_outflow'), 3)
        snapshot = self.report.get_owner_snapshot(self.filters)
        self.assertFalse(snapshot['complete'])
        self.assertNotIn('totals', snapshot['periods'][0])

    def test_non_accountant_and_foreign_company_are_rejected(self):
        user = self.env['res.users'].create({
            'name': 'Isolated owner employee', 'login': 'isolated-owner-no-account',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
        })
        with self.assertRaises(AccessError):
            self.report.with_user(user).get_owner_snapshot(self.filters)
        foreign = self.env['res.company'].create({'name': 'Isolated owner forbidden company'})
        with self.assertRaises(AccessError):
            self.report.with_context(allowed_company_ids=self.company.ids).get_owner_snapshot({
                **self.filters, 'company_id': foreign.id,
            })

    def test_hidden_partial_reconciliation_fails_closed(self):
        _bill, _payment, _adjustment, _liquidity, payable = self._split_payment()
        groups = [self.env.ref('base.group_user').id,
                  self.env.ref('account.group_account_user').id,
                  self.env.ref('point_of_sale.group_pos_user').id]
        if 'baseer.procurement.representative.advance' in self.env:
            groups.append(self.env.ref('baseer_procurement_requests.group_procurement_accountant').id)
        reader = self.env['res.users'].create({
            'name': 'Isolated owner accountant', 'login': 'isolated-owner-restricted-reader',
            'group_ids': [Command.set(groups)], 'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        secured = self.report.with_user(reader).with_context(allowed_company_ids=self.company.ids)
        self.assertTrue(secured.get_owner_snapshot(self.filters)['complete'])
        hidden = payable.matched_credit_ids[:1]
        rule = self.env['ir.rule'].create({
            'name': 'Isolated owner hide reconciliation',
            'model_id': self.env['ir.model']._get('account.partial.reconcile').id,
            'domain_force': f"[('id', '!=', {hidden.id})]",
        })
        try:
            rule.flush_recordset()
            with self.assertRaises(AccessError):
                secured.get_owner_snapshot(self.filters)
        finally:
            rule.unlink()
