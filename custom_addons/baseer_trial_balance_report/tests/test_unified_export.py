"""Focused unified-export parity and boundary checks; all data is synthetic."""

from decimal import Decimal
from io import BytesIO
import os
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.baseer_reports_menu.report_values import source_money
from .test_trial_balance import TestTrialBalance


@tagged('post_install', '-at_install', 'reports_unified_export')
class TestUnifiedExport(TransactionCase):
    _entry = TestTrialBalance._entry
    _accountant = TestTrialBalance._accountant

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.write({'fiscalyear_last_day': 31, 'fiscalyear_last_month': '12'})
        self.report = self.env['baseer.trial.balance.report']
        self.filters = {'company_id': self.company.id, 'date_from': '2044-10-01',
                        'date_to': '2044-10-31', 'journal_ids': []}
        accounts = self.env['account.account'].with_company(self.company)
        for index, (name, kind) in enumerate((('cash', 'asset_cash'), ('income', 'income'), ('expense', 'expense')), 1):
            setattr(self, name, accounts.create({'code': '9622' + str(index),
                'name': 'Unified trial_balance ' + name, 'account_type': kind,
                'company_ids': [Command.set(self.company.ids)]}))
        self.accounts = {'income': self.income, 'expense': self.expense}
        self.balance = self.cash
        self.journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        self.assertTrue(self.journal)
        self._entry('2044-10-10', self.cash, self.income, 120)
        self._entry('2044-10-11', self.expense, self.cash, 40)

    def test_source_parity_as_readonly_accountant(self):
        report = self.report.with_user(self._accountant()).sudo(False).with_context(allowed_company_ids=self.company.ids)
        doc = report._get_export_document(self.filters)
        source = report._build_trial_balance(self.filters, full=True)
        keys = ('opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit')
        for account in source['accounts']:
            cell = next(row['cells'] for row in doc['rows'] if row['cells']['label'] == f"{account['code']} {account['name']}".strip())
            self.assertEqual({key: cell[key] for key in keys}, {key: source_money(account[key]) for key in keys})
        self.assertEqual({key: doc['rows'][-1]['cells'][key] for key in keys}, {key: source_money(source['total'][key]) for key in keys})

    def test_denied_foreign_and_tampered_filters(self):
        denied = self.env['res.users'].create({'name': 'Export denied trial_balance', 'login': 'export_denied_trial_balance',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)]})
        with self.assertRaises(AccessError):
            self.report.with_user(denied).sudo(False)._get_export_document(self.filters)
        other = self.env['res.company'].create({'name': 'Foreign export trial_balance'})
        with self.assertRaises(AccessError):
            self.report.with_context(allowed_company_ids=[self.company.id, other.id])._get_export_document(dict(self.filters, company_id=other.id))
        with self.assertRaises(ValidationError):
            self.report._get_export_document(dict(self.filters, amount='999.99'))

    def test_document_cap_fails_without_truncation(self):
        source = self.report._build_trial_balance(self.filters, full=True)
        source['accounts'] = [source['accounts'][0]] * 5001
        with patch.object(type(self.report), '_build_trial_balance', return_value=source), self.assertRaises(ValidationError):
            self.report._get_export_document(self.filters)

    def test_actual_files_and_optional_visual_evidence(self):
        exports = self.env['baseer.report.export']
        for lang, suffix in (('en_US', 'en'), ('ar_001', 'ar')):
            for file_format in ('xlsx', 'pdf'):
                payload, mime, filename = exports.with_context(lang=lang)._export('trial_balance', self.filters, file_format)
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
                    Path(target, 'trial_balance-export-' + suffix + '.' + file_format).write_bytes(payload)
