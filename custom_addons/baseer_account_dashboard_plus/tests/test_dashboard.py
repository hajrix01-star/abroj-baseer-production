from odoo.tests import tagged, TransactionCase
from ..models.journal import classify_journal


@tagged('post_install', '-at_install')
class TestDashboardPlus(TransactionCase):
    def assert_complete_window(self, action, model):
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], model)
        self.assertTrue(action['name'])
        self.assertIsInstance(action['views'], list)
        self.assertTrue(all(isinstance(view, (list, tuple)) and len(view) == 2 for view in action['views']))
        self.assertTrue({'list', 'form'}.issubset({view[1] for view in action['views']}))
        self.assertEqual(action['view_mode'], 'list,form')
        self.assertIsInstance(action['domain'], list)
        self.assertIsInstance(action['context'], dict)
        self.assertEqual(action['target'], 'current')

    def test_summary_actions_complete(self):
        journals = self.env['account.journal']
        for kind in ('bank', 'cash', 'custody', 'delivery', 'receivable', 'payable', 'draft', 'vat'):
            with self.subTest(kind=kind):
                action = journals.baseer_summary_action(kind)
                self.assert_complete_window(action, 'account.move' if kind == 'draft' else 'account.move.line')
                if kind != 'draft':
                    self.assert_company_filters(action, self.env.companies)
                    self.assertEqual(action['context']['search_default_posted'], 1)
                if kind in ('receivable', 'payable'):
                    expected = 'asset_receivable' if kind == 'receivable' else 'liability_payable'
                    self.assertEqual(action['context']['search_default_account_type'], expected)
                    self.assertEqual(action['context']['search_default_unreconciled'], 1)
                    self.assertEqual(action['domain'], [])

    def assert_company_filters(self, action, companies):
        self.assertEqual(action['context']['allowed_company_ids'], companies.ids)
        self.assertEqual(action['context']['company_ids'], companies.ids)
        self.assertEqual(action['context']['search_default_company_ids'], 1)

    def assert_residual_matches_tile(self, company, kind):
        journals = self.env['account.journal'].with_context(allowed_company_ids=company.ids)
        action = journals.baseer_summary_action(kind)
        ctx = action['context']
        domain = [('company_id', 'in', ctx['company_ids']), ('parent_state', '=', 'posted'),
                  ('account_id.account_type', '=', ctx['search_default_account_type']),
                  ('amount_residual', '!=', 0), ('account_id.reconcile', '=', True)]
        lines = self.env['account.move.line'].with_context(allowed_company_ids=company.ids).search(domain)
        amount = sum(lines.mapped('amount_residual')) * (-1 if kind == 'payable' else 1)
        row = journals.baseer_dashboard_summary()['companies'][0]
        self.assertAlmostEqual(amount, row[kind], places=2)

    def test_filters_for_newly_created_company(self):
        from odoo import Command
        company = self.env['res.company'].create({'name': 'New filters company', 'currency_id': self.env.company.currency_id.id})
        self.env.user.write({'company_ids': [Command.link(company.id)]})
        journals = self.env['account.journal'].with_context(allowed_company_ids=company.ids)
        for kind, account_type in (('receivable', 'asset_receivable'), ('payable', 'liability_payable')):
            action = journals.baseer_summary_action(kind)
            self.assert_company_filters(action, company)
            self.assertEqual(action['context']['search_default_account_type'], account_type)
            self.assertEqual(action['context']['search_default_posted'], 1)
            self.assertEqual(action['context']['search_default_unreconciled'], 1)
            self.assertEqual(action['domain'], [])
            self.assert_residual_matches_tile(company, kind)
        for kind in ('bank', 'cash', 'custody', 'delivery'):
            action = journals.baseer_summary_action(kind)
            self.assert_company_filters(action, company)
            self.assertEqual(action['domain'], [('id', '=', False)])

    def test_journal_account_filters(self):
        from odoo import Command
        company = self.env.company
        other = self.env['res.company'].create({'name': 'Journal filter company', 'currency_id': company.currency_id.id})
        self.env.user.write({'company_ids': [Command.link(other.id)]})
        for target in (company, other):
            for name, code, journal_type in (('Bank filter', 'FBK', 'bank'), ('Cash filter', 'FCS', 'cash'),
                                              ('custody filter', 'FCU', 'cash'), ('Keeta filter', 'FKE', 'bank')):
                account = self.env['account.account'].with_company(target).create({
                    'name': name, 'code': code, 'account_type': 'asset_cash', 'company_ids': [Command.set(target.ids)]})
                self.env['account.journal'].with_company(target).create({
                    'name': name, 'code': code, 'type': journal_type, 'company_id': target.id, 'default_account_id': account.id})
        for companies in (company, other, company | other):
            journals = self.env['account.journal'].with_context(allowed_company_ids=companies.ids)
            candidates = journals.search([('company_id', 'in', companies.ids), ('type', 'in', ['bank', 'cash'])])
            for kind in ('bank', 'cash', 'custody', 'delivery'):
                selected = candidates.filtered(lambda j: j.type == kind if kind in ('bank', 'cash') else classify_journal(j.name, j.code, j.type)[0] == kind)
                action = journals.baseer_summary_action(kind)
                self.assert_company_filters(action, companies)
                self.assertEqual(set(action['context']['account_ids']), set(selected.default_account_id.ids))
                self.assertEqual(action['context']['search_default_account_ids'], 1)
                self.assertNotIn('search_default_unreconciled', action['context'])
                self.assertEqual(action['domain'], [])

    def test_action_normalization(self):
        journals = self.env['account.journal']
        incomplete = {'type': 'ir.actions.act_window', 'name': 'Journal Items',
                      'res_model': 'account.move.line', 'view_mode': 'list,form', 'domain': []}
        self.assert_complete_window(journals._baseer_complete_action(incomplete), 'account.move.line')
        self.assertNotIn('views', incomplete)
        self.assertFalse(journals._baseer_complete_action({'type': 'ir.actions.client'}))
        self.assertFalse(journals._baseer_complete_action({'type': 'ir.actions.act_window'}))

    def test_ledger_action_complete(self):
        from odoo import Command
        company = self.env.company
        account = self.env['account.account'].create({'name': 'Ledger action cash', 'code': 'BACT01',
            'account_type': 'asset_cash', 'company_ids': [Command.set(company.ids)]})
        journal = self.env['account.journal'].create({'name': 'Ledger action bank', 'code': 'BACT',
            'type': 'bank', 'company_id': company.id, 'default_account_id': account.id})
        action = journal.baseer_open_ledger()
        self.assert_complete_window(action, 'account.move.line')
        self.assertIn(('account_id', '=', account.id), action['domain'])

    def test_classification(self):
        self.assertEqual(classify_journal('Keeta ••1310', 'K', 'bank'), ('delivery', 'Keeta'))
        self.assertEqual(classify_journal('جاهز', 'J', 'cash'), ('delivery', 'Jahez'))
        self.assertEqual(classify_journal('هنقر', 'H', 'bank'), ('delivery', 'HungerStation'))
        self.assertEqual(classify_journal('عهدة أسامة', 'C', 'cash')[0], 'custody')
        self.assertFalse(classify_journal('custody', 'C', 'bank')[0])

    def test_report_links(self):
        journal = self.env['account.journal']
        for key in ('ledger', 'receivable', 'payable'):
            action = journal.baseer_report_action(key)
            self.assertEqual(action['type'], 'ir.actions.client')
            self.assertTrue(action['tag'])
            self.assertTrue(action['name'])
            self.assertIn('context', action)
            self.assertTrue(action['target'])
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
        receivable.non_trade = True
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
        for kind in ('receivable', 'payable'):
            self.assert_residual_matches_tile(company, kind)
        bank_action = self.env['account.journal'].with_context(allowed_company_ids=company.ids).baseer_summary_action('bank')
        bank_context = bank_action['context']
        lines = self.env['account.move.line'].with_context(allowed_company_ids=company.ids).search([
            ('company_id', 'in', bank_context['company_ids']), ('parent_state', '=', 'posted'),
            ('account_id', 'in', bank_context['account_ids'])])
        self.assertAlmostEqual(sum(lines.mapped('balance')), row['bank'], places=2)

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
