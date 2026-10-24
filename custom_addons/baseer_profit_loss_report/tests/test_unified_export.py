"""Focused unified-export parity and boundary checks; all data is synthetic."""

from decimal import Decimal
from io import BytesIO
import os
import logging
import re
from uuid import uuid4
from time import perf_counter
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from openpyxl import load_workbook
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.baseer_reports_menu.report_values import source_money
from .test_profit_loss import TestProfitLoss
from ..models.profit_loss import SECTION_KEYS
from ..report.profit_loss_report import LABELS

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'reports_unified_export')
class TestUnifiedExport(TransactionCase):
    _entry = TestProfitLoss._entry
    _accountant = TestProfitLoss._accountant
    _hide_record = TestProfitLoss._hide_record

    def setUp(self):
        super().setUp()
        self.env['res.lang']._activate_lang('ar_001')
        self.company = self.env.company
        self.company.write({'fiscalyear_last_day': 31, 'fiscalyear_last_month': '12'})
        self.report = self.env['baseer.profit.loss.report']
        self.filters = {'company_id': self.company.id, 'date_from': '2044-10-01',
                        'date_to': '2044-10-31', 'journal_ids': []}
        accounts = self.env['account.account'].with_company(self.company)
        for index, (name, kind) in enumerate((('cash', 'asset_cash'), ('income', 'income'), ('expense', 'expense')), 1):
            setattr(self, name, accounts.create({'code': '9624' + str(index),
                'name': 'Unified profit_loss ' + name, 'account_type': kind,
                'company_ids': [Command.set(self.company.ids)]}))
        self.accounts = {'income': self.income, 'expense': self.expense}
        self.balance = self.cash
        self.journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        self.assertTrue(self.journal)
        self._entry('income', 120, day='2044-10-10')
        self._entry('expense', 40, day='2044-10-11')

    def test_source_parity_as_readonly_accountant(self):
        report = self.report.with_user(self._accountant()).sudo(False).with_context(allowed_company_ids=self.company.ids)
        doc = report._get_export_document(self.filters)
        source = report.get_report(self.filters)
        summary = [row for row in doc['rows'] if row.get('indent', 0) == 0]
        self.assertEqual(len(summary), len(source['rows']))
        for actual, expected in zip(summary, source['rows']):
            for period in source['periods']:
                self.assertEqual(actual['cells'][period['key']], source_money(expected['amounts'][period['key']]['amount']))
        expense = next(row for row in doc['rows'] if row['cells']['label'] == f"{self.expense.code} {self.expense.name}")
        self.assertEqual(expense['cells']['current'], Decimal('40.00'))

    def test_denied_foreign_and_tampered_filters(self):
        denied = self.env['res.users'].create({'name': 'Export denied profit_loss', 'login': 'export_denied_profit_loss',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)]})
        with self.assertRaises(AccessError):
            self.report.with_user(denied).sudo(False)._get_export_document(self.filters)
        other = self.env['res.company'].create({'name': 'Foreign export profit_loss'})
        with self.assertRaises(AccessError):
            self.report.with_context(allowed_company_ids=[self.company.id, other.id])._get_export_document(dict(self.filters, company_id=other.id))
        with self.assertRaises(ValidationError):
            self.report._get_export_document(dict(self.filters, amount='999.99'))

    def test_document_cap_fails_without_truncation(self):
        grouped = {key: [] for key in SECTION_KEYS}
        grouped['income'] = [{'account': SimpleNamespace(id=index), 'raw': Decimal('1')}
                             for index in range(5001)]
        with patch.object(type(self.report), '_section_rows', return_value=grouped), \
             patch.object(type(self.report), '_revenue_channels') as channels, self.assertRaises(ValidationError):
            self.report._get_export_document(self.filters)
        channels.assert_not_called()
        # Optional channel rows count toward the same complete-document cap.
        channels = {self.income.id: {f'payment_{index}': ('Synthetic channel', Decimal('0'))
                                   for index in range(5001)}}
        with patch.object(type(self.report), '_revenue_channels', return_value=channels), self.assertRaises(ValidationError):
            self.report._get_export_document(self.filters)

    def _legacy_export_rows(self, report, filters):
        """Old paged export traversal retained only as a parity oracle."""
        source = report.get_report(filters)
        result = []
        arabic = (report.env.lang or '').startswith('ar')

        def append(label, amounts, kind='detail', indent=0):
            result.append({'kind': kind, 'indent': indent, 'cells': {'label': label,
                **{period['key']: source_money(amounts[period['key']]['amount']) for period in source['periods']}}})

        for row in source['rows']:
            append(LABELS.get(row['key'], (row['label'], row['label']))[0 if arabic else 1],
                   row['amounts'], 'total' if row['kind'] == 'result' else row['kind'])
            if not row.get('expandable'):
                continue
            page, count = 1, 0
            while True:
                detail = report.get_accounts(filters, row['section'], page)
                for account in detail['accounts']:
                    append(f"{account['code']} {account['name']}".strip(), account['amounts'], indent=1)
                    for channel in account['channels']:
                        append(channel['name'], channel['amounts'], indent=2)
                count += len(detail['accounts'])
                if count == detail['total_count']:
                    break
                self.assertTrue(detail['accounts'])
                page += 1
        return result

    def test_full_legacy_parity_comparisons_journals_negative_and_single_collection(self):
        other = self.env['account.journal'].create({'name': 'Export parity alternate', 'code': 'EPP',
            'type': 'general', 'company_id': self.company.id})
        self._entry('income', -150, day='2044-10-12', journal=other)
        self._entry('income', 37, day='2044-09-10')
        self._entry('expense', -9, day='2044-09-11')
        for index, kind in enumerate(('income_other', 'expense_depreciation'), 1):
            self.accounts[kind] = self.env['account.account'].create({'code': '96249' + str(index),
                'name': 'Export parity ' + kind, 'account_type': kind,
                'company_ids': [Command.set(self.company.ids)]})
            self._entry(kind, index * 3, day='2044-10-12')
        report = self.report.with_user(self._accountant()).sudo(False).with_context(allowed_company_ids=self.company.ids)
        for lang in ('en_US', 'ar_001'):
            localized = report.with_context(lang=lang)
            for journals in ([], [other.id]):
                filters = dict(self.filters, journal_ids=journals,
                    comparison={'kind': 'previous_periods', 'count': 2, 'order': 'ascending'})
                # Force multiple lazy pages to ensure the export is not page-truncated.
                started, query_start = perf_counter(), self.env.cr.sql_log_count
                with patch.object(type(report), 'PAGE_SIZE', 1):
                    expected = self._legacy_export_rows(localized, filters)
                legacy_seconds, legacy_queries = perf_counter() - started, self.env.cr.sql_log_count - query_start
                started, query_start = perf_counter(), self.env.cr.sql_log_count
                with patch.object(type(report), '_section_rows', wraps=localized._section_rows) as groups, \
                     patch.object(type(report), '_revenue_channels', wraps=localized._revenue_channels) as channels:
                    actual = localized._get_export_document(filters)
                self.assertEqual(actual['rows'], expected)
                self.assertEqual(groups.call_count, len(actual['columns']) - 1)
                self.assertEqual(channels.call_count, len(actual['columns']) - 1)
                _logger.info('PL_EXPORT_SYNTHETIC_REUSE lang=%s filtered=%s legacy_s=%.4f legacy_queries=%s '
                             'optimized_s=%.4f optimized_queries=%s; not a QA latency certificate',
                             lang, bool(journals), legacy_seconds, legacy_queries,
                             perf_counter() - started, self.env.cr.sql_log_count - query_start)
        # A new request must collect again rather than reusing stale company/context data.
        self._entry('income', 13, day='2044-10-14')
        self.assertEqual(report._get_export_document(self.filters)['rows'],
                         self._legacy_export_rows(report, self.filters))

    def test_empty_export_avoids_optional_pos_collection(self):
        filters = dict(self.filters, date_from='2045-01-01', date_to='2045-01-31')
        with patch.object(type(self.report), '_revenue_channels') as channels:
            doc = self.report._get_export_document(filters)
        channels.assert_not_called()
        self.assertEqual(len(doc['rows']), 9)
        self.assertTrue(all(row['cells']['current'] == Decimal('0') for row in doc['rows']))

    def test_channel_budget_exact_boundary_and_comparison_union(self):
        # 9 summary rows + 2 account rows leave exactly 4,989 channel rows.
        channels = {self.income.id: {f'payment_{index}': ('Synthetic channel', Decimal('0'))
                                   for index in range(4989)}}
        filters = dict(self.filters, comparison={'kind': 'previous_period', 'count': 1, 'order': 'ascending'})
        with patch.object(type(self.report), '_revenue_channels', return_value=channels):
            self.assertEqual(len(self.report._get_export_document(filters)['rows']), 5000)
        channels[self.income.id]['payment_extra'] = ('Only comparison', Decimal('0'))
        with patch.object(type(self.report), '_revenue_channels', side_effect=[channels, {}]), \
             patch.object(type(self.report), '_account_section') as projection, self.assertRaises(ValidationError):
            self.report._get_export_document(filters)
        projection.assert_not_called()
        budget = {'keys': set(), 'limit': 1}
        self.report._claim_export_channel(budget, self.income.id, 'same')
        self.report._claim_export_channel(budget, self.income.id, 'same')
        with self.assertRaises(ValidationError):
            self.report._claim_export_channel(budget, self.income.id, 'new')

    def _native_channel_orders(self, count=2):
        if 'pos.order' not in self.env:
            self.skipTest('Native POS is optional; covered by the all-provider runtime.')
        receivable = self.env['account.account'].create({'code': '962481', 'name': 'PL POS receivable',
            'account_type': 'asset_receivable', 'reconcile': True, 'company_ids': [Command.set(self.company.ids)]})
        sale = self.env['account.journal'].create({'name': 'PL POS sale', 'code': 'PPS', 'type': 'sale',
                                                 'company_id': self.company.id})
        cash = self.env['account.journal'].create({'name': 'PL POS cash', 'code': 'PPC', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': self.cash.id})
        method = self.env['pos.payment.method'].create({'name': 'PL batch cash', 'company_id': self.company.id,
            'journal_id': cash.id, 'receivable_account_id': receivable.id})
        config = self.env['pos.config'].create({'name': 'PL batch POS', 'company_id': self.company.id,
            'journal_id': sale.id, 'invoice_journal_id': sale.id, 'cash_control': False,
            'payment_method_ids': [Command.set(method.ids)]})
        session = self.env['pos.session'].create({'config_id': config.id})
        session.set_opening_control(0, 'Synthetic PL channel fixture')
        product = self.env['product.product'].create({'name': 'PL synthetic native item', 'type': 'service',
            'available_in_pos': True, 'property_account_income_id': self.income.id, 'taxes_id': [Command.clear()]})
        orders = self.env['pos.order']
        for _index in range(count):
            orders |= self.env['pos.order'].create({'session_id': session.id, 'company_id': self.company.id,
                'state': 'paid', 'source': 'pos', 'date_order': '2044-10-18 12:00:00',
                'amount_total': 100, 'amount_tax': 0, 'amount_paid': 100, 'amount_return': 0,
                'lines': [Command.create({'product_id': product.id, 'uuid': str(uuid4()), 'qty': 1,
                    'price_unit': 100, 'price_subtotal': 100, 'price_subtotal_incl': 100,
                    'full_product_name': product.display_name, 'tax_ids': [Command.clear()]})],
                'payment_ids': [Command.create({'payment_method_id': method.id, 'amount': 100})]})
        move = self._entry('income', count * 100, day='2044-10-18')
        orders.account_move = move
        reader = self._accountant()
        reader.write({'group_ids': [Command.link(self.env.ref('point_of_sale.group_pos_manager').id)]})
        return orders, move, self.report.with_user(reader).sudo(False).with_context(allowed_company_ids=self.company.ids)

    def _native_channels(self, report, move, scalar=False):
        from odoo.fields import Domain
        domain = Domain('move_id', '=', move.id) & Domain('account_id', '=', self.income.id)
        if not scalar:
            return report._revenue_channels(self.company, domain)

        def scalar_census(orders):
            result = {'lines': {}, 'payments': {}}
            for order in orders:
                for key, query in (
                    ('lines', 'SELECT id FROM pos_order_line WHERE order_id=%s'),
                    ('payments', 'SELECT id FROM pos_payment WHERE pos_order_id=%s'),
                ):
                    self.env.cr.execute(query, [order.id])
                    result[key][order.id] = {row[0] for row in self.env.cr.fetchall()}
            return result

        with patch.object(type(report), '_channel_child_ids', new=lambda model, orders: scalar_census(orders)):
            return report._revenue_channels(self.company, domain)

    def test_native_census_constant_queries_and_fresh_scalar_parity(self):
        orders, move, report = self._native_channel_orders(8)
        original = type(self.env.cr).execute

        def query_count(selected):
            calls = []
            def execute(cursor, query, *args, **kwargs):
                sql = re.sub(r'\s+', ' ', str(getattr(query, 'code', query))).lower()
                if sql.startswith(('select order_id, id from pos_order_line', 'select pos_order_id, id from pos_payment')):
                    calls.append(sql)
                return original(cursor, query, *args, **kwargs)
            with patch.object(type(self.env.cr), 'execute', new=execute):
                census = report._channel_child_ids(selected.with_env(report.env))
            self.assertEqual(census['lines'], {order.id: set(order.lines.ids) for order in selected})
            self.assertEqual(census['payments'], {order.id: set(order.payment_ids.ids) for order in selected})
            return len(calls)

        self.assertEqual(query_count(orders[:2]), 2)
        self.assertEqual(query_count(orders), 2)
        expected = self._native_channels(report, move, scalar=True)
        self.assertEqual(self._native_channels(report, move), expected)
        self.assertEqual(sum(value for _name, value in expected[self.income.id].values()), Decimal('800'))
        # A posted payment is immutable. Change its reader visibility legally,
        # then prove a fresh request cannot reuse the earlier successful evidence.
        rule = self._hide_record('pos.payment', orders[:1].payment_ids)
        try:
            report.env.invalidate_all()
            injected = report.with_context(pl_channel_child_ids={'payments': {}}, pl_verified=True)
            actual = self._native_channels(injected, move)
            self.assertEqual(actual, self._native_channels(report, move, scalar=True))
            self.assertNotEqual(actual, expected)
            self.assertEqual(actual[self.income.id]['unallocated'][1], Decimal('100'))
        finally:
            rule.unlink()
        report.env.invalidate_all()
        self.assertEqual(self._native_channels(report, move), expected)

    def test_native_hidden_child_keeps_original_fallback_scope(self):
        orders, move, report = self._native_channel_orders()
        method = orders.payment_ids.payment_method_id
        for model, record, unallocated in (
            ('pos.order.line', orders[:1].lines, Decimal('200')),
            ('pos.payment', orders[:1].payment_ids, Decimal('100')),
            ('pos.order', orders[:1], Decimal('200')),
            ('pos.session', orders.session_id, Decimal('200')),
            ('pos.payment.method', method, Decimal('200')),
        ):
            rule = self._hide_record(model, record)
            try:
                report.env.invalidate_all()
                actual = self._native_channels(report, move)
                self.assertEqual(actual, self._native_channels(report, move, scalar=True))
                self.assertEqual(actual[self.income.id]['unallocated'][1], unallocated)
                self.assertTrue(all(isinstance(name, str) and isinstance(amount, Decimal)
                                    for name, amount in actual[self.income.id].values()))
                if model == 'pos.payment':
                    self.assertEqual(actual[self.income.id][f'payment_{method.id}'][1], Decimal('100'))
            finally:
                rule.unlink()
        other = self.env['res.company'].create({'name': 'PL foreign channel company'})
        visible = orders[:1].with_env(report.env)
        proof = report._channel_child_ids(visible)
        self.assertEqual(report._order_channels(visible, Decimal('100'), other,
                         _payment_ids=proof['payments'][visible.id]), {'unallocated': ('', Decimal('100'))})

    def test_export_rejects_hidden_linked_records(self):
        reader = self._accountant()
        move = self._entry('income', 7, day='2044-10-13')
        for model, record in (('account.move', move), ('account.account', self.income), ('account.journal', self.journal)):
            rule = self._hide_record(model, record)
            try:
                with self.assertRaises(AccessError):
                    self.report.with_user(reader).sudo(False)._get_export_document(self.filters)
            finally:
                rule.unlink()

    def test_comparison_columns_preserve_server_order_and_signed_results(self):
        filters = dict(self.filters, comparison={'kind': 'previous_periods', 'count': 2, 'order': 'ascending'})
        source = self.report.get_report(filters)
        doc = self.report._get_export_document(filters)
        self.assertEqual([column['key'] for column in doc['columns'][1:]], [period['key'] for period in source['periods']])
        summary = [row for row in doc['rows'] if row.get('indent', 0) == 0]
        for exported, original in zip(summary, source['rows']):
            for period in source['periods']:
                self.assertEqual(exported['cells'][period['key']], source_money(original['amounts'][period['key']]['amount']))

    def test_actual_files_and_optional_visual_evidence(self):
        exports = self.env['baseer.report.export']
        for lang, suffix in (('en_US', 'en'), ('ar_001', 'ar')):
            for file_format in ('xlsx', 'pdf'):
                payload, mime, filename = exports.with_context(lang=lang)._export('profit_loss', self.filters, file_format)
                self.assertTrue(filename.endswith('.' + file_format))
                if file_format == 'xlsx':
                    sheet = load_workbook(BytesIO(payload)).active
                    self.assertEqual(sheet.sheet_view.rightToLeft, suffix == 'ar')
                    for row in sheet:
                        for cell in row:
                            self.assertIsNone(cell.hyperlink)
                            self.assertNotEqual(cell.data_type, 'f')
                    self.assertTrue(any(cell.data_type == 'n' and cell.value is not None for row in sheet for cell in row))
                else:
                    self.assertEqual(mime, 'application/pdf')
                    self.assertTrue(payload.startswith(b'%PDF-'))
                target = os.environ.get('BASEER_EXPORT_EVIDENCE_DIR')
                if target and os.path.isdir(target):
                    Path(target, 'profit_loss-export-' + suffix + '.' + file_format).write_bytes(payload)
