"""Regression tests for migration of already-posted employee receivables.

All records in this module are fictitious and live in the isolated test DB.
"""

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from psycopg2 import IntegrityError
from unittest import TestCase
from unittest.mock import patch


@tagged('post_install', '-at_install')
class LegacyAdvanceMigrationCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.write({'group_ids': [Command.link(cls.env.ref(xmlid).id) for xmlid in (
            'account.group_account_user', 'account.group_account_manager',
            'hr.group_hr_manager', 'om_hr_payroll.group_hr_payroll_manager',
        )]})
        cls.company = cls.env.company
        def account(code, kind, reconcile=False):
            return cls.env['account.account'].create({
                'code': code, 'name': 'Legacy test ' + code,
                'account_type': kind, 'reconcile': reconcile,
                'company_ids': [Command.set(cls.company.ids)],
            })
        cls.expense = account('978101', 'expense')
        cls.payable = account('978102', 'liability_payable', True)
        cls.advance = account('978103', 'asset_receivable', True)
        cls.other_deduction = account('978104', 'income_other')
        cls.opening = account('978105', 'equity')
        cls.cash = account('978106', 'asset_cash')
        cls.journal = cls.env['account.journal'].create({
            'name': 'Legacy test payroll', 'code': 'LGP', 'type': 'general',
            'company_id': cls.company.id,
        })
        cls.bank = cls.env['account.journal'].create({
            'name': 'Legacy test bank', 'code': 'LGB', 'type': 'bank',
            'company_id': cls.company.id, 'default_account_id': cls.cash.id,
        })
        cls.payroll_analytic = cls.env['account.analytic.account'].create({
            'name': 'Legacy test payroll cost',
            'plan_id': cls.env.ref('baseer_payroll.payroll_cost_plan').id,
            'company_id': cls.company.id,
        })
        cls.company.write({
            'baseer_salary_expense_id': cls.expense.id,
            'baseer_salary_payable_id': cls.payable.id,
            'baseer_loan_account_id': cls.advance.id,
            'baseer_deduction_account_id': cls.other_deduction.id,
            'baseer_payroll_journal_id': cls.journal.id,
            'baseer_payroll_analytic_account_id': cls.payroll_analytic.id,
            'baseer_payroll_analytic_enabled': True,
            'baseer_structure_id': False,
        })
        cls.work_partner = cls.env['res.partner'].create({
            'name': 'Current work contact', 'company_id': cls.company.id,
            'property_account_payable_id': cls.payable.id,
            'property_account_receivable_id': cls.advance.id,
        })
        cls.historical_partner = cls.env['res.partner'].create({
            'name': 'Prior accounting contact', 'company_id': cls.company.id,
            'property_account_receivable_id': cls.advance.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Legacy fictional employee', 'company_id': cls.company.id,
            'work_contact_id': cls.work_partner.id, 'baseer_payroll_enabled': True,
        })
        cls.employee.version_id.write({
            'date_version': '2026-01-01', 'contract_date_start': '2026-01-01',
            'wage': 2000, 'baseer_salary_mode': 'fixed',
        })

    def _posted_opening(self, rows, date='2026-05-31'):
        """Rows: (source reference, amount, partner). No cash is posted."""
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.journal.id,
            'company_id': self.company.id, 'date': date,
            'ref': 'Fictional source opening',
            'line_ids': [Command.create({
                'name': ref, 'account_id': self.advance.id,
                'partner_id': partner.id, 'debit': amount,
            }) for ref, amount, partner in rows] + [Command.create({
                'name': 'Opening balance', 'account_id': self.opening.id,
                'credit': sum(amount for _, amount, _ in rows),
            })],
        })
        move.action_post()
        self.assertEqual(move.state, 'posted')
        return move

    def _legacy(self, line, ref, amount, date='2026-03-01', original=None, recovered=0):
        loan = self.env['baseer.hr.loan'].create({
            'name': 'Historical ' + ref, 'company_id': self.company.id,
            'employee_id': self.employee.id, 'source_type': 'legacy',
            'source_reference': ref, 'principal_line_id': line.id,
            'historical_original_amount': amount if original is None else original,
            'historical_recovery_amount': recovered,
            'historical_recovery_evidence': 'Prior fictional payroll recovery' if recovered else False,
            'legacy_identity_evidence': 'Fictitious test identity cross-check',
            'amount': amount, 'date': date,
        })
        loan.action_attest_legacy_identity()
        return loan

    def _run(self, month='2026-06-01'):
        run = self.env['hr.payslip.run'].create({
            'baseer_managed': True, 'baseer_month': month, 'company_id': self.company.id,
        })
        run.slip_ids.filtered(lambda slip: slip.employee_id != self.employee).unlink()
        self.assertEqual(len(run.slip_ids), 1)
        return run, run.slip_ids

    def test_opening_link_uses_only_its_own_posted_line_and_no_cash(self):
        move = self._posted_opening([
            ('ADV-T001', 300, self.historical_partner),
            ('ADV-T002', 200, self.historical_partner),
        ])
        lines = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        cash_before = self.env['account.move.line'].search_count([('account_id', '=', self.cash.id)])
        first = self._legacy(lines.filtered(lambda row: row.name == 'ADV-T001'), 'ADV-T001', 300)
        second = self._legacy(lines.filtered(lambda row: row.name == 'ADV-T002'), 'ADV-T002', 200)
        first.action_link_legacy()
        second.action_link_legacy()
        self.assertEqual((first.state, second.state), ('running', 'running'))
        self.assertEqual((first.balance, second.balance), (300, 200))
        self.assertEqual(first._principal_lines(), lines.filtered(lambda row: row.name == 'ADV-T001'))
        self.assertEqual(second._principal_lines(), lines.filtered(lambda row: row.name == 'ADV-T002'))
        self.assertEqual(self.env['account.move.line'].search_count([('account_id', '=', self.cash.id)]), cash_before)
        self.assertFalse(first.line_ids | second.line_ids, 'No fictitious fixed installments should be created')

    def test_noorix_import_draft_cannot_disburse_even_before_conversion(self):
        loan = self.env['baseer.hr.loan'].create({
            'name': 'Noorix ADV-20260531-001 | DRAFT ONLY',
            'employee_id': self.employee.id, 'amount': 300, 'journal_id': self.bank.id,
        })
        count = self.env['account.move'].search_count([])
        with self.assertRaises(UserError), self.cr.savepoint():
            loan.write({'name': 'Ordinary advance', 'repayment_mode': 'flexible'})
        with self.assertRaises(UserError):
            loan.action_disburse()
        self.assertEqual(loan.state, 'draft')
        self.assertEqual(self.env['account.move'].search_count([]), count)

    def test_reversed_opening_cannot_be_linked(self):
        move = self._posted_opening([('ADV-REVERSED', 300, self.work_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        loan = self._legacy(line, 'ADV-REVERSED', 300)
        move._reverse_moves()
        with self.assertRaises(ValidationError):
            loan.action_link_legacy()
        self.assertFalse(loan.move_id)

    def test_opening_date_limits_payroll_and_direct_recovery(self):
        move = self._posted_opening([('ADV-POSTING-DATE', 300, self.work_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        loan = self._legacy(line, 'ADV-POSTING-DATE', 300)
        loan.action_link_legacy()
        self.assertFalse(loan._open_available('2026-05-30'))
        self.assertEqual(loan._open_available('2026-05-31'), loan)
        wizard = self.env['baseer.hr.loan.repay'].create({
            'loan_id': loan.id, 'amount': 100, 'date': '2026-05-30', 'journal_id': self.bank.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm()
        self.assertFalse(wizard.move_id)
        self.assertEqual(loan.balance, 300)

    def test_same_partner_payroll_recovery_can_be_corrected(self):
        move = self._posted_opening([('ADV-CORRECT', 300, self.work_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        loan = self._legacy(line, 'ADV-CORRECT', 300)
        loan.action_link_legacy()
        run, slip = self._run()
        slip.write({'baseer_legacy_repayment': 100})
        run.action_approve()
        self.assertEqual(loan.balance, 200)
        correction = self.env['baseer.payroll.correction'].create({
            'slip_id': slip.id, 'company_id': self.company.id, 'kind': 'payroll_recovery',
            'date': '2026-07-01', 'reason': 'Synthetic same-partner correction', 'reviewed': True,
        })
        correction.action_confirm()
        self.assertEqual((loan.balance, line.amount_residual), (300, 300))
        self.assertEqual(loan.allocation_ids.reversal_move_id, correction.move_id)
        self.assertEqual(move.state, 'posted')

    def test_duplicate_source_or_principal_is_rejected(self):
        move = self._posted_opening([('ADV-T010', 300, self.historical_partner),
                                     ('ADV-T011', 300, self.historical_partner)])
        lines = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        line = lines.filtered(lambda row: row.name == 'ADV-T010')
        self._legacy(line, 'ADV-T010', 300).action_link_legacy()
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError, IntegrityError)), self.cr.savepoint():
            self._legacy(line, 'ADV-T010', 300).action_link_legacy()
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError, IntegrityError)), self.cr.savepoint():
            self._legacy(line, 'ADV-T011', 300).action_link_legacy()
        other_line = lines.filtered(lambda row: row.name == 'ADV-T011')
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError, IntegrityError)), self.cr.savepoint():
            self._legacy(other_line, 'ADV-T010', 300).action_link_legacy()

    def test_shared_move_does_not_mix_two_employees(self):
        other_partner = self.env['res.partner'].create({
            'name': 'Second historical partner', 'company_id': self.company.id,
        })
        other_employee = self.env['hr.employee'].create({
            'name': 'Second fictional employee', 'company_id': self.company.id,
            'work_contact_id': other_partner.id,
        })
        move = self._posted_opening([('ADV-P01', 300, self.historical_partner),
                                     ('ADV-P02', 200, other_partner)])
        lines = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        first = self._legacy(lines.filtered(lambda row: row.name == 'ADV-P01'), 'ADV-P01', 300)
        second = self.env['baseer.hr.loan'].create({
            'name': 'Second employee advance', 'company_id': self.company.id,
            'employee_id': other_employee.id, 'source_type': 'legacy',
            'source_reference': 'ADV-P02', 'principal_line_id': lines.filtered(lambda row: row.name == 'ADV-P02').id,
            'historical_original_amount': 200, 'historical_recovery_amount': 0,
            'legacy_identity_evidence': 'Fictitious second employee match',
            'amount': 200, 'date': '2026-04-01',
        })
        second.action_attest_legacy_identity()
        (first | second).action_link_legacy()
        self.assertEqual((first.balance, second.balance), (300, 200))
        self.assertNotEqual(first._principal_lines(), second._principal_lines())
        self.assertEqual(first._principal_lines().partner_id, self.historical_partner)
        self.assertEqual(second._principal_lines().partner_id, other_partner)

    def test_identity_attestation_cannot_be_skipped_or_retargeted(self):
        move = self._posted_opening([('ADV-P03', 300, self.historical_partner),
                                     ('ADV-P04', 200, self.historical_partner)])
        lines = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        loan = self.env['baseer.hr.loan'].create({
            'name': 'Unattested historical advance', 'company_id': self.company.id,
            'employee_id': self.employee.id, 'source_type': 'legacy',
            'source_reference': 'ADV-P03', 'principal_line_id': lines.filtered(lambda row: row.name == 'ADV-P03').id,
            'historical_original_amount': 300, 'historical_recovery_amount': 0,
            'legacy_identity_evidence': 'Fictitious employee identity evidence',
            'amount': 300, 'date': '2026-03-01',
        })
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            loan.action_link_legacy()
        loan.action_attest_legacy_identity()
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            loan.write({'principal_line_id': lines.filtered(lambda row: row.name == 'ADV-P04').id})
        self.assertEqual(loan.principal_line_id.name, 'ADV-P03')

    def test_cancelled_attested_draft_preserves_evidence_and_allows_one_corrected_link(self):
        move = self._posted_opening([('ADV-CORRECT', 300, self.historical_partner)])
        principal = move.line_ids.filtered(lambda line: line.account_id == self.advance)
        original_date, original_partner, original_residual = move.date, principal.partner_id, principal.amount_residual
        wrong = self._legacy(principal, 'ADV-CORRECT', 300)
        evidence = (wrong.legacy_identity_evidence, wrong.legacy_identity_employee_id,
                    wrong.legacy_identity_partner_id, wrong.legacy_identity_principal_id,
                    wrong.legacy_identity_reference, wrong.legacy_identity_confirmed_by,
                    wrong.legacy_identity_confirmed_at)
        self.assertTrue(all(evidence))
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            wrong.unlink()
        self.assertTrue(wrong.exists())
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError, IntegrityError)), self.cr.savepoint():
            self._legacy(principal, 'ADV-CORRECT', 300)
        wrong.action_cancel()
        self.assertEqual(wrong.state, 'cancel')
        self.assertEqual((wrong.legacy_identity_evidence, wrong.legacy_identity_employee_id,
                          wrong.legacy_identity_partner_id, wrong.legacy_identity_principal_id,
                          wrong.legacy_identity_reference, wrong.legacy_identity_confirmed_by,
                          wrong.legacy_identity_confirmed_at), evidence)
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            wrong.unlink()
        self.assertTrue(wrong.exists())
        replacement = self._legacy(principal, 'ADV-CORRECT', 300)
        replacement.action_link_legacy()
        self.assertEqual((replacement.state, replacement.balance), ('running', 300))
        self.assertEqual(replacement.principal_line_id, principal)
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError, IntegrityError)), self.cr.savepoint():
            self._legacy(principal, 'ADV-CORRECT', 300).action_link_legacy()
        self.assertEqual((move.state, move.date, principal.partner_id, principal.amount_residual),
                         ('posted', original_date, original_partner, original_residual))
        self.assertEqual(wrong.state, 'cancel')

    def test_missing_uniqueness_index_blocks_legacy_without_affecting_regular(self):
        move = self._posted_opening([
            ('ADV-GUARD-1', 300, self.historical_partner),
            ('ADV-GUARD-2', 200, self.historical_partner),
            ('ADV-GUARD-3', 100, self.historical_partner),
        ])
        lines = move.line_ids.filtered(lambda line: line.account_id == self.advance)
        pending = self.env['baseer.hr.loan'].create({
            'name': 'Pending attestation', 'company_id': self.company.id,
            'employee_id': self.employee.id, 'source_type': 'legacy',
            'source_reference': 'ADV-GUARD-1',
            'principal_line_id': lines.filtered(lambda line: line.name == 'ADV-GUARD-1').id,
            'historical_original_amount': 300, 'historical_recovery_amount': 0,
            'legacy_identity_evidence': 'Fictional evidence', 'amount': 300, 'date': '2026-03-01',
        })
        attested = self._legacy(lines.filtered(lambda line: line.name == 'ADV-GUARD-2'), 'ADV-GUARD-2', 200)
        active = self._legacy(lines.filtered(lambda line: line.name == 'ADV-GUARD-3'), 'ADV-GUARD-3', 100)
        active.action_link_legacy()
        wizard = self.env['baseer.hr.loan.repay'].create({
            'loan_id': active.id, 'amount': 100, 'date': '2026-06-10', 'journal_id': self.bank.id,
        })
        indexes = ('baseer_hr_loan_legacy_reference_active_unique',
                   'baseer_hr_loan_legacy_principal_active_unique')
        for index in indexes:
            with self.subTest(index=index):
                # PostgreSQL DDL is transactional. Force rollback of this
                # savepoint so the real test index is restored each time.
                with self.assertRaises(RuntimeError), self.cr.savepoint():
                    self.cr.execute('DROP INDEX "%s"' % index)
                    with self.assertRaises(UserError):
                        self._legacy(lines[0], 'ADV-GUARD-NEW', 1)
                    with self.assertRaises(UserError):
                        pending.action_attest_legacy_identity()
                    with self.assertRaises(UserError):
                        attested.action_link_legacy()
                    moves_before = self.env['account.move'].search_count([])
                    with self.assertRaises(UserError), self.cr.savepoint():
                        wizard.action_confirm()
                    self.assertEqual(self.env['account.move'].search_count([]), moves_before)
                    self.assertEqual(active.balance, 100)
                    regular = self.env['baseer.hr.loan'].create({
                        'name': 'Regular remains available', 'company_id': self.company.id,
                        'employee_id': self.employee.id, 'amount': 50,
                        'date': '2026-06-01', 'first_due_date': '2026-06-30',
                        'installment_count': 1, 'journal_id': self.bank.id,
                    })
                    self.assertEqual(regular.source_type, 'regular')
                    raise RuntimeError('Restore the temporarily dropped test index')
    def test_linked_posted_origin_is_immutable_as_a_whole(self):
        move = self._posted_opening([('ADV-LOCK-1', 300, self.historical_partner),
                                     ('ADV-LOCK-2', 200, self.work_partner)])
        line = move.line_ids.filtered(lambda row: row.name == 'ADV-LOCK-1')
        self._legacy(line, 'ADV-LOCK-1', 300).action_link_legacy()
        original_date, original_journal = move.date, move.journal_id
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            move.write({'date': '2026-05-30'})
        self.assertEqual(move.date, original_date)
        other_journal = self.env['account.journal'].create({
            'name': 'Alternative opening journal', 'code': 'ALT', 'type': 'general',
            'company_id': self.company.id,
        })
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            move.write({'journal_id': other_journal.id})
        self.assertEqual(move.journal_id, original_journal)
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            move._reverse_moves()
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            move.unlink()
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            self.env['account.move.line'].create({
                'name': 'Injected line', 'move_id': move.id,
                'account_id': self.advance.id, 'partner_id': self.work_partner.id, 'debit': 1,
            })
        self.assertEqual(move.state, 'posted')
        self.assertEqual(len(move.line_ids), 3)

    def test_reference_is_a_whole_source_identifier_not_a_substring(self):
        move = self._posted_opening([('Noorix ADV-10 — historical', 300, self.historical_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            self._legacy(line, 'ADV-1', 300).action_link_legacy()

    def test_reference_rejects_leading_trailing_or_internal_whitespace(self):
        move = self._posted_opening([('Noorix ADV-EXACT — historical', 300, self.historical_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        for ref in (' ADV-EXACT', 'ADV-EXACT ', 'ADV -EXACT'):
            with self.subTest(ref=ref):
                with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
                    self._legacy(line, ref, 300).action_link_legacy()

    def test_invalid_balance_reference_or_unposted_origin_fails(self):
        move = self._posted_opening([('ADV-T020', 300, self.historical_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        for ref, amount in [('ADV-T021', 300), ('ADV-T020', 301)]:
            with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
                self._legacy(line, ref, amount).action_link_legacy()

    def test_prior_recovery_is_evidence_without_new_cash_or_recovery_allocation(self):
        move = self._posted_opening([('ADV-HIST', 1400, self.historical_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        before_moves = self.env['account.move'].search_count([])
        loan = self._legacy(line, 'ADV-HIST', 1400, original=3000, recovered=1600)
        loan.action_link_legacy()
        self.assertEqual((loan.historical_original_amount, loan.historical_recovery_amount, loan.balance),
                         (3000, 1600, 1400))
        self.assertFalse(loan.allocation_ids)
        self.assertEqual(self.env['account.move'].search_count([]), before_moves)

    def test_foreign_company_origin_and_unposted_origin_are_rejected(self):
        other = self.env['res.company'].create({'name': 'Foreign legacy fixture'})
        other_journal = self.env['account.journal'].with_company(other).create({
            'name': 'Foreign legacy journal', 'code': 'FLG', 'type': 'general', 'company_id': other.id,
        })
        other_advance = self.env['account.account'].with_company(other).create({
            'name': 'Foreign receivable', 'code': '978103', 'account_type': 'asset_receivable',
            'reconcile': True, 'company_ids': [Command.set(other.ids)],
        })
        other_equity = self.env['account.account'].with_company(other).create({
            'name': 'Foreign equity', 'code': '978105', 'account_type': 'equity',
            'company_ids': [Command.set(other.ids)],
        })
        other_partner = self.env['res.partner'].with_company(other).create({
            'name': 'Foreign partner', 'company_id': other.id,
        })
        foreign = self.env['account.move'].with_company(other).create({
            'move_type': 'entry', 'company_id': other.id, 'journal_id': other_journal.id,
            'date': '2026-05-31', 'line_ids': [
                Command.create({'name': 'ADV-X01', 'account_id': other_advance.id,
                                'partner_id': other_partner.id, 'debit': 300}),
                Command.create({'name': 'opening', 'account_id': other_equity.id, 'credit': 300}),
            ],
        })
        foreign.action_post()
        foreign_line = foreign.line_ids.filtered(lambda row: row.account_id == other_advance)
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            self._legacy(foreign_line, 'ADV-X01', 300).action_link_legacy()
        draft = self.env['account.move'].create({
            'move_type': 'entry', 'company_id': self.company.id, 'journal_id': self.journal.id,
            'date': '2026-05-31', 'line_ids': [
                Command.create({'name': 'ADV-X02', 'account_id': self.advance.id,
                                'partner_id': self.historical_partner.id, 'debit': 300}),
                Command.create({'name': 'opening', 'account_id': self.opening.id, 'credit': 300}),
            ],
        })
        with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
            self._legacy(draft.line_ids.filtered(lambda row: row.account_id == self.advance),
                         'ADV-X02', 300).action_link_legacy()

    def test_open_repayment_is_zero_by_default_then_partial_and_full(self):
        self.employee.version_id.write({'wage': 4000})
        move = self._posted_opening([('ADV-T030', 300, self.historical_partner),
                                     ('ADV-T031', 200, self.work_partner)])
        lines = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        first = self._legacy(lines.filtered(lambda row: row.name == 'ADV-T030'), 'ADV-T030', 300, '2026-03-01')
        second = self._legacy(lines.filtered(lambda row: row.name == 'ADV-T031'), 'ADV-T031', 200, '2026-04-01')
        (first | second).action_link_legacy()
        run, slip = self._run()
        self.assertEqual(slip.baseer_legacy_repayment, 0)
        self.assertEqual(slip.baseer_loan_amount, 0)
        slip.write({'baseer_legacy_repayment': 350})
        self.assertEqual(slip.baseer_loan_amount, 350)
        self.assertEqual(slip.baseer_net, 3650)
        self.assertIn('ADV-T030: 300.00', slip.baseer_legacy_preview)
        self.assertIn('ADV-T031: 50.00', slip.baseer_legacy_preview)
        run.action_approve()
        self.assertEqual((slip.state, slip.move_id.state), ('done', 'posted'))
        self.assertEqual((first.balance, second.balance), (0, 150))
        self.assertEqual(sum((first | second).mapped('allocation_ids.amount')), 350)
        self.assertEqual(move.state, 'posted')
        self.assertEqual(set(lines.mapped('partner_id').ids), {self.historical_partner.id, self.work_partner.id})
        bridges = (first | second).mapped('allocation_ids.bridge_move_id')
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges.state, 'posted')
        self.assertEqual(bridges.baseer_legacy_origin_move_id, slip.move_id)
        self.assertEqual(sum(bridges.line_ids.mapped('balance')), 0)
        self.assertEqual(set(bridges.line_ids.mapped('account_id').ids), set(self.advance.ids))
        self.assertEqual(set(bridges.line_ids.mapped('partner_id').ids),
                         {self.work_partner.id, self.historical_partner.id})
        self.assertEqual(sum(bridges.line_ids.mapped('debit')), 300)
        with TestCase.assertRaises(self, (UserError, AccessError, ValidationError)), self.cr.savepoint():
            lines.filtered(lambda row: row.name == 'ADV-T030').write({'partner_id': self.work_partner.id})
        self.assertEqual(lines.filtered(lambda row: row.name == 'ADV-T030').partner_id, self.historical_partner)
        later_run, later_slip = self._run('2026-07-01')
        later_slip.write({'baseer_legacy_repayment': 150})
        later_run.action_approve()
        self.assertEqual((first.balance, second.balance), (0, 0))
        self.assertEqual(sum((first | second).mapped('allocation_ids.amount')), 500)
        self.assertEqual(sum(slip.move_id.line_ids.mapped('balance')), 0)

    def test_repayment_cannot_exceed_outstanding_or_net_salary(self):
        move = self._posted_opening([('ADV-T040', 300, self.historical_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        self._legacy(line, 'ADV-T040', 300).action_link_legacy()
        run, slip = self._run()
        with TestCase.assertRaises(self, (UserError, ValidationError)), self.cr.savepoint():
            slip.write({'baseer_legacy_repayment': 301})
        self.assertEqual(slip.baseer_legacy_repayment, 0)
        self.assertEqual(run.state, 'draft')

    def test_repayment_cannot_exceed_salary_even_when_balance_is_larger(self):
        move = self._posted_opening([('ADV-T041', 2500, self.historical_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        self._legacy(line, 'ADV-T041', 2500).action_link_legacy()
        _run, slip = self._run()
        self.assertEqual(slip.baseer_gross, 2000)
        with TestCase.assertRaises(self, (UserError, ValidationError)), self.cr.savepoint():
            slip.write({'baseer_legacy_repayment': 2001})
        self.assertEqual(slip.baseer_legacy_repayment, 0)

    def test_failed_reconciliation_rolls_back_entire_approval(self):
        move = self._posted_opening([('ADV-T050', 300, self.historical_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        loan = self._legacy(line, 'ADV-T050', 300)
        loan.action_link_legacy()
        run, slip = self._run()
        slip.write({'baseer_legacy_repayment': 100})
        move_count = self.env['account.move'].search_count([])
        partial_class = type(self.env['account.partial.reconcile'])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            with patch.object(partial_class, 'create', side_effect=ValidationError('Forced failure')):
                run.action_approve()
        self.env.invalidate_all()
        self.assertEqual(self.env['account.move'].search_count([]), move_count)
        self.assertEqual(loan.balance, 300)
        self.assertFalse(loan.allocation_ids)
        self.assertFalse(slip.move_id)
        self.assertNotEqual(slip.state, 'done')
        self.assertEqual(line.amount_residual, 300)

    def test_direct_full_repayment_reconciles_and_is_idempotent(self):
        move = self._posted_opening([('ADV-T060', 300, self.historical_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        loan = self._legacy(line, 'ADV-T060', 300)
        loan.action_link_legacy()
        wizard = self.env['baseer.hr.loan.repay'].create({
            'loan_id': loan.id, 'amount': 300, 'date': '2026-06-01', 'journal_id': self.bank.id,
        })
        wizard.action_confirm()
        self.assertEqual(loan.balance, 0)
        self.assertEqual(loan.state, 'closed')
        self.assertEqual(wizard.move_id.state, 'posted')
        self.assertEqual(len(loan.allocation_ids), 1)
        allocation = loan.allocation_ids
        self.assertEqual(allocation.kind, 'repayment')
        self.assertTrue(allocation.bridge_move_id)
        history_action = loan.action_view_moves()
        history_moves = self.env['account.move'].search(history_action['domain'])
        self.assertEqual(set(history_moves.ids),
                         {move.id, wizard.move_id.id, allocation.bridge_move_id.id},
                         'domain=%r origin=%s repayment=%s bridge=%s returned=%r' % (
                             history_action['domain'], move.id, wizard.move_id.id,
                             allocation.bridge_move_id.id, history_moves.ids))
        posted_id = wizard.move_id.id
        wizard.action_confirm()
        self.assertEqual(wizard.move_id.id, posted_id)
        self.assertEqual(len(loan.allocation_ids), 1)

    def test_legacy_original_correction_is_blocked_before_creating_any_move(self):
        move = self._posted_opening([('ADV-R1', 300, self.historical_partner),
                                     ('ADV-R2', 200, self.work_partner)])
        lines = move.line_ids.filtered(lambda line: line.account_id == self.advance)
        loan = self._legacy(lines.filtered(lambda line: line.name == 'ADV-R1'), 'ADV-R1', 300)
        loan.action_link_legacy()
        correction = self.env['baseer.payroll.correction'].create({
            'loan_id': loan.id, 'company_id': self.company.id, 'kind': 'advance',
            'date': '2026-06-30', 'reason': 'Synthetic correction test', 'reviewed': True,
        })
        original = [(line.id, line.balance, line.amount_residual, line.partner_id.id) for line in move.line_ids]
        before_moves = self.env['account.move'].search_count([])
        with patch.object(type(self.env['account.move']), 'create', side_effect=AssertionError('Correction must not create a move')):
            with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
                correction._reverse_advance()
        self.assertEqual(self.env['account.move'].search_count([]), before_moves)
        self.assertEqual(move.state, 'posted')
        self.assertEqual([(line.id, line.balance, line.amount_residual, line.partner_id.id) for line in move.line_ids], original)
        self.assertEqual((loan.state, loan.balance), ('running', 300))

    def test_legacy_direct_recovery_correction_is_blocked_before_new_move(self):
        move = self._posted_opening([('ADV-R3', 300, self.historical_partner)])
        loan = self._legacy(move.line_ids.filtered(lambda line: line.account_id == self.advance), 'ADV-R3', 300)
        loan.action_link_legacy()
        wizard = self.env['baseer.hr.loan.repay'].create({
            'loan_id': loan.id, 'amount': 100, 'date': '2026-06-10', 'journal_id': self.bank.id,
        })
        wizard.action_confirm()
        allocation = loan.allocation_ids
        self.assertTrue(allocation.bridge_move_id)
        correction = self.env['baseer.payroll.correction'].create({
            'loan_id': loan.id, 'company_id': self.company.id, 'kind': 'repayment',
            'date': '2026-06-30', 'reason': 'Synthetic correction test', 'reviewed': True,
        })
        before_moves = self.env['account.move'].search_count([])
        before_partials = self.env['account.partial.reconcile'].search_count([])
        with patch.object(type(self.env['account.move']), 'create', side_effect=AssertionError('Correction must not create a move')):
            with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
                correction._reverse_recovery()
        self.assertEqual(self.env['account.move'].search_count([]), before_moves)
        self.assertEqual(self.env['account.partial.reconcile'].search_count([]), before_partials)
        self.assertEqual((loan.state, loan.balance), ('running', 200))
        self.assertFalse(allocation.reversal_move_id)
        self.assertEqual((move.state, wizard.move_id.state, allocation.bridge_move_id.state), ('posted', 'posted', 'posted'))

    def test_mixed_payroll_recovery_correction_blocks_before_any_change(self):
        move = self._posted_opening([('ADV-R4', 300, self.historical_partner)])
        legacy = self._legacy(move.line_ids.filtered(lambda line: line.account_id == self.advance), 'ADV-R4', 300)
        legacy.action_link_legacy()
        regular = self.env['baseer.hr.loan'].create({
            'name': 'Ordinary advance in mixed payroll', 'company_id': self.company.id,
            'employee_id': self.employee.id, 'amount': 100, 'date': '2026-06-01',
            'first_due_date': '2026-06-30', 'installment_count': 1, 'journal_id': self.bank.id,
        })
        regular.action_disburse()
        run, slip = self._run()
        slip.write({'baseer_legacy_repayment': 100})
        self.assertEqual(slip.baseer_loan_amount, 200)
        run.action_approve()
        self.assertEqual((regular.balance, legacy.balance), (0, 200))
        allocations = regular.allocation_ids | legacy.allocation_ids
        self.assertEqual(len(allocations), 2)
        correction = self.env['baseer.payroll.correction'].create({
            'slip_id': slip.id, 'company_id': self.company.id, 'kind': 'payroll_recovery',
            'date': '2026-07-01', 'reason': 'Synthetic mixed correction test', 'reviewed': True,
        })
        before_moves = self.env['account.move'].search_count([])
        before_partials = self.env['account.partial.reconcile'].search_count([])
        regular_schedule = [(line.id, line.amount, line.balance) for line in regular.line_ids]
        with patch.object(type(self.env['account.move']), 'create', side_effect=AssertionError('Correction must not create a move')):
            with TestCase.assertRaises(self, (UserError, ValidationError, AccessError)), self.cr.savepoint():
                correction._reverse_recovery()
        self.assertEqual(self.env['account.move'].search_count([]), before_moves)
        self.assertEqual(self.env['account.partial.reconcile'].search_count([]), before_partials)
        self.assertEqual((regular.balance, legacy.balance), (0, 200))
        self.assertEqual([(line.id, line.amount, line.balance) for line in regular.line_ids], regular_schedule)
        self.assertFalse(allocations.filtered('reversal_move_id'))
        self.assertEqual((move.state, slip.move_id.state), ('posted', 'posted'))

    def test_open_draft_requires_refresh_after_direct_partial_repayment(self):
        self.employee.version_id.write({'wage': 2500})
        move = self._posted_opening([('ADV-T070', 300, self.historical_partner)])
        line = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        loan = self._legacy(line, 'ADV-T070', 300)
        loan.action_link_legacy()
        run, slip = self._run()
        slip.write({'baseer_legacy_repayment': 250})
        self.assertEqual(slip.baseer_loan_amount, 250)
        wizard = self.env['baseer.hr.loan.repay'].create({
            'loan_id': loan.id, 'amount': 100, 'date': '2026-06-10', 'journal_id': self.bank.id,
        })
        wizard.action_confirm()
        slip.invalidate_recordset()
        self.assertEqual(loan.balance, 200)
        self.assertTrue(slip.baseer_needs_refresh)
        self.assertEqual(slip.baseer_legacy_repayment, 250)
        self.assertFalse(slip.baseer_legacy_preview)
        with TestCase.assertRaises(self, (UserError, ValidationError)), self.cr.savepoint():
            run.action_approve()
        with TestCase.assertRaises(self, (UserError, ValidationError)), self.cr.savepoint():
            run.action_load_employees()
        slip.write({'baseer_legacy_repayment': 200})
        run.action_load_employees()
        self.assertEqual(slip.baseer_loan_amount, 200)
        self.assertEqual(slip.baseer_net, 2300)
        run.action_approve()
        self.assertEqual(loan.balance, 0)

    def test_direct_repayment_from_newer_loan_still_allocates_fifo(self):
        move = self._posted_opening([('ADV-FIFO-OLD', 300, self.historical_partner),
                                     ('ADV-FIFO-NEW', 200, self.work_partner)])
        lines = move.line_ids.filtered(lambda row: row.account_id == self.advance)
        old = self._legacy(lines.filtered(lambda row: row.name == 'ADV-FIFO-OLD'),
                           'ADV-FIFO-OLD', 300, '2026-03-01')
        newer = self._legacy(lines.filtered(lambda row: row.name == 'ADV-FIFO-NEW'),
                             'ADV-FIFO-NEW', 200, '2026-04-01')
        (old | newer).action_link_legacy()
        wizard = self.env['baseer.hr.loan.repay'].create({
            'loan_id': newer.id, 'amount': 400, 'date': '2026-06-10', 'journal_id': self.bank.id,
        })
        wizard.action_confirm()
        self.assertEqual((old.balance, newer.balance), (0, 100))
        self.assertEqual(sum(old.allocation_ids.mapped('amount')), 300)
        self.assertEqual(sum(newer.allocation_ids.mapped('amount')), 100)

    def test_regular_advance_still_issues_cash_and_scheduled_deduction(self):
        loan = self.env['baseer.hr.loan'].create({
            'name': 'Ordinary fictitious advance', 'company_id': self.company.id,
            'employee_id': self.employee.id, 'amount': 300,
            'date': '2026-06-01', 'first_due_date': '2026-06-30',
            'installment_count': 1, 'journal_id': self.bank.id,
        })
        loan.action_disburse()
        self.assertEqual(loan.state, 'running')
        self.assertEqual(loan.balance, 300)
        self.assertEqual(len(loan.line_ids), 1)
        self.assertEqual(loan.move_id.state, 'posted')
        self.assertEqual(sum(loan.move_id.line_ids.filtered(lambda line: line.account_id == self.cash).mapped('credit')), 300)
        run, slip = self._run()
        self.assertEqual(slip.baseer_loan_amount, 300)
        run.action_approve()
        self.assertEqual(loan.balance, 0)
        self.assertEqual(loan.state, 'closed')

    def test_two_opening_entries_and_zero_default(self):
        self.employee.version_id.write({'wage': 2500})
        older = self._posted_opening([('ADV-QA-OLDER', 2600, self.work_partner)], '2026-09-13')
        newer = self._posted_opening([('ADV-QA-NEWER', 2400, self.work_partner)], '2026-09-13')
        first = self._legacy(older.line_ids.filtered(lambda line: line.account_id == self.advance),
                             'ADV-QA-OLDER', 2600, '2026-08-07', original=5000, recovered=2400)
        second = self._legacy(newer.line_ids.filtered(lambda line: line.account_id == self.advance),
                              'ADV-QA-NEWER', 2400, '2026-09-08')
        before = tuple(self.env[model].search_count([]) for model in (
            'account.move', 'account.move.line', 'account.partial.reconcile'))
        (first | second).action_link_legacy()
        self.assertEqual(before, tuple(self.env[model].search_count([]) for model in (
            'account.move', 'account.move.line', 'account.partial.reconcile')))
        self.assertEqual((first.move_id, second.move_id), (older, newer))
        self.assertFalse((first | second).line_ids)
        run, slip = self._run('2026-11-01')
        self.assertEqual((slip.baseer_open_advance_balance, slip.baseer_legacy_repayment,
                          slip.baseer_loan_amount, slip.baseer_net), (5000, 0, 0, 2500))
        run.action_approve()
        run, slip = self._run('2026-12-01')
        self.assertEqual((slip.baseer_open_advance_balance, slip.baseer_legacy_repayment), (5000, 0))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            slip.write({'baseer_legacy_repayment': 250.01})
        slip.write({'baseer_legacy_repayment': 200})
        run.action_approve()
        self.assertEqual((first.balance, second.balance, slip.baseer_net), (2400, 2400, 2300))
        self.assertEqual(first.allocation_ids.move_id, slip.move_id)
        self.assertFalse(first.allocation_ids.bridge_move_id)
        self.assertFalse(second.allocation_ids)

    def test_new_flexible_advance_pays_partially_then_closes_directly(self):
        loan = self.env['baseer.hr.loan'].create({
            'name': 'Ordinary flexible fictitious advance', 'company_id': self.company.id,
            'employee_id': self.employee.id, 'amount': 300, 'date': '2026-06-01',
            'repayment_mode': 'flexible', 'journal_id': self.bank.id,
        })
        loan.action_disburse()
        posted = loan.move_id
        loan.action_disburse()
        self.assertEqual(loan.move_id, posted)
        self.assertEqual((loan.balance, loan.installment_count), (300, 0))
        self.assertFalse(loan.first_due_date or loan.line_ids)
        with self.assertRaises(UserError), self.cr.savepoint():
            loan.write({'repayment_mode': 'scheduled'})
        run, slip = self._run()
        self.assertEqual((slip.baseer_open_advance_balance, slip.baseer_loan_amount), (300, 0))
        slip.write({'baseer_legacy_repayment': 100})
        run.action_approve()
        self.assertEqual((loan.balance, loan.allocation_ids.amount), (200, 100))
        self.assertFalse(loan.allocation_ids.line_id)
        repayment = self.env['baseer.hr.loan.repay'].create({
            'loan_id': loan.id, 'amount': 200, 'date': '2026-07-01', 'journal_id': self.bank.id,
        })
        repayment.action_confirm()
        repayment.action_confirm()
        self.assertEqual((loan.balance, loan.state, len(loan.allocation_ids)), (0, 'closed', 2))

    def test_scheduled_and_flexible_recoveries_reverse_to_their_own_balances(self):
        Loan = self.env['baseer.hr.loan']
        common = {'employee_id': self.employee.id, 'amount': 100, 'date': '2026-06-01',
                  'journal_id': self.bank.id}
        scheduled, flexible = Loan.create([
            dict(common, name='Scheduled', first_due_date='2026-06-30'),
            dict(common, name='Flexible', repayment_mode='flexible'),
        ])
        (scheduled | flexible).action_disburse()
        run, slip = self._run()
        self.assertEqual((slip.baseer_open_advance_balance, slip.baseer_loan_amount), (100, 100))
        slip.write({'baseer_legacy_repayment': 80})
        run.action_approve()
        self.assertEqual((scheduled.balance, flexible.balance), (0, 20))
        self.assertEqual((scheduled.allocation_ids.amount, flexible.allocation_ids.amount), (100, 80))
        correction = self.env['baseer.payroll.correction'].create({
            'slip_id': slip.id, 'company_id': self.company.id, 'kind': 'payroll_recovery',
            'date': '2026-07-01', 'reason': 'Synthetic mixed correction', 'reviewed': True,
        })
        correction.action_confirm()
        self.assertEqual((scheduled.balance, flexible.balance), (100, 100))
        self.assertEqual(scheduled.line_ids.balance, 100)
        self.assertFalse(flexible.line_ids)
