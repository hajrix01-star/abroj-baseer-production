import base64
import io
import zipfile
from decimal import Decimal

from .common import EngineCase


class TestCashFlow(EngineCase):
    def _opening_fixture(self):
        company = self._company('Opening rule')
        cash = self._account(company, '10480', 'asset_cash')
        income = self._account(company, '40480', 'income')
        journal = self._journal(company, 'CR80')
        move = self._entry(company, journal, '2041-02-01', cash, income, 13)
        return company, self._engine(company), move

    def test_opening_company_move(self):
        company, engine, move = self._opening_fixture()
        company.account_opening_move_id = move
        self.assertEqual(Decimal(self._value(engine.get_report('cash_flow', self._options()), 'beginning')), 13)

    def test_opening_parameter_name(self):
        _company, engine, move = self._opening_fixture()
        self.env['ir.config_parameter'].sudo().set_param('baseer_report_engine.cash_flow_opening_moves', move.name)
        self.assertEqual(Decimal(self._value(engine.get_report('cash_flow', self._options()), 'beginning')), 13)

    def test_opening_parameter_id(self):
        _company, engine, move = self._opening_fixture()
        self.env['ir.config_parameter'].sudo().set_param('baseer_report_engine.cash_flow_opening_moves', str(move.id))
        self.assertEqual(Decimal(self._value(engine.get_report('cash_flow', self._options()), 'beginning')), 13)

    def test_unknown_opening_token_notice(self):
        _company, engine, _move = self._opening_fixture()
        self.env['ir.config_parameter'].sudo().set_param('baseer_report_engine.cash_flow_opening_moves', 'missing-token')
        self.assertTrue(any('missing-token' in n['text'] for n in engine.get_report('cash_flow', self._options())['cash_notices']))

    def test_opening_before_period_counted_once(self):
        company, engine, move = self._opening_fixture()
        company.account_opening_move_id = move
        report = engine.get_report('cash_flow', self._options(date_from='2041-03-01'))
        self.assertEqual(Decimal(self._value(report, 'beginning')), 13)
        self.assertEqual(Decimal(self._value(report, 'net')), 0)

    def test_transfer_warning_balance_and_domain(self):
        company, engine, move = self._opening_fixture()
        transfer = self._account(company, '10980', 'asset_current')
        company.transfer_account_id = transfer
        journal = move.journal_id
        income = move.line_ids.filtered(lambda line: line.account_id.account_type == 'income').account_id
        one_sided = self._entry(company, journal, '2041-03-01', transfer, income, 17)
        report = engine.get_report('cash_flow', self._options())
        notice = next(n for n in report['cash_notices'] if n.get('action'))
        self.assertEqual(self.env['account.move.line'].search(notice['action']['domain']), one_sided.line_ids.filtered(lambda line: line.account_id == transfer))
        self._entry(company, journal, '2041-04-01', income, transfer, 17)
        self.assertFalse(any(n.get('action') for n in engine.get_report('cash_flow', self._options())['cash_notices']))

    def test_automatic_opening_rules(self):
        company = self._company('Automatic cash openings')
        engine = self._engine(company)
        cash = self._account(company, '10381', 'asset_cash')
        equity = self._account(company, '999999', 'equity_unaffected')
        income = self._account(company, '40381', 'income')
        journal = self._journal(company, 'CO81')
        self._entry(company, journal, '2041-01-01', cash, equity, 10)
        named = self._entry(company, journal, '2041-02-01', cash, income, 20)
        named.ref = 'Opening reset 31/10/2026'
        arabic = self._entry(company, journal, '2041-02-02', cash, income, 5)
        arabic.ref = 'رصيد افتتاح الفترة'
        self._entry(company, journal, '2041-03-01', cash, income, 7)
        report = engine.get_report('cash_flow', self._options())
        self.assertEqual(Decimal(self._value(report, 'beginning')), 35)
        self.assertEqual(Decimal(self._value(report, 'unclassified_in')), 7)
        self.assertEqual(Decimal(self._value(report, 'net')), 7)
        tb = engine.get_report('trial_balance', self._options())
        self.assertEqual(Decimal(self._value(report, 'closing')), Decimal(next(r for r in tb['lines'] if r.get('account_id') == cash.id)['amounts'][-1]['value']))

    def test_excluded_cash_and_journal_default(self):
        company = self._company('Cash exclusions')
        engine = self._engine(company)
        cash = self._account(company, '10382', 'asset_cash')
        excluded = self._account(company, '105002', 'asset_cash')
        default = self._account(company, '108990', 'asset_current')
        income = self._account(company, '40382', 'income')
        journal = self._journal(company, 'CO82')
        self.env['account.journal'].with_company(company).create({
            'name': 'Cash default', 'code': 'CD82', 'type': 'cash',
            'company_id': company.id, 'default_account_id': default.id})
        self._entry(company, journal, '2040-12-31', excluded, income, 10)
        self._entry(company, journal, '2041-01-01', excluded, income, 20)
        self._entry(company, journal, '2041-02-01', excluded, cash, 5)
        self._entry(company, journal, '2041-03-01', default, income, 7)
        params = self.env['ir.config_parameter'].sudo()
        options = self._options()
        original = engine.get_report('cash_flow', options)
        self.assertEqual(Decimal(self._value(original, 'closing')), 37)
        self.assertIn(default.id, engine._cash_liquidity_accounts().ids)
        for token in (excluded.code, str(excluded.id)):
            params.set_param('baseer_report_engine.cash_flow_excluded_accounts', token)
            report = engine.get_report('cash_flow', options, with_accounts=True)
            self.assertEqual(Decimal(self._value(report, 'beginning')), 0)
            self.assertEqual(Decimal(self._value(report, 'closing')), 2)
            self.assertEqual(Decimal(self._value(report, 'unclassified_out')), -5)
            self.assertIn(excluded.id, {r['id'] for r in next(l for l in report['lines'] if l['code'] == 'unclassified_out')['accounts']})
            self.assertIn('Excluded from cash: 105002', report['notes'])
            self.assertTrue(any('Excluded from cash: 105002' in n['text'] for n in report['cash_notices']))
            self.assertIn('Excluded from cash: 105002', engine._export_payload('cash_flow', options)['notes'])
        params.set_param('baseer_report_engine.cash_flow_excluded_accounts', '')
        self.assertEqual(Decimal(self._value(engine.get_report('cash_flow', options), 'closing')), 37)

    def test_excluded_closing_notice_exports_and_options(self):
        company = self._company('Clearing notice')
        engine = self._engine(company)
        excluded = self._account(company, '105005', 'asset_cash')
        zero = self._account(company, '105006', 'asset_cash')
        income = self._account(company, '40505', 'income')
        journal = self._journal(company, 'CN05')
        self._entry(company, journal, '2040-12-31', excluded, income, 12)
        self._entry(company, journal, '2041-02-01', zero, income, 4)
        self._entry(company, journal, '2041-03-01', income, zero, 4)
        self._entry(company, journal, '2041-04-01', excluded, income, 3, posted=False)
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('baseer_report_engine.cash_flow_excluded_accounts', '105005,105006')
        options = self._options()
        prefix = 'Clearing accounts not reconciled, excluded from cash:'
        report = engine.get_report('cash_flow', options)
        notice = next(n['text'] for n in report['cash_notices'] if n['text'].startswith(prefix))
        self.assertIn('105005 asset_cash 105005: 12.00', notice)
        self.assertNotIn('105006', notice)
        self.assertIn(notice, report['notes'])
        draft = engine.get_report('cash_flow', dict(options, posted_only=False))
        self.assertTrue(any('105005: 15.00' in n['text'] for n in draft['cash_notices']))
        xlsx = base64.b64decode(engine.export_xlsx('cash_flow', options)['content'])
        with zipfile.ZipFile(io.BytesIO(xlsx)) as workbook:
            self.assertIn(notice, workbook.read('xl/sharedStrings.xml').decode())
        html, _ = self.env['ir.actions.report'].with_company(company).with_context(allowed_company_ids=[company.id])._render_qweb_html(
            'baseer_report_engine.report_pdf', docids=engine._definition('cash_flow').ids,
            data={'report_code': 'cash_flow', 'options': options})
        self.assertIn(notice, html.decode())
        self._entry(company, journal, '2041-05-01', income, excluded, 12)
        self.assertFalse(any(n['text'].startswith(prefix) for n in engine.get_report('cash_flow', options)['cash_notices']))
        params.set_param('baseer_report_engine.cash_flow_excluded_accounts', '')
        self.assertFalse(any(n['text'].startswith(prefix) for n in engine.get_report('cash_flow', dict(options, posted_only=False))['cash_notices']))

    def test_cash_identity_and_unfold(self):
        company = self._company('Cash flow company')
        engine = self._engine(company)
        cash = self._account(company, '10101', 'asset_cash')
        bank = self._account(company, '10102', 'asset_cash')
        revenue = self._account(company, '40101', 'income')
        revenue.tag_ids = [(4, self.env.ref('account.account_tag_operating').id)]
        journal = self._journal(company, 'CF1')
        self._entry(company, journal, '2040-12-31', cash, revenue, 100)
        self._entry(company, journal, '2041-01-15', cash, revenue, 40)
        self._entry(company, journal, '2041-02-15', bank, cash, 10)
        self._entry(company, journal, '2041-03-15', revenue, cash, 5, posted=False)
        options = self._options()
        report = engine.get_report('cash_flow', options)
        self.assertEqual(Decimal(self._value(report, 'beginning')), Decimal(100))
        self.assertEqual(Decimal(self._value(report, 'closing')), Decimal(140))
        self.assertEqual(Decimal(self._value(report, 'net')), Decimal(40))
        self.assertEqual(Decimal(self._value(report, 'operating_in')), Decimal(40))
        rows = engine.get_line_accounts('cash_flow', options, 'closing')['accounts']
        self.assertEqual({r['id'] for r in rows}, {cash.id, bank.id})
        detail = engine.get_move_line_action('cash_flow', options, 'operating_in', 'c0', revenue.id, company.id)
        self.assertEqual(detail['res_model'], 'account.move.line')
        self.assertEqual(engine.get_move_line_action('cash_flow', options, 'closing', 'c0', cash.id, company.id)['tag'], 'baseer_report_engine')
        draft = engine.get_report('cash_flow', dict(options, posted_only=False))
        self.assertEqual(Decimal(self._value(draft, 'closing')) - Decimal(self._value(draft, 'beginning')), Decimal(self._value(draft, 'net')))
        self.assertTrue(engine.export_xlsx('cash_flow', options)['content'])
        self.assertTrue(engine.export_pdf('cash_flow', options))

    def test_reconciliation_and_tags(self):
        from odoo import Command
        company = self._company('Cash reconciliation')
        engine = self._engine(company)
        cash = self._account(company, '10001', 'asset_cash')
        receivable = self._account(company, '11001', 'asset_receivable')
        payable = self._account(company, '21001', 'liability_payable')
        revenue = self._account(company, '40001', 'income')
        tax = self._account(company, '22001', 'liability_current')
        expense = self._account(company, '50001', 'expense')
        invest = self._account(company, '15001', 'asset_fixed')
        finance = self._account(company, '25001', 'liability_current')
        for acc in (revenue, tax, expense):
            acc.tag_ids = [Command.link(self.env.ref('account.account_tag_operating').id)]
        invest.tag_ids = [Command.link(self.env.ref('account.account_tag_investing').id)]
        finance.tag_ids = [Command.link(self.env.ref('account.account_tag_financing').id)]
        receivable.reconcile = payable.reconcile = True
        journal = self._journal(company, 'CF2')
        invoice = self.env['account.move'].with_company(company).create({'company_id': company.id, 'date': '2041-01-01', 'journal_id': journal.id, 'line_ids': [
            Command.create({'name': 'receivable', 'account_id': receivable.id, 'debit': 100}),
            Command.create({'name': 'sale', 'account_id': revenue.id, 'credit': 80}),
            Command.create({'name': 'tax', 'account_id': tax.id, 'credit': 20}),
        ]})
        invoice.action_post()
        payment = self._entry(company, journal, '2041-02-01', cash, receivable, 50)
        (invoice | payment).line_ids.filtered(lambda l: l.account_id == receivable).reconcile()
        bill = self._entry(company, journal, '2041-01-01', expense, payable, 30)
        paid = self._entry(company, journal, '2041-02-01', payable, cash, 30)
        (bill | paid).line_ids.filtered(lambda l: l.account_id == payable).reconcile()
        self._entry(company, journal, '2041-03-01', cash, receivable, 10)
        self._entry(company, journal, '2041-03-02', payable, cash, 8)
        self._entry(company, journal, '2041-03-03', invest, cash, 12)
        self._entry(company, journal, '2041-03-04', cash, finance, 25)
        options = self._options()
        report = engine.get_report('cash_flow', options)
        for code, expected in [('operating_in', 50), ('operating_out', -30), ('advance_received', 10), ('advance_paid', -8), ('investing_out', -12), ('financing_in', 25), ('net', 35)]:
            self.assertEqual(float(self._value(report, code)), expected, code)
        rows = engine.get_line_accounts('cash_flow', options, 'operating_in')['accounts']
        self.assertEqual({r['id']: float(r['amounts'][0]['value']) for r in rows}, {revenue.id: 40, tax.id: 10})
        action = engine.get_move_line_action('cash_flow', options, 'operating_in', 'c0', tax.id, company.id)
        self.assertEqual(set(self.env['account.move.line'].search(action['domain']).move_id.ids), {payment.id})
        tb = engine.get_report('trial_balance', options)
        cash_row = next(r for r in tb['lines'] if r.get('account_id') == cash.id)
        self.assertEqual(float(cash_row['amounts'][-1]['value']), float(self._value(report, 'closing')))

    def test_journal_filter_and_identity_against_trial_balance(self):
        import random
        company = self._company('Cash random')
        engine = self._engine(company)
        cash = self._account(company, '10111', 'asset_cash')
        other = self._account(company, '40111', 'income')
        journals = [self._journal(company, 'C11'), self._journal(company, 'C12')]
        randomizer = random.Random(19)
        for index in range(18):
            debit, credit = (cash, other) if randomizer.randrange(2) else (other, cash)
            self._entry(company, journals[index % 2], '2041-03-%02d' % (index + 1), debit, credit, randomizer.randrange(1, 80))
        for journal_ids in ([], [journals[0].id], [journals[1].id]):
            options = self._options(journal_ids=journal_ids)
            report = engine.get_report('cash_flow', options)
            beginning = Decimal(self._value(report, 'beginning'))
            closing = Decimal(self._value(report, 'closing'))
            self.assertEqual(Decimal(self._value(report, 'net')), closing - beginning)
            leaves = ('advance_received', 'operating_in', 'advance_paid', 'operating_out', 'investing_in', 'investing_out', 'financing_in', 'financing_out', 'unclassified_in', 'unclassified_out')
            self.assertEqual(sum(Decimal(self._value(report, c)) for c in leaves), closing - beginning)
            tb = engine.get_report('trial_balance', options)
            row = next(r for r in tb['lines'] if r.get('account_id') == cash.id)
            self.assertEqual(Decimal(row['amounts'][-1]['value']), closing)

    def test_outstanding_and_multi_company(self):
        first = self._company('Cash domestic')
        second = self._company('Cash foreign')
        eur = self.env.ref('base.EUR')
        eur.active = True
        second.currency_id = eur
        self.env['res.currency.rate'].create({'currency_id': eur.id, 'name': '2041-01-01', 'rate': 2.0, 'company_id': second.id})
        outstanding = self._account(first, '12001', 'asset_current')
        income = self._account(first, '41001', 'income')
        bank = self.env['account.journal'].with_company(first).create({'name': 'Cash bank', 'code': 'CFBK', 'type': 'bank', 'company_id': first.id})
        bank.inbound_payment_method_line_ids[0].payment_account_id = outstanding
        journal = self._journal(first, 'CFD')
        self._entry(first, journal, '2041-04-01', outstanding, income, 10)
        foreign_cash = self._account(second, '10002', 'asset_cash')
        foreign_income = self._account(second, '41002', 'income')
        foreign_journal = self._journal(second, 'CFF')
        self._entry(second, foreign_journal, '2041-04-01', foreign_cash, foreign_income, 20)
        engine = self._engine(first).with_context(allowed_company_ids=[first.id, second.id])
        options = self._options()
        report = engine.get_report('cash_flow', options)
        expected = 10 + eur._convert(20, first.currency_id, second, '2041-06-30')
        self.assertAlmostEqual(float(self._value(report, 'closing')), expected, places=2)
        tb = engine.get_report('trial_balance', options)
        value = sum(Decimal(r['amounts'][-1]['value']) for r in tb['lines'] if r.get('account_id') in (outstanding.id, foreign_cash.id))
        self.assertEqual(value, Decimal(self._value(report, 'closing')))
        self.assertEqual(Decimal(self._value(report, 'net')), Decimal(self._value(report, 'closing')) - Decimal(self._value(report, 'beginning')))

    def test_rpc_menu_and_pdf(self):
        from odoo.service.model import call_kw
        company = self._company('Cash RPC')
        engine = self._engine(company)
        options = self._options()
        payload = call_kw(engine, 'get_report', ['cash_flow', options], {})
        self.assertEqual(payload['report']['report_kind'], 'cash_flow')
        self.assertEqual(call_kw(engine, 'get_line_accounts', ['cash_flow', options, 'closing'], {})['accounts'], [])
        html, _ = self.env['ir.actions.report'].with_company(company).with_context(allowed_company_ids=[company.id])._render_qweb_html(
            'baseer_report_engine.report_pdf', docids=engine._definition('cash_flow').ids,
            data={'report_code': 'cash_flow', 'options': options})
        self.assertIn('Cash flows from operating activities', html.decode())
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine'], ['ar_001'], overwrite=True)
        self.assertEqual(self.env.ref('baseer_report_engine.menu_cash_flow').with_context(lang='ar_001').name, 'قائمة التدفقات النقدية (جديد)')

    def test_future_partial_stays_advance(self):
        company = self._company('Cash cutoff')
        engine = self._engine(company)
        cash = self._account(company, '10031', 'asset_cash')
        receivable = self._account(company, '11031', 'asset_receivable')
        receivable.reconcile = True
        revenue = self._account(company, '40031', 'income')
        revenue.tag_ids = [(4, self.env.ref('account.account_tag_operating').id)]
        journal = self._journal(company, 'CF31')
        payment = self._entry(company, journal, '2041-06-01', cash, receivable, 50)
        invoice = self._entry(company, journal, '2041-07-01', receivable, revenue, 50)
        (payment | invoice).line_ids.filtered(lambda line: line.account_id == receivable).reconcile()
        report = engine.get_report('cash_flow', self._options())
        self.assertEqual(Decimal(self._value(report, 'advance_received')), Decimal(50))
        self.assertEqual(Decimal(self._value(report, 'operating_in')), Decimal(0))

    def test_residual_has_non_drillable_detail(self):
        from unittest.mock import patch
        company = self._company('Cash rounding')
        engine = self._engine(company)
        cash = self._account(company, '10032', 'asset_cash')
        income = self._account(company, '40032', 'income')
        journal = self._journal(company, 'CF32')
        self._entry(company, journal, '2041-03-01', cash, income, 50)
        with patch.object(type(engine), '_ledger_convert', return_value=Decimal('49.99')):
            report = engine.get_report('cash_flow', self._options(), with_accounts=True)
        line = next(row for row in report['lines'] if row['code'] == 'unclassified_in')
        residual = next(row for row in line['accounts'] if not row['id'])
        self.assertEqual(residual['name'], 'Exchange difference / rounding')
        self.assertFalse(residual['amounts'][0]['drill'])
        self.assertEqual(sum(Decimal(row['amounts'][0]['value']) for row in line['accounts']), Decimal(line['amounts'][0]['value']))

    def test_query_count_does_not_grow_with_moves(self):
        company = self._company('Cash query count')
        engine = self._engine(company)
        cash = self._account(company, '10033', 'asset_cash')
        income = self._account(company, '40033', 'income')
        journal = self._journal(company, 'CF33')
        options = self._options()
        def count():
            self.env.flush_all()
            self.env.invalidate_all()
            start = self.cr.sql_log_count
            engine.get_report('cash_flow', options)
            return self.cr.sql_log_count - start
        for index in range(5):
            self._entry(company, journal, '2041-03-01', cash, income, 1)
        small = count()
        for index in range(25):
            self._entry(company, journal, '2041-03-01', cash, income, 1)
        large = count()
        self.assertLessEqual(large, small + 5, (small, large))

    def test_invoice_and_bill_payment_workflows(self):
        from odoo import Command
        company = self._company('Cash workflow')
        company.country_id = self.env.ref('base.us')
        engine = self._engine(company)
        rec = self._account(company, '11041', 'asset_receivable')
        pay = self._account(company, '21041', 'liability_payable')
        rec.reconcile = pay.reconcile = True
        income = self._account(company, '40041', 'income')
        expense = self._account(company, '50041', 'expense')
        tax_account = self._account(company, '22041', 'liability_current')
        for account in (income, expense, tax_account):
            account.tag_ids = [Command.link(self.env.ref('account.account_tag_operating').id)]
        partner = self.env['res.partner'].create({'name': 'Cash workflow partner'})
        partner.with_company(company).write({'property_account_receivable_id': rec.id, 'property_account_payable_id': pay.id})
        company.transfer_account_id = self._account(company, '10941', 'asset_current')
        sales = self.env['account.journal'].with_company(company).create({'name': 'Sales', 'code': 'CFS', 'type': 'sale', 'company_id': company.id, 'default_account_id': income.id})
        purchases = self.env['account.journal'].with_company(company).create({'name': 'Purchases', 'code': 'CFP', 'type': 'purchase', 'company_id': company.id, 'default_account_id': expense.id})
        bank = self.env['account.journal'].with_company(company).create({'name': 'Bank', 'code': 'CFB', 'type': 'bank', 'company_id': company.id})
        (bank.inbound_payment_method_line_ids | bank.outbound_payment_method_line_ids).payment_account_id = bank.default_account_id
        tax_group = self.env['account.tax.group'].with_company(company).create({'name': 'Cash tax', 'company_id': company.id})
        tax = self.env['account.tax'].with_company(company).create({'name': '15 percent', 'amount': 15, 'type_tax_use': 'sale', 'company_id': company.id, 'tax_group_id': tax_group.id, 'country_id': self.env.ref('base.us').id})
        tax.invoice_repartition_line_ids.filtered(lambda l: l.repartition_type == 'tax').account_id = tax_account
        def invoice(kind, journal, account, price, taxes):
            move = self.env['account.move'].with_company(company).create({'move_type': kind, 'company_id': company.id, 'journal_id': journal.id, 'partner_id': partner.id, 'invoice_date': '2041-02-01', 'date': '2041-02-01', 'invoice_line_ids': [Command.create({'name': 'Workflow', 'account_id': account.id, 'price_unit': price, 'tax_ids': [Command.set(taxes.ids)]})]})
            move.action_post()
            return move
        def register(move, amount):
            wizard = self.env['account.payment.register'].with_company(company).with_context(active_model='account.move', active_ids=move.ids)
            wizard.create({'journal_id': bank.id, 'payment_date': '2041-03-01', 'amount': amount})._create_payments()
        register(invoice('out_invoice', sales, income, 100, tax), 115)
        register(invoice('out_invoice', sales, income, 100, self.env['account.tax']), 40)
        register(invoice('in_invoice', purchases, expense, 30, self.env['account.tax']), 30)
        report = engine.get_report('cash_flow', self._options(), with_accounts=True)
        self.assertEqual(Decimal(self._value(report, 'operating_in')), Decimal(155))
        self.assertEqual(Decimal(self._value(report, 'operating_out')), Decimal(-30))
        rows = next(line['accounts'] for line in report['lines'] if line['code'] == 'operating_in')
        self.assertEqual({row['id']: Decimal(row['amounts'][0]['value']) for row in rows}, {income.id: Decimal(140), tax_account.id: Decimal(15)})

    def test_advance_payments_and_liquidity_workflows(self):
        from odoo import Command, fields
        from datetime import date

        company = self._company('Cash advance workflows')
        engine = self._engine(company)
        receivable = self._account(company, '11051', 'asset_receivable')
        payable = self._account(company, '21051', 'liability_payable')
        receivable.reconcile = payable.reconcile = True
        income = self._account(company, '40051', 'income')
        income.tag_ids = [Command.link(self.env.ref('account.account_tag_operating').id)]
        partner = self.env['res.partner'].create({'name': 'Advance partner'})
        partner.with_company(company).write({'property_account_receivable_id': receivable.id, 'property_account_payable_id': payable.id})
        bank = self.env['account.journal'].with_company(company).create({'name': 'Advance bank', 'code': 'CA51', 'type': 'bank', 'company_id': company.id})
        cash_journal = self.env['account.journal'].with_company(company).create({'name': 'Advance cash', 'code': 'CC51', 'type': 'cash', 'company_id': company.id})
        outstanding = self._account(company, '12051', 'asset_current')
        bank.inbound_payment_method_line_ids[0].payment_account_id = outstanding
        bank.outbound_payment_method_line_ids[0].payment_account_id = bank.default_account_id
        company.transfer_account_id = self._account(company, '10951', 'asset_current')

        def payment(kind, partner_type, amount, day):
            method = (bank.inbound_payment_method_line_ids if kind == 'inbound' else bank.outbound_payment_method_line_ids)[0]
            result = self.env['account.payment'].with_company(company).create({
                'company_id': company.id, 'journal_id': bank.id, 'payment_type': kind,
                'partner_type': partner_type, 'partner_id': partner.id, 'amount': amount,
                'date': day, 'payment_method_line_id': method.id,
            })
            result.action_post()
            return result

        customer = payment('inbound', 'customer', 100, '2041-03-01')
        payment('outbound', 'supplier', 30, '2041-03-02')
        general = self._journal(company, 'CA52')
        self._entry(company, general, '2040-12-31', bank.default_account_id, income, 20)
        self._entry(company, general, '2041-03-03', cash_journal.default_account_id, bank.default_account_id, 10)
        options = self._options()
        report = engine.get_report('cash_flow', options)
        self.assertEqual(Decimal(self._value(report, 'advance_received')), Decimal(100))
        self.assertEqual(Decimal(self._value(report, 'advance_paid')), Decimal(-30))
        self.assertEqual(Decimal(self._value(report, 'net')), Decimal(70))
        self.assertIn(outstanding.id, {row['id'] for row in engine.get_line_accounts('cash_flow', options, 'closing')['accounts']})
        liquidity_ids = set(engine._cash_liquidity_accounts().ids)
        for cf_code, end in [('beginning', date(2040, 12, 31)), ('closing', date(2041, 6, 30))]:
            tb = engine.get_report('trial_balance', self._options(date_to=fields.Date.to_string(end), as_of=fields.Date.to_string(end), date_from=fields.Date.to_string(end.replace(month=1, day=1))))
            balance = sum(Decimal(row['amounts'][-1]['value']) for row in tb['lines'] if row.get('account_id') in liquidity_ids)
            self.assertEqual(Decimal(self._value(report, cf_code)), balance)

        sales = self.env['account.journal'].with_company(company).create({'name': 'Advance sales', 'code': 'CS51', 'type': 'sale', 'company_id': company.id, 'default_account_id': income.id})
        invoice = self.env['account.move'].with_company(company).create({
            'move_type': 'out_invoice', 'company_id': company.id, 'journal_id': sales.id,
            'partner_id': partner.id, 'invoice_date': '2041-07-01', 'date': '2041-07-01',
            'invoice_line_ids': [Command.create({'name': 'Later invoice', 'account_id': income.id, 'price_unit': 100, 'tax_ids': [Command.clear()]})],
        })
        invoice.action_post()
        (customer.move_id | invoice).line_ids.filtered(lambda line: line.account_id == receivable).reconcile()
        report = engine.get_report('cash_flow', options)
        self.assertEqual(Decimal(self._value(report, 'advance_received')), Decimal(100))
        extended = engine.get_report('cash_flow', self._options(date_to='2041-07-31', as_of='2041-07-31'))
        self.assertEqual(Decimal(self._value(extended, 'operating_in')), Decimal(100))
        self.assertEqual(Decimal(self._value(extended, 'advance_received')), Decimal(0))

    def test_opening_entries_and_transfer_warning(self):
        company = self._company('Cash opening and transfer')
        engine = self._engine(company)
        cash = self._account(company, '10371', 'asset_cash')
        other = self._account(company, '40371', 'income')
        transfer = self._account(company, '10971', 'asset_current')
        company.transfer_account_id = transfer
        journal = self._journal(company, 'CO71')
        old = self._entry(company, journal, '2040-12-31', cash, other, 5)
        opening = self._entry(company, journal, '2041-01-01', cash, other, 10)
        named = self._entry(company, journal, '2041-02-01', cash, other, 20)
        numbered = self._entry(company, journal, '2041-03-01', cash, other, 30)
        company.account_opening_move_id = opening
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('baseer_report_engine.cash_flow_opening_moves', '%s, %s\nmissing-token' % (named.name, numbered.id))
        options = self._options()
        report = engine.get_report('cash_flow', options, with_accounts=True)
        self.assertEqual(Decimal(self._value(report, 'beginning')), Decimal(65))
        self.assertEqual(Decimal(self._value(report, 'net')), Decimal(0))
        self.assertEqual(Decimal(self._value(report, 'closing')), Decimal(65))
        self.assertTrue(any('missing-token' in n['text'] for n in report['cash_notices']))
        row = next(r for r in report['lines'] if r['code'] == 'beginning')['accounts'][0]
        self.assertEqual(Decimal(row['amounts'][0]['value']), Decimal(65))
        tb = engine.get_report('trial_balance', options)
        self.assertEqual(Decimal(next(r for r in tb['lines'] if r.get('account_id') == cash.id)['amounts'][-1]['value']), Decimal(65))
        company.account_opening_move_id = old
        params.set_param('baseer_report_engine.cash_flow_opening_moves', '')
        report = engine.get_report('cash_flow', options)
        self.assertEqual(Decimal(self._value(report, 'beginning')), Decimal(5))
        self._entry(company, journal, '2041-04-01', transfer, other, 17)
        filtered_journal = self._journal(company, 'CO72')
        report = engine.get_report('cash_flow', dict(options, journal_ids=[filtered_journal.id]))
        notice = next(n for n in report['cash_notices'] if n.get('action'))
        self.assertIn('17.00', notice['text'])
        self.assertEqual(self.env['account.move.line'].search(notice['action']['domain']).mapped('account_id'), transfer)
        self.assertIn(notice['text'], report['notes'])
        self._entry(company, journal, '2041-04-02', other, transfer, 17)
        report = engine.get_report('cash_flow', options)
        self.assertFalse(any(n.get('action') for n in report['cash_notices']))
        extra = self._account(company, '10972', 'asset_current')
        params.set_param('baseer_report_engine.cash_flow_transfer_accounts', extra.code)
        self._entry(company, journal, '2041-04-03', extra, other, 9, posted=False)
        self.assertFalse(any(n.get('action') for n in engine.get_report('cash_flow', options)['cash_notices']))
        draft = engine.get_report('cash_flow', dict(options, posted_only=False))
        self.assertTrue(any('9.00' in n['text'] for n in draft['cash_notices']))
