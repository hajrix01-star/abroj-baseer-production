"""Accountless display notes must not hide real invoice ledger facts."""

from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDashboardSalesNotes(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        accounts = self.env['account.account'].with_company(self.company)
        receivable = accounts.create({
            'name': 'Display test receivable', 'code': '958701',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [Command.set(self.company.ids)],
        })
        income = accounts.create({
            'name': 'Display test income', 'code': '958702', 'account_type': 'income',
            'company_ids': [Command.set(self.company.ids)],
        })
        partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Display test customer', 'property_account_receivable_id': receivable.id,
        })
        journal = self.env['account.journal'].with_company(self.company).create({
            'name': 'Display test sales', 'code': 'IDS', 'type': 'sale',
            'company_id': self.company.id,
        })
        self.invoice = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'journal_id': journal.id, 'invoice_date': '2046-08-10',
            'invoice_line_ids': [
                Command.create({'name': 'Service', 'quantity': 1, 'price_unit': 100,
                                'account_id': income.id, 'tax_ids': [Command.clear()]}),
                Command.create({'display_type': 'line_note', 'name': 'Nonfinancial note'}),
            ],
        })
        self.invoice.action_post()
        self.note = self.invoice.line_ids.filtered(lambda line: line.display_type == 'line_note')
        self.assertEqual(len(self.note), 1)
        self.assertFalse(self.note.account_id)
        self.report = self.env['baseer.financial.dashboard.operations']
        self.billing = self.env['baseer.operations.report']
        self.filters = {'company_id': self.company.id, 'date_from': '2046-08-01',
                        'date_to': '2046-08-31', 'journal_ids': []}

    def test_zero_note_preserves_invoice_and_does_not_change_billing(self):
        facts = self.report._owner_sales_invoices(self.invoice, self.company)
        self.assertEqual(facts[self.invoice.id]['amount'], Decimal('100.00'))
        snapshot = self.report.get_owner_snapshot(self.filters)
        self.assertTrue(snapshot['complete'])
        sales = next(row for row in snapshot['periods'][0]['totals'] if row['key'] == 'incoming_total')
        self.assertEqual(sales['amount'], '100.00')
        with self.assertRaises(AccessError):
            self.billing._owner_sales_invoices(self.invoice, self.company)

    def test_accountless_section_is_still_rejected(self):
        self.note.flush_recordset(['display_type'])
        try:
            self.env.cr.execute("UPDATE account_move_line SET display_type='line_section' WHERE id=%s",
                                [self.note.id])
            self.note.invalidate_recordset(['display_type'])
            with self.assertRaises(AccessError):
                self.report._owner_sales_invoices(self.invoice, self.company)
        finally:
            self.env.cr.execute("UPDATE account_move_line SET display_type='line_note' WHERE id=%s",
                                [self.note.id])
            self.note.invalidate_recordset(['display_type'])

    def test_nonzero_note_is_not_filtered(self):
        original = type(self.report)._owner_sales_money
        def nonzero_note_guard(model, value, currency):
            return Decimal('0.01') if value == self.note.debit else original(model, value, currency)
        with patch.object(type(self.report), '_owner_sales_money', nonzero_note_guard):
            with self.assertRaises(AccessError):
                self.report._owner_sales_invoices(self.invoice, self.company)

    def test_note_handling_does_not_change_hr_or_accept_context_flag(self):
        # HR uses the same account-move relation census as invoices. It must
        # still receive the accountless note and reject it, even when callers
        # try to provide a context value resembling an internal flag.
        for context in ({}, {'_dashboard_sales_note_scope': True}):
            report = self.report.with_context(**context)
            lines = report._owner_sales_pairs(self.invoice, 'line_ids', 'account.move.line', 'move_id')
            self.assertIn(self.note, lines)
            with self.assertRaises(AccessError):
                report._owner_hr_move_lines(self.invoice, self.company)
        with self.assertRaises(AccessError):
            self.billing._owner_hr_move_lines(self.invoice, self.company)

    def test_tax_relation_on_note_is_not_silently_ignored(self):
        tax = self.env['account.tax'].create({
            'name': 'Display note test tax', 'amount': 0, 'type_tax_use': 'sale',
            'company_id': self.company.id,
        })
        # Test-only malformed relation, inserted directly so this case cannot
        # be normalized away by the invoice form's nonfinancial-line logic.
        self.env.cr.execute(
            'INSERT INTO account_move_line_account_tax_rel '
            '(account_move_line_id, account_tax_id) VALUES (%s, %s)',
            [self.note.id, tax.id],
        )
        self.note.invalidate_recordset(['tax_ids'])
        try:
            with self.assertRaises(AccessError):
                self.report._owner_sales_invoices(self.invoice, self.company)
        finally:
            self.env.cr.execute(
                'DELETE FROM account_move_line_account_tax_rel '
                'WHERE account_move_line_id=%s AND account_tax_id=%s',
                [self.note.id, tax.id],
            )
            self.note.invalidate_recordset(['tax_ids'])

    def test_rule_hidden_tax_relation_is_not_treated_as_absent(self):
        tax = self.env['account.tax'].create({
            'name': 'Hidden display note tax', 'amount': 0, 'type_tax_use': 'sale',
            'company_id': self.company.id,
        })
        self.env.cr.execute(
            'INSERT INTO account_move_line_account_tax_rel '
            '(account_move_line_id, account_tax_id) VALUES (%s, %s)',
            [self.note.id, tax.id],
        )
        self.note.invalidate_recordset(['tax_ids'])
        reader = self.env['res.users'].create({
            'name': 'Hidden tax accountant', 'login': 'hidden-display-tax-accountant',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('account.group_account_user').id])],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
        })
        rule = self.env['ir.rule'].create({
            'name': 'Display test hide tax',
            'model_id': self.env['ir.model']._get('account.tax').id,
            'domain_force': "[('id', '!=', %d)]" % tax.id,
        })
        try:
            rule.flush_recordset()
            with self.assertRaises(AccessError):
                self.report.with_user(reader)._owner_sales_invoices(
                    self.invoice.with_user(reader), self.company.with_user(reader))
        finally:
            rule.unlink()
            self.env.cr.execute(
                'DELETE FROM account_move_line_account_tax_rel '
                'WHERE account_move_line_id=%s AND account_tax_id=%s',
                [self.note.id, tax.id],
            )
            self.note.invalidate_recordset(['tax_ids'])

    def test_hidden_note_still_fails_complete_source_census(self):
        reader = self.env['res.users'].create({
            'name': 'Display test accountant', 'login': 'display-note-accountant',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('account.group_account_user').id])],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
        })
        rule = self.env['ir.rule'].create({
            'name': 'Display test hide note',
            'model_id': self.env['ir.model']._get('account.move.line').id,
            'domain_force': "[('id', '!=', %d)]" % self.note.id,
        })
        try:
            rule.flush_recordset()
            with self.assertRaises(AccessError):
                self.report.with_user(reader)._owner_sales_invoices(
                    self.invoice.with_user(reader), self.company.with_user(reader))
        finally:
            rule.unlink()
