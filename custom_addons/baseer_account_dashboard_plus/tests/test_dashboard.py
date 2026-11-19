from odoo.tests import tagged, TransactionCase
from ..models.journal import classify_journal


@tagged('post_install', '-at_install')
class TestDashboardPlus(TransactionCase):
    def test_classification(self):
        self.assertEqual(classify_journal('Keeta ••1310', 'K', 'bank'), ('delivery', 'Keeta'))
        self.assertEqual(classify_journal('جاهز', 'J', 'cash'), ('delivery', 'Jahez'))
        self.assertEqual(classify_journal('هنقر', 'H', 'bank'), ('delivery', 'HungerStation'))
        self.assertEqual(classify_journal('عهدة أسامة', 'C', 'cash')[0], 'custody')
        self.assertFalse(classify_journal('custody', 'C', 'bank')[0])

    def test_report_links(self):
        journal = self.env['account.journal']
        self.assertTrue(journal.baseer_report_action('ledger'))
        self.assertFalse(journal.baseer_report_action('missing'))
        from unittest.mock import patch
        from ..models.journal import REPORTS
        with patch.dict(REPORTS, {'optional_missing': ('baseer_missing.action_report', 'Missing')}):
            self.assertFalse(journal.baseer_report_action('optional_missing'))

    def test_view_and_summary(self):
        view = self.env.ref('account.account_journal_dashboard_kanban_view')
        result = self.env['account.journal'].get_views([(view.id, 'kanban')])
        self.assertIn('baseer_open_ledger', result['views']['kanban']['arch'])
        summary = self.env['account.journal'].baseer_dashboard_summary()
        self.assertEqual({r['id'] for r in summary['companies']}, set(self.env.companies.ids))

    def test_style_mobile(self):
        from pathlib import Path
        import re
        scss = (Path(__file__).resolve().parents[1] / 'static/src/summary.scss').read_text()
        self.assertRegex(scss, r'max-width:\s*(?:420|767)px')
        self.assertFalse(any(int(n) > 412 for n in re.findall(r'min-width:\s*(\d+)px', scss)))

    def test_draft_filter_and_company_isolation(self):
        from odoo import Command
        company = self.env.company
        other = self.env['res.company'].create({'name': 'Other dashboard company', 'currency_id': company.currency_id.id})
        self.env.user.write({'company_ids': [Command.link(other.id)]})
        journals = self.env['account.journal']
        for target in (company, other):
            journal = journals.with_company(target).create({'name': 'Agent entries', 'code': 'AGNT', 'type': 'general', 'company_id': target.id})
            for ref in ('AGENT: sample', 'other reference'):
                self.env['account.move'].with_company(target).create({'journal_id': journal.id, 'company_id': target.id, 'ref': ref})
        summary = journals.with_context(allowed_company_ids=[other.id]).baseer_dashboard_summary()
        self.assertEqual([row['id'] for row in summary['companies']], [other.id])
        self.assertEqual(summary['draft_count'], 1)
        domain = journals.with_context(allowed_company_ids=[other.id]).baseer_summary_action('draft')['domain']
        self.assertEqual(len(self.env['account.move'].with_context(allowed_company_ids=[other.id]).search(domain)), 1)

    def test_posted_ledger_and_summary_balances(self):
        from odoo import Command, fields
        company = self.env.company
        Account = self.env['account.account'].with_company(company)
        def account(code, kind, reconcile=False):
            return Account.create({'name': code, 'code': code, 'account_type': kind,
                                   'reconcile': reconcile, 'company_ids': [Command.set(company.ids)]})
        bank = account('BTEST01', 'asset_cash')
        counterpart = account('BTEST02', 'equity')
        receivable = account('BTEST03', 'asset_receivable', True)
        payable = account('BTEST04', 'liability_payable', True)
        tax_account = account('BTEST05', 'liability_current')
        partner = self.env['res.partner'].create({'name': 'Dashboard partner'})
        journal = self.env['account.journal'].create({'name': 'Dashboard bank', 'code': 'TBNK', 'type': 'bank', 'company_id': company.id, 'default_account_id': bank.id})
        general = self.env['account.journal'].create({'name': 'Dashboard test', 'code': 'TGEN', 'type': 'general', 'company_id': company.id})
        tax = self.env['account.tax'].create({'name': 'Dashboard output tax', 'amount': 15, 'type_tax_use': 'sale', 'company_id': company.id})
        count_before = self.env['account.journal'].baseer_dashboard_summary()['draft_count']
        move = self.env['account.move'].create({'journal_id': general.id, 'date': fields.Date.today(), 'ref': 'AGENT: posted excluded', 'line_ids': [
            Command.create({'name': 'Bank', 'account_id': bank.id, 'debit': 100}),
            Command.create({'name': 'Receivable', 'account_id': receivable.id, 'partner_id': partner.id, 'debit': 200}),
            Command.create({'name': 'Payable', 'account_id': payable.id, 'partner_id': partner.id, 'credit': 50}),
            Command.create({'name': 'Tax', 'account_id': tax_account.id, 'tax_repartition_line_id': tax.invoice_repartition_line_ids.filtered(lambda line: line.repartition_type == 'tax')[:1].id, 'credit': 30}),
            Command.create({'name': 'Offset', 'account_id': counterpart.id, 'credit': 220}),
        ]})
        move.action_post()
        draft = self.env['account.move'].create({'journal_id': general.id, 'date': fields.Date.today(), 'ref': 'AGENT: draft amount', 'line_ids': [
            Command.create({'name': 'Draft debit', 'account_id': bank.id, 'debit': 175}),
            Command.create({'name': 'Draft credit', 'account_id': counterpart.id, 'credit': 175}),
        ]})
        self.assertEqual(abs(draft.amount_total), 175)
        card = journal._get_journal_dashboard_data_batched()[journal.id]
        self.assertEqual(card['baseer_ledger_balance'], company.currency_id.format(100))
        self.assertTrue(card['baseer_has_ledger_diff'])
        summary = self.env['account.journal'].with_context(allowed_company_ids=[company.id]).baseer_dashboard_summary()
        self.assertEqual(summary['draft_count'], count_before + 1)
        row = next(row for row in summary['companies'] if row['id'] == company.id)
        self.assertGreaterEqual(row['draft_amount'], 175)
        self.assertGreaterEqual(row['bank'], 100)
        self.assertGreaterEqual(row['receivable'], 200)
        self.assertGreaterEqual(row['payable'], 50)
        self.assertGreaterEqual(row['vat'], 30)

    def test_ledger_two_companies(self):
        from odoo import Command, fields
        other = self.env['res.company'].create({'name': 'Ledger second company', 'currency_id': self.env.company.currency_id.id})
        self.env.user.write({'company_ids': [Command.link(other.id)]})
        companies = self.env.company | other
        journals = self.env['account.journal']
        amounts = {}
        for company, amount in zip(companies, (120, 340)):
            env_company = self.env['account.account'].with_company(company)
            cash = env_company.create({'name': 'Ledger bank', 'code': 'BTEST51', 'account_type': 'asset_cash', 'company_ids': [Command.set(company.ids)]})
            equity = env_company.create({'name': 'Ledger offset', 'code': 'BTEST52', 'account_type': 'equity', 'company_ids': [Command.set(company.ids)]})
            bank = self.env['account.journal'].with_company(company).create({'name': 'Ledger bank', 'code': 'LBK', 'type': 'bank', 'company_id': company.id, 'default_account_id': cash.id})
            general = self.env['account.journal'].with_company(company).create({'name': 'Ledger entries', 'code': 'LGE', 'type': 'general', 'company_id': company.id})
            move = self.env['account.move'].with_company(company).create({'company_id': company.id, 'journal_id': general.id, 'date': fields.Date.today(), 'line_ids': [Command.create({'name': 'Bank', 'account_id': cash.id, 'debit': amount}), Command.create({'name': 'Offset', 'account_id': equity.id, 'credit': amount})]})
            move.action_post()
            journals |= bank
            amounts[bank.id] = amount
        journals = journals.with_context(allowed_company_ids=companies.ids)
        cards = journals._get_journal_dashboard_data_batched()
        for journal in journals:
            self.assertEqual(cards[journal.id]['baseer_ledger_balance'], journal.company_id.currency_id.format(amounts[journal.id]))
            self.assertTrue(cards[journal.id]['baseer_has_ledger_diff'])
        for company in companies:
            result = self.env['account.journal'].with_context(allowed_company_ids=[company.id]).baseer_dashboard_summary()
            self.assertEqual([row['id'] for row in result['companies']], [company.id])
            self.assertGreaterEqual(result['companies'][0]['bank'], amounts[journals.filtered(lambda j: j.company_id == company).id])
