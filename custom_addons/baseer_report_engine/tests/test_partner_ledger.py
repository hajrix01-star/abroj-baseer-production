"""Tests for the partner grouping used by the ledger engine."""
from odoo.tests.common import tagged

from .common import EngineCase


@tagged('post_install', '-at_install')
class TestPartnerLedgerGrouping(EngineCase):
    def test_grouping_includes_unknown_and_cumulative_opening(self):
        company = self._company('Partner grouping')
        engine = self._engine(company)
        journal = self._journal(company, 'PLG')
        receivable = self._account(company, '1100', 'asset_receivable')
        other = self._account(company, '4000', 'income')
        partner = self.env['res.partner'].create({'name': 'Grouping partner'})
        first = self._entry(company, journal, '2040-04-01', receivable, other, 10)
        second = self._entry(company, journal, '2041-04-01', receivable, other, 7)
        self._entry(company, journal, '2041-04-02', receivable, other, 3)
        (first | second).line_ids.filtered(lambda line: line.account_id == receivable).partner_id = partner
        report = engine._definition('general_ledger')
        options = engine._normalize_options(report, self._options(date_from='2041-04-01', date_to='2041-04-30'))
        initial, period = engine._ledger_partner_data(options, [('account_id', '=', receivable.id)])
        self.assertEqual(initial[partner.id]['balance'], 10)
        self.assertEqual(period[partner.id]['balance'], 7)
        self.assertEqual(period[0]['balance'], 3)

    def test_report_and_partner_page(self):
        company = self._company('Partner report')
        engine = self._engine(company)
        journal = self._journal(company, 'PLR')
        receivable = self._account(company, '1100', 'asset_receivable')
        other = self._account(company, '4000', 'income')
        partner = self.env['res.partner'].create({'name': 'Report partner'})
        move = self._entry(company, journal, '2041-04-01', receivable, other, 7)
        move.line_ids.filtered(lambda line: line.account_id == receivable).partner_id = partner
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        payload = engine.get_report('partner_ledger', options)
        row = next(row for row in payload['lines'] if row.get('partner_id') == partner.id)
        self.assertEqual(float(row['amounts'][-1]['value']), 7)
        page = engine.get_ledger_lines('partner_ledger', options, partner.id)
        self.assertEqual(page['rows'][0]['id'], move.line_ids.filtered(lambda line: line.account_id == receivable).id)
        self.assertEqual(engine.get_partner_action(partner.id)['res_id'], partner.id)
        action = engine.get_move_line_action('partner_ledger', options, row['code'], 'balance', partner.id)
        self.assertEqual(sum(self.env['account.move.line'].search(action['domain']).mapped('balance')), 7)

    def test_invalid_partner_options(self):
        from odoo.exceptions import ValidationError
        company = self._company('Partner options')
        engine = self._engine(company)
        for options in ({'account_types': []}, {'account_types': ['income']},
                        {'partner_ids': [True]}, {'unreconciled': 1}):
            with self.assertRaises(ValidationError):
                engine.get_report('partner_ledger', options)

    def test_unknown_opening_and_paging(self):
        company = self._company('Partner pages')
        engine = self._engine(company).with_context(baseer_gl_page_size=2)
        journal = self._journal(company, 'PLP')
        receivable = self._account(company, '1100', 'asset_receivable')
        other = self._account(company, '4000', 'income')
        for day, amount in [('2041-03-01', 5), ('2041-04-01', 2), ('2041-04-02', 3), ('2041-04-03', 4)]:
            self._entry(company, journal, day, receivable, other, amount)
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        report = engine.get_report('partner_ledger', options)
        row = next(r for r in report['lines'] if r.get('partner_id') == 0)
        self.assertEqual(float(row['amounts'][-1]['value']), 14)
        page = engine.get_ledger_lines('partner_ledger', options, False)
        self.assertEqual(page['rows'][0]['type'], 'initial')
        self.assertTrue(page['has_more'])
        page = engine.get_ledger_lines('partner_ledger', options, False, offset=2)
        self.assertEqual(float(page['rows'][0]['amounts'][-1]['value']), 14)
        self.assertFalse(page['has_more'])

    def _fixture(self):
        company = self._company('Partner ledger fixtures')
        engine = self._engine(company)
        journal = self._journal(company, 'PLF')
        rec = self._account(company, '1100', 'asset_receivable')
        pay = self._account(company, '2100', 'liability_payable')
        nontrade = self._account(company, '1200', 'asset_receivable')
        nontrade.non_trade = True
        other = self._account(company, '4000', 'income')
        partners = self.env['res.partner'].create([{'name': 'Alpha ledger'}, {'name': 'Beta ledger'}])
        return company, engine, journal, rec, pay, nontrade, other, partners

    def _partner_entry(self, company, journal, day, debit, credit, amount, partner=False, posted=True):
        move = self._entry(company, journal, day, debit, credit, amount, posted=posted)
        move.line_ids.filtered(lambda line: line.account_id in (debit | credit) and line.account_id.account_type in ('asset_receivable', 'liability_payable')).partner_id = partner
        return move

    def test_trial_balance_reconciliation_by_account_type(self):
        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        self._partner_entry(company, journal, '2040-12-01', rec, other, 10, partners[0])
        self._partner_entry(company, journal, '2041-04-01', rec, other, 7, partners[0])
        self._partner_entry(company, journal, '2041-04-02', other, pay, 4, partners[1])
        self._partner_entry(company, journal, '2041-04-03', nontrade, other, 3, partners[0])
        self._partner_entry(company, journal, '2041-04-04', rec, other, 2)
        self._partner_entry(company, journal, '2041-07-01', rec, other, 99, partners[0])
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        tb = engine.get_report('trial_balance', options)
        tb_rows = {r['account_id']: r for r in tb['lines'] if r.get('account_id')}
        for types, accounts in [(None, rec | pay), (['receivable'], rec), (['payable'], pay), (['non_trade_receivable'], nontrade)]:
            opts = dict(options, **({'account_types': types} if types else {}))
            rows = engine.get_report('partner_ledger', opts)['lines'][:-1]
            self.assertAlmostEqual(sum(float(r['amounts'][-1]['value']) for r in rows), sum(float(tb_rows[a.id]['amounts'][-1]['value']) for a in accounts))
            for row in rows:
                domain = [('company_id', '=', company.id), ('account_id', 'in', accounts.ids), ('partner_id', '=', row['partner_id'] or False), ('parent_state', '=', 'posted'), ('date', '<=', options['date_to'])]
                self.assertAlmostEqual(float(row['amounts'][-1]['value']), sum(self.env['account.move.line'].search(domain).mapped('balance')))

    def test_running_totals_paging_and_unknown_drill(self):
        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        for day, amount, partner in [('2041-03-01', 10, partners[0]), ('2041-04-03', 3, partners[0]), ('2041-04-01', 1, partners[0]), ('2041-04-02', 2, partners[0]), ('2041-04-02', 5, False)]:
            self._partner_entry(company, journal, day, rec, other, amount, partner)
        self._partner_entry(company, journal, '2041-04-04', other, pay, 4, partners[1])
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        report = engine.get_report('partner_ledger', options)
        row = next(r for r in report['lines'] if r.get('partner_id') == partners[0].id)
        unknown = next(r for r in report['lines'] if r.get('partner_id') == 0)
        self.assertEqual(unknown['name'], 'Unknown Partner')
        self.assertEqual([float(a['value']) for a in report['lines'][-1]['amounts']], [21, 4, 17])
        paged = engine.with_context(baseer_gl_page_size=2)
        first = paged.get_ledger_lines('partner_ledger', options, partners[0].id)
        second = paged.get_ledger_lines('partner_ledger', options, partners[0].id, offset=2)
        rows = first['rows'] + second['rows']
        self.assertTrue(first['has_more'])
        self.assertFalse(second['has_more'])
        self.assertEqual(rows, engine.with_context(baseer_gl_page_size=100).get_ledger_lines('partner_ledger', options, partners[0].id)['rows'])
        self.assertEqual([r['type'] for r in rows], ['initial', 'item', 'item', 'item', 'total'])
        self.assertEqual([float(r['amounts'][-1]['value']) for r in rows], [10, 11, 13, 16, 16])
        self.assertEqual(rows[-1]['name'], 'Total Alpha ledger')
        unknown_page = engine.get_ledger_lines('partner_ledger', options, False)
        self.assertEqual([r['type'] for r in unknown_page['rows']], ['item', 'total'])
        for r in (row, unknown):
            action = engine.get_move_line_action('partner_ledger', options, r['code'], 'balance', r['partner_id'])
            lines = self.env['account.move.line'].search(action['domain'])
            self.assertEqual([sum(lines.mapped(k)) for k in ('debit', 'credit', 'balance')], [float(a['value']) for a in r['amounts']])
        self.assertEqual(engine.get_partner_action(partners[0].id)['res_model'], 'res.partner')
        self.assertEqual(engine.get_move_action(rows[1]['id'])['res_id'], self.env['account.move.line'].browse(rows[1]['id']).move_id.id)

    def test_partner_filters_drafts_and_dates(self):
        from odoo import Command
        from odoo.exceptions import AccessError
        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        category = self.env['res.partner.category'].create({'name': 'Ledger category'})
        partners[0].category_id = [Command.link(category.id)]
        self._partner_entry(company, journal, '2041-03-01', rec, other, 10, partners[0])
        self._partner_entry(company, journal, '2041-04-01', rec, other, 5, partners[1], posted=False)
        self._partner_entry(company, journal, '2041-07-01', rec, other, 100, partners[0])
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        def ids(opts):
            return {r['partner_id'] for r in engine.get_report('partner_ledger', opts)['lines'] if 'partner_id' in r}
        self.assertEqual(ids(options), {partners[0].id})
        self.assertEqual(ids(dict(options, posted_only=False)), set(partners.ids))
        self.assertEqual(ids(dict(options, posted_only=False, partner_ids=partners[1].ids)), {partners[1].id})
        self.assertEqual(ids(dict(options, posted_only=False, partner_category_ids=category.ids)), {partners[0].id})
        user = self.env['res.users'].create({'name': 'Partner reader', 'login': 'partner_ledger_reader', 'company_id': company.id, 'company_ids': [Command.set(company.ids)], 'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('account.group_account_readonly').id])]})
        self.assertTrue(engine.with_user(user).get_report('partner_ledger', options)['lines'])
        rule = self.env['ir.rule'].create({'name': 'Hide ledger partner', 'model_id': self.env['ir.model']._get_id('res.partner'), 'domain_force': repr([('id', '!=', partners[0].id)])})
        with self.assertRaises(AccessError):
            engine.with_user(user).get_report('partner_ledger', dict(options, partner_ids=partners[0].ids))
        rule.unlink()
        user.group_ids = [Command.set([self.env.ref('base.group_user').id])]
        with self.assertRaises(AccessError):
            engine.with_user(user).get_report('partner_ledger', options)

    def test_rpc_validation_and_arabic_names(self):
        from odoo.exceptions import AccessError, ValidationError
        from odoo.service.model import call_kw
        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        move = self._partner_entry(company, journal, '2041-04-01', rec, other, 7, partners[0])
        line = move.line_ids.filtered(lambda l: l.account_id == rec)
        options = self._options()
        call = lambda method, args: call_kw(engine, method, args, {'context': engine.env.context})
        self.assertTrue(call('get_bootstrap', ['partner_ledger']))
        report = call('get_report', ['partner_ledger', options])
        row = next(r for r in report['lines'] if r.get('partner_id') == partners[0].id)
        self.assertTrue(call('get_ledger_lines', ['partner_ledger', options, partners[0].id])['rows'])
        self.assertEqual(call('get_partner_action', [partners[0].id])['res_id'], partners[0].id)
        self.assertEqual(call('get_move_action', [line.id])['res_id'], move.id)
        self.assertTrue(call('get_move_line_action', ['partner_ledger', options, row['code'], 'balance', partners[0].id])['domain'])
        self.assertTrue(call('get_draft_entries_action', ['partner_ledger', options]))
        self.assertTrue(call('export_xlsx', ['partner_ledger', options])['content'])
        self.assertTrue(call('export_pdf', ['partner_ledger', options])['type'])
        for bad in ({'account_types': []}, {'account_types': ['bad']}, {'partner_ids': ['1']}, {'partner_ids': [True]}):
            with self.assertRaises(ValidationError):
                call('get_report', ['partner_ledger', dict(options, **bad)])
        with self.assertRaises(AccessError):
            call('get_report', ['partner_ledger', dict(options, partner_ids=[999999999])])
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine'], ['ar_001'], overwrite=True)
        for xmlid in ('menu_partner_ledger', 'action_partner_ledger'):
            self.assertEqual(self.env.ref('baseer_report_engine.' + xmlid).with_context(lang='ar_001').name, 'دفتر الأستاذ العام للشركاء (جديد)')
        self.assertEqual(engine._definition('partner_ledger').with_context(lang='ar_001').name, 'دفتر الأستاذ العام للشركاء')

    def test_query_count_independent_of_partners(self):
        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        options = self._options()
        def add(number):
            for index in range(number):
                partner = self.env['res.partner'].create({'name': 'Scaling %s' % index})
                self._partner_entry(company, journal, '2041-04-01', rec, other, 1, partner)
        def count():
            engine.get_report('partner_ledger', options)
            start = self.cr.sql_log_count
            engine.get_report('partner_ledger', options)
            return self.cr.sql_log_count - start
        add(2)
        small = count()
        add(8)
        large = count()
        self.assertLessEqual(large, small + 5, (small, large))

    def test_companies_combine_and_convert_partner_balance(self):
        first, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        second = self._company('Partner ledger foreign company')
        eur = self.env.ref('base.EUR')
        eur.active = True
        second.currency_id = eur
        self.env['res.currency.rate'].create({'currency_id': eur.id, 'name': '2041-01-01', 'rate': 2.0, 'company_id': second.id})
        second_journal = self._journal(second, 'PLB')
        second_rec = self._account(second, '1100', 'asset_receivable')
        second_other = self._account(second, '4000', 'income')
        self._partner_entry(first, journal, '2041-04-01', rec, other, 10, partners[0])
        self._partner_entry(second, second_journal, '2041-04-01', second_rec, second_other, 20, partners[0])
        engine = engine.with_context(allowed_company_ids=[first.id, second.id])
        options = self._options()
        rows = [r for r in engine.get_report('partner_ledger', options)['lines'] if r.get('partner_id') == partners[0].id]
        self.assertEqual(len(rows), 1)
        converted = second.currency_id._convert(20, first.currency_id, second, '2041-06-30', round=False)
        self.assertAlmostEqual(float(rows[0]['amounts'][-1]['value']), 10 + converted, places=2)

    def test_invoice_payments_unreconciled_and_item_metadata(self):
        from odoo import Command, fields
        from datetime import timedelta
        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        rec.reconcile = True
        partners.with_company(company).property_account_receivable_id = rec
        sales = self.env['account.journal'].with_company(company).create({'name': 'Partner Sales', 'code': 'PLS', 'type': 'sale', 'company_id': company.id, 'default_account_id': other.id})
        company.transfer_account_id = self._account(company, '1090', 'asset_current')
        bank = self.env['account.journal'].with_company(company).create({'name': 'Partner Bank', 'code': 'PLBK', 'type': 'bank', 'company_id': company.id})
        today = fields.Date.context_today(self.env.user)
        past = today - timedelta(days=20)
        future = today + timedelta(days=20)
        invoices = self.env['account.move'].with_company(company).create([{
            'move_type': 'out_invoice', 'company_id': company.id, 'journal_id': sales.id,
            'partner_id': partners[0].id, 'invoice_date': past, 'date': past,
            'invoice_date_due': due,
            'invoice_line_ids': [Command.create({'name': 'Ledger invoice', 'account_id': other.id, 'price_unit': 100, 'tax_ids': [Command.clear()]})],
        } for due in (past, future, past)])
        invoices.action_post()
        register = self.env['account.payment.register'].with_company(company).with_context(active_model='account.move', active_ids=invoices[0].ids)
        register.create({'journal_id': bank.id, 'payment_date': today, 'amount': 100})._create_payments()
        register = self.env['account.payment.register'].with_company(company).with_context(active_model='account.move', active_ids=invoices[1].ids)
        register.create({'journal_id': bank.id, 'payment_date': today, 'amount': 40})._create_payments()
        lines = invoices.line_ids.filtered(lambda l: l.account_id == rec)
        full, partial, overdue = (lines.filtered(lambda l: l.move_id == invoice) for invoice in invoices)
        self.assertTrue(full.reconciled)
        self.assertFalse(partial.reconciled)
        eur = self.env.ref('base.EUR')
        eur.active = True
        foreign_move = self.env['account.move'].with_company(company).create({'company_id': company.id, 'date': today, 'journal_id': journal.id, 'line_ids': [Command.create({'name': 'Foreign', 'account_id': rec.id, 'partner_id': partners[0].id, 'debit': 10, 'currency_id': eur.id, 'amount_currency': 10}), Command.create({'name': 'Counterpart', 'account_id': other.id, 'credit': 10, 'currency_id': eur.id, 'amount_currency': -10})]})
        foreign_move._post(soft=False)
        foreign_line = foreign_move.line_ids.filtered(lambda l: l.account_id == rec)
        foreign_line.name = 'Mixed reference - ' + foreign_move.name
        options = self._options(date_from=str(past - timedelta(days=1)), date_to=str(future))
        page = engine.get_ledger_lines('partner_ledger', options, partners[0].id)
        items = {r['id']: r for r in page['rows'] if r['type'] == 'item'}
        self.assertEqual(items[full.id]['journal'], sales.code)
        self.assertEqual(items[full.id]['account'], rec.code)
        self.assertEqual(items[full.id]['invoice_date_raw'], str(past))
        self.assertEqual(items[full.id]['due_date_raw'], str(past))
        self.assertFalse(items[full.id]['overdue'])
        self.assertTrue(full.matching_number)
        self.assertEqual(items[full.id]['matching'], full.matching_number)
        self.assertFalse(items[partial.id]['overdue'])
        self.assertTrue(items[overdue.id]['overdue'])
        self.assertEqual(items[foreign_line.id]['name'], foreign_move.name + ' Mixed reference')
        self.assertEqual(items[foreign_line.id]['move_label'], foreign_move.name)
        self.assertEqual(items[foreign_line.id]['detail_label'], 'Mixed reference')
        self.assertTrue(items[foreign_line.id]['amount_currency'])
        self.assertFalse(items[full.id]['amount_currency'])
        filtered = engine.get_ledger_lines('partner_ledger', dict(options, unreconciled=True), partners[0].id)
        filtered_ids = {r['id'] for r in filtered['rows'] if r['type'] == 'item'}
        self.assertNotIn(full.id, filtered_ids)
        self.assertIn(partial.id, filtered_ids)

    def test_partner_exports(self):
        import base64
        import io
        from datetime import datetime
        from openpyxl import load_workbook

        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        self._partner_entry(company, journal, '2041-03-01', rec, other, 10, partners[0])
        move = self._partner_entry(company, journal, '2041-04-01', rec, other, 7, partners[0], posted=False)
        move.invoice_date = '2041-04-01'
        move.action_post()
        line = move.line_ids.filtered(lambda l: l.account_id == rec)
        line.date_maturity = '2041-04-20'
        self._partner_entry(company, journal, '2041-04-03', rec, other, 2, partners[0])
        self._partner_entry(company, journal, '2041-04-02', rec, other, 3, partners[1])
        options = dict(self._options(date_from='2041-04-01', date_to='2041-04-30'), unfolded_partners=[partners[0].id], partner_ids=partners.ids, posted_only=False, unreconciled=True)
        for lang, title in [('en_US', 'Partner Ledger'), ('ar_001', 'دفتر الأستاذ العام للشركاء')]:
            self.env['res.lang']._activate_lang(lang)
            self.env['ir.module.module']._load_module_terms(['baseer_report_engine'], [lang], overwrite=True)
            localized = engine.with_context(lang=lang, baseer_gl_page_size=1)
            payload = localized.get_report('partner_ledger', options)
            exported = localized.export_xlsx('partner_ledger', options)
            sheet = load_workbook(io.BytesIO(base64.b64decode(exported['content']))).active
            values = [[cell.value for cell in row] for row in sheet]
            flat = [str(v) for row in values for v in row if v is not None]
            self.assertIn(title, flat)
            self.assertIn(partners[0].name, ' '.join(flat))
            self.assertIn(localized._labels()['draft_entries'], ' '.join(flat))
            self.assertIn(localized._labels()['unreconciled_entries'], ' '.join(flat))
            page = localized.get_ledger_lines('partner_ledger', options, partners[0].id)
            for item in page['rows']:
                self.assertIn(item['name'], flat)
            item_row = next(row for row in values if row[0] == page['rows'][1]['name'])
            self.assertIsInstance(item_row[3], datetime)
            self.assertIsInstance(item_row[4], datetime)
            self.assertEqual(item_row[9], 17)
            partner_total = next(row for row in values if row[0] == localized._export_payload('partner_ledger', options)['lines'][0]['ledger']['rows'][-1]['name'])
            self.assertEqual(partner_total[9], 19)
            grand = next(row for row in values if row[0] == payload['lines'][-1]['name'])
            self.assertEqual([grand[i] for i in (6, 7, 9)], [float(a['value']) for a in payload['lines'][-1]['amounts']])
            self.assertEqual(bool(sheet.sheet_view.rightToLeft), lang == 'ar_001')
            html, _ = self.env['ir.actions.report'].with_company(company).with_context(lang=lang, allowed_company_ids=[company.id])._render_qweb_html('baseer_report_engine.report_pdf', docids=localized._definition('partner_ledger').ids, data={'report_code': 'partner_ledger', 'options': options})
            html = html.decode()
            self.assertIn(title, html)
            self.assertIn(payload['column_groups'][0]['label'], html)
            self.assertIn(page['rows'][1]['name'], html)
            self.assertIn(payload['lines'][-1]['amounts'][-1]['display'], html)
            if lang == 'ar_001':
                self.assertIn('dir="rtl"', html)
        all_payload = engine.with_context(baseer_gl_page_size=1)._export_payload('partner_ledger', dict(options, unfold_all=True))
        self.assertTrue(all(row.get('ledger') and not row['ledger']['has_more'] for row in all_payload['lines'] if row.get('foldable')))
        self.assertEqual(len([item for item in all_payload['lines'][0]['ledger']['rows'] if item['type'] == 'item']), 2)

    def test_partnerless_reconciliation_attribution(self):
        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        rec.reconcile = True
        invoice = self._partner_entry(company, journal, '2041-03-01', rec, other, 15, partners[0])
        payment = self._partner_entry(company, journal, '2041-04-01', other, rec, 10)
        partial_payment = self._partner_entry(company, journal, '2041-04-02', other, rec, 8)
        untouched = self._partner_entry(company, journal, '2041-04-03', other, rec, 3)
        invoice_line = invoice.line_ids.filtered(lambda l: l.account_id == rec)
        payment_line = payment.line_ids.filtered(lambda l: l.account_id == rec)
        partial_line = partial_payment.line_ids.filtered(lambda l: l.account_id == rec)
        (invoice_line | payment_line | partial_line).reconcile()
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        report = engine.get_report('partner_ledger', options)
        rows = {r.get('partner_id'): r for r in report['lines'][:-1]}
        self.assertEqual([float(a['value']) for a in rows[partners[0].id]['amounts']], [15, 15, 0])
        self.assertEqual([float(a['value']) for a in rows[0]['amounts']], [0, 6, -6])
        self.assertEqual([float(a['value']) for a in report['lines'][-1]['amounts']], [15, 21, -6])
        trial_balance = engine.get_report('trial_balance', options)
        tb_row = next(r for r in trial_balance['lines'] if r.get('account_id') == rec.id)
        self.assertEqual(sum(float(r['amounts'][-1]['value']) for r in report['lines'][:-1]),
                         float(tb_row['amounts'][-1]['value']))
        page = engine.with_context(baseer_gl_page_size=1).get_ledger_lines('partner_ledger', options, partners[0].id)
        self.assertEqual(page['rows'][1]['id'], payment_line.id)
        page = engine.with_context(baseer_gl_page_size=1).get_ledger_lines('partner_ledger', options, partners[0].id, offset=1)
        self.assertEqual(page['rows'][0]['id'], partial_line.id)
        self.assertEqual(float(page['rows'][0]['amounts'][-1]['value']), 0)
        action = engine.get_move_line_action('partner_ledger', options, rows[partners[0].id]['code'], 'balance', partners[0].id)
        self.assertIn(payment_line, self.env['account.move.line'].search(action['domain']))
        self.assertIn(partial_line, self.env['account.move.line'].search(action['domain']))
        unknown = engine.get_ledger_lines('partner_ledger', options, 0)
        self.assertEqual({r['id'] for r in unknown['rows'] if r['type'] == 'item'}, {partial_line.id, untouched.line_ids.filtered(lambda l: l.account_id == rec).id})
        filtered = engine.get_report('partner_ledger', dict(options, partner_ids=partners[0].ids))
        self.assertEqual(float(filtered['lines'][-1]['amounts'][-1]['value']), 0)
        remaining = engine.get_report('partner_ledger', dict(options, unreconciled=True))
        self.assertEqual(float(remaining['lines'][-1]['amounts'][-1]['value']), -11)

    def test_batch_matches_attributed_pages(self):
        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        rec.reconcile = True
        invoice = self._partner_entry(company, journal, '2041-03-01', rec, other, 15, partners[0])
        payment = self._partner_entry(company, journal, '2041-04-01', other, rec, 10)
        partial = self._partner_entry(company, journal, '2041-04-02', other, rec, 8)
        (invoice.line_ids | payment.line_ids | partial.line_ids).filtered(lambda line: line.account_id == rec).reconcile()
        self._partner_entry(company, journal, '2041-04-03', rec, other, 3, partners[1])
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        engine = engine.with_context(baseer_gl_page_size=1)
        for opts in (options, dict(options, partner_ids=partners[0].ids), dict(options, unreconciled=True)):
            batch = engine.get_partner_items_batch('partner_ledger', opts)
            keys = [row['partner_id'] for row in engine.get_report('partner_ledger', opts)['lines'] if row.get('foldable')]
            self.assertEqual(set(batch), set(keys))
            for key in keys:
                page = engine.get_ledger_lines('partner_ledger', opts, key)
                actual = batch[key]
                self.assertEqual(([actual['initial']] if actual['initial'] else []) + actual['items'], page['rows'])
                self.assertEqual((actual['has_more'], actual['next_offset']), (page['has_more'], page['next_offset']))

    def test_batch_query_count_independent_of_partner_count(self):
        company, engine, journal, rec, pay, nontrade, other, partners = self._fixture()
        options = self._options()
        def add(number):
            for index in range(number):
                partner = self.env['res.partner'].create({'name': 'Batch %s' % index})
                self._partner_entry(company, journal, '2041-04-01', rec, other, 1, partner)
        def count():
            engine.get_partner_items_batch('partner_ledger', options)
            self.env.invalidate_all()
            start = self.cr.sql_log_count
            engine.get_partner_items_batch('partner_ledger', options)
            return self.cr.sql_log_count - start
        add(5)
        small = count()
        add(45)
        large = count()
        self.assertLessEqual(large, small + 2, (small, large))

    def test_item_label_removes_move_occurrences(self):
        from ..models.ledger import _item_labels
        for move, detail, expected in [
            ('INV/2026/00045', 'SHAMI - 000003 - INV/2026/00045', 'INV/2026/00045 SHAMI - 000003'),
            ('INV/1', 'INV/1', 'INV/1'),
            ('BNK1/2026/00009', 'INV/2026/00008', 'BNK1/2026/00009 INV/2026/00008'),
            ('X', '', 'X'), ('X', 'X — X / note : X', 'X note')]:
            self.assertEqual(_item_labels(move, detail)[2], expected)
