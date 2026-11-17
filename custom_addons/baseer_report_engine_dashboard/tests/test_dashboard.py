import json
import re
from pathlib import Path

from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestDashboard(TransactionCase):
    def test_create_new_action_requires_view_normalization(self):
        journals = self.env['account.journal'].create([
            {'name': 'New sale', 'code': 'DNSL', 'type': 'sale'},
            {'name': 'New general', 'code': 'DNGE', 'type': 'general'},
        ])
        for journal in journals:
            action = journal.action_create_new()
            self.assertIsInstance(action, dict)
            self.assertEqual(action['type'], 'ir.actions.act_window')
            self.assertEqual(action['view_mode'], 'form')
            # The dashboard must construct views before passing this to doAction.
            self.assertNotIn('views', action)

    def test_dashboard_scope_and_data(self):
        Journal = self.env['account.journal']
        journals = Journal.create([
            {'name': 'Dashboard ' + name, 'code': code, 'type': kind, 'show_on_dashboard': True}
            for name, code, kind in [('Sales', 'DSAL', 'sale'), ('Purchases', 'DPUR', 'purchase'),
                                     ('Bank', 'DBNK', 'bank'), ('Cash', 'DCSH', 'cash'),
                                     ('Misc', 'DMIS', 'general')]
        ])
        hidden = Journal.create({'name': 'Dashboard hidden', 'code': 'DHID', 'type': 'general', 'show_on_dashboard': False})
        service = self.env['baseer.accounting.dashboard']
        dates = {j.id: j.write_date for j in journals | hidden}
        data = service.get_dashboard({'search': 'Dashboard'})
        cards = {c['id']: c for c in data['journals']}
        self.assertTrue(set(journals.ids) <= set(cards))
        self.assertNotIn(hidden.id, cards)
        for journal in journals:
            expected = json.loads(journal.kanban_dashboard)
            expected.pop('onboarding', None)
            self.assertEqual(cards[journal.id]['dashboard'], expected)
        self.assertIn(hidden.id, [c['id'] for c in service.get_dashboard({'favorites_only': False, 'search': 'hidden'})['journals']])
        self.assertEqual(dates, {j.id: j.write_date for j in journals | hidden})
        self.assertTrue(all(self.env.ref(r['xmlid'], raise_if_not_found=False) for r in data['reports']))
        self.assertEqual(data['is_user'], self.env.user.has_group('account.group_account_user'))
        accountant = new_test_user(self.env, login='dashboard_accountant', groups='account.group_account_user')
        self.assertTrue(service.with_user(accountant).get_dashboard({'search': 'Dashboard'})['is_user'])
        general = next(card for card in cards.values() if card['type'] == 'general')
        self.assertIn('number_draft', general['dashboard'])
        for xmlid in ('account.action_account_invoice_report_all', 'account.action_account_invoice_report_all_supp'):
            self.assertTrue(self.env.ref(xmlid))

    def test_assets(self):
        root = Path(__file__).resolve().parents[1] / 'static/src'
        css = (root / 'dashboard.scss').read_text()
        xml = (root / 'dashboard.xml').read_text()
        js = (root / 'dashboard.js').read_text()
        self.assertIn('function normalizeAction(action)', js)
        self.assertIn('action.view_mode.split(",").map', js)
        self.assertIn('this.action.doAction(normalizeAction(action))', js)
        self.assertIn('max-width: 767px', css)
        self.assertIn('grid-template-columns: minmax(0, 1fr)', css)
        self.assertIn('<bdi dir="ltr"', xml)
        self.assertRegex(xml, r'class="o_bre_graph"\s+dir="ltr"')
        self.assertNotIn('الإزالة من المفضلة', xml)
        self.assertIn("card.type === 'general' and state.is_user", xml)
        self.assertIn('search_default_no_auto_post: 1', xml)
        self.assertIn('Misc. Operations', xml)
        self.assertNotIn('Miscellaneous Operations', xml)
        self.assertNotIn('o_sample_data', xml.split('<div class="o_bre_body"', 1)[1].split('>', 1)[0])
        translation = (root.parents[1] / 'i18n/ar_001.po').read_text()
        self.assertIn('msgid "Misc. Operations"\nmsgstr "العمليات المنوعة"', translation)
        labels = {
            'Favorites': 'المفضلة', 'Transactions': 'المعاملات', 'Balance': 'الرصيد',
            'Last Statement': 'آخر كشف حساب', 'Payments': 'الدفعات',
            'Misc. Operations': 'العمليات المنوعة', 'Unpaid': 'غير مدفوعة',
            'To Pay': 'بانتظار الدفع', 'Late': 'متأخر', 'To Validate': 'بانتظار التصديق',
            'New': 'جديد', 'View': 'عرض', 'Reporting': 'إعداد التقارير',
            'Configuration': 'التهيئة', 'Invoices Analysis': 'تحليل الفواتير',
            'Bills Analysis': 'تحليل الفواتير',
        }
        for source, target in labels.items():
            self.assertIn(f'msgid "{source}"\nmsgstr "{target}"', translation)
        # OWL strips indentation between nodes, so a conditional label needs an
        # explicit space after its count; ordinary text labels need a leading space.
        for match in re.finditer(r'<t t-(?:esc|out)="card\.dashboard\.(?:number_\w+|num_checks_to_print)"\s*/>([^<]*)(<[^>]+>)?', xml):
            text, next_tag = match.groups()
            self.assertTrue(text.startswith(' ') or (next_tag and 't-esc="\' \'"' in next_tag), match.group())
        self.assertNotIn('chart.js', (root / 'dashboard.js').read_text().lower())
        self.assertNotRegex(css, r'min-width:\s*(?:4(?:1[3-9]|[2-9]\d)|[5-9]\d\d|\d{4,})px')

    def test_company_scope(self):
        company = self.env['res.company'].create({'name': 'Dashboard second company'})
        journal = self.env['account.journal'].with_company(company).create({
            'name': 'Second company journal', 'code': 'SCJ', 'type': 'general',
            'company_id': company.id, 'show_on_dashboard': True,
        })
        service = self.env['baseer.accounting.dashboard']
        own = service.with_context(allowed_company_ids=self.env.company.ids).get_dashboard({'favorites_only': False})
        self.assertNotIn(journal.id, [card['id'] for card in own['journals']])
        both = service.with_context(allowed_company_ids=(self.env.company | company).ids).get_dashboard({'favorites_only': False})
        self.assertIn(journal.id, [card['id'] for card in both['journals']])
        self.assertTrue(all(card['show_company'] for card in both['journals']))

    def test_report_translations(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine_dashboard'], ['ar_001'], overwrite=True)
        menu = self.env.ref('baseer_report_engine_dashboard.menu_dashboard')
        self.assertEqual(menu.with_context(lang='ar_001').name, 'لوحة المحاسبة (جديد)')
        reports = self.env['baseer.accounting.dashboard'].with_context(lang='ar_001').get_dashboard()['reports']
        labels = {report['xmlid']: report['label'] for report in reports}
        self.assertEqual(labels['baseer_report_engine.action_balance_sheet'], 'الميزانية العمومية')
        self.assertEqual(labels['baseer_report_engine.action_aged_payable'], 'حسابات دائنة مستحقة متأخرة')

    def test_transaction_figures(self):
        from datetime import timedelta
        from odoo import Command, fields

        company = self.env.company
        Account = self.env['account.account']
        def account(code, kind):
            return Account.create({'name': code, 'code': code, 'account_type': kind,
                                   'company_ids': [Command.set(company.ids)]})
        receivable = account('DASHAR', 'asset_receivable')
        payable = account('DASHAP', 'liability_payable')
        income = account('DASHIN', 'income')
        expense = account('DASHEX', 'expense')
        partner = self.env['res.partner'].create({'name': 'Dashboard customer',
            'property_account_receivable_id': receivable.id, 'property_account_payable_id': payable.id})
        sale = self.env['account.journal'].create({'name': 'Dashboard sales figures', 'code': 'DFSL', 'type': 'sale'})
        purchase = self.env['account.journal'].create({'name': 'Dashboard purchase figures', 'code': 'DFPU', 'type': 'purchase'})
        general = self.env['account.journal'].create({
            'name': 'Dashboard general figures', 'code': 'DFGE', 'type': 'general',
        })
        self.env['account.move'].create({
            'journal_id': general.id,
            'line_ids': [
                Command.create({'name': 'Debit', 'account_id': expense.id, 'debit': 50}),
                Command.create({'name': 'Credit', 'account_id': income.id, 'credit': 50}),
            ],
        })
        bank_account = account('DASHBK', 'asset_cash')
        suspense = account('DASHSP', 'asset_current')
        bank = self.env['account.journal'].create({'name': 'Dashboard bank figures', 'code': 'DFBK', 'type': 'bank', 'default_account_id': bank_account.id, 'suspense_account_id': suspense.id})
        today = fields.Date.context_today(self.env.user)
        statement_line = self.env['account.bank.statement.line'].create({'journal_id': bank.id, 'payment_ref': 'Deposit', 'date': today, 'amount': 123})
        if statement_line.move_id.state == 'draft':
            statement_line.move_id.action_post()
        for due in (today - timedelta(days=10), today + timedelta(days=10)):
            move = self.env['account.move'].create({'move_type': 'out_invoice', 'journal_id': sale.id,
                'partner_id': partner.id, 'invoice_date': today, 'invoice_date_due': due,
                'invoice_line_ids': [Command.create({'name': 'Item', 'account_id': income.id, 'quantity': 1, 'price_unit': 100})]})
            move.action_post()
        self.env['account.move'].create({'move_type': 'in_invoice', 'journal_id': purchase.id,
            'partner_id': partner.id, 'invoice_date': today,
            'invoice_line_ids': [Command.create({'name': 'Bill', 'account_id': expense.id, 'quantity': 1, 'price_unit': 50})]})
        self.env.flush_all()
        bank.invalidate_recordset(['has_statement_lines', 'current_statement_balance'])
        (sale | purchase | bank).invalidate_recordset(['kanban_dashboard', 'kanban_dashboard_graph'])
        cards = {card['id']: card for card in self.env['baseer.accounting.dashboard'].get_dashboard({'favorites_only': False})['journals']}
        for journal in sale | purchase:
            expected = json.loads(journal.kanban_dashboard)
            for key in ('number_waiting', 'number_late', 'sum_waiting', 'sum_late', 'number_draft', 'sum_draft'):
                self.assertEqual(cards[journal.id]['dashboard'][key], expected[key])
        self.assertEqual(cards[bank.id]['dashboard']['account_balance'], json.loads(bank.kanban_dashboard)['account_balance'])
        self.assertTrue(cards[bank.id]['dashboard']['nb_lines_bank_account_balance'])
        self.assertEqual(cards[sale.id]['dashboard']['number_waiting'], 2)
        self.assertEqual(cards[sale.id]['dashboard']['number_late'], 1)
        self.assertEqual(cards[purchase.id]['dashboard']['number_draft'], 1)
        self.assertEqual(cards[general.id]['dashboard']['number_draft'], 1)
