import logging

from odoo import Command, api
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class DailyPurchaseReportCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company_b = cls.env['res.company'].create({
            'name': 'Daily report other company', 'currency_id': cls.company.currency_id.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Daily report supplier'})
        cls.expense = cls.env['account.account'].create({
            'name': 'Daily report expense', 'code': 'DPR600', 'account_type': 'expense',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.payable = cls.env['account.account'].create({
            'name': 'Daily report payable', 'code': 'DPR200', 'account_type': 'liability_payable',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.partner.with_company(cls.company).property_account_payable_id = cls.payable
        cls.journal = cls.env['account.journal'].create({
            'name': 'Daily report purchase journal', 'code': 'DPRJ',
            'type': 'purchase', 'company_id': cls.company.id,
        })
        cls.settlement_journal = cls.env['account.journal'].create({
            'name': 'Daily report settlement', 'code': 'DPRM',
            'type': 'general', 'company_id': cls.company.id,
        })
        cls.users = {}
        for role in ('owner', 'accountant', 'cashier', 'pos_cashier'):
            cls.users[role] = cls.env['res.users'].sudo().with_context(no_reset_password=True).create({
                'name': 'Daily report ' + role, 'login': 'daily_report_' + role,
                'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
                'baseer_access_role': role,
            })

    def _report(self, role):
        env = api.Environment(self.env.cr, self.users[role].id, {
            'allowed_company_ids': [self.company.id],
        })
        return env['baseer.purchase.daily.report']

    def _bill(self, price, kind='in_invoice', day='2099-09-15', post=True):
        bill = self.env['account.move'].create({
            'company_id': self.company.id, 'move_type': kind,
            'partner_id': self.partner.id, 'journal_id': self.journal.id,
            'invoice_date': day, 'ref': 'SUP-DAILY',
            'invoice_line_ids': [Command.create({
                'name': 'Report goods', 'quantity': 1, 'price_unit': price,
                'account_id': self.expense.id, 'tax_ids': [Command.clear()],
            })],
        })
        if post:
            bill.action_post()
        return bill

    def _settle(self, bill, amount):
        """Exercise genuine Odoo payable reconciliation, not a mocked residual."""
        entry = self.env['account.move'].create({
            'move_type': 'entry', 'company_id': self.company.id,
            'journal_id': self.settlement_journal.id, 'date': bill.invoice_date,
            'line_ids': [
                Command.create({'name': 'Settlement payable', 'account_id': self.payable.id,
                                'partner_id': self.partner.id, 'debit': amount, 'credit': 0}),
                Command.create({'name': 'Settlement offset', 'account_id': self.expense.id,
                                'debit': 0, 'credit': amount}),
            ],
        })
        entry.action_post()
        (bill.line_ids | entry.line_ids).filtered(lambda line: line.account_id == self.payable and not line.reconciled).reconcile()

    def test_actual_partial_and_full_reconciliation(self):
        bill = self._bill(100)
        report = self._report('cashier')
        before = report.get_days('2099-09-15', '2099-09-15', 'all')['days'][0]
        self.assertEqual((before['total'], before['residual'], before['paid']), ('100.00', '100.00', '0.00'))
        self._settle(bill, 40)
        self.assertEqual(bill.payment_state, 'partial')
        partial = report.get_days('2099-09-15', '2099-09-15', 'partial')['days'][0]
        self.assertEqual((partial['total'], partial['residual'], partial['paid']), ('100.00', '60.00', '0.00'))
        self.assertEqual(report.get_invoice(bill.id)['residual'], '60.00')
        self._settle(bill, 60)
        self.assertEqual(bill.payment_state, 'paid')
        paid = report.get_days('2099-09-15', '2099-09-15', 'paid')['days'][0]
        self.assertEqual((paid['total'], paid['residual'], paid['paid']), ('100.00', '0.00', '0.00'))

    def test_manual_cash_entry_is_unavailable_and_noncash_entry_is_zero(self):
        bill = self._bill(100, day='2099-09-15')
        cash = self.env['account.account'].create({
            'name': 'Manual payment cash', 'code': 'DPR115', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        entry = self.env['account.move'].create({
            'move_type': 'entry', 'company_id': self.company.id,
            'journal_id': self.settlement_journal.id, 'date': bill.invoice_date,
            'line_ids': [
                Command.create({'name': 'Supplier payable', 'account_id': self.payable.id,
                                'partner_id': self.partner.id, 'debit': 40, 'credit': 0}),
                Command.create({'name': 'Cash paid', 'account_id': cash.id,
                                'debit': 0, 'credit': 40}),
            ],
        })
        entry.action_post()
        (bill.line_ids | entry.line_ids).filtered(
            lambda line: line.account_id == self.payable and not line.reconciled
        ).reconcile()
        report = self._report('cashier')
        detail = report.get_invoice(bill.id)
        self.assertEqual(detail['residual'], '60.00')
        self.assertTrue(detail['paid_unavailable'])
        self.assertIsNone(detail['paid'])
        day = report.get_days('2099-09-15', '2099-09-15', 'all')['days'][0]
        self.assertTrue(day['paid_unavailable'])
        self.assertIsNone(day['paid'])

        noncash = self._bill(100, day='2099-09-14')
        self._settle(noncash, 40)
        detail = report.get_invoice(noncash.id)
        self.assertEqual((detail['paid'], detail['residual']), ('0.00', '60.00'))
        self.assertFalse(detail['paid_unavailable'])

    def test_actual_cash_payment_not_noncash_settlement(self):
        bill = self._bill(100)
        cash_account = self.env['account.account'].create({
            'name': 'Test cash', 'code': 'DPR101', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        journal = self.env['account.journal'].create({
            'name': 'Test cash journal', 'code': 'DPRC', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': cash_account.id,
        })
        journal.outbound_payment_method_line_ids.write({'payment_account_id': cash_account.id})
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({'journal_id': journal.id, 'amount': 40, 'payment_date': bill.invoice_date})
        payment = wizard._create_payments()
        self.assertEqual(payment.state, 'paid')
        report = self._report('cashier')
        detail = report.get_invoice(bill.id)
        self.assertEqual((detail['paid'], detail['residual']), ('40.00', '60.00'))
        self.assertEqual(report.get_days('2099-09-15', '2099-09-15', 'all')['days'][0]['paid'], '40.00')
        self._settle(bill, 60)
        detail = report.get_invoice(bill.id)
        self.assertEqual((detail['paid'], detail['residual']), ('40.00', '0.00'))

    def _cash_journal(self):
        account = self.env['account.account'].create({
            'name': 'Cash evidence', 'code': 'DPR110', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        journal = self.env['account.journal'].create({
            'name': 'Cash evidence', 'code': 'DPRX', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': account.id,
        })
        (journal.outbound_payment_method_line_ids | journal.inbound_payment_method_line_ids).write({'payment_account_id': account.id})
        return journal

    def test_cash_refund_and_payment_distributed_across_bills(self):
        journal = self._cash_journal()
        first, second = self._bill(60), self._bill(40)
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=(first | second).ids,
        ).create({'journal_id': journal.id, 'payment_date': first.invoice_date, 'group_payment': True})
        payments = wizard._create_payments()
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments.state, 'paid')
        report = self._report('cashier')
        self.assertEqual(report.get_invoice(first.id)['paid'], '60.00')
        self.assertEqual(report.get_invoice(second.id)['paid'], '40.00')
        refund = self._bill(20, kind='in_refund')
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=refund.ids,
        ).create({'journal_id': journal.id, 'payment_date': refund.invoice_date})._create_payments()
        self.assertEqual(report.get_invoice(refund.id)['paid'], '-20.00')
        self.assertEqual(report.get_days('2099-09-15', '2099-09-15', 'all')['days'][0]['paid'], '80.00')

    def test_mixed_cash_and_writeoff_is_unavailable(self):
        journal = self._cash_journal()
        bill = self._bill(100)
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': journal.id, 'amount': 80, 'payment_date': bill.invoice_date,
            'payment_difference_handling': 'reconcile', 'writeoff_account_id': self.expense.id,
        })._create_payments()
        report = self._report('cashier')
        self.assertIsNone(report.get_invoice(bill.id)['paid'])
        day = report.get_days('2099-09-15', '2099-09-15', 'all')['days'][0]
        self.assertTrue(day['paid_unavailable'])
        self.assertIsNone(day['paid'])

    def test_pending_payment_without_move_is_not_confirmed_paid(self):
        bill = self._bill(100)
        journal = self.env['account.journal'].create({
            'name': 'Pending cash', 'code': 'DPRP', 'type': 'cash', 'company_id': self.company.id,
        })
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({'journal_id': journal.id, 'amount': 40, 'payment_date': bill.invoice_date})
        payment = wizard._create_payments()
        self.assertEqual(payment.state, 'in_process')
        detail = self._report('cashier').get_invoice(bill.id)
        self.assertEqual(detail['paid'], '0.00')
        self.assertTrue(detail['paid_pending'])

    def test_paid_state_on_unsettled_outstanding_account_is_unavailable(self):
        bill = self._bill(100)
        journal = self._cash_journal()
        outstanding = self.env['account.account'].create({
            'name': 'Unsettled payment account', 'code': 'DPR113',
            'account_type': 'asset_current', 'reconcile': True,
            'company_ids': [Command.set(self.company.ids)],
        })
        journal.outbound_payment_method_line_ids.write({'payment_account_id': outstanding.id})
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({'journal_id': journal.id, 'amount': 40, 'payment_date': bill.invoice_date})._create_payments()
        self.assertTrue(payment.move_id)
        payment.action_validate()  # Odoo allows this without a bank match.
        self.assertEqual(payment.state, 'paid')
        liquidity, _, _ = payment._seek_for_lines()
        self.assertEqual(liquidity.account_id, outstanding)
        detail = self._report('cashier').get_invoice(bill.id)
        self.assertTrue(detail['paid_unavailable'])
        self.assertIsNone(detail['paid'])

    def test_daily_query_count_is_bounded_for_unpaid_batch(self):
        self._bill(1, day='2099-09-14')
        for index in range(30):
            self._bill(index + 1)
        self.env.flush_all()
        report = self._report('cashier')
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        report.get_days('2099-09-14', '2099-09-14', 'all')
        one = self.env.cr.sql_log_count - before
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        report.get_days('2099-09-15', '2099-09-15', 'all')
        many = self.env.cr.sql_log_count - before
        _logger.warning('Daily purchase query measurement: 1 invoice=%s, 30 invoices=%s', one, many)
        self.assertLessEqual(many, one + 20, 'Invoice count must not cause per-invoice SQL queries')

    def test_daily_query_count_with_separate_cash_payments(self):
        journal = self._cash_journal()
        for day, count in [('2099-09-14', 1), ('2099-09-15', 10)]:
            for index in range(count):
                bill = self._bill(index + 1, day=day)
                self.env['account.payment.register'].with_context(
                    active_model='account.move', active_ids=bill.ids,
                ).create({'journal_id': journal.id, 'payment_date': bill.invoice_date})._create_payments()
        self.env.flush_all()
        report = self._report('cashier')
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        report.get_days('2099-09-14', '2099-09-14', 'all')
        one = self.env.cr.sql_log_count - before
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        report.get_days('2099-09-15', '2099-09-15', 'all')
        many = self.env.cr.sql_log_count - before
        _logger.warning('Daily purchase paid query measurement: 1 invoice=%s, 10 invoices=%s', one, many)
        self.assertLessEqual(many, one + 20, 'Paid invoice count must not cause per-invoice SQL queries')

    def test_invoice_detail_preserves_discount(self):
        bill = self.env['account.move'].create({
            'company_id': self.company.id, 'move_type': 'in_invoice',
            'partner_id': self.partner.id, 'journal_id': self.journal.id,
            'invoice_date': '2099-09-15',
            'invoice_line_ids': [Command.create({
                'name': 'Discounted purchase', 'quantity': 1, 'price_unit': 100,
                'discount': 20, 'account_id': self.expense.id, 'tax_ids': [Command.clear()],
            })],
        })
        bill.action_post()
        detail = self._report('cashier').get_invoice(bill.id)
        self.assertEqual(detail['lines'][0]['unit_price'], '100')
        self.assertEqual(detail['lines'][0]['discount'], '20')
        self.assertEqual(detail['lines'][0]['subtotal'], '80.00')
        self.assertEqual(detail['total'], '80.00')

    def test_foreign_currency_is_included_without_summing_in_original_currency(self):
        foreign = self.env['res.currency'].create({
            'name': 'DRX', 'symbol': 'DX', 'rounding': 0.01, 'active': True,
        })
        self.env['res.currency.rate'].create({
            'name': '2099-01-01', 'currency_id': foreign.id,
            'company_id': self.company.id, 'rate': 2.0,
        })
        bill = self.env['account.move'].create({
            'company_id': self.company.id, 'move_type': 'in_invoice',
            'partner_id': self.partner.id, 'journal_id': self.journal.id,
            'currency_id': foreign.id, 'invoice_date': '2099-09-15',
            'invoice_line_ids': [Command.create({
                'name': 'Foreign purchase', 'quantity': 1, 'price_unit': 100,
                'account_id': self.expense.id, 'tax_ids': [Command.clear()],
            })],
        })
        bill.action_post()
        report = self._report('cashier')
        row = report.get_day('2099-09-15', 'all', 0)['rows'][0]
        total = report.get_days('2099-09-15', '2099-09-15', 'all')['days'][0]
        self.assertEqual((row['currency'], row['total']), ('DRX', '100.00'))
        self.assertEqual(row['company_total'], total['total'])
        self.assertNotEqual(row['company_total'], row['total'])
        self.assertTrue(row['paid_unavailable'])
        self.assertIsNone(row['paid'])
        self.assertIsNone(total['paid'])

    def test_direct_bank_statement_payment(self):
        bill = self._bill(100)
        cash = self.env['account.account'].create({
            'name': 'Bank cash', 'code': 'DPR111', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        suspense = self.env['account.account'].create({
            'name': 'Bank suspense', 'code': 'DPR112', 'account_type': 'asset_current',
            'company_ids': [Command.set(self.company.ids)],
        })
        journal = self.env['account.journal'].create({
            'name': 'Bank evidence', 'code': 'DPRN', 'type': 'bank', 'company_id': self.company.id,
            'default_account_id': cash.id, 'suspense_account_id': suspense.id,
        })
        statement = self.env['account.bank.statement.line'].create({
            'payment_ref': 'Supplier payment', 'journal_id': journal.id,
            'amount': -40, 'date': bill.invoice_date, 'partner_id': self.partner.id,
        })
        _liquidity, counterpart, _other = statement.with_context(skip_account_move_synchronization=True)._seek_for_lines()
        counterpart.account_id = self.payable
        (counterpart | bill.line_ids.filtered(lambda line: line.account_id == self.payable)).reconcile()
        report = self._report('cashier')
        self.assertEqual(report.get_invoice(bill.id)['paid'], '40.00')
        self.assertEqual(report.get_days('2099-09-15', '2099-09-15', 'all')['days'][0]['paid'], '40.00')

    def test_native_batch_bill_and_direct_bill_each_appear_once(self):
        sar = self.env.ref('base.SAR')
        sar.active = True
        company = self.env['res.company'].create({'name': 'Daily report batch SAR', 'currency_id': sar.id})
        self.env.user.sudo().write({'company_ids': [Command.link(company.id)]})
        self.users['cashier'].sudo().write({'company_ids': [Command.link(company.id)]})
        context = dict(self.env.context, allowed_company_ids=[company.id])
        scoped = self.env(context=context)
        expense = scoped['account.account'].create({
            'name': 'Batch expense', 'code': 'DPR601', 'account_type': 'expense',
            'company_ids': [Command.set(company.ids)],
        })
        payable = scoped['account.account'].create({
            'name': 'Batch payable', 'code': 'DPR201', 'account_type': 'liability_payable',
            'company_ids': [Command.set(company.ids)],
        })
        partner = scoped['res.partner'].create({'name': 'Batch report supplier'})
        partner.with_company(company).property_account_payable_id = payable
        journal = scoped['account.journal'].create({
            'name': 'Batch purchase', 'code': 'DPRB', 'type': 'purchase',
            'company_id': company.id, 'default_account_id': expense.id,
        })
        direct = scoped['account.move'].create({
            'company_id': company.id, 'move_type': 'in_invoice', 'partner_id': partner.id,
            'journal_id': journal.id, 'invoice_date': '2099-09-15', 'ref': 'DIRECT-1',
            'invoice_line_ids': [Command.create({'name': 'Direct', 'quantity': 1, 'price_unit': 25,
                'account_id': expense.id, 'tax_ids': [Command.clear()]})],
        })
        direct.action_post()
        batch = scoped['baseer.purchase.batch'].create({
            'company_id': company.id, 'entry_date': '2099-09-15',
            'line_ids': [Command.create({
                'partner_id': partner.id, 'invoice_date': '2099-09-15',
                'supplier_ref': 'BATCH-1', 'gross_amount': 75,
                'is_credit': True, 'tax_id': False,
            })],
        })
        # Simulate a line entered by the branch manager and approved by the
        # accountant: the two audit creators are intentionally different.
        self.env.cr.execute(
            'UPDATE baseer_purchase_batch_line SET create_uid = %s WHERE id = %s',
            [self.users['cashier'].id, batch.line_ids.id],
        )
        batch.line_ids.invalidate_recordset(['create_uid'])
        batch.action_approve()
        bill = batch.line_ids.move_id
        self.assertEqual(bill.state, 'posted')
        report = api.Environment(self.env.cr, self.users['cashier'].id, context)['baseer.purchase.daily.report']
        daily = report.get_days('2099-09-15', '2099-09-15', 'all')['days'][0]
        self.assertEqual((daily['count'], daily['total']), (2, '100.00'))
        rows = {row['id']: row for row in report.get_day('2099-09-15', 'all', 0)['rows']}
        self.assertEqual(set(rows), {direct.id, bill.id})
        self.assertEqual((rows[direct.id]['entered_by'], rows[direct.id]['entry_source']),
                         (direct.create_uid.name, 'invoice'))
        self.assertEqual((rows[bill.id]['entered_by'], rows[bill.id]['entry_source']),
                         (self.users['cashier'].name, 'batch'))
        detail = report.get_invoice(bill.id)
        self.assertEqual((detail['entered_by'], detail['entry_source']), (self.users['cashier'].name, 'batch'))
        # Even a user authorised for both companies cannot pull an arbitrary
        # other-company bill while the active company is the first one.
        wrong_company = self._report('cashier')
        with self.assertRaises(AccessError):
            wrong_company.get_invoice(bill.id)

    def test_daily_aggregation_refunds_filters_details_and_state(self):
        first = self._bill(100)
        second = self._bill(50)
        refund = self._bill(20, kind='in_refund')
        self._bill(999, post=False)
        # Create reproducible status fixtures without altering any real records.
        self.env.flush_all()
        self.env.cr.execute("UPDATE account_move SET payment_state = 'paid' WHERE id = %s", [second.id])
        self.env.cr.execute("UPDATE account_move SET payment_state = 'partial' WHERE id = %s", [first.id])
        (first | second).invalidate_recordset(['payment_state'])
        for role in ('owner', 'accountant', 'cashier'):
            report = self._report(role)
            days = report.get_days('2099-09-15', '2099-09-15', 'all')['days']
            self.assertEqual(len(days), 1)
            self.assertEqual(days[0]['date'], '2099-09-15')
            self.assertEqual(days[0]['count'], 3)
            self.assertEqual(days[0]['total'], '130.00')
            self.assertEqual(report.get_days('2099-09-15', '2099-09-15', 'paid')['days'][0]['count'], 1)
            self.assertEqual(report.get_days('2099-09-15', '2099-09-15', 'partial')['days'][0]['count'], 1)
            rows = report.get_day('2099-09-15', 'all', 0)
            self.assertEqual({row['id'] for row in rows['rows']}, {first.id, second.id, refund.id})
            self.assertFalse(rows['has_more'])
            detail = report.get_invoice(refund.id)
            self.assertEqual(detail['kind'], 'in_refund')
            self.assertEqual(detail['company_total'], '-20.00')
            self.assertEqual(detail['lines'][0]['description'], 'Report goods')

    def test_no_access_to_pos_cashier_other_company_or_draft(self):
        bill = self._bill(42)
        draft = self._bill(3, post=False)
        report = self._report('cashier')
        self.assertEqual(report.get_invoice(bill.id)['id'], bill.id)
        # Authorized roles may open a draft from the drafts / unapproved filter.
        self.assertEqual(report.get_invoice(draft.id)['id'], draft.id)
        self.assertEqual(report.get_invoice(draft.id)['status'], 'draft')
        # The default posted view includes the posted bill only, not the draft.
        payload = report.get_days('2099-09-15', '2099-09-15', 'all')
        self.assertEqual(payload['days'][0]['count'], 1)
        self.assertNotIn(draft.id, [row['id'] for row in report.get_day('2099-09-15', 'all', 0)['rows']])
        # Altering a context's active company cannot bypass the user company guard.
        forged = report.with_context(allowed_company_ids=[self.company_b.id])
        with self.assertRaises(AccessError):
            forged.get_days('2099-09-15', '2099-09-15', 'all')
        with self.assertRaises(AccessError):
            forged.get_invoice(bill.id)
        unauthorized = self._report('pos_cashier')
        for operation in (
            lambda: unauthorized.get_days('2099-09-15', '2099-09-15', 'all'),
            lambda: unauthorized.get_day('2099-09-15', 'all', 0),
            lambda: unauthorized.get_invoice(bill.id),
            lambda: unauthorized.get_invoice(draft.id),
        ):
            with self.assertRaises(AccessError):
                operation()

    def test_validation_and_pagination(self):
        report = self._report('cashier')
        for operation in (
            lambda: report.get_days('2098-01-01', '2099-09-15', 'all'),
            lambda: report.get_days('2099-09-16', '2099-09-15', 'all'),
            lambda: report.get_days('2099-09-15', '2099-09-15', 'made_up'),
            lambda: report.get_day('2099-09-15', 'all', -1),
            lambda: report.get_day('2099-09-15', 'all', True),
        ):
            with self.assertRaises(ValidationError):
                operation()
        for index in range(51):
            self._bill(index + 1)
        first = report.get_day('2099-09-15', 'all', 0)
        second = report.get_day('2099-09-15', 'all', 50)
        self.assertEqual((len(first['rows']), first['count'], first['has_more']), (50, 51, True))
        self.assertEqual((len(second['rows']), second['has_more']), (1, False))
        self.assertFalse(set(row['id'] for row in first['rows']) & set(row['id'] for row in second['rows']))


    def _pay(self, bill, journal, amount=None):
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': journal.id,
            'amount': amount if amount is not None else bill.amount_residual,
            'payment_date': bill.invoice_date,
        })
        payment = wizard._create_payments()
        self.assertEqual(payment.state, 'paid')
        return payment

    def _osama_journal(self):
        account = self.env['account.account'].create({
            'name': 'Representative Petty Cash | عهدة مندوبي المشتريات',
            'code': 'DPR199', 'account_type': 'asset_current',
            'company_ids': [Command.set(self.company.ids)],
        })
        journal = self.env['account.journal'].create({
            'name': 'عهدة أسامة', 'code': 'OSMC', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': account.id,
        })
        (journal.outbound_payment_method_line_ids | journal.inbound_payment_method_line_ids).write({
            'payment_account_id': account.id,
        })
        return journal

    def _bank_journal(self, name='Test bank', code='DPRB', acc_number=None):
        account = self.env['account.account'].create({
            'name': name + ' account', 'code': 'DPR' + code, 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        journal = self.env['account.journal'].create({
            'name': name, 'code': code, 'type': 'bank',
            'company_id': self.company.id, 'default_account_id': account.id,
        })
        if acc_number:
            journal.bank_account_id = self.env['res.partner.bank'].create({
                'acc_number': acc_number,
                'partner_id': self.company.partner_id.id,
                'company_id': self.company.id,
            })
        (journal.outbound_payment_method_line_ids | journal.inbound_payment_method_line_ids).write({
            'payment_account_id': account.id,
        })
        return journal

    def test_payment_method_cards_and_filters(self):
        cash = self._cash_journal()
        osama = self._osama_journal()
        bank = self._bank_journal('الراجحي ••2029', 'DPR1')
        cash_bill = self._bill(40, day='2099-09-15')
        osama_bill = self._bill(50, day='2099-09-15')
        bank_bill = self._bill(60, day='2099-09-15')
        self._pay(cash_bill, cash)
        self._pay(osama_bill, osama)
        self._pay(bank_bill, bank)
        report = self._report('cashier')
        payload = report.get_days('2099-09-15', '2099-09-15', 'all')
        methods = {card['key']: card for card in payload['methods']}
        self.assertEqual(methods['osama']['count'], 1)
        self.assertEqual(methods['osama']['total'], '50.00')
        self.assertEqual(methods['cash']['count'], 1)
        self.assertEqual(methods['cash']['total'], '40.00')
        bank_key = f'journal:{bank.id}'
        self.assertEqual(methods[bank_key]['count'], 1)
        self.assertEqual(methods[bank_key]['total'], '60.00')
        self.assertEqual(payload['days'][0]['count'], 3)
        osama_only = report.get_days('2099-09-15', '2099-09-15', 'all', 'osama')
        self.assertEqual(osama_only['days'][0]['count'], 1)
        self.assertEqual(osama_only['days'][0]['total'], '50.00')
        self.assertEqual({card['key'] for card in osama_only['methods']}, set(methods))
        rows = report.get_day('2099-09-15', 'all', 0, 'osama')['rows']
        self.assertEqual([row['id'] for row in rows], [osama_bill.id])
        self.assertEqual(rows[0]['payment_methods'][0]['key'], 'osama')
        with self.assertRaises(ValidationError):
            report.get_days('2099-09-15', '2099-09-15', 'all', 'made_up')

    def test_osama_settlement_entry_and_1994_account(self):
        bill = self._bill(25, day='2099-09-16')
        custody = self.env['account.account'].create({
            'name': 'Custody 1994', 'code': 'DPR194', 'account_type': 'asset_current',
            'company_ids': [Command.set(self.company.ids)],
        })
        entry = self.env['account.move'].create({
            'move_type': 'entry', 'company_id': self.company.id,
            'journal_id': self.settlement_journal.id, 'date': bill.invoice_date,
            'ref': 'تسوية عهدة أسامة',
            'line_ids': [
                Command.create({'name': 'Supplier payable', 'account_id': self.payable.id,
                                'partner_id': self.partner.id, 'debit': 25, 'credit': 0}),
                Command.create({'name': 'عهدة أسامة', 'account_id': custody.id,
                                'debit': 0, 'credit': 25}),
            ],
        })
        entry.action_post()
        (bill.line_ids | entry.line_ids).filtered(
            lambda line: line.account_id == self.payable and not line.reconciled
        ).reconcile()
        report = self._report('cashier')
        payload = report.get_days('2099-09-16', '2099-09-16', 'all')
        self.assertEqual(payload['methods'][0]['key'], 'osama')
        self.assertEqual(payload['methods'][0]['count'], 1)

        numbered = self._bill(15, day='2099-09-17')
        journal = self._bank_journal('Personal custody', 'PERS', acc_number='SA0000000000000000001994')
        self._pay(numbered, journal)
        card = report.get_days('2099-09-17', '2099-09-17', 'all')['methods'][0]
        self.assertEqual(card['key'], 'osama')
        self.assertEqual(card['total'], '15.00')

    def test_draft_and_unapproved_match_and_exclude_unpaid(self):
        draft = self._bill(80, day='2099-09-18', post=False)
        unpaid = self._bill(90, day='2099-09-18')
        cancelled = self._bill(10, day='2099-09-18')
        cancelled.button_draft()
        cancelled.button_cancel()
        report = self._report('cashier')
        all_days = report.get_days('2099-09-18', '2099-09-18', 'all')
        self.assertEqual(all_days['days'][0]['count'], 1)
        self.assertEqual(all_days['days'][0]['total'], '90.00')
        statuses = {card['key']: card for card in all_days['statuses']}
        self.assertEqual(statuses['not_paid']['count'], 1)
        self.assertEqual(statuses['not_paid']['total'], '90.00')
        self.assertEqual(statuses['draft']['count'], 1)
        self.assertEqual(statuses['draft']['total'], '80.00')
        self.assertEqual(statuses['unapproved']['count'], 1)
        self.assertEqual(statuses['unapproved']['total'], '80.00')
        drafts = report.get_days('2099-09-18', '2099-09-18', 'draft')
        unapproved = report.get_days('2099-09-18', '2099-09-18', 'unapproved')
        self.assertEqual(drafts['days'][0]['count'], 1)
        self.assertEqual(drafts['days'][0]['total'], '80.00')
        self.assertEqual(unapproved['days'][0]['count'], drafts['days'][0]['count'])
        self.assertEqual(unapproved['days'][0]['total'], drafts['days'][0]['total'])
        self.assertEqual(report.get_day('2099-09-18', 'draft', 0)['rows'][0]['id'], draft.id)
        self.assertEqual(report.get_day('2099-09-18', 'unapproved', 0)['rows'][0]['id'], draft.id)
        self.assertEqual(report.get_invoice(draft.id)['status'], 'draft')
        self.assertNotIn(cancelled.id, [row['id'] for row in report.get_day('2099-09-18', 'unapproved', 0)['rows']])
        self.assertNotIn(unpaid.id, [row['id'] for row in report.get_day('2099-09-18', 'unapproved', 0)['rows']])
        # «لم تُعتمد» must stay identical to drafts even if a posted bill is unmarked as reviewed.
        unpaid.checked = False
        statuses = {card['key']: card for card in report.get_days('2099-09-18', '2099-09-18', 'all')['statuses']}
        self.assertEqual(statuses['draft']['count'], 1)
        self.assertEqual(statuses['unapproved']['count'], 1)
        self.assertEqual(statuses['not_paid']['count'], 1)
        self.assertEqual(
            {row['id'] for row in report.get_day('2099-09-18', 'unapproved', 0)['rows']},
            {row['id'] for row in report.get_day('2099-09-18', 'draft', 0)['rows']},
        )
        self.assertEqual({row['id'] for row in report.get_day('2099-09-18', 'draft', 0)['rows']}, {draft.id})

    def test_mixed_methods_appear_on_each_card(self):
        cash = self._cash_journal()
        bank = self._bank_journal('Mixed bank', 'MXB')
        bill = self._bill(100, day='2099-09-19')
        self._pay(bill, cash, 40)
        self._pay(bill, bank, 60)
        report = self._report('cashier')
        methods = {card['key']: card for card in report.get_days('2099-09-19', '2099-09-19', 'all')['methods']}
        self.assertEqual(methods['cash']['count'], 1)
        self.assertEqual(methods[f'journal:{bank.id}']['count'], 1)
        self.assertEqual(report.get_days('2099-09-19', '2099-09-19', 'all', 'cash')['days'][0]['count'], 1)
