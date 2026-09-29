from copy import deepcopy
from decimal import Decimal
import inspect
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import Command, SUPERUSER_ID, api, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.baseer_noorix_migration import karak_payroll_writer as writer
from ..models.migration_models import WRITER_CONTEXT


@tagged('noorix_karak_payroll')
class NoorixKarakPayrollSettlementCase(AccountTestInvoicingCommon):
    """Acceptance coverage for the bounded owner-declared net-payroll move."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.writer_env = api.Environment(
            cls.env.cr,
            SUPERUSER_ID,
            {**cls.env.context, WRITER_CONTEXT: True},
        )
        cls.company = cls.env.company
        cls.bank_journal = cls.company_data['default_journal_bank']
        cls.salary_expense_account = cls.company_data['default_account_expense']
        cls.bank_account = cls.bank_journal.default_account_id
        cls.salary_payable_account = cls.company_data['default_account_payable']
        cls.employee_advance_account = cls.company_data['default_account_receivable']
        cls.migration_run = cls.writer_env['baseer.noorix.migration.run'].create({
            'name': 'NOORIX-KARAK-NET-PAYROLL-TEST',
            'source_archive_sha256': 'karak-payroll-archive',
            'source_tenant_id': 'tenant-karak',
            'payload_sha256': 'karak-payroll-payload',
            'scope': 'payroll_settlement',
        })

    def _move(self, reference='Karak owner-declared net salary'):
        return self.env['account.move'].create({
            'move_type': 'entry',
            'company_id': self.company.id,
            'journal_id': self.bank_journal.id,
            'date': fields.Date.to_date('2026-05-06'),
            'ref': reference,
            'line_ids': [
                Command.create({
                    'name': reference,
                    'account_id': self.salary_expense_account.id,
                    'debit': 10216.67,
                    'credit': 0,
                    'partner_id': False,
                }),
                Command.create({
                    'name': reference,
                    'account_id': self.bank_account.id,
                    'debit': 0,
                    'credit': 10216.67,
                    'partner_id': False,
                }),
            ],
        })

    def _mapping_values(self, move, source_run_id='cmotzl3tn016i11ch29ycedtd'):
        return {
            'source_tenant_id': 'tenant-karak',
            'source_company_id': 'cmnvui7x70001etuf8p6xz3d0',
            'source_payroll_run_id': source_run_id,
            'source_run_number': 'PR-2605-001',
            'source_row_sha256': 'payroll-run-row-sha',
            'source_accrual_rows_sha256': 'five-accrual-rows-sha',
            'source_accrual_count': 5,
            'source_archive_sha256': self.migration_run.source_archive_sha256,
            'canonical_key': 'karak-payroll:' + source_run_id,
            'source_gross_raw': '19266.6700',
            'source_advances_raw': '9050.0000',
            'source_net_raw': '10216.6700',
            'source_period': fields.Date.to_date('2026-04-01'),
            'source_completion_date': fields.Date.to_date('2026-05-06'),
            'target_posting_date': fields.Date.to_date('2026-05-06'),
            'date_basis': 'owner_declaration_plus_source_completion',
            'owner_declaration': 'treat_net_as_paid_from_bank',
            'decision': 'create_owner_declared_bank_move',
            'company_id': self.company.id,
            'journal_id': self.bank_journal.id,
            'salary_expense_account_id': self.salary_expense_account.id,
            'bank_account_id': self.bank_account.id,
            'target_amount': 10216.67,
            'move_id': move.id,
            'run_id': self.migration_run.id,
        }

    def _valid_payload(self):
        return {
            'target_database': writer.TARGET_DATABASE,
            'source_archive_sha256': writer.ARCHIVE_SHA256,
            'approved_policy': writer.APPROVED_POLICY,
            'report': deepcopy(writer.EXPECTED_REPORT),
            'allowlist': deepcopy(writer.EXPECTED_ALLOWLIST),
            'settlement': {
                'source_system': 'noorix',
                'source_tenant_id': writer.SOURCE_TENANT_ID,
                'source_company_id': writer.SOURCE_COMPANY_ID,
                'source_payroll_run_id': writer.SOURCE_PAYROLL_RUN_ID,
                'source_run_number': writer.SOURCE_RUN_NUMBER,
                'source_row_sha256': 'a' * 64,
                'source_accrual_rows_sha256': 'b' * 64,
                'source_accrual_count': 5,
                'source_archive_sha256': writer.ARCHIVE_SHA256,
                'canonical_key': 'payroll-settlement:%s:%s' % (
                    writer.SOURCE_COMPANY_ID,
                    writer.SOURCE_PAYROLL_RUN_ID,
                ),
                'source_gross_raw': '19266.6700',
                'source_advances_raw': '9050.0000',
                'source_net_raw': '10216.6700',
                'source_period': '2026-04-01',
                'source_completion_date': '2026-05-06',
                'target_posting_date': '2026-05-06',
                'date_basis': 'owner_declaration_plus_source_completion',
                'owner_declaration': 'treat_net_as_paid_from_bank',
                'decision': 'create_owner_declared_bank_move',
                'target_company_id': 4,
                'target_journal_id': 62,
                'target_salary_expense_account_id': 708,
                'target_bank_account_id': 792,
                'target_amount': '10216.67',
                'target_reference': writer.TARGET_REFERENCE,
            },
        }

    def _generic_target(self, _env, _payload, _row, check_lock_date=True):
        del check_lock_date
        return self.company, self.bank_journal, {
            708: self.salary_expense_account,
            792: self.bank_account,
            801: self.salary_payable_account,
            802: self.employee_advance_account,
        }

    def _verify_generic_mapping(self, mapping, row, company):
        self.assertEqual(mapping.company_id, company)
        self.assertEqual(mapping.source_payroll_run_id, row['source_payroll_run_id'])
        self.assertEqual(mapping.source_row_sha256, row['source_row_sha256'])
        self.assertEqual(mapping.source_accrual_rows_sha256, row['source_accrual_rows_sha256'])
        self.assertEqual(mapping.date_basis, 'owner_declaration_plus_source_completion')
        self.assertEqual(mapping.owner_declaration, 'treat_net_as_paid_from_bank')
        self.assertEqual(mapping.source_period, fields.Date.to_date('2026-04-01'))
        self.assertEqual(mapping.source_completion_date, fields.Date.to_date('2026-05-06'))
        self.assertEqual(mapping.target_posting_date, fields.Date.to_date('2026-05-06'))
        move = mapping.move_id
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.move_type, 'entry')
        self.assertEqual(move.journal_id, self.bank_journal)
        self.assertEqual(move.ref, writer.TARGET_REFERENCE)
        self.assertFalse(move.partner_id)
        self.assertFalse(move.line_ids.partner_id)
        self.assertEqual(len(move.line_ids), 2)
        debit = move.line_ids.filtered(
            lambda line: line.account_id == self.salary_expense_account
        )
        credit = move.line_ids.filtered(lambda line: line.account_id == self.bank_account)
        self.assertEqual(len(debit), 1)
        self.assertEqual(len(credit), 1)
        self.assertEqual(writer.money(debit.debit), Decimal('10216.67'))
        self.assertEqual(writer.money(debit.credit), Decimal('0.00'))
        self.assertEqual(writer.money(credit.credit), Decimal('10216.67'))
        self.assertEqual(writer.money(credit.debit), Decimal('0.00'))
        self.assertFalse(move.line_ids.filtered(
            lambda line: line.account_id in (
                self.salary_payable_account,
                self.employee_advance_account,
            )
        ))
        self.assertEqual(writer.money(sum(move.line_ids.mapped('balance'))), Decimal('0.00'))
        return move

    def _apply_in_test_company(self, payload=None, payload_sha=None, verifier=None):
        payload = payload or self._valid_payload()
        payload_sha = payload_sha or writer.EXPECTED_PAYLOAD_SHA256
        row = payload['settlement']
        with patch.object(writer, 'TARGET_DATABASE', self.env.cr.dbname), patch.object(
            writer, 'TARGET_BANK_JOURNAL_ID', self.bank_journal.id,
        ), patch.object(
            writer, 'load_payload', return_value=(payload, row, payload_sha),
        ), patch.object(
            writer, '_validate_target', side_effect=self._generic_target,
        ), patch.object(
            writer, '_verify_mapping', side_effect=verifier or self._verify_generic_mapping,
        ):
            return writer.apply_settlement(
                self.env,
                payload_path='unused-in-memory-payroll-payload.json',
                expected_sha256=payload_sha,
            )

    def test_payroll_settlement_map_is_writer_only_write_once_and_append_only(self):
        values = self._mapping_values(self._move())
        with self.assertRaises(AccessError):
            self.env['baseer.noorix.payroll.settlement.map'].create(values)

        mapping = self.writer_env['baseer.noorix.payroll.settlement.map'].create(values)
        self.assertEqual(mapping.run_id.scope, 'payroll_settlement')
        self.assertEqual(mapping.date_basis, 'owner_declaration_plus_source_completion')
        with self.assertRaises(UserError):
            mapping.write({'source_row_sha256': 'changed'})
        with self.assertRaises(AccessError):
            mapping.unlink()

    @mute_logger('odoo.sql_db')
    def test_payroll_source_identity_and_target_move_are_unique(self):
        model = self.writer_env['baseer.noorix.payroll.settlement.map']
        first_move = self._move('Karak first settlement target')
        values = self._mapping_values(first_move)
        model.create(values)

        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            model.create(self._mapping_values(
                self._move('Karak duplicate source target'),
                source_run_id=values['source_payroll_run_id'],
            ))
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            model.create(self._mapping_values(
                first_move,
                source_run_id='different-source-payroll-run',
            ))

    def test_strict_payload_preserves_owner_declared_date_and_source_distinction(self):
        payload = self._valid_payload()
        row = writer.validate_payload(payload)
        self.assertEqual(row['source_period'], '2026-04-01')
        self.assertEqual(row['source_completion_date'], '2026-05-06')
        self.assertEqual(row['target_posting_date'], '2026-05-06')
        self.assertEqual(row['date_basis'], 'owner_declaration_plus_source_completion')
        self.assertEqual(row['owner_declaration'], 'treat_net_as_paid_from_bank')
        self.assertEqual(writer.TARGET_BANK_JOURNAL_ID, 62)
        self.assertEqual(
            payload['allowlist']['salary_expense_account'],
            {'id': 708, 'code': '400003', 'type': 'expense'},
        )
        self.assertEqual(
            payload['allowlist']['bank_account'],
            {'id': 792, 'code': '101001', 'type': 'asset_cash'},
        )
        self.assertEqual(
            payload['allowlist']['unchanged_accounts'],
            [
                {'id': 801, 'code': '201090', 'type': 'liability_payable'},
                {'id': 802, 'code': '102090', 'type': 'asset_receivable'},
            ],
        )

        mutations = (
            ('source payroll identity', 'source_payroll_run_id', 'another-run'),
            ('source period', 'source_period', '2026-05-06'),
            ('source completion date', 'source_completion_date', '2026-05-07'),
            ('owner-declared posting date', 'target_posting_date', '2026-04-01'),
            ('date evidence basis', 'date_basis', 'source_bank_allocation'),
            ('owner declaration', 'owner_declaration', 'source_proved_bank_payment'),
            ('native move reference', 'target_reference', 'PR-2605-001'),
        )
        for label, field_name, value in mutations:
            with self.subTest(label=label):
                candidate = deepcopy(payload)
                candidate['settlement'][field_name] = value
                with self.assertRaisesRegex(UserError, field_name):
                    writer.validate_payload(candidate)

    def test_payload_amounts_are_exact_and_source_raw_values_are_not_floats(self):
        row = writer.validate_payload(self._valid_payload())
        self.assertEqual(
            writer.source_decimal(row['source_gross_raw'])
            - writer.source_decimal(row['source_advances_raw']),
            writer.source_decimal(row['source_net_raw']),
        )
        self.assertEqual(writer.money(row['source_net_raw']), Decimal('10216.67'))
        for invalid in (10216.67, '10216.67', '-1.0000', 'NaN', '1e4', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                writer.source_decimal(invalid)

        for field_name, value in (
            ('source_gross_raw', '19266.6600'),
            ('source_advances_raw', '9049.9900'),
            ('source_net_raw', '10216.6600'),
            ('target_amount', '10216.68'),
        ):
            candidate = self._valid_payload()
            candidate['settlement'][field_name] = value
            with self.subTest(field_name=field_name), self.assertRaises(UserError):
                writer.validate_payload(candidate)

    def test_payload_loader_accepts_only_the_frozen_receipt_hash(self):
        self.assertEqual(
            writer.EXPECTED_PAYLOAD_SHA256,
            '5657a4d93119a0a9faf1e35ebe80649ee390975ed61e3de0c3aade5eda0217df',
        )
        with self.assertRaisesRegex(UserError, 'receipt differs'):
            writer.load_payload(
                path='must-not-be-read-after-receipt-rejection.json',
                expected_sha256='f' * 64,
            )

    def test_apply_creates_one_posted_two_line_move_and_no_forbidden_records(self):
        forbidden_before = writer._forbidden_snapshot(self.env, self.company)
        protected_before = {
            account.id: writer._account_effect(self.env, self.company, account)
            for account in (self.salary_payable_account, self.employee_advance_account)
        }
        move_count = self.env['account.move'].search_count([])
        line_count = self.env['account.move.line'].search_count([])

        result = self._apply_in_test_company()

        mapping = self.writer_env['baseer.noorix.payroll.settlement.map'].browse(
            result['mapping_id']
        )
        move = self._verify_generic_mapping(
            mapping, self._valid_payload()['settlement'], self.company
        )
        self.assertEqual(self.env['account.move'].search_count([]), move_count + 1)
        self.assertEqual(self.env['account.move.line'].search_count([]), line_count + 2)
        self.assertEqual(writer._forbidden_snapshot(self.env, self.company), forbidden_before)
        self.assertEqual(result['payments_created'], 0)
        self.assertEqual(result['vendor_bills_created'], 0)
        self.assertEqual(result['stock_moves_created'], 0)
        self.assertEqual(result['salary_payable_effect'], '0.00')
        self.assertEqual(result['employee_advance_effect'], '0.00')
        self.assertEqual(move.line_ids.mapped('partner_id'), self.env['res.partner'])
        for account in (self.salary_payable_account, self.employee_advance_account):
            self.assertEqual(
                writer._account_effect(self.env, self.company, account),
                protected_before[account.id],
            )

    def test_exact_replay_is_noop_and_changed_payload_hash_is_rejected(self):
        move_count = self.env['account.move'].search_count([])
        first = self._apply_in_test_company()
        replay = self._apply_in_test_company()
        self.assertEqual(replay['status'], 'already_reconciled')
        self.assertEqual(replay['run_id'], first['run_id'])
        self.assertEqual(replay['mapping_id'], first['mapping_id'])
        self.assertEqual(replay['move_id'], first['move_id'])
        self.assertEqual(self.env['account.move'].search_count([]), move_count + 1)

        with self.assertRaisesRegex(UserError, 'changed evidence'):
            self._apply_in_test_company(payload_sha='f' * 64)
        self.assertEqual(self.env['account.move'].search_count([]), move_count + 1)

    def test_changed_source_row_hash_is_rejected_on_mapping_replay(self):
        mapping = self.writer_env['baseer.noorix.payroll.settlement.map'].create(
            self._mapping_values(self._move('Karak source-hash replay target'))
        )
        direct_fields = (
            'source_system', 'source_tenant_id', 'source_company_id',
            'source_payroll_run_id', 'source_run_number', 'source_row_sha256',
            'source_accrual_rows_sha256', 'source_archive_sha256', 'canonical_key',
            'source_gross_raw', 'source_advances_raw', 'source_net_raw', 'date_basis',
            'owner_declaration', 'decision',
        )
        row = {field_name: mapping[field_name] for field_name in direct_fields}
        row['source_row_sha256'] = 'changed-source-row-hash'
        with self.assertRaisesRegex(UserError, 'source_row_sha256'):
            writer._verify_mapping(mapping, row, self.company)

    def test_writer_locks_before_replay_lookup_and_owns_no_transaction_boundary(self):
        source = inspect.getsource(writer.apply_settlement)
        lock_position = source.index('pg_advisory_xact_lock')
        self.assertLess(lock_position, source.index('existing_run = Run.search'))
        self.assertLess(lock_position, source.index('SettlementMap.search'))
        self.assertNotIn('.commit(', source)
        self.assertNotIn('.savepoint(', source)

    def test_caller_rollback_removes_run_move_lines_and_mapping_atomically(self):
        tracked_models = (
            'baseer.noorix.migration.run',
            'baseer.noorix.payroll.settlement.map',
            'account.move',
            'account.move.line',
            'account.payment',
            'stock.move',
            'stock.picking',
        )
        before = {
            model: (
                self.writer_env[model]
                if model.startswith('baseer.noorix.') else self.env[model]
            ).search_count([])
            for model in tracked_models
        }

        with self.assertRaisesRegex(RuntimeError, 'injected payroll failure'):
            with self.env.cr.savepoint():
                self._apply_in_test_company(
                    verifier=lambda *_args: (_ for _ in ()).throw(
                        RuntimeError('injected payroll failure')
                    )
                )

        for model in tracked_models:
            records = (
                self.writer_env[model]
                if model.startswith('baseer.noorix.') else self.env[model]
            )
            self.assertEqual(records.search_count([]), before[model])
