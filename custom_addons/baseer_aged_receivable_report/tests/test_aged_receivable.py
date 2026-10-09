"""Money, cutoff, access and print checks for the customer-only report."""

from decimal import Decimal

from lxml import html as lxml_html

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAgedReceivable(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.report = self.env['baseer.aged.receivable.report']
        Account = self.env['account.account'].with_company(self.company)

        def account(code, kind, reconcile=False):
            return Account.create({
                'code': code, 'name': f'AR report {kind} {code}',
                'account_type': kind, 'reconcile': reconcile,
                'company_ids': [Command.set(self.company.ids)],
            })

        self.receivable = account('958801', 'asset_receivable', True)
        self.income = account('958802', 'income')
        self.bank = account('958803', 'asset_cash')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'AR synthetic customer',
            'property_account_receivable_id': self.receivable.id,
        })
        self.general = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        self.assertTrue(self.general)
        self.sales = self.env['account.journal'].with_company(self.company).create({
            'name': 'AR synthetic sales', 'code': 'ARS', 'type': 'sale',
            'company_id': self.company.id,
        })

    def _invoice(self, move_type, day, amount):
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': move_type, 'partner_id': self.partner.id,
            'journal_id': self.sales.id, 'invoice_date': day, 'invoice_date_due': day,
            'invoice_line_ids': [Command.create({
                'name': 'AR synthetic invoice line', 'quantity': 1,
                'price_unit': amount, 'account_id': self.income.id,
            })],
        })
        move.action_post()
        line = move.line_ids.filtered(lambda item: item.account_id == self.receivable)
        self.assertEqual(len(line), 1)
        return line

    def _entry(self, day, debit_account, credit_account, amount, posted=True,
               partner=None, date_maturity=None, currency=None):
        partner = self.partner if partner is None else partner
        debit = {
            'name': 'AR synthetic debit', 'partner_id': partner.id if partner else False,
            'account_id': debit_account.id, 'debit': amount,
        }
        credit = {
            'name': 'AR synthetic credit', 'partner_id': partner.id if partner else False,
            'account_id': credit_account.id, 'credit': amount,
        }
        if date_maturity:
            (debit if debit_account == self.receivable else credit)['date_maturity'] = date_maturity
        if currency:
            debit.update({'currency_id': currency.id, 'amount_currency': amount * 2})
            credit.update({'currency_id': currency.id, 'amount_currency': -amount * 2})
        move = self.env['account.move'].with_company(self.company).create({
            'date': day, 'journal_id': self.general.id, 'move_type': 'entry',
            'line_ids': [Command.create(debit), Command.create(credit)],
        })
        if posted:
            move._post(soft=False)
        return move.line_ids.filtered(lambda item: item.account_id == self.receivable)

    def _readonly(self):
        return self.env['res.users'].create({
            'name': 'AR readonly accountant', 'login': 'ar_readonly_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })

    def _hide(self, model, record):
        return self.env['ir.rule'].create({
            'name': f'AR hide {model} {record.id}',
            'model_id': self.env['ir.model']._get(model).id,
            'domain_force': f"[('id', '!=', {record.id})]",
        })

    def test_cutoff_credits_and_aging_match_posted_source(self):
        invoice = self._invoice('out_invoice', '2025-01-10', 100)
        credit = self._invoice('out_refund', '2025-01-25', 20)
        early = self._entry('2025-01-20', self.bank, self.receivable, 30)
        late = self._entry('2025-02-10', self.bank, self.receivable, 40)
        (invoice + early).reconcile()
        (invoice + late).reconcile()
        self._entry('2025-01-15', self.receivable, self.income, 999, posted=False)

        january = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        self.assertEqual(january['summary']['receivables'], '70.00')
        self.assertEqual(january['summary']['credits'], '20.00')
        self.assertEqual(january['summary']['net'], '50.00')
        self.assertEqual(january['summary']['buckets']['d1_30'], '70.00')
        self.assertEqual(january['partner_count'], 1)
        posted_balance = sum((Decimal(str(line.balance)) for line in self.env[
            'account.move.line'
        ].search([
            ('company_id', '=', self.company.id), ('parent_state', '=', 'posted'),
            ('date', '<=', '2025-01-31'), ('account_id', '=', self.receivable.id),
        ])), Decimal('0'))
        self.assertEqual(Decimal(january['summary']['net'].replace(',', '')), posted_balance)
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
        self.assertEqual(february['summary']['receivables'], '30.00')
        self.assertEqual(february['summary']['credits'], '20.00')
        self.assertEqual(february['summary']['net'], '10.00')
        self.assertEqual(february['summary']['buckets']['d31_60'], '30.00')

    def test_two_due_dates_on_one_posted_entry_remain_separate(self):
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2025-01-01', 'journal_id': self.general.id,
            'line_ids': [
                Command.create({
                    'name': 'First installment', 'partner_id': self.partner.id,
                    'account_id': self.receivable.id, 'debit': 10,
                    'date_maturity': '2025-01-15',
                }),
                Command.create({
                    'name': 'Second installment', 'partner_id': self.partner.id,
                    'account_id': self.receivable.id, 'debit': 20,
                    'date_maturity': '2025-03-01',
                }),
                Command.create({
                    'name': 'Revenue', 'partner_id': self.partner.id,
                    'account_id': self.income.id, 'credit': 30,
                }),
            ],
        })
        move._post(soft=False)
        report = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        self.assertEqual(report['summary']['buckets']['d1_30'], '10.00')
        self.assertEqual(report['summary']['buckets']['not_due'], '20.00')
        self.assertEqual(report['partners'][0]['open_count'], 2)

    def test_due_buckets_partnerless_and_company_currency(self):
        self._entry('2025-01-01', self.receivable, self.income, 10,
                    date_maturity='2025-02-01', partner=False)
        self._entry('2025-01-01', self.receivable, self.income, 20,
                    date_maturity='2025-01-01')
        self._entry('2025-01-01', self.receivable, self.income, 30,
                    date_maturity='2024-12-20')
        foreign = self.env['res.currency'].create({
            'name': 'ARF', 'symbol': 'ARF', 'rounding': 0.01, 'active': True,
        })
        self._entry('2025-01-01', self.receivable, self.income, 5,
                    date_maturity='2024-11-20', currency=foreign)
        result = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        self.assertEqual(result['summary']['receivables'], '65.00')
        self.assertEqual(result['summary']['buckets']['not_due'], '10.00')
        self.assertEqual(result['summary']['buckets']['d1_30'], '20.00')
        self.assertEqual(result['summary']['buckets']['d31_60'], '30.00')
        self.assertEqual(result['summary']['buckets']['d61_90'], '5.00')
        self.assertEqual(result['partner_count'], 2)
        self.assertIn(False, [row['id'] for row in result['partners']])
        self.assertEqual(self.report.get_partner_lines({
            'cutoff_date': '2025-01-31', 'partner_id': False, 'page': 1,
        })['lines'][0]['open'], '10.00')

    def test_unapplied_credits_are_aged_separately_from_claims(self):
        recent = self._entry('2025-01-20', self.bank, self.receivable, 11)
        old = self._entry('2024-12-01', self.bank, self.receivable, 17)
        result = self.report.get_report({'cutoff_date': '2025-01-31', 'page': 1})
        self.assertEqual(result['summary']['receivables'], '0.00')
        self.assertEqual(result['summary']['credits'], '28.00')
        self.assertEqual(result['summary']['net'], '-28.00')
        self.assertEqual(result['summary']['credit_buckets']['d1_30'], '11.00')
        self.assertEqual(result['summary']['credit_buckets']['d61_90'], '17.00')
        self.assertEqual(result['summary']['buckets']['d1_30'], '0.00')
        rows = self.report.get_partner_lines({
            'cutoff_date': '2025-01-31', 'partner_id': self.partner.id, 'page': 1,
        })['lines']
        by_id = {row['id']: row for row in rows}
        self.assertEqual(by_id[recent.id]['credit_age_bucket'], 'd1_30')
        self.assertEqual(by_id[old.id]['credit_age_bucket'], 'd61_90')
        self.assertEqual(by_id[recent.id]['bucket'], 'credit')

    def test_matched_credit_note_and_reconciliation_removal(self):
        invoice = self._invoice('out_invoice', '2025-01-10', 100)
        refund = self._invoice('out_refund', '2025-01-20', 20)
        (invoice + refund).reconcile()
        options = {'cutoff_date': '2025-01-31', 'page': 1}
        matched = self.report.get_report(options)
        self.assertEqual(matched['summary']['receivables'], '80.00')
        self.assertEqual(matched['summary']['credits'], '0.00')
        partial = self.env['account.partial.reconcile'].search([
            ('debit_move_id', '=', invoice.id), ('credit_move_id', '=', refund.id),
        ], limit=1)
        self.assertTrue(partial)
        partial.unlink()
        unmatched = self.report.get_report(options)
        self.assertEqual(unmatched['summary']['receivables'], '100.00')
        self.assertEqual(unmatched['summary']['credits'], '20.00')
        self.assertEqual(unmatched['summary']['net'], '80.00')

    def test_hidden_source_and_reconciliation_fail_closed(self):
        invoice = self._invoice('out_invoice', '2025-01-10', 100)
        payment = self._entry('2025-01-20', self.bank, self.receivable, 30)
        (invoice + payment).reconcile()
        partial = self.env['account.partial.reconcile'].search([
            ('debit_move_id', '=', invoice.id),
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
            'name': 'AR internal only', 'login': 'ar_internal_only',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        with self.assertRaises(AccessError):
            self.report.with_user(internal).get_report({
                'cutoff_date': '2025-01-31', 'page': 1,
            })

    def test_hidden_reconciliation_counterpart_and_related_records_fail_closed(self):
        invoice = self._invoice('out_invoice', '2025-01-10', 100)
        payment = self._entry('2025-01-20', self.bank, self.receivable, 30)
        (invoice + payment).reconcile()
        readonly_report = self.report.with_user(self._readonly())
        options = {'cutoff_date': '2025-01-31', 'page': 1}
        for model, record in (
            ('account.move.line', payment),
            ('account.move', invoice.move_id),
            ('account.account', self.receivable),
            ('account.journal', self.sales),
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
        self._invoice('out_invoice', '2025-01-10', 100)
        action = self.report.action_print({'cutoff_date': '2025-01-31'})
        self.assertEqual(action['data'], {'cutoff_date': '2025-01-31'})
        pdf = self.env['report.baseer_aged_receivable_report.aged_receivable_pdf']
        values = pdf._get_report_values([], action['data'])
        self.assertEqual(values['report']['summary']['net'], '100.00')
        self.assertEqual(len(values['report']['lines']), 1)
        self.assertEqual(self.env.ref(
            'baseer_aged_receivable_report.action_aged_receivable_pdf',
        ).paperformat_id.orientation, 'Landscape')
        html, _format = self.env['ir.actions.report']._render_qweb_html(
            'baseer_aged_receivable_report.aged_receivable_pdf', docids=[],
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
