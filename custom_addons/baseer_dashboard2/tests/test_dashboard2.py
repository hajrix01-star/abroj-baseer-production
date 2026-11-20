from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDashboard2(TransactionCase):
    def test_event_date_constraint(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['baseer.dashboard2.event'].create({'name': 'Event', 'date_from': '2026-03-02', 'date_to': '2026-03-01'})

    def test_company_scope(self):
        service = self.env['baseer.dashboard2.service']
        with self.assertRaises(AccessError):
            service._scope('54')
        with self.assertRaises(AccessError):
            service._scope('56')

    def test_categories(self):
        service = self.env['baseer.dashboard2.service']
        categories = self.env['baseer.dashboard2.category'].search([])
        account = self.env['account.account'].new({'code': '400003', 'name': 'Salary', 'account_type': 'expense'})
        self.assertEqual(service._category(account, categories), 'salaries')
        account.code = '500001'
        account.account_type = 'income'
        self.assertEqual(service._category(account, categories), 'revenue')

    def test_meta_and_overview(self):
        service = self.env['baseer.dashboard2.service']
        company = self.env.company
        self.env['ir.config_parameter'].set_param('baseer_dashboard2.company_map', '%s:Test' % company.id)
        meta = service.get_meta()
        self.assertEqual(meta['default_company_key'], str(company.id))
        from datetime import timedelta
        from odoo import fields
        previous = (fields.Date.context_today(service).replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        self.assertEqual(meta['default_month'], next((m for m in meta['months_available'] if m <= previous), previous))
        result = service.get_section('overview', {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-10'}})
        self.assertTrue(result['available'])
        self.assertEqual(len(result['trend']), 6)
        self.assertEqual(result['current']['sales_net'], 0)

    def test_accounting_and_noorix(self):
        from datetime import date
        company = self.env.company
        account_model = self.env['account.account'].with_company(company)
        def account(code, account_type):
            return account_model.create({'code': code, 'name': code, 'account_type': account_type, 'company_ids': [(6, 0, [company.id])]})
        revenue = account('D250001', 'income')
        food = account('400001', 'expense_direct_cost')
        salary = account('400003', 'expense')
        cash = account('D210001', 'asset_cash')
        app = account('D211001', 'asset_receivable')
        journal = self.env['account.journal'].create({'name': 'Dashboard Misc', 'code': 'D2MIS', 'type': 'general', 'company_id': company.id})
        def entry(ref, day, lines, reversed_id=False):
            move = self.env['account.move'].create({'journal_id': journal.id, 'date': day, 'ref': ref, 'reversed_entry_id': reversed_id,
                'line_ids': [(0, 0, {'account_id': acc.id, 'name': name, 'debit': debit, 'credit': credit}) for acc, name, debit, credit in lines]})
            move.action_post()
            return move
        move = entry('NOORIX-SALES', '2026-10-01', [(cash, 'cash', 600, 0), (app, 'keeta', 400, 0), (revenue, 'Sales', 0, 1000)])
        entry('reversal', '2026-10-02', [(cash, 'cash', 0, 60), (app, 'keeta', 0, 40), (revenue, 'Sales', 100, 0)], move.id)
        vat = account('D220001', 'liability_current')
        entry('ملخص المبيعات | Sales summaries/01049', '2026-10-04', [(cash, 'ملخص - بنك | Bank', 115, 0), (revenue, 'Sales', 0, 100), (vat, 'VAT', 0, 15)])
        entry('cost', '2026-10-03', [(food, 'Food', 300, 0), (salary, 'Salary', 200, 0), (cash, 'Paid', 0, 500)])
        service = self.env['baseer.dashboard2.service']
        data = service._accounting([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(data['sales_net'], 1000)
        self.assertEqual(data['categories']['food_cost'], 300)
        self.assertEqual(data['categories']['salaries'], 200)
        self.assertEqual(data['net_profit'], 500)
        sales, _, _, _ = service._sales_summary([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(sales['channels']['cash'], 540)
        self.assertEqual(sales['channels']['keeta'], 360)
        self.assertEqual(sales['channels']['card'], 115)
        self.assertEqual(sales['source_counts']['summary'], 3)
        self.assertEqual(service._sales_vat([company.id], date(2026, 10, 1), date(2026, 10, 31))['value'], 15)
        self.assertFalse(sales['customers']['available'])
        self.env['ir.config_parameter'].set_param('baseer_dashboard2.company_map', '%s:Test' % company.id)
        pnl = service.get_section('pnl', {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-10'}})
        revenue_row = next(row for row in pnl['rows'] if row['key'] == 'revenue')
        self.assertAlmostEqual(sum(child['months'][-1] for child in revenue_row['children']), revenue_row['months'][-1], places=2)
        self.assertIsNone(revenue_row['months'][-2])
        self.assertIsNone(service._timeline([company.id], date(2026, 10, 31), 'monthly')['months'][8]['value'])

    def test_all_sections_smoke(self):
        company = self.env.company
        self.env['ir.config_parameter'].set_param('baseer_dashboard2.company_map', '%s:Test' % company.id)
        params = {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-10'}, 'heatmap_month': '2026-10'}
        service = self.env['baseer.dashboard2.service']
        for section in ('overview', 'revenue', 'expenses', 'ratios', 'pnl', 'inout', 'heatmap'):
            self.assertTrue(service.get_section(section, params)['available'], section)

    def test_scope_and_targets(self):
        from odoo.tests.common import new_test_user
        company = self.env.company
        other = self.env['res.company'].create({'name': 'Dashboard test company'})
        self.env['ir.config_parameter'].set_param('baseer_dashboard2.company_map', f'{company.id}:One,{other.id}:Two,54:Forbidden,56:Forbidden')
        reader = new_test_user(self.env, login='bd2_readonly', groups='account.group_account_readonly', company_id=company.id, company_ids=[(6, 0, [company.id])])
        manager = new_test_user(self.env, login='bd2_manager', groups='account.group_account_manager', company_id=company.id, company_ids=[(6, 0, [company.id, other.id])])
        service = self.env['baseer.dashboard2.service']
        self.assertEqual([c['key'] for c in service.with_user(reader).get_meta()['companies']], [str(company.id)])
        result = service.with_user(reader).get_section('overview', {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-10'}})
        self.assertTrue(result['available'])
        for section in ('revenue', 'expenses', 'ratios', 'pnl', 'inout', 'heatmap'):
            self.assertTrue(service.with_user(reader).get_section(section, {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-10'}})['available'])
        with self.assertRaises(AccessError):
            service.with_user(reader)._scope(str(other.id))
        with self.assertRaises(AccessError):
            service.with_user(reader).save_target(str(company.id), 'food_pct', 29)
        self.assertTrue(service.with_user(manager).save_target(str(company.id), 'food_pct', 29))
        self.assertEqual(service.with_user(manager)._scope('all'), [company.id, other.id])

    def test_cash_custody_and_transfer(self):
        from datetime import date
        company = self.env.company
        account_model = self.env['account.account'].with_company(company)
        def account(code, account_type):
            return account_model.create({'code': code, 'name': code, 'account_type': account_type, 'company_ids': [(6, 0, [company.id])]})
        custody = account('108990', 'asset_current')
        bank = account('D210100', 'asset_cash')
        salary = account('400003', 'expense')
        journal = self.env['account.journal'].create({'name': 'عهدة اختبار', 'code': 'D2CUS', 'type': 'cash', 'company_id': company.id, 'default_account_id': custody.id})
        self.env['baseer.dashboard2.settings'].create({'company_id': company.id, 'outflow_journal_ids': [(6, 0, [journal.id])], 'custody_journal_ids': [(6, 0, [journal.id])]})
        def entry(debit_account, amount):
            move = self.env['account.move'].create({'journal_id': journal.id, 'date': '2026-10-03', 'line_ids': [
                (0, 0, {'name': 'Debit', 'account_id': debit_account.id, 'debit': amount, 'credit': 0}),
                (0, 0, {'name': 'Credit', 'account_id': custody.id, 'debit': 0, 'credit': amount})]})
            move.action_post()
        entry(salary, 200)
        entry(bank, 150)
        result = self.env['baseer.dashboard2.service']._cash_out([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(result['total'], 200)
        self.assertEqual(result['items']['salaries'], 200)
        self.assertEqual(result['sources']['عهدة اختبار'], 200)

    def test_pos_sales(self):
        from datetime import date
        company = self.env.company
        method = self.env['pos.payment.method'].create({'name': 'cash', 'company_id': company.id})
        sale_journal = self.env['account.journal'].create({'name': 'POS sales', 'code': 'D2POS', 'type': 'sale', 'company_id': company.id})
        config = self.env['pos.config'].create({'name': 'Dashboard POS', 'company_id': company.id, 'journal_id': sale_journal.id, 'payment_method_ids': [(6, 0, [method.id])]})
        session = self.env['pos.session'].create({'config_id': config.id})
        order = self.env['pos.order'].create({'company_id': company.id, 'session_id': session.id, 'date_order': '2026-10-01 10:00:00', 'state': 'paid',
                                              'amount_tax': 0, 'amount_total': 115, 'amount_paid': 115, 'amount_return': 0})
        self.env['pos.payment'].create({'pos_order_id': order.id, 'payment_method_id': method.id, 'amount': 115})
        summary, days, _, hours = self.env['baseer.dashboard2.service']._sales_summary([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(summary['gross'], 115)
        self.assertEqual(summary['channels']['cash'], 115)
        self.assertEqual(summary['customers']['value'], 1)
        self.assertTrue(hours)
        account_model = self.env['account.account'].with_company(company)
        cash = account_model.create({'code': 'D2NC', 'name': 'Cash', 'account_type': 'asset_cash', 'company_ids': [(6, 0, [company.id])]})
        revenue = account_model.create({'code': 'D2NR', 'name': 'Sales', 'account_type': 'income', 'company_ids': [(6, 0, [company.id])]})
        misc = self.env['account.journal'].create({'name': 'Noorix', 'code': 'D2NOO', 'type': 'general', 'company_id': company.id})
        move = self.env['account.move'].create({'journal_id': misc.id, 'date': '2026-10-01', 'ref': 'NOORIX-SALES', 'line_ids': [
            (0, 0, {'name': 'cash', 'account_id': cash.id, 'debit': 300, 'credit': 0}),
            (0, 0, {'name': 'sale', 'account_id': revenue.id, 'debit': 0, 'credit': 300})]})
        move.action_post()
        summary, _, _, _ = self.env['baseer.dashboard2.service']._sales_summary([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(summary['gross'], 115)

    def test_outstanding_reconciliation(self):
        from datetime import date
        company = self.env.company
        model = self.env['account.account'].with_company(company)
        def account(code, kind, reconcile=False):
            return model.create({'code': code, 'name': code, 'account_type': kind, 'reconcile': reconcile, 'company_ids': [(6, 0, [company.id])]})
        bank = account('D2BANK', 'asset_cash')
        outstanding = account('D2OUT', 'asset_current', True)
        salary = account('400003', 'expense')
        journal = self.env['account.journal'].create({'name': 'Bank', 'code': 'D2BNK', 'type': 'bank', 'company_id': company.id, 'default_account_id': bank.id})
        misc = self.env['account.journal'].create({'name': 'Misc', 'code': 'D2OTH', 'type': 'general', 'company_id': company.id})
        methods = journal.outbound_payment_method_line_ids
        self.assertTrue(methods)
        methods[0].payment_account_id = outstanding
        def entry(journal, debit, credit):
            move = self.env['account.move'].create({'journal_id': journal.id, 'date': '2026-10-03', 'line_ids': [
                (0, 0, {'name': 'Debit', 'account_id': debit.id, 'debit': 250, 'credit': 0}),
                (0, 0, {'name': 'Credit', 'account_id': credit.id, 'debit': 0, 'credit': 250})]})
            move.action_post()
            return move
        payment = entry(journal, outstanding, bank)
        expense = entry(misc, salary, outstanding)
        (payment.line_ids + expense.line_ids).filtered(lambda line: line.account_id == outstanding).reconcile()
        result = self.env['baseer.dashboard2.service']._cash_out([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(result['total'], 250)
        self.assertEqual(result['items']['salaries'], 250)

    def test_unpaid_bill_not_outflow(self):
        from datetime import date
        company = self.env.company
        expense = self.env['account.account'].create({'code': 'D2EXP', 'name': 'Expense', 'account_type': 'expense', 'company_ids': [(6, 0, [company.id])]})
        payable = self.env['account.account'].create({'code': 'D2PAY', 'name': 'Payable', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, [company.id])]})
        partner = self.env['res.partner'].create({'name': 'Supplier', 'property_account_payable_id': payable.id})
        journal = self.env['account.journal'].create({'name': 'Purchase', 'code': 'D2PUR', 'type': 'purchase', 'company_id': company.id})
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'journal_id': journal.id, 'partner_id': partner.id, 'invoice_date': '2026-10-03',
            'invoice_line_ids': [(0, 0, {'name': 'Purchase', 'account_id': expense.id, 'quantity': 1, 'price_unit': 100})]})
        bill.action_post()
        service = self.env['baseer.dashboard2.service']
        self.assertEqual(abs(service._unpaid_bills([company.id], date(2026, 10, 31))['value']), 100)
        self.assertEqual(service._cash_out([company.id], date(2026, 10, 1), date(2026, 10, 31))['total'], 0)

    def test_all_companies_sum(self):
        from datetime import date
        company = self.env.company
        other = self.env['res.company'].create({'name': 'Dashboard second company'})
        self.env.user.company_ids = [(4, other.id)]
        self.env['ir.config_parameter'].set_param('baseer_dashboard2.company_map', f'{company.id}:One,{other.id}:Two')
        for co, amount in ((company, 100), (other, 200)):
            env = self.env(context=dict(self.env.context, allowed_company_ids=[co.id]))
            revenue = env['account.account'].with_company(co).create({'code': 'D2R', 'name': 'Sales', 'account_type': 'income', 'company_ids': [(6, 0, [co.id])]})
            cash = env['account.account'].with_company(co).create({'code': 'D2C', 'name': 'Cash', 'account_type': 'asset_cash', 'company_ids': [(6, 0, [co.id])]})
            journal = env['account.journal'].create({'name': 'Misc', 'code': 'D2CO', 'type': 'general', 'company_id': co.id})
            move = env['account.move'].create({'journal_id': journal.id, 'company_id': co.id, 'date': '2026-10-01', 'line_ids': [
                (0, 0, {'name': 'Cash', 'account_id': cash.id, 'debit': amount, 'credit': 0}),
                (0, 0, {'name': 'Sales', 'account_id': revenue.id, 'debit': 0, 'credit': amount})]})
            move.action_post()
        service = self.env['baseer.dashboard2.service']
        first, last = date(2026, 10, 1), date(2026, 10, 31)
        self.assertEqual(service._accounting(service._scope('all'), first, last)['sales_net'], 300)
        self.assertEqual(service._accounting([company.id], first, last)['sales_net'] + service._accounting([other.id], first, last)['sales_net'], 300)


class TestDashboardThemeLiterals(TransactionCase):
    def test_colour_literals_only_in_theme(self):
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / 'static' / 'src'
        pattern = re.compile(r"(?<![\w])#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(")
        for path in root.rglob('*'):
            if path.is_file() and path.name != 'theme.scss':
                self.assertFalse(pattern.search(path.read_text()), str(path))
