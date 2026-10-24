"""Full export, not the visible keyset page; reject hidden source rows."""

from datetime import date
from decimal import Decimal
from io import BytesIO
import os
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.baseer_reports_menu.report_values import export_document, source_money

from .test_activity import TestAccountActivity


@tagged('post_install', '-at_install', 'reports_unified_export')
class TestActivityUnifiedExport(TransactionCase):
    _entry = TestAccountActivity._entry

    def setUp(self):
        super().setUp()
        self.env['res.lang']._activate_lang('ar_001')
        self.company = self.env.company
        self.asset = self.env['account.account'].create({
            'code': '915019', 'name': 'Unified activity asset', 'account_type': 'asset_current',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.counterpart = self.env['account.account'].search([
            ('company_ids', 'in', self.company.id), ('account_type', '=', 'expense')], limit=1)
        self.journal = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        self.report = self.env['baseer.account.activity']
        self.filters = {'company_id': self.company.id, 'account_id': self.asset.id,
                        'date_from': '2041-03-01', 'date_to': '2041-03-31'}
        self._entry(date(2041, 2, 1), self.asset, debit=15, label='Opening')
        self.first = self._entry(date(2041, 3, 2), self.asset, debit=20, label='First')
        self._entry(date(2041, 3, 3), self.asset, credit=5, label='Second')
        self._entry(date(2041, 3, 4), self.asset, debit=2, label='Third')
        self.reader = self.env['res.users'].create({
            'name': 'Activity export reader', 'login': 'activity.export.reader',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                      self.env.ref('account.group_account_readonly').id])],
        })

    def test_complete_paginated_projection_and_native_files(self):
        report = self.report.with_user(self.reader).with_context(allowed_company_ids=self.company.ids)
        with patch.object(type(report), 'PAGE_SIZE', 2):
            document = report._get_export_document(self.filters)
        self.assertEqual(len(document['rows']), 5)
        self.assertEqual([row['cells']['running'] for row in document['rows']],
                         list(map(Decimal, ['15', '35', '30', '32', '32'])))
        self.assertEqual(document['rows'][-1]['cells']['debit'], Decimal('22'))
        self.assertEqual(document['rows'][-1]['cells']['credit'], Decimal('5'))
        engine = self.env['baseer.report.export'].with_user(self.reader).with_context(
            allowed_company_ids=self.company.ids, lang='ar_001')
        target = os.environ.get('BASEER_EXPORT_EVIDENCE_DIR')
        for file_format in ('xlsx', 'pdf'):
            payload, _mime, _name = engine._export('activity', self.filters, file_format)
            if target and os.path.isdir(target):
                Path(target, 'activity-export-ar.' + file_format).write_bytes(payload)
            if file_format == 'xlsx':
                sheet = load_workbook(BytesIO(payload)).active
                self.assertTrue(sheet.sheet_view.rightToLeft)
                self.assertTrue(all(cell.hyperlink is None and cell.data_type != 'f' for row in sheet for cell in row))
                self.assertTrue(any(cell.value == 32 for row in sheet for cell in row))
            else:
                self.assertTrue(payload.startswith(b'%PDF-'))

    def test_scope_cap_and_hidden_source_fail_closed(self):
        with self.assertRaises(AccessError):
            self.report._get_export_document({**self.filters, 'company_id': self.company.id + 999999})
        with self.assertRaises(ValidationError):
            self.report._get_export_document({**self.filters, 'domain': []})
        with patch.object(type(self.report), 'EXPORT_SOURCE_LIMIT', 1):
            with self.assertRaises(ValidationError):
                self.report._get_export_document(self.filters)
        self.env['ir.rule'].create({
            'name': 'Activity export hide a source line',
            'model_id': self.env['ir.model']._get_id('account.move.line'),
            'domain_force': "[('id', '!=', %s)]" % self.first.id,
        })
        with self.assertRaises(AccessError):
            self.report.with_user(self.reader).with_context(
                allowed_company_ids=self.company.ids)._get_export_document(self.filters)

    def test_denied_user_and_exact_value_helper(self):
        plain = self.env['res.users'].create({
            'name': 'Activity export plain user', 'login': 'activity.export.plain',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set(self.env.ref('base.group_user').ids)],
        })
        with self.assertRaises(AccessError):
            self.report.with_user(plain)._get_export_document(self.filters)
        for value in (1.2, float('nan'), True, '12,34', '=1+1', Decimal('NaN')):
            with self.assertRaises(ValidationError):
                source_money(value)
        self.assertEqual(source_money('-1,234.50'), Decimal('-1234.50'))
        self.assertIsNone(source_money(None))

    def test_final_document_caps_have_localized_scope_guidance(self):
        columns = [{'key': 'label', 'label': 'Label', 'type': 'text'}]
        row = {'kind': 'detail', 'cells': {'label': 'Source'}}
        with self.assertRaisesRegex(ValidationError, 'shorter period'):
            export_document(self.env(context=dict(self.env.context, lang='en_US')),
                            'Report', columns, [row] * 5001)
        many_columns = [{'key': 'column' + str(index), 'label': str(index), 'type': 'text'}
                        for index in range(11)]
        with self.assertRaisesRegex(ValidationError, 'قلّل فترات المقارنة'):
            export_document(self.env(context=dict(self.env.context, lang='ar_001')),
                            'تقرير', many_columns, [row] * 4600)

    def test_hidden_opening_move_and_journal_are_denied(self):
        opening = self.env['account.move.line'].search([
            ('account_id', '=', self.asset.id), ('date', '<', self.filters['date_from'])], limit=1)
        for model, identity in [('account.move.line', opening.id),
                                ('account.move', opening.move_id.id),
                                ('account.journal', self.journal.id)]:
            rule = self.env['ir.rule'].create({
                'name': 'Activity export hidden related source',
                'model_id': self.env['ir.model']._get_id(model),
                'domain_force': "[('id', '!=', %s)]" % identity,
            })
            with self.assertRaises(AccessError):
                self.report.with_user(self.reader).with_context(
                    allowed_company_ids=self.company.ids)._get_export_document(self.filters)
            rule.unlink()

    def test_empty_period_negative_and_malformed_cursor(self):
        empty = self.report._get_export_document({**self.filters,
            'date_from': '2041-04-01', 'date_to': '2041-04-30'})
        self.assertEqual(len(empty['rows']), 2)
        self.assertEqual(empty['rows'][-1]['cells']['running'], Decimal('32'))
        self._entry(date(2041, 3, 5), self.asset, credit=50, label='Negative closing')
        document = self.report._get_export_document(self.filters)
        self.assertEqual(document['rows'][-1]['cells']['running'], Decimal('-18'))
        arguments = [self.filters[key] for key in ('company_id', 'account_id', 'date_from', 'date_to')]
        page = self.report.get_activity(*arguments)
        page['next_cursor'] = {'date': '2041-03-01', 'id': 999999}
        with patch.object(type(self.report), 'get_activity', return_value=page):
            with self.assertRaises(ValidationError):
                self.report._get_export_document(self.filters)
