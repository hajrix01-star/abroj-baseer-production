from decimal import Decimal

from .common import EngineCase


class TestCashFlow(EngineCase):
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
