from datetime import date
from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.activity import BaseerAccountActivity


@tagged('post_install', '-at_install')
class TestAccountActivity(TransactionCase):
    """Ledger slice: accounting dates and posted lines, never payment dates."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        Account = self.env['account.account'].with_company(self.company)
        self.asset = Account.search([
            ('company_ids', 'in', self.company.id),
            ('account_type', '=', 'asset_current'),
            ('reconcile', '=', False),
        ], limit=1)
        self.income = Account.search([
            ('company_ids', 'in', self.company.id),
            ('account_type', '=', 'income'),
        ], limit=1)
        self.counterpart = Account.search([
            ('company_ids', 'in', self.company.id),
            ('account_type', '=', 'expense'),
        ], limit=1)
        self.journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        self.assertTrue(self.asset and self.income and self.counterpart and self.journal)
        self.report = self.env['baseer.account.activity']

    def _entry(self, day, account, debit=0, credit=0, posted=True, label='Activity',
               currency=None, amount_currency=None):
        amount = Decimal(str(debit)) - Decimal(str(credit))
        values = {
            'name': label,
            'account_id': account.id,
            'debit': float(debit),
            'credit': float(credit),
        }
        if currency:
            values.update({'currency_id': currency.id, 'amount_currency': float(amount_currency)})
        move = self.env['account.move'].with_company(self.company).create({
            'date': day, 'journal_id': self.journal.id, 'move_type': 'entry',
            'ref': label,
            'line_ids': [
                Command.create(values),
                Command.create({
                    'name': label + ' counterpart', 'account_id': self.counterpart.id,
                    'debit': float(credit), 'credit': float(debit),
                }),
            ],
        })
        if posted:
            move._post(soft=False)
        return move.line_ids.filtered(lambda line: line.account_id == account)[:1]

    def _read(self, account=None, start='2041-03-01', end='2041-03-31', **kwargs):
        return self.report.get_activity(
            self.company.id, (account or self.asset).id, start, end, **kwargs,
        )

    def test_opening_period_and_draft_reversal(self):
        self._entry(date(2040, 12, 20), self.asset, debit=50, label='prior year')
        self._entry(date(2041, 2, 1), self.asset, debit=100, label='opening')
        sale = self._entry(date(2041, 3, 2), self.asset, debit=20, label='in period')
        self._entry(date(2041, 3, 3), self.asset, debit=999, posted=False, label='draft')
        self._entry(date(2041, 3, 4), self.asset, credit=5, label='reversal')
        self._entry(date(2041, 4, 1), self.asset, debit=80, label='after end')
        data = self._read()
        self.assertEqual((data['opening'], data['debit'], data['credit'], data['closing']),
                         ('150.00', '20.00', '5.00', '165.00'))
        self.assertEqual([row['running'] for row in data['lines']], ['170.00', '165.00'])
        self.assertEqual(data['lines'][0]['id'], sale.id)
        self.assertEqual(data['lines'][0]['move_id'], sale.move_id.id)
        self.assertEqual(data['next_cursor'], None)
        self.assertEqual(Decimal(data['opening']) + Decimal(data['debit']) - Decimal(data['credit']),
                         Decimal(data['closing']))

    def test_income_opening_starts_at_fiscal_year(self):
        self._entry(date(2040, 12, 20), self.income, credit=90, label='old income')
        self._entry(date(2041, 2, 1), self.income, credit=12, label='current income')
        data = self._read(account=self.income)
        self.assertEqual(data['opening'], '-12.00')
        self.assertEqual(data['closing'], '-12.00')

    def test_custom_fiscal_year_and_unaffected_equity_reset(self):
        self.company.write({'fiscalyear_last_month': '6', 'fiscalyear_last_day': 30})
        self._entry(date(2040, 6, 20), self.income, credit=90, label='previous fiscal year')
        self._entry(date(2040, 9, 1), self.income, credit=12, label='current fiscal year')
        self.assertEqual(self._read(account=self.income)['opening'], '-12.00')
        equity = self.env['account.account'].with_company(self.company).search([
            ('company_ids', 'in', self.company.id),
            ('account_type', '=', 'equity_unaffected'),
        ], limit=1)
        if equity:
            self._entry(date(2040, 6, 20), equity, credit=40, label='prior equity')
            self._entry(date(2040, 9, 1), equity, credit=7, label='current equity')
            self.assertEqual(self._read(account=equity)['opening'], '-7.00')
        with self.assertRaises(ValidationError):
            self._read(start='2041-06-30', end='2041-07-01')

    def test_rejects_cross_fiscal_year_and_invalid_cursor(self):
        with self.assertRaises(ValidationError):
            self._read(start='2040-12-31', end='2041-01-01')
        with self.assertRaises(ValidationError):
            self._read(cursor_date='2041-03-01', cursor_id=-1)
        with self.assertRaises(ValidationError):
            self._read(cursor_date='2041-03-01')
        other_account_line = self._entry(date(2041, 3, 1), self.income, credit=2)
        with self.assertRaises(ValidationError):
            self._read(cursor_date='2041-03-01', cursor_id=other_account_line.id)

    def test_keyset_pagination_keeps_running_balance(self):
        first = self._entry(date(2041, 3, 5), self.asset, debit=10, label='first')
        second = self._entry(date(2041, 3, 5), self.asset, credit=3, label='second')
        third = self._entry(date(2041, 3, 6), self.asset, debit=2, label='third')
        with patch.object(BaseerAccountActivity, 'PAGE_SIZE', 2):
            page1 = self._read()
            cursor = page1['next_cursor']
            page2 = self._read(cursor_date=cursor['date'], cursor_id=cursor['id'])
        self.assertEqual([row['id'] for row in page1['lines']], [first.id, second.id])
        self.assertEqual([row['running'] for row in page1['lines']], ['10.00', '7.00'])
        self.assertEqual([row['id'] for row in page2['lines']], [third.id])
        self.assertEqual(page2['lines'][0]['running'], '9.00')
        self.assertEqual(page2['closing'], '9.00')
        self.assertIsNone(page2['next_cursor'])

    def test_company_boundary_and_non_accountant(self):
        another = self.env['res.company'].create({'name': 'Activity other company'})
        with self.assertRaises(AccessError):
            self.report.get_activity(another.id, self.asset.id, '2041-03-01', '2041-03-31')
        internal = self.env['res.users'].create({
            'name': 'Activity internal user', 'login': 'activity_internal_user',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id,
            'company_ids': [Command.set([self.company.id])],
        })
        with self.assertRaises(AccessError):
            self.report.with_user(internal).get_activity(
                self.company.id, self.asset.id, '2041-03-01', '2041-03-31',
            )

    def test_readonly_accountant_can_read_and_open_only_authorized_move(self):
        line = self._entry(date(2041, 3, 12), self.asset, debit=18.25)
        accountant = self.env['res.users'].create({
            'name': 'Activity readonly accountant', 'login': 'activity_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set([self.company.id])],
        })
        report = self.report.with_user(accountant).with_context(
            allowed_company_ids=[self.company.id],
        )
        data = report.get_activity(self.company.id, self.asset.id,
                                   '2041-03-01', '2041-03-31')
        self.assertEqual(data['closing'], '18.25')
        self.assertEqual(data['lines'][0]['move_id'], line.move_id.id)
        self.env['account.move'].with_user(accountant).browse(
            data['lines'][0]['move_id'],
        ).check_access('read')

    def test_allowed_second_company_cannot_use_first_company_only_account(self):
        another = self.env['res.company'].create({'name': 'Activity allowed second company'})
        self.assertNotIn(another, self.asset.company_ids)
        accountant = self.env['res.users'].create({
            'name': 'Activity multicompany accountant', 'login': 'activity_multi_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set([self.company.id, another.id])],
        })
        report = self.report.with_user(accountant).with_context(
            allowed_company_ids=[self.company.id, another.id],
        )
        with self.assertRaises(AccessError):
            report.get_activity(another.id, self.asset.id, '2041-03-01', '2041-03-31')

    def test_fractional_totals_reconcile_at_currency_precision(self):
        self._entry(date(2041, 2, 10), self.asset, debit=0.10, label='opening fraction 1')
        self._entry(date(2041, 2, 11), self.asset, debit=0.20, label='opening fraction 2')
        self._entry(date(2041, 3, 10), self.asset, debit=0.30, label='period fraction 1')
        self._entry(date(2041, 3, 11), self.asset, credit=0.10, label='period fraction 2')
        data = self._read()
        self.assertEqual((data['opening'], data['debit'], data['credit'], data['closing']),
                         ('0.30', '0.30', '0.10', '0.50'))
        self.assertEqual([line['running'] for line in data['lines']], ['0.60', '0.50'])
        self.assertEqual(Decimal(data['opening']) + Decimal(data['debit']) - Decimal(data['credit']),
                         Decimal(data['closing']))

    def test_currency_is_company_currency_and_amount_currency_not_added(self):
        foreign = self.env['res.currency'].create({
            'name': 'XBA', 'symbol': 'XBA', 'rounding': 0.01, 'active': True,
            'rate_ids': [Command.create({'name': '2041-01-01', 'rate': 2})],
        })
        self._entry(date(2041, 3, 8), self.asset, debit=25, label='foreign currency',
                    currency=foreign, amount_currency=50)
        data = self._read()
        self.assertEqual(data['debit'], '25.00')
        self.assertEqual(data['closing'], '25.00')
        self.assertEqual(data['currency_symbol'], self.company.currency_id.symbol)

    def test_storno_negative_debit_is_not_silently_reclassified(self):
        self.company.account_storno = True
        original = self._entry(date(2041, 3, 9), self.asset, debit=10, label='storno source')
        reversal_action = self.env['account.move.reversal'].create({
            'move_ids': original.move_id.ids,
            'date': date(2041, 3, 10),
            'journal_id': self.journal.id,
        }).refund_moves()
        reversed_move = self.env['account.move'].browse(reversal_action['res_id'])
        self.assertEqual(reversed_move.date, date(2041, 3, 10))
        if reversed_move.state != 'posted':
            # Odoo schedules future-dated reversals by default. Disable that
            # automation only in this fixture so the posted-only report sees it.
            reversed_move.auto_post = 'no'
            reversed_move._post(soft=False)
        self.assertEqual(reversed_move.state, 'posted')
        negative = reversed_move.line_ids.filtered(lambda line: line.account_id == self.asset)
        self.assertEqual((negative.debit, negative.credit), (-10.0, 0.0))
        data = self._read()
        self.assertEqual((data['debit'], data['credit'], data['closing']), ('0.00', '0.00', '0.00'))
        self.assertEqual([line['running'] for line in data['lines']], ['10.00', '0.00'])
        self.assertEqual(data['lines'][1]['debit'], '-10.00')
