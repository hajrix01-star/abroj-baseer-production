from odoo import Command, api
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


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
        self.assertEqual((before['total'], before['residual'], before['settled']), ('100.00', '100.00', '0.00'))
        self._settle(bill, 40)
        self.assertEqual(bill.payment_state, 'partial')
        partial = report.get_days('2099-09-15', '2099-09-15', 'partial')['days'][0]
        self.assertEqual((partial['total'], partial['residual'], partial['settled']), ('100.00', '60.00', '40.00'))
        self.assertEqual(report.get_invoice(bill.id)['residual'], '60.00')
        self._settle(bill, 60)
        self.assertEqual(bill.payment_state, 'paid')
        paid = report.get_days('2099-09-15', '2099-09-15', 'paid')['days'][0]
        self.assertEqual((paid['total'], paid['residual'], paid['settled']), ('100.00', '0.00', '100.00'))

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
        batch.action_approve()
        bill = batch.line_ids.move_id
        self.assertEqual(bill.state, 'posted')
        report = api.Environment(self.env.cr, self.users['cashier'].id, context)['baseer.purchase.daily.report']
        daily = report.get_days('2099-09-15', '2099-09-15', 'all')['days'][0]
        self.assertEqual((daily['count'], daily['total']), (2, '100.00'))
        self.assertEqual({row['id'] for row in report.get_day('2099-09-15', 'all', 0)['rows']}, {direct.id, bill.id})
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
        with self.assertRaises(AccessError):
            report.get_invoice(draft.id)
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
