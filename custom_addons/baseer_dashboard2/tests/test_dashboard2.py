from datetime import date

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
        account.account_type = 'income_other'
        self.assertEqual(service._category(account, categories), 'other_income')
        account.account_type = 'expense'
        for code, expected in [('400051', 'commissions'), ('400057', 'non_operating'), ('400061', 'non_operating'), ('400035', 'non_operating'), ('999001', 'non_operating'), ('999002', 'non_operating'), ('400032', 'other_opex'), ('400042', 'other_opex'), ('400048', 'other_opex')]:
            account.code = code
            self.assertEqual(service._category(account, categories), expected)

    def test_meta_and_overview(self):
        service = self.env['baseer.dashboard2.service']
        company = self.env.company
        self.env['ir.config_parameter'].set_param('baseer_dashboard2.company_map', '%s:Test' % company.id)
        meta = service.get_meta()
        self.assertEqual(meta['default_company_key'], str(company.id))
        from datetime import timedelta
        from odoo import fields
        previous = (fields.Date.context_today(service).replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        self.assertEqual(meta['default_month'], previous)
        result = service.get_section('overview', {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-10'}})
        self.assertTrue(result['available'])
        self.assertEqual(len(result['trend']), 6)
        self.assertEqual(result['current']['sales_net'], 0)

    def test_accounting_and_noorix(self):
        from datetime import date
        company = self.env.company
        self.env['baseer.dashboard2.settings'].search([('company_id', '=', company.id)]).pos_cutover_date = '2026-11-01'
        account_model = self.env['account.account'].with_company(company)
        def account(code, account_type):
            return account_model.create({'code': code, 'name': code, 'account_type': account_type, 'company_ids': [(6, 0, [company.id])]})
        revenue = account('D250001', 'income')
        food = account('400001', 'expense_direct_cost')
        salary = account('400003', 'expense')
        nonop = account('400057', 'expense')
        offset = account('999001', 'expense')
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
        entry('non-operating', '2026-10-03', [(nonop, 'expense', 80, 0), (offset, 'offset', 0, 30), (cash, 'paid', 0, 50)])
        service = self.env['baseer.dashboard2.service']
        data = service._accounting([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(data['sales_net'], 1000)
        self.assertEqual(data['categories']['food_cost'], 300)
        self.assertEqual(data['categories']['salaries'], 200)
        self.assertEqual(data['categories']['non_operating'], 50)
        self.assertEqual(data['operating_profit'], 500)
        self.assertEqual(data['net_profit'], 450)
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
        self.assertEqual(service.get_section('overview', params)['breakeven'], service.get_section('ratios', params)['breakeven'])

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
        settings = self.env['baseer.dashboard2.settings'].search([('company_id', '=', company.id)], limit=1) or self.env['baseer.dashboard2.settings'].create({'company_id': company.id})
        settings.write({'liquidity_account_ids': [(4, custody.id)], 'liquidity_ids': [(0, 0, {'account_id': custody.id, 'kind': 'custody', 'label': 'عهدة اختبار'})]})
        empty = self.env['baseer.dashboard2.service']._inout([company.id], date(2026, 9, 30))
        self.assertTrue({'salaries', 'rent', 'utilities', 'purchases', 'commissions', 'marketing', 'non_operating', 'other'} <= set(empty['total']['items']))
        self.assertTrue({'bank', 'cash'} <= set(empty['total']['sources']))
        self.assertEqual(empty['total']['sources']['عهدة اختبار'], 0)
        self.assertTrue(all(m['outgoing']['sources']['عهدة اختبار'] == 0 for m in empty['months']))
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
        settings.write({'excluded_journal_ids': [(6, 0, [journal.id])]})
        result = self.env['baseer.dashboard2.service']._cash_out([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertTrue(result['available'])
        self.assertEqual(result['total'], 200)


    def test_cash_out_excludes_vat_and_keeps_zakat(self):
        from datetime import date
        company = self.env.company
        model = self.env['account.account'].with_company(company)
        def account(code, kind):
            return model.create({'code': code, 'name': code, 'account_type': kind, 'company_ids': [(6, 0, [company.id])]})
        bank = account('D2VATBANK', 'asset_cash')
        vat = account('202003', 'liability_payable')
        zakat = account('400072', 'expense')
        journal = self.env['account.journal'].create({'name': 'VAT test', 'code': 'D2VAT', 'type': 'general', 'company_id': company.id})
        move = self.env['account.move'].create({'journal_id': journal.id, 'date': '2026-10-05', 'line_ids': [
            (0, 0, {'name': 'VAT', 'account_id': vat.id, 'debit': 100}),
            (0, 0, {'name': 'Zakat', 'account_id': zakat.id, 'debit': 50}),
            (0, 0, {'name': 'Bank', 'account_id': bank.id, 'credit': 150})]})
        move.action_post()
        service = self.env['baseer.dashboard2.service']
        out = service._cash_out([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(out['total'], 50)
        self.assertEqual(out['items']['zakat_tax'], 50)
        self.assertNotIn('vat_paid', out['items'])
        self.assertAlmostEqual(sum(out['items'].values()), out['total'], places=2)
        self.assertAlmostEqual(sum(out['sources'].values()), out['total'], places=2)
        report = service._inout([company.id], date(2026, 10, 31))
        self.assertEqual(report['months'][-1]['outgoing']['total'], 50)
        self.assertEqual(report['total']['outgoing'], 50)
        self.assertEqual(report['months'][-1]['net'], report['months'][-1]['incoming']['gross'] - 50)
        self.assertAlmostEqual(sum(report['total']['items'].values()), report['total']['outgoing'], places=2)
        self.assertAlmostEqual(sum(report['total']['sources'].values()), report['total']['outgoing'], places=2)

    def test_pos_sales(self):
        from datetime import date, timedelta
        company = self.env.company
        settings = self.env['baseer.dashboard2.settings'].search([('company_id', '=', company.id)], limit=1)
        settings.app_balance_start_date = '2026-10-01'
        method = self.env['pos.payment.method'].create({'name': 'cash', 'company_id': company.id})
        journal = self.env['account.journal'].create({'name': 'POS sales', 'code': 'D2POS', 'type': 'sale', 'company_id': company.id})
        misc = self.env['account.journal'].create({'name': 'Noorix', 'code': 'D2NOO', 'type': 'general', 'company_id': company.id})
        config = self.env['pos.config'].create({'name': 'Dashboard POS', 'company_id': company.id, 'journal_id': journal.id, 'payment_method_ids': [(6, 0, [method.id])]})
        summary_config = self.env['pos.config'].create({'name': 'ملخصات', 'company_id': company.id, 'journal_id': journal.id, 'payment_method_ids': [(6, 0, [method.id])]})
        account = self.env['account.account'].with_company(company)
        cash = account.create({'code': 'D2NC', 'name': 'Cash', 'account_type': 'asset_cash', 'company_ids': [(6, 0, [company.id])]})
        revenue = account.create({'code': 'D2NR', 'name': 'Sales', 'account_type': 'income', 'company_ids': [(6, 0, [company.id])]})
        def entry(day, amount=300, label='cash'):
            move = self.env['account.move'].create({'journal_id': misc.id, 'date': day, 'line_ids': [
                (0, 0, {'name': label, 'account_id': cash.id, 'debit': amount, 'credit': 0}),
                (0, 0, {'name': 'sale', 'account_id': revenue.id, 'debit': 0, 'credit': amount})]})
            move.action_post()
            return move
        def order(session, day, amount):
            rec = self.env['pos.order'].create({'company_id': company.id, 'session_id': session.id, 'date_order': str(day) + ' 10:00:00', 'state': 'paid', 'amount_tax': 0, 'amount_total': amount, 'amount_paid': amount, 'amount_return': 0})
            self.env['pos.payment'].create({'pos_order_id': rec.id, 'payment_method_id': method.id, 'amount': amount})
        def new_session(config):
            self.env['pos.session'].search([('config_id', '=', config.id), ('state', '!=', 'closed')]).write({'state': 'closed'})
            return self.env['pos.session'].create({'config_id': config.id})
        service = self.env['baseer.dashboard2.service']
        def result(day):
            return service._sales_summary([company.id], day, day)
        # Repeated Noorix days retain their full amount despite real and tiny orders.
        for start, count in [(date(2026, 10, 25), 1), (date(2026, 11, 1), 16), (date(2026, 9, 24), 9)]:
            for offset in range(count):
                day = start + timedelta(days=offset)
                entry(day)
                session = new_session(config)
                order(session, day, 1)
                order(session, day, 115)
                summary, days, _, hours = result(day)
                self.assertEqual(summary['gross'], 300)
                self.assertEqual(days[(company.id, day)]['source'], 'summary')
                self.assertEqual(summary['customers']['value'], 1)
                self.assertEqual(sum(row['orders'] for row in hours.values()), 1)
                self.assertFalse(summary['warnings'])
        # A cancelled session closing cannot add its orders to Noorix.
        cancelled_day = date(2026, 10, 1)
        cancelled = new_session(config)
        cancelled.name = 'TEST/01438'
        cancelled_move = entry(cancelled_day, 115)
        cancelled_move.button_draft()
        cancelled_move.button_cancel()
        cancelled.move_id = cancelled_move
        order(cancelled, cancelled_day, 115)
        self.assertEqual(result(cancelled_day)[0]['gross'], 300)
        self.assertFalse(result(cancelled_day)[0]['warnings'])
        # An override does not remove the underlying summary replacement.
        override = self.env['baseer.dashboard2.source.override'].create({
            'settings_id': settings.id, 'date_from': cancelled_day, 'date_to': cancelled_day, 'source': 'pos'})
        self.assertFalse(result(cancelled_day)[0]['warnings'])
        override.unlink()
        missing_day = date(2026, 10, 5)
        missing = new_session(config)
        missing.name = 'TEST/01439'
        missing_move = entry(missing_day, 115)
        missing_move.button_draft()
        missing_move.button_cancel()
        missing.move_id = missing_move
        order(missing, missing_day, 115)
        self.assertEqual(result(missing_day)[0]['warnings'][0]['label'], 'جلسة إقفال ملغاة لم تُعد: 01439 — مفقود 115 (1 طلب)')
        order(missing, date(2026, 10, 1), 30)  # Covered on a different order day.
        order(missing, date(2026, 10, 6), 25)
        warnings = service._sales_summary([company.id], date(2026, 10, 1), date(2026, 10, 6))[0]['warnings']
        self.assertEqual([(w['date'], w['label']) for w in warnings], [('2026-10-05', 'جلسة إقفال ملغاة لم تُعد: 01439 — مفقود 115 (1 طلب)'), ('2026-10-06', 'جلسة إقفال ملغاة لم تُعد: 01439 — مفقود 25 (1 طلب)')])
        replacement = entry(missing_day, 2)
        replacement.ref = missing.name
        self.assertFalse(result(missing_day)[0]['warnings'])
        tiny_day = date(2026, 10, 6)
        tiny = new_session(config)
        tiny_move = entry(tiny_day, 1)
        tiny_move.button_draft()
        tiny_move.button_cancel()
        tiny.move_id = tiny_move
        order(tiny, tiny_day, 1)
        self.assertFalse(result(tiny_day)[0]['warnings'])
        test_day = date(2026, 10, 4)
        entry(test_day)
        test_session = new_session(config)
        test_session.move_id = entry(test_day, 1)
        order(test_session, test_day, 1)
        self.assertFalse(result(test_day)[0]['warnings'])
        day = date(2026, 10, 3)
        session = new_session(config)
        session.move_id = entry(day, 115)
        order(session, day, 115)
        order(session, day, 1)
        self.assertEqual(result(day)[0]['gross'], 115)
        self.assertEqual(result(day)[1][(company.id, day)]['source'], 'pos')
        for day in (date(2026, 10, 25), date(2026, 10, 31)):
            if day.day == 31:
                entry(day)
            session = new_session(config)
            session.move_id = entry(day, 115)
            order(session, day, 115)
            summary, days, _, _ = result(day)
            self.assertEqual(summary['gross'], 415)
            self.assertEqual(days[(company.id, day)]['source'], 'mixed')
            self.assertEqual(len(summary['warnings']), 1)
            self.assertEqual(service._heatmap([company.id], '2026-10')['days'][day.day - 1]['source'], 'mixed')
        # The review cutoff suppresses both warning types but preserves sales.
        settings.app_balance_start_date = '2026-11-01'
        self.assertFalse(result(date(2026, 10, 25))[0]['warnings'])
        self.assertFalse(service._cancelled_session_warnings([company.id], date(2026, 10, 5), date(2026, 10, 6)))
        november = date(2026, 11, 20)
        late = new_session(config)
        late.name = 'TEST/01440'
        late_move = entry(november, 90)
        late_move.button_draft()
        late_move.button_cancel()
        late.move_id = late_move
        order(late, november, 90)
        self.assertEqual(result(november)[0]['warnings'][0]['label'], 'جلسة إقفال ملغاة لم تُعد: 01440 — مفقود 90 (1 طلب)')
        settings.app_balance_start_date = '2026-10-01'
        override = self.env['baseer.dashboard2.source.override'].create({'settings_id': settings.id, 'date_from': '2026-10-25', 'date_to': '2026-10-25', 'source': 'summary'})
        self.assertEqual(result(date(2026, 10, 25))[0]['gross'], 300)
        override.source = 'pos'
        self.assertEqual(result(date(2026, 10, 25))[0]['gross'], 115)
        override.source = 'auto'
        self.assertEqual(result(date(2026, 10, 25))[0]['gross'], 415)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['baseer.dashboard2.source.override'].create({'settings_id': settings.id, 'date_from': '2026-10-25', 'date_to': '2026-10-26', 'source': 'pos'})
        day = date(2026, 9, 15)
        session = new_session(summary_config)
        session.move_id = entry(day, 500, 'keeta')
        order(session, day, 500)
        summary, _, _, _ = result(day)
        self.assertEqual(summary['gross'], 500)
        self.assertEqual(summary['apps'], 500)
        self.assertFalse(summary['customers']['available'])
        clearing = account.create({'code': 'D2CLR', 'name': 'Clearing', 'account_type': 'asset_current', 'company_ids': [(6, 0, [company.id])]})
        receipt = self.env['account.move'].create({'journal_id': misc.id, 'date': day, 'ref': 'Combine POS payments', 'line_ids': [
            (0, 0, {'name': 'cash', 'account_id': cash.id, 'debit': 500, 'credit': 0}),
            (0, 0, {'name': 'clearing', 'account_id': clearing.id, 'debit': 0, 'credit': 500})]})
        receipt.action_post()
        self.assertEqual(result(day)[0]['gross'], 500)

    def test_official_events_loaded(self):
        event = self.env.ref('baseer_dashboard2.event_ramadan_1447')
        self.assertEqual(str(event.date_from), '2026-02-18')
        self.assertEqual(str(event.date_to), '2026-03-19')
        self.assertFalse(event.company_ids)
        self.assertIn('المصدر:', event.note)

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
        settings = self.env['baseer.dashboard2.settings'].search([('company_id', '=', company.id)], limit=1) or self.env['baseer.dashboard2.settings'].create({'company_id': company.id})
        settings.write({'outflow_journal_ids': [(6, 0, [journal.id])]})
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
        payment_journal = self.env['account.journal'].create({'name': 'Bill settlement', 'code': 'D2SET', 'type': 'general', 'company_id': company.id})
        payment = self.env['account.move'].create({'journal_id': payment_journal.id, 'date': '2026-11-10', 'line_ids': [
            (0, 0, {'name': 'Payable', 'account_id': payable.id, 'partner_id': partner.id, 'debit': 100, 'credit': 0}),
            (0, 0, {'name': 'Offset', 'account_id': expense.id, 'debit': 0, 'credit': 100})]})
        payment.action_post()
        (bill.line_ids + payment.line_ids).filtered(lambda line: line.account_id == payable).reconcile()
        self.assertEqual(service._unpaid_bills([company.id], date(2026, 10, 31))['value'], 100)
        self.assertEqual(service._unpaid_bills([company.id], date(2026, 11, 30))['value'], 0)
        self.assertEqual(service._cash_out([company.id], date(2026, 10, 1), date(2026, 10, 31))['total'], 0)

    def test_channel_mapping_and_unreceived(self):
        from datetime import date
        company = self.env.company
        settings = self.env['baseer.dashboard2.settings'].search([('company_id', '=', company.id)], limit=1) or self.env['baseer.dashboard2.settings'].create({'company_id': company.id})
        settings.app_balance_start_date = '2026-10-01'
        model = self.env['account.account'].with_company(company)
        def account(code, kind):
            return model.create({'code': code, 'name': code, 'account_type': kind, 'company_ids': [(6, 0, [company.id])]})
        wallet = account('D2WAL', 'asset_receivable')
        revenue = account('D2MAPREV', 'income')
        cash = account('D2MAPC', 'asset_cash')
        channel = self.env.ref('baseer_dashboard2.channel_keeta')
        self.env['baseer.dashboard2.channel.map'].create({'settings_id': settings.id, 'company_id': company.id, 'source': 'account', 'account_id': wallet.id, 'channel_id': channel.id, 'kind': 'app'})
        journal = self.env['account.journal'].create({'name': 'Summary', 'code': 'D2MAP', 'type': 'general', 'company_id': company.id})
        def entry(day, lines):
            move = self.env['account.move'].create({'journal_id': journal.id, 'date': day, 'line_ids': [(0, 0, {'account_id': acc.id, 'name': name, 'debit': debit, 'credit': credit}) for acc, name, debit, credit in lines]})
            move.action_post()
        entry('2026-09-01', [(wallet, 'opening', 20, 0), (cash, 'offset', 0, 20)])
        wallet2 = account('D2WAL2', 'asset_receivable')
        self.env['baseer.dashboard2.channel.map'].create({'settings_id': settings.id, 'company_id': company.id, 'source': 'account', 'account_id': wallet2.id, 'channel_id': self.env.ref('baseer_dashboard2.channel_hunger').id, 'kind': 'app'})
        entry('2026-10-01', [(wallet, 'cash', 100, 0), (revenue, 'sales', 0, 100)])
        entry('2026-10-02', [(wallet2, 'hunger', 30, 0), (revenue, 'sales', 0, 30)])
        entry('2026-10-03', [(cash, 'settlement', 20, 0), (wallet2, 'wallet', 0, 20)])
        entry('2026-11-01', [(cash, 'cash', 40, 0), (wallet, 'wallet', 0, 40)])
        excluded = account('D2EXCL', 'asset_receivable')
        nonreceivable = account('D2NONREC', 'asset_current')
        for acc in (excluded, nonreceivable):
            self.env['baseer.dashboard2.channel.map'].create({'settings_id': settings.id, 'company_id': company.id, 'source': 'account', 'account_id': acc.id, 'channel_id': channel.id, 'kind': 'app'})
            entry('2026-10-04', [(acc, 'app', 50, 0), (revenue, 'sales', 0, 50)])
        settings.write({'liquidity_account_ids': [(4, excluded.id)]})
        service = self.env['baseer.dashboard2.service']
        result = service._sales_summary([company.id], date(2026, 10, 1), date(2026, 10, 31))[0]
        self.assertEqual(result['channels']['keeta'], 200)
        self.assertEqual(result['apps_unreceived']['value'], 110)
        result = service._sales_summary([company.id], date(2026, 10, 1), date(2026, 11, 30))[0]
        self.assertEqual(result['apps_unreceived']['value'], 70)
        app = next(x for x in result['apps_unreceived']['breakdown'] if x['key'] == 'keeta')
        self.assertEqual(app['cumulative'], 80)
        settings.app_balance_start_date = '2026-11-01'
        unavailable = service._sales_summary([company.id], date(2026, 10, 1), date(2026, 10, 31))[0]['apps_unreceived']
        self.assertFalse(unavailable['available'])
        self.assertIsNone(unavailable['value'])
        self.assertEqual(unavailable['breakdown'], [])
        straddling = service._sales_summary([company.id], date(2026, 10, 1), date(2026, 11, 30))[0]['apps_unreceived']
        self.assertEqual(straddling['value'], 0)

    def test_seed_checks_and_preserves_settings(self):
        from unittest.mock import patch
        company = self.env.company
        other = self.env['res.company'].create({'name': 'Other seed company'})
        journal = self.env['account.journal'].create({'name': 'Seed bank', 'code': 'D2SED', 'type': 'bank', 'company_id': company.id})
        settings = self.env['baseer.dashboard2.settings'].search([('company_id', '=', company.id)], limit=1) or self.env['baseer.dashboard2.settings'].create({'company_id': company.id})
        settings.write({'outflow_journal_ids': [(6, 0, [journal.id])], 'custody_journal_ids': [(5, 0, 0)], 'excluded_journal_ids': [(5, 0, 0)]})
        defaults = {company.id: {'custody': (journal.id, journal.default_account_id.id), 'excluded': (99999998,)}, other.id: {'custody': (journal.id, journal.default_account_id.id), 'excluded': (journal.id,)}}
        with patch('odoo.addons.baseer_dashboard2.models.configuration.DOCUMENTED_DEFAULTS', defaults):
            self.env['baseer.dashboard2.settings']._seed_documented_defaults()
        self.assertEqual(settings.outflow_journal_ids, journal)
        self.assertEqual(settings.custody_journal_ids, journal)
        other_settings = self.env['baseer.dashboard2.settings'].search([('company_id', '=', other.id)])
        self.assertFalse(other_settings.custody_journal_ids)
        self.assertFalse(other_settings.excluded_journal_ids)
        settings.custody_journal_ids = [(5, 0, 0)]
        with patch('odoo.addons.baseer_dashboard2.models.configuration.DOCUMENTED_DEFAULTS', {company.id: {'custody': (journal.id, 99999999), 'excluded': ()}}):
            self.env['baseer.dashboard2.settings']._seed_documented_defaults()
        self.assertFalse(settings.custody_journal_ids)

    def test_app_balance_default_and_upgrade(self):
        from datetime import date
        from importlib.util import spec_from_file_location, module_from_spec
        from pathlib import Path
        model = self.env['baseer.dashboard2.settings']
        company = self.env['res.company'].browse(1)
        settings = model.search([('company_id', '=', company.id)], limit=1)
        settings.app_balance_start_date = False
        model._seed_documented_defaults(company_ids=[company.id])
        self.assertEqual(settings.app_balance_start_date, date(2026, 11, 1))
        path = Path(__file__).resolve().parents[1] / 'migrations/19.0.1.2.0/post-migration.py'
        spec = spec_from_file_location('dashboard2_migration_120', path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        for old, expected in [('2026-10-01', date(2026, 11, 1)), (False, date(2026, 11, 1)), ('2026-09-15', date(2026, 9, 15))]:
            settings.app_balance_start_date = old
            migration.migrate(self.env.cr, '19.0.1.1.0')
            settings.invalidate_recordset(['app_balance_start_date'])
            self.assertEqual(settings.app_balance_start_date, expected)

    def test_seed_cutover_only_when_empty(self):
        from datetime import date
        settings_model = self.env['baseer.dashboard2.settings']
        company = self.env['res.company'].browse(1).exists()
        self.assertTrue(company)
        settings = settings_model.search([('company_id', '=', company.id)], limit=1)
        settings.pos_cutover_date = False
        settings_model._seed_documented_defaults(company_ids=[company.id])
        self.assertEqual(settings.pos_cutover_date, date(2026, 10, 3))
        settings.pos_cutover_date = '2026-11-01'
        settings_model._seed_documented_defaults(force=True, company_ids=[company.id])
        self.assertEqual(settings.pos_cutover_date, date(2026, 11, 1))

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

    def test_liquidity_reset_and_reconciliation(self):
        from datetime import date
        company = self.env.company
        model = self.env['account.account'].with_company(company)
        def account(code, kind, reconcile=False):
            return model.create({'code': code, 'name': code, 'account_type': kind, 'reconcile': reconcile, 'company_ids': [(6, 0, [company.id])]})
        bank = account('D2APP', 'asset_current')
        cash = account('D2CASH', 'asset_cash')
        salary = account('400003', 'expense')
        rent = account('400016', 'expense')
        payable = account('D2PAY2', 'liability_payable', True)
        intermediary = account('102014', 'asset_current', True)
        salaries_due = account('201090', 'liability_current')
        reset = account('999999', 'equity')
        revenue = account('D2REVENUE', 'income')
        journal = self.env['account.journal'].create({'name': 'Test misc', 'code': 'D2ZZ', 'type': 'general', 'company_id': company.id})
        settings = self.env['baseer.dashboard2.settings'].search([('company_id', '=', company.id)], limit=1) or self.env['baseer.dashboard2.settings'].create({'company_id': company.id})
        settings.write({'pos_cutover_date': '2026-11-01', 'liquidity_account_ids': [(4, bank.id)], 'liquidity_ids': [(0, 0, {'account_id': bank.id, 'kind': 'bank', 'label': 'حساب الأهلي — كيتا'})]})
        self.env['baseer.dashboard2.channel.map'].create({'settings_id': settings.id, 'company_id': company.id, 'source': 'account', 'account_id': bank.id, 'channel_id': self.env.ref('baseer_dashboard2.channel_keeta').id, 'kind': 'app'})
        def entry(debit, credit, amount, day='2026-10-03'):
            move = self.env['account.move'].create({'journal_id': journal.id, 'date': day, 'line_ids': [
                (0, 0, {'name': 'Debit', 'account_id': debit.id, 'debit': amount}),
                (0, 0, {'name': 'Credit', 'account_id': credit.id, 'credit': amount})]})
            move.action_post()
            return move
        entry(bank, revenue, 1000)
        entry(salary, bank, 100)
        payment = entry(payable, bank, 80)
        bill = entry(rent, payable, 80)
        (payment.line_ids | bill.line_ids).filtered(lambda line: line.account_id == payable).reconcile()
        payment2 = entry(intermediary, bank, 60)
        payroll = entry(salaries_due, intermediary, 60)
        (payment2.line_ids | payroll.line_ids).filtered(lambda line: line.account_id == intermediary).reconcile()
        entry(cash, bank, 50)
        entry(reset, bank, 20, '2026-10-31')
        service = self.env['baseer.dashboard2.service']
        out = service._cash_out([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(out['total'], 240)
        self.assertEqual(out['items']['salaries'], 160)
        self.assertEqual(out['items']['rent'], 80)
        self.assertEqual(out['sources']['حساب الأهلي — كيتا'], 240)
        before, _, _, _ = service._sales_summary([company.id], date(2026, 10, 1), date(2026, 10, 30))
        self.assertFalse(before['apps_unreceived']['available'])
        summary, _, _, _ = service._sales_summary([company.id], date(2026, 10, 1), date(2026, 10, 31))
        self.assertFalse(summary['apps_unreceived']['available'])
        self.assertEqual(summary['apps_unreceived']['breakdown'], [])
        after, _, _, _ = service._sales_summary([company.id], date(2026, 10, 1), date(2026, 11, 1))
        self.assertEqual(after['apps_unreceived']['value'], 0)

    def test_salaries_warning_three_months(self):
        company = self.env.company
        accounts = self.env['account.account'].with_company(company)
        salary = accounts.create({'code': '400003', 'name': 'رواتب | Salaries', 'account_type': 'expense', 'company_ids': [(6, 0, [company.id])]})
        cash = accounts.create({'code': 'D2SAC', 'name': 'Cash', 'account_type': 'asset_cash', 'company_ids': [(6, 0, [company.id])]})
        journal = self.env['account.journal'].create({'name': 'Salaries', 'code': 'D2SAL', 'type': 'general', 'company_id': company.id})
        for month, amount in [(7, 100), (8, 100), (9, 100), (10, 69)]:
            move = self.env['account.move'].create({'journal_id': journal.id, 'date': '2026-%02d-01' % month, 'line_ids': [
                (0, 0, {'name': 'Salary', 'account_id': salary.id, 'debit': amount}),
                (0, 0, {'name': 'Cash', 'account_id': cash.id, 'credit': amount})]})
            move.action_post()
        self.env['ir.config_parameter'].set_param('baseer_dashboard2.company_map', '%s:Configured label' % company.id)
        service = self.env['baseer.dashboard2.service']
        params = {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-10'}}
        for section in ('overview', 'expenses', 'pnl'):
            self.assertTrue(service.get_section(section, params)['salaries_warning'])
        no_salary = self.env['account.move'].create({'journal_id': journal.id, 'date': '2026-11-01', 'line_ids': [
            (0, 0, {'name': 'Expense', 'account_id': self.env['account.account'].create({'code': 'D2OTHER', 'name': 'Other', 'account_type': 'expense', 'company_ids': [(6, 0, [company.id])]}).id, 'debit': 10}),
            (0, 0, {'name': 'Cash', 'account_id': cash.id, 'credit': 10})]})
        no_salary.action_post()
        params_zero = {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-11'}}
        for section in ('overview', 'expenses', 'pnl'):
            self.assertTrue(service.get_section(section, params_zero)['salaries_warning'])
        self.assertIsNone(service._timeline([company.id], date(2026, 10, 31), 'monthly')['months'][6]['value'])
        overview = service.get_section('overview', params)
        self.assertEqual(overview['companies_compare'][0]['name'], 'Configured label')
        self.assertEqual(next(a for a in overview['current']['accounts'] if a['account_id'] == salary.id)['name'], 'رواتب')
