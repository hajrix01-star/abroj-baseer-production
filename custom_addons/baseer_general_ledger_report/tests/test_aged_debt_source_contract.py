"""Characterize native Odoo 19 receivable/payable sources before an aged-debt report.

These tests add no report calculator or production behavior.  They run with the
existing general-ledger CI database so the G2 contract is checked against the
same pinned Odoo image used for Baseer reports.
"""

from datetime import date
from decimal import Decimal

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAgedDebtNativeSourceContract(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        accounts = self.env['account.account'].with_company(self.company)

        def account(code, name, kind, reconcile=False):
            return accounts.create({
                'code': code, 'name': name, 'account_type': kind,
                'reconcile': reconcile,
                'company_ids': [Command.set(self.company.ids)],
            })

        self.receivable = account('958901', 'Debt contract receivable',
                                  'asset_receivable', True)
        self.payable = account('958902', 'Debt contract payable',
                               'liability_payable', True)
        self.income = account('958903', 'Debt contract income', 'income')
        self.expense = account('958904', 'Debt contract expense', 'expense')
        self.bank = account('958905', 'Debt contract bank', 'asset_cash')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Debt contract synthetic counterparty',
            'property_account_receivable_id': self.receivable.id,
            'property_account_payable_id': self.payable.id,
        })
        self.general = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        self.assertTrue(self.general)

    def _invoice(self, move_type, journal, account, amount):
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': move_type, 'partner_id': self.partner.id,
            'journal_id': journal.id, 'invoice_date': '2041-05-10',
            'invoice_line_ids': [Command.create({
                'name': 'Synthetic debt contract line', 'quantity': 1,
                'price_unit': amount, 'account_id': account.id,
            })],
        })
        move.action_post()
        kind = 'asset_receivable' if move_type.startswith('out_') else 'liability_payable'
        line = move.line_ids.filtered(lambda item: item.account_id.account_type == kind)
        self.assertEqual(len(line), 1)
        return line

    def _entry(self, day, debit_account, credit_account, amount,
               company=None, journal=None, partner_id=None):
        company = company or self.company
        journal = journal or self.general
        partner_id = self.partner.id if partner_id is None else partner_id
        move = self.env['account.move'].with_company(company).create({
            'date': day, 'journal_id': journal.id, 'move_type': 'entry',
            'line_ids': [
                Command.create({'name': 'Synthetic debit', 'partner_id': partner_id,
                                'account_id': debit_account.id, 'debit': amount}),
                Command.create({'name': 'Synthetic credit', 'partner_id': partner_id,
                                'account_id': credit_account.id, 'credit': amount}),
            ],
        })
        move._post(soft=False)
        return move

    def test_native_invoice_and_refund_sign_matrix(self):
        journals = {}
        for kind, code in (('sale', 'DCS'), ('purchase', 'DCP')):
            journals[kind] = self.env['account.journal'].with_company(self.company).create({
                'name': f'Debt contract {kind}', 'code': code,
                'type': kind, 'company_id': self.company.id,
            })
        cases = (
            ('out_invoice', 'sale', self.income, '100.00'),
            ('out_refund', 'sale', self.income, '-25.00'),
            ('in_invoice', 'purchase', self.expense, '-100.00'),
            ('in_refund', 'purchase', self.expense, '25.00'),
        )
        for move_type, journal_kind, account, expected in cases:
            with self.subTest(move_type=move_type):
                line = self._invoice(move_type, journals[journal_kind], account,
                                     abs(Decimal(expected)))
                self.assertEqual(Decimal(str(line.balance)), Decimal(expected))

        # Native journal entries establish sign, not a trustworthy payment type.
        direct = (
            (self.receivable, self.bank, '100.00'),
            (self.bank, self.receivable, '-40.00'),
            (self.expense, self.payable, '-60.00'),
            (self.payable, self.bank, '20.00'),
        )
        for debit, credit, expected in direct:
            move = self._entry('2041-05-12', debit, credit, abs(Decimal(expected)))
            debt_account = debit if debit in (self.receivable, self.payable) else credit
            line = move.line_ids.filtered(lambda item: item.account_id == debt_account)
            self.assertEqual(move.move_type, 'entry')
            self.assertEqual(Decimal(str(line.balance)), Decimal(expected))
        partnerless = self._entry('2041-05-13', self.receivable, self.bank,
                                  10, partner_id=False)
        line = partnerless.line_ids.filtered(lambda item: item.account_id == self.receivable)
        self.assertFalse(line.partner_id)
        self.assertEqual(Decimal(str(line.balance)), Decimal('10.00'))

    def test_partial_max_date_is_line_date_not_reconciliation_creation(self):
        invoice = self._entry('2025-01-10', self.receivable, self.income, 100)
        early = self._entry('2025-01-20', self.bank, self.receivable, 30)
        late = self._entry('2025-02-10', self.bank, self.receivable, 40)
        debit_line = invoice.line_ids.filtered(lambda line: line.account_id == self.receivable)
        early_line = early.line_ids.filtered(lambda line: line.account_id == self.receivable)
        late_line = late.line_ids.filtered(lambda line: line.account_id == self.receivable)

        (debit_line + early_line).reconcile()
        (debit_line + late_line).reconcile()
        partials = self.env['account.partial.reconcile'].search([
            ('debit_move_id', '=', debit_line.id),
        ])
        self.assertEqual(len(partials), 2)
        by_date = {item.max_date: Decimal(str(item.amount)) for item in partials}
        self.assertEqual(by_date, {
            date(2025, 1, 20): Decimal('30.00'),
            date(2025, 2, 10): Decimal('40.00'),
        })
        self.assertEqual(Decimal(str(debit_line.amount_residual)), Decimal('30.00'))
        self.assertEqual(sum(
            (Decimal(str(item.amount)) for item in partials
             if item.max_date <= date(2025, 1, 31)),
            Decimal('0.00'),
        ), Decimal('30.00'))
        self.assertEqual(Decimal(str(debit_line.balance)) - Decimal('30.00'),
                         Decimal('70.00'))
        self.assertTrue(all(item.create_date.date() > date(2025, 1, 31)
                            for item in partials))

        bill = self._entry('2025-01-10', self.expense, self.payable, 100)
        early_payment = self._entry('2025-01-20', self.payable, self.bank, 30)
        late_payment = self._entry('2025-02-10', self.payable, self.bank, 40)
        credit_line = bill.line_ids.filtered(lambda line: line.account_id == self.payable)
        for payment in (early_payment, late_payment):
            payment_line = payment.line_ids.filtered(
                lambda line: line.account_id == self.payable,
            )
            (credit_line + payment_line).reconcile()
        payable_partials = self.env['account.partial.reconcile'].search([
            ('credit_move_id', '=', credit_line.id),
        ])
        self.assertEqual({item.max_date: Decimal(str(item.amount))
                          for item in payable_partials}, by_date)
        self.assertEqual(Decimal(str(credit_line.amount_residual)), Decimal('-30.00'))
        self.assertEqual(Decimal(str(credit_line.balance)) + Decimal('30.00'),
                         Decimal('-70.00'))

    def test_readonly_accountant_has_native_reconciliation_read_acl(self):
        invoice = self._entry('2025-01-10', self.receivable, self.income, 100)
        payment = self._entry('2025-01-20', self.bank, self.receivable, 30)
        invoice_line = invoice.line_ids.filtered(
            lambda line: line.account_id == self.receivable,
        )
        payment_line = payment.line_ids.filtered(
            lambda line: line.account_id == self.receivable,
        )
        (invoice_line + payment_line).reconcile()
        partial = self.env['account.partial.reconcile'].search([
            ('debit_move_id', '=', invoice_line.id),
        ], limit=1)
        self.assertTrue(partial)
        readonly = self.env['res.users'].create({
            'name': 'Debt contract readonly', 'login': 'debt_contract_readonly',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        for model_name in ('account.account', 'account.move', 'account.move.line',
                           'account.journal', 'account.partial.reconcile',
                           'res.partner'):
            with self.subTest(model=model_name):
                self.assertTrue(self.env[model_name].with_user(readonly).check_access_rights(
                    'read', raise_exception=False,
                ))
        for record in (invoice, invoice_line, payment_line, partial,
                       self.receivable, self.general, self.partner):
            record.with_user(readonly).check_access('read')
        self.assertEqual(self.env['account.partial.reconcile'].with_user(readonly).search([
            ('id', '=', partial.id),
        ]).ids, partial.ids)

        other = self.env['res.company'].create({'name': 'Debt contract other company'})
        accounts = self.env['account.account'].with_company(other)
        other_receivable = accounts.create({
            'code': '958901', 'name': 'Other company receivable',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [Command.set(other.ids)],
        })
        other_bank = accounts.create({
            'code': '958905', 'name': 'Other company bank',
            'account_type': 'asset_cash',
            'company_ids': [Command.set(other.ids)],
        })
        other_journal = self.env['account.journal'].with_company(other).create({
            'name': 'Debt contract other journal', 'code': 'DCO',
            'type': 'general', 'company_id': other.id,
        })
        hidden = self._entry('2025-01-10', other_receivable, other_bank, 10,
                             company=other, journal=other_journal, partner_id=False)
        hidden_line = hidden.line_ids.filtered(
            lambda line: line.account_id == other_receivable,
        )
        with self.assertRaises(AccessError):
            hidden_line.with_user(readonly).check_access('read')
        self.assertFalse(self.env['account.move.line'].with_user(readonly).search([
            ('id', '=', hidden_line.id),
        ]))
