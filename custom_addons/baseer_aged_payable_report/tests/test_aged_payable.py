"""Money, cutoff, access and print checks for the supplier-only report."""

from decimal import Decimal
from types import SimpleNamespace

from lxml import html as lxml_html

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAgedPayable(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.report = self.env['baseer.aged.payable.report']
        Account = self.env['account.account'].with_company(self.company)

        def account(code, kind, reconcile=False):
            return Account.create({
                'code': code, 'name': f'AP report {kind} {code}',
                'account_type': kind, 'reconcile': reconcile,
                'company_ids': [Command.set(self.company.ids)],
            })

        self.payable = account('958811', 'liability_payable', True)
        self.expense = account('958812', 'expense')
        self.bank = account('958813', 'asset_cash')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'AP synthetic supplier',
            'property_account_payable_id': self.payable.id,
        })
        self.general = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        self.assertTrue(self.general)
        self.purchases = self.env['account.journal'].with_company(self.company).create({
            'name': 'AP synthetic purchases', 'code': 'APS', 'type': 'purchase',
            'company_id': self.company.id,
        })

    def _invoice(self, move_type, day, amount):
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': move_type, 'partner_id': self.partner.id,
            'journal_id': self.purchases.id, 'invoice_date': day, 'invoice_date_due': day,
            'invoice_line_ids': [Command.create({
                'name': 'AP synthetic invoice line', 'quantity': 1,
                'price_unit': amount, 'account_id': self.expense.id,
            })],
        })
        move.action_post()
        line = move.line_ids.filtered(lambda item: item.account_id == self.payable)
        self.assertEqual(len(line), 1)
        return line

    def _entry(self, day, debit_account, credit_account, amount, posted=True,
               partner=None, date_maturity=None, currency=None, foreign_amount=None):
        partner = self.partner if partner is None else partner
        debit = {
            'name': 'AP synthetic debit', 'partner_id': partner.id if partner else False,
            'account_id': debit_account.id, 'debit': amount,
        }
        credit = {
            'name': 'AP synthetic credit', 'partner_id': partner.id if partner else False,
            'account_id': credit_account.id, 'credit': amount,
        }
        if date_maturity:
            (debit if debit_account == self.payable else credit)['date_maturity'] = date_maturity
        if currency:
            foreign_amount = foreign_amount if foreign_amount is not None else amount * 2
            debit.update({'currency_id': currency.id, 'amount_currency': foreign_amount})
            credit.update({'currency_id': currency.id, 'amount_currency': -foreign_amount})
        move = self.env['account.move'].with_company(self.company).create({
            'date': day, 'journal_id': self.general.id, 'move_type': 'entry',
            'line_ids': [Command.create(debit), Command.create(credit)],
        })
        if posted:
            move._post(soft=False)
        return move.line_ids.filtered(lambda item: item.account_id == self.payable)

    def _readonly(self):
        return self.env['res.users'].create({
            'name': 'AP readonly accountant', 'login': 'ap_readonly_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })

    def _hide(self, model, record):
        return self.env['ir.rule'].create({
            'name': f'AP hide {model} {record.id}',
            'model_id': self.env['ir.model']._get(model).id,
            'domain_force': f"[('id', '!=', {record.id})]",
        })

    def test_cutoff_credits_and_aging_match_posted_source(self):
        invoice = self._invoice('in_invoice', '2025-01-10', 100)
        credit = self._invoice('in_refund', '2025-01-25', 20)
        early = self._entry('2025-01-20', self.payable, self.bank, 30)
        late = self._entry('2025-02-10', self.payable, self.bank, 40)
        (invoice + early).reconcile()
        (invoice + late).reconcile()
        self._entry('2025-01-15', self.expense, self.payable, 999, posted=False)

        january = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        self.assertEqual(january['summary']['payables'], '70.00')
        self.assertEqual(january['summary']['counter_balances'], '20.00')
        self.assertEqual(january['summary']['net'], '50.00')
        self.assertEqual(january['summary']['buckets']['d1_30'], '70.00')
        self.assertEqual(january['partner_count'], 1)
        posted_balance = sum((Decimal(str(line.balance)) for line in self.env[
            'account.move.line'
        ].search([
            ('company_id', '=', self.company.id), ('parent_state', '=', 'posted'),
            ('date', '<=', '2025-01-31'), ('account_id', '=', self.payable.id),
        ])), Decimal('0'))
        self.assertEqual(Decimal(january['summary']['net'].replace(',', '')), -posted_balance)
        rows = self.report.get_partner_lines({
            'cutoff_date': '2025-01-31', 'partner_id': self.partner.id, 'page': 1,
        })['lines']
        by_id = {row['id']: row for row in rows}
        self.assertEqual(by_id[invoice.id]['open'], '70.00')
        self.assertEqual(by_id[invoice.id]['kind'], 'invoice')
        self.assertEqual(by_id[credit.id]['open'], '-20.00')
        self.assertEqual(by_id[credit.id]['kind'], 'credit_note')
        self.assertNotIn(late.id, by_id)
        self.assertEqual(self.report.action_open_line({
            'line_id': invoice.id, 'cutoff_date': '2025-01-31',
        })['domain'], [('id', '=', invoice.id)])
        with self.assertRaises(AccessError):
            self.report.action_open_line({
                'line_id': late.id, 'cutoff_date': '2025-01-31',
            })

        february = self.report.get_report({'cutoff_date': '2025-02-28', 'page': 1})
        self.assertEqual(february['summary']['payables'], '30.00')
        self.assertEqual(february['summary']['counter_balances'], '20.00')
        self.assertEqual(february['summary']['net'], '10.00')
        self.assertEqual(february['summary']['buckets']['d31_60'], '30.00')

    def test_two_due_dates_on_one_posted_entry_remain_separate(self):
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2025-01-01', 'journal_id': self.general.id,
            'line_ids': [
                Command.create({
                    'name': 'First installment', 'partner_id': self.partner.id,
                    'account_id': self.payable.id, 'credit': 10,
                    'date_maturity': '2025-01-15',
                }),
                Command.create({
                    'name': 'Second installment', 'partner_id': self.partner.id,
                    'account_id': self.payable.id, 'credit': 20,
                    'date_maturity': '2025-03-01',
                }),
                Command.create({
                    'name': 'Expense', 'partner_id': self.partner.id,
                    'account_id': self.expense.id, 'debit': 30,
                }),
            ],
        })
        move._post(soft=False)
        report = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        self.assertEqual(report['summary']['buckets']['d1_30'], '10.00')
        self.assertEqual(report['summary']['buckets']['not_due'], '20.00')
        self.assertEqual(report['partners'][0]['open_count'], 2)

    def test_over_90_days_and_archived_payable_account_remain_in_source(self):
        self._entry('2024-09-01', self.expense, self.payable, 7,
                    date_maturity='2024-09-01')
        self.payable.active = False
        report = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        self.assertEqual(report['summary']['payables'], '7.00')
        self.assertEqual(report['summary']['buckets']['over_90'], '7.00')

    def test_document_label_follows_source_type_and_cutoff_sign(self):
        bill = SimpleNamespace(move_id=SimpleNamespace(move_type='in_invoice'))
        refund = SimpleNamespace(move_id=SimpleNamespace(move_type='in_refund'))
        direct = SimpleNamespace(move_id=SimpleNamespace(move_type='entry'))
        self.assertEqual(self.report._kind(bill, Decimal('1')), 'invoice')
        self.assertEqual(self.report._kind(bill, Decimal('-1')), 'unusual')
        self.assertEqual(self.report._kind(refund, Decimal('-1')), 'credit_note')
        self.assertEqual(self.report._kind(refund, Decimal('1')), 'unusual')
        self.assertEqual(self.report._kind(direct, Decimal('1')), 'direct_claim')
        self.assertEqual(self.report._kind(direct, Decimal('-1')), 'counter_balance')

    def test_due_buckets_partnerless_and_company_currency(self):
        self._entry('2025-01-01', self.expense, self.payable, 10,
                    date_maturity='2025-02-01', partner=False)
        self._entry('2025-01-01', self.expense, self.payable, 20,
                    date_maturity='2025-01-01')
        self._entry('2025-01-01', self.expense, self.payable, 30,
                    date_maturity='2024-12-20')
        foreign = self.env['res.currency'].create({
            'name': 'APF', 'symbol': 'APF', 'rounding': 0.01, 'active': True,
        })
        self._entry('2025-01-01', self.expense, self.payable, 5,
                    date_maturity='2024-11-20', currency=foreign)
        result = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        self.assertEqual(result['summary']['payables'], '65.00')
        self.assertEqual(result['summary']['buckets']['not_due'], '10.00')
        self.assertEqual(result['summary']['buckets']['d1_30'], '20.00')
        self.assertEqual(result['summary']['buckets']['d31_60'], '30.00')
        self.assertEqual(result['summary']['buckets']['d61_90'], '5.00')
        self.assertEqual(result['partner_count'], 2)
        self.assertIn(False, [row['id'] for row in result['partners']])
        unassigned = self.report.get_partner_lines({
            'cutoff_date': '2025-01-31', 'partner_id': False, 'page': 1,
        })['lines'][0]
        self.assertEqual(unassigned['open'], '10.00')
        self.assertEqual(unassigned['kind'], 'direct_claim')

    def test_counter_balances_are_aged_separately_from_claims(self):
        recent = self._entry('2025-01-20', self.payable, self.bank, 11)
        old = self._entry('2024-12-01', self.payable, self.bank, 17)
        result = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        self.assertEqual(result['summary']['payables'], '0.00')
        self.assertEqual(result['summary']['counter_balances'], '28.00')
        self.assertEqual(result['summary']['net'], '-28.00')
        self.assertEqual(result['summary']['counter_buckets']['d1_30'], '11.00')
        self.assertEqual(result['summary']['counter_buckets']['d61_90'], '17.00')
        self.assertEqual(result['summary']['buckets']['d1_30'], '0.00')
        rows = self.report.get_partner_lines({
            'cutoff_date': '2025-01-31', 'partner_id': self.partner.id, 'page': 1,
        })['lines']
        by_id = {row['id']: row for row in rows}
        self.assertEqual(by_id[recent.id]['counter_age_bucket'], 'd1_30')
        self.assertEqual(by_id[old.id]['counter_age_bucket'], 'd61_90')
        self.assertEqual(by_id[recent.id]['bucket'], 'counter')
        self.assertEqual(by_id[recent.id]['kind'], 'counter_balance')

    def test_matched_credit_note_and_reconciliation_removal(self):
        invoice = self._invoice('in_invoice', '2025-01-10', 100)
        refund = self._invoice('in_refund', '2025-01-20', 20)
        (invoice + refund).reconcile()
        options = {'cutoff_date': '2025-01-31', 'page': 1}
        matched = self.report.get_report(options)
        self.assertEqual(matched['summary']['payables'], '80.00')
        self.assertEqual(matched['summary']['counter_balances'], '0.00')
        partial = self.env['account.partial.reconcile'].search([
            ('credit_move_id', '=', invoice.id), ('debit_move_id', '=', refund.id),
        ], limit=1)
        self.assertTrue(partial)
        partial.unlink()
        unmatched = self.report.get_report(options)
        self.assertEqual(unmatched['summary']['payables'], '100.00')
        self.assertEqual(unmatched['summary']['counter_balances'], '20.00')
        self.assertEqual(unmatched['summary']['net'], '80.00')

    def test_foreign_currency_full_settlement_with_exchange_difference_at_cutoff(self):
        foreign = self.env['res.currency'].create({
            'name': 'APX', 'symbol': 'APX', 'rounding': 0.01, 'active': True,
        })
        invoice = self._entry(
            '2025-01-10', self.expense, self.payable, 100,
            currency=foreign, foreign_amount=200,
        )
        payment = self._entry(
            '2025-02-10', self.payable, self.bank, 120,
            currency=foreign, foreign_amount=200,
        )
        (invoice + payment).reconcile()
        before = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        after = self.report.get_report({'cutoff_date': '2025-02-28', 'page': 1})
        self.assertEqual(before['summary']['net'], '100.00')
        self.assertEqual(after['summary']['net'], '0.00')
        exchange_lines = self.env['account.move.line'].search([
            ('company_id', '=', self.company.id), ('parent_state', '=', 'posted'),
            ('date', '<=', '2025-02-28'), ('account_id', '=', self.payable.id),
        ]) - invoice - payment
        self.assertTrue(exchange_lines)
        self.assertEqual(sum((Decimal(str(line.balance)) for line in exchange_lines),
                             Decimal('0')), Decimal('-20'))

    def test_hidden_source_and_reconciliation_fail_closed(self):
        invoice = self._invoice('in_invoice', '2025-01-10', 100)
        payment = self._entry('2025-01-20', self.payable, self.bank, 30)
        (invoice + payment).reconcile()
        partial = self.env['account.partial.reconcile'].search([
            ('credit_move_id', '=', invoice.id),
        ], limit=1)
        readonly = self._readonly()
        report = self.report.with_user(readonly)
        self.assertEqual(report.get_report({
            'cutoff_date': '2025-01-31', 'page': 1,
        })['summary']['net'], '70.00')

        source_rule = self._hide('account.move.line', invoice)
        try:
            with self.assertRaises(AccessError):
                report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        finally:
            source_rule.unlink()
        partial_rule = self._hide('account.partial.reconcile', partial)
        try:
            with self.assertRaises(AccessError):
                report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        finally:
            partial_rule.unlink()

        internal = self.env['res.users'].create({
            'name': 'AP internal only', 'login': 'ap_internal_only',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        with self.assertRaises(AccessError):
            self.report.with_user(internal).get_report({
                'cutoff_date': '2025-01-31', 'page': 1,
            })

    def test_hidden_reconciliation_counterpart_and_related_records_fail_closed(self):
        invoice = self._invoice('in_invoice', '2025-01-10', 100)
        payment = self._entry('2025-01-20', self.payable, self.bank, 30)
        (invoice + payment).reconcile()
        readonly_report = self.report.with_user(self._readonly())
        options = {'cutoff_date': '2025-01-31', 'page': 1}
        for model, record in (
            ('account.move.line', payment),
            ('account.move', invoice.move_id),
            ('account.account', self.payable),
            ('account.journal', self.purchases),
            ('res.partner', self.partner),
        ):
            with self.subTest(hidden_model=model):
                rule = self._hide(model, record)
                try:
                    with self.assertRaises(AccessError):
                        readonly_report.get_report(options)
                finally:
                    rule.unlink()

    def test_pdf_uses_full_snapshot_and_a4(self):
        self._invoice('in_invoice', '2025-01-10', 100)
        action = self.report.action_print({'cutoff_date': '2025-01-31'})
        self.assertEqual(action['data'], {'cutoff_date': '2025-01-31'})
        pdf = self.env['report.baseer_aged_payable_report.aged_payable_pdf']
        values = pdf._get_report_values([], action['data'])
        self.assertEqual(values['report']['summary']['net'], '100.00')
        self.assertEqual(len(values['report']['lines']), 1)
        self.assertEqual(self.env.ref(
            'baseer_aged_payable_report.action_aged_payable_pdf',
        ).paperformat_id.orientation, 'Landscape')
        html, _format = self.env['ir.actions.report']._render_qweb_html(
            'baseer_aged_payable_report.aged_payable_pdf', docids=[],
            data=action['data'],
        )
        document = lxml_html.fromstring(html)
        self.assertEqual(len(document.xpath(
            "//div[contains(@class, 'bar-pdf')]//table[contains(@class, 'detail')]/tbody/tr"
        )), 2)
        self.assertIn(b'100.00', html)
        with self.assertRaises(ValidationError):
            pdf._get_report_values([], {'cutoff_date': 'not-a-date'})

    def test_strict_inputs(self):
        for options in ({'cutoff_date': '2025-02-30', 'page': 1},
                        {'cutoff_date': '2025-01-31', 'page': True},
                        {'cutoff_date': '2025-01-31', 'page': 0}):
            with self.subTest(options=options):
                with self.assertRaises(ValidationError):
                    self.report.get_report(options)
