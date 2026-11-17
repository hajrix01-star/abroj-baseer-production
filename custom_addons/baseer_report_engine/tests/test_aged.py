from datetime import date, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import EngineCase


@tagged('post_install', '-at_install')
class TestAged(EngineCase):
    def setUp(self):
        super().setUp()
        self.company = self._company('Aged Test')
        self.engine = self._engine(self.company)
        self.receivable = self._account(self.company, 'AR001', 'asset_receivable')
        self.payable = self._account(self.company, 'AP001', 'liability_payable')
        self.other = self._account(self.company, 'OT001', 'asset_current')
        self.journal = self._journal(self.company, 'AGE')

    def test_buckets_and_payable_sign(self):
        asof = date(2041, 6, 30)
        for days in (-3, 0, 1, 30, 31, 120, 121):
            self._entry(self.company, self.journal, asof - timedelta(days=max(days, 0)), self.receivable, self.other, 10)
            line = self.env['account.move.line'].search([('account_id', '=', self.receivable.id)], order='id desc', limit=1)
            line.date_maturity = asof - timedelta(days=days)
        self._entry(self.company, self.journal, asof, self.other, self.payable, 25)
        report = self.engine.get_report('aged_receivable', self._options())
        row = next(row for row in report['lines'] if row['code'] == 'total')
        self.assertEqual([round(float(a['value']), 2) for a in row['amounts']], [20, 20, 10, 0, 10, 10, 70])
        report15 = self.engine.get_report('aged_receivable', self._options(period_length=15))
        self.assertEqual([round(float(a['value']), 2) for a in report15['lines'][-1]['amounts']], [20, 10, 10, 10, 0, 20, 70])
        payable = self.engine.get_report('aged_payable', self._options())
        self.assertEqual(float(payable['lines'][-1]['amounts'][-1]['value']), 25)
        for bad in (0, -1, '30', 1.5):
            with self.assertRaises(ValidationError):
                self.engine.get_report('aged_receivable', self._options(period_length=bad))
        with self.assertRaises(ValidationError):
            self.engine.get_report('aged_receivable', self._options(aging_basis='bad'))

    def test_boundary_matrix_for_both_bases(self):
        asof = date(2041, 6, 30)
        for n in (30, 15):
            for basis in ('due_date', 'invoice_date'):
                partner = self.env['res.partner'].create({'name': 'Matrix %s %s' % (n, basis)})
                for days in (0, 1, n, n + 1, 4 * n, 4 * n + 1):
                    move = self._entry(self.company, self.journal, '2041-01-01', self.receivable, self.other, 1, posted=False)
                    move.invoice_date = asof - timedelta(days=days)
                    move.action_post()
                    line = move.line_ids.filtered(lambda item: item.account_id == self.receivable)
                    line.partner_id = partner
                    line.date_maturity = asof - timedelta(days=days)
                report = self.engine.get_report('aged_receivable', self._options(
                    partner_ids=[partner.id], period_length=n, aging_basis=basis))
                self.assertEqual([float(a['value']) for a in report['lines'][-1]['amounts']],
                                 [1, 2, 1, 0, 1, 1, 6], (n, basis))

    def test_total_matches_independent_asof_residual(self):
        self.receivable.reconcile = True
        invoice = self._entry(self.company, self.journal, '2041-01-01', self.receivable, self.other, 100)
        before = self._entry(self.company, self.journal, '2041-03-01', self.other, self.receivable, 30)
        after = self._entry(self.company, self.journal, '2041-07-01', self.other, self.receivable, 20)
        lines = (invoice | before | after).line_ids.filtered(lambda line: line.account_id == self.receivable)
        lines.reconcile()
        cutoff = date(2041, 6, 30)
        lines = self.env['account.move.line'].search([('account_id', '=', self.receivable.id), ('date', '<=', cutoff)])
        expected = 0
        for line in lines:
            partials = self.env['account.partial.reconcile'].search([
                ('max_date', '<=', cutoff), '|', ('debit_move_id', '=', line.id), ('credit_move_id', '=', line.id)])
            expected += line.balance - (1 if line.balance > 0 else -1) * sum(partials.mapped('amount'))
        total = self.engine.get_report('aged_receivable', self._options())['lines'][-1]['amounts'][-1]['value']
        self.assertAlmostEqual(float(total), expected, places=2)

    def test_reconciliation_at_asof_and_ledger_totals(self):
        partner = self.env['res.partner'].create({'name': 'Aging customer'})
        for account, report_code, sign in ((self.receivable, 'aged_receivable', 1), (self.payable, 'aged_payable', -1)):
            account.reconcile = True
            debit, credit = (account, self.other) if sign == 1 else (self.other, account)
            invoice = self._entry(self.company, self.journal, '2041-01-01', debit, credit, 100)
            payment = self._entry(self.company, self.journal, '2041-03-01', credit, debit, 30)
            future = self._entry(self.company, self.journal, '2041-07-01', credit, debit, 20)
            invoice_line = invoice.line_ids.filtered(lambda line: line.account_id == account)
            payment_line = payment.line_ids.filtered(lambda line: line.account_id == account)
            future_line = future.line_ids.filtered(lambda line: line.account_id == account)
            (invoice_line | payment_line | future_line).partner_id = partner
            (invoice_line | payment_line | future_line).reconcile()
            options = self._options()
            aged = self.engine.get_report(report_code, options)
            self.assertEqual(float(aged['lines'][-1]['amounts'][-1]['value']), 70)
            row = next(r for r in aged['lines'] if r.get('partner_id') == partner.id)
            action = self.engine.get_move_line_action(report_code, options, row['code'], 'total', partner.id)
            self.assertEqual(self.env['account.move.line'].search(action['domain']), invoice_line)
            self.assertEqual(self.engine.get_ledger_lines(report_code, options, partner.id)['rows'][0]['id'], invoice_line.id)
            ledger_options = self._options(account_types=['receivable' if sign == 1 else 'payable'])
            ledger = self.engine.get_report('partner_ledger', ledger_options)
            self.assertEqual(sign * float(ledger['lines'][-1]['amounts'][-1]['value']), 70)
            tb = self.engine.get_report('trial_balance', options)
            tb_row = next(r for r in tb['lines'] if r.get('account_id') == account.id)
            self.assertEqual(sign * float(tb_row['amounts'][-1]['value']), 70)
            # After the last partial, no reconciliation crosses the cutoff.
            later = self._options(as_of='2041-08-01', date_to='2041-08-01')
            aged_later = self.engine.get_report(report_code, later)
            ledger_later = self.engine.get_report('partner_ledger', dict(later, account_types=ledger_options['account_types']))
            tb_later = self.engine.get_report('trial_balance', later)
            tb_later_row = next(r for r in tb_later['lines'] if r.get('account_id') == account.id)
            self.assertEqual(float(aged_later['lines'][-1]['amounts'][-1]['value']), 50)
            self.assertEqual(sign * float(ledger_later['lines'][-1]['amounts'][-1]['value']), 50)
            self.assertEqual(sign * float(tb_later_row['amounts'][-1]['value']), 50)

    def test_basis_filters_drafts_and_settled(self):
        partner = self.env['res.partner'].create({'name': 'Aging filter'})
        category = self.env['res.partner.category'].create({'name': 'Aging category'})
        partner.category_id = category
        move = self._entry(self.company, self.journal, '2041-04-01', self.receivable, self.other, 40, posted=False)
        move.invoice_date = '2041-05-31'
        move.action_post()
        line = move.line_ids.filtered(lambda item: item.account_id == self.receivable)
        line.partner_id = partner
        line.date_maturity = '2041-07-01'
        draft = self._entry(self.company, self.journal, '2041-06-01', self.receivable, self.other, 5, posted=False)
        draft.line_ids.filtered(lambda item: item.account_id == self.receivable).partner_id = partner
        nontrade = self._account(self.company, 'AR002', 'asset_receivable')
        nontrade.non_trade = True
        self._entry(self.company, self.journal, '2041-06-01', nontrade, self.other, 7)
        opts = self._options(partner_ids=[partner.id], partner_category_ids=[category.id])
        due = self.engine.get_report('aged_receivable', opts)
        invoice = self.engine.get_report('aged_receivable', dict(opts, aging_basis='invoice_date'))
        self.assertEqual(float(due['lines'][-1]['amounts'][0]['value']), 40)
        self.assertEqual(float(invoice['lines'][-1]['amounts'][1]['value']), 40)
        draft_report = self.engine.get_report('aged_receivable', dict(opts, posted_only=False))
        self.assertEqual(float(draft_report['lines'][-1]['amounts'][-1]['value']), 45)
        self.assertEqual(float(self.engine.get_report('aged_receivable', self._options(account_types=['non_trade_receivable']))['lines'][-1]['amounts'][-1]['value']), 7)
        self.receivable.reconcile = True
        paid = self._entry(self.company, self.journal, '2041-06-01', self.other, self.receivable, 40)
        paid_line = paid.line_ids.filtered(lambda item: item.account_id == self.receivable)
        paid_line.partner_id = partner
        (line | paid_line).reconcile()
        settled = self.engine.get_report('aged_receivable', opts)
        self.assertEqual(float(settled['lines'][-1]['amounts'][-1]['value']), 0)
        self.assertFalse(any(row.get('partner_id') == partner.id for row in settled['lines']))

    def test_future_reconciliation_attributes_unknown_and_drill(self):
        partner = self.env['res.partner'].create({'name': 'Attribution'})
        self.receivable.reconcile = True
        invoice = self._entry(self.company, self.journal, '2041-05-01', self.receivable, self.other, 10)
        payment = self._entry(self.company, self.journal, '2041-06-01', self.other, self.receivable, 15)
        invoice_line = invoice.line_ids.filtered(lambda item: item.account_id == self.receivable)
        payment_line = payment.line_ids.filtered(lambda item: item.account_id == self.receivable)
        invoice_line.partner_id = partner
        (invoice_line | payment_line).reconcile()
        # The remaining payment is genuinely partner-less after the settled portion.
        rows = self.engine.get_report('aged_receivable', self._options())['lines']
        unknown = next(row for row in rows if row.get('partner_id') == 0)
        self.assertEqual(float(unknown['amounts'][-1]['value']), -5)
        self.assertEqual(unknown['name'], 'Unknown Partner')
        action = self.engine.get_move_line_action('aged_receivable', self._options(), unknown['code'], 'period1', 0)
        self.assertEqual(self.env['account.move.line'].search(action['domain']), payment_line)
        self.assertEqual(float(rows[-1]['amounts'][-1]['value']), -5)

    def test_menu_names_arabic(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine'], ['ar_001'], overwrite=True)
        for kind, name in [('receivable', 'المتأخر المدين (جديد)'), ('payable', 'حسابات دائنة مستحقة متأخرة (جديد)')]:
            self.assertEqual(self.env.ref('baseer_report_engine.menu_aged_' + kind).with_context(lang='ar_001').name, name)

    def test_company_conversion_and_query_count(self):
        second = self._company('Aged foreign')
        eur = self.env.ref('base.EUR')
        eur.active = True
        second.currency_id = eur
        self.env['res.currency.rate'].create({'currency_id': eur.id, 'name': '2041-01-01', 'rate': 2, 'company_id': second.id})
        rec = self._account(second, 'AR002', 'asset_receivable')
        other = self._account(second, 'OT002', 'asset_current')
        journal = self._journal(second, 'AG2')
        partner = self.env['res.partner'].create({'name': 'Multi-company partner'})
        for company, j, account, counterpart, amount in ((self.company, self.journal, self.receivable, self.other, 10), (second, journal, rec, other, 20)):
            move = self._entry(company, j, '2041-04-01', account, counterpart, amount)
            move.line_ids.filtered(lambda item: item.account_id == account).partner_id = partner
        engine = self.engine.with_context(allowed_company_ids=[self.company.id, second.id])
        row = next(row for row in engine.get_report('aged_receivable', self._options())['lines'] if row.get('partner_id') == partner.id)
        converted = eur._convert(20, self.company.currency_id, second, '2041-06-30', round=False)
        self.assertAlmostEqual(float(row['amounts'][-1]['value']), 10 + converted, places=2)
        def count():
            engine.get_report('aged_receivable', self._options())
            start = self.cr.sql_log_count
            engine.get_report('aged_receivable', self._options())
            return self.cr.sql_log_count - start
        small = count()
        for index in range(8):
            p = self.env['res.partner'].create({'name': 'Aged scaling %s' % index})
            move = self._entry(self.company, self.journal, '2041-04-01', self.receivable, self.other, 1)
            move.line_ids.filtered(lambda item: item.account_id == self.receivable).partner_id = p
        large = count()
        self.assertLessEqual(large, small + 5, (small, large))

    def test_aged_exports_include_aligned_unfolded_items(self):
        import base64
        import io
        from openpyxl import load_workbook
        partner = self.env['res.partner'].create({'name': 'Export aging'})
        move = self._entry(self.company, self.journal, '2041-06-01', self.receivable, self.other, 42)
        move.line_ids.filtered(lambda line: line.account_id == self.receivable).partner_id = partner
        options = self._options(unfolded_partners=[partner.id])
        payload = self.engine._export_payload('aged_receivable', options)
        item = next(line for line in payload['lines'] if line.get('partner_id') == partner.id)['ledger']['rows'][0]
        book = load_workbook(io.BytesIO(base64.b64decode(self.engine.export_xlsx('aged_receivable', options)['content'])))
        rows = [[cell.value for cell in row] for row in book.active]
        row = next(row for row in rows if row[0] == item['name'])
        self.assertEqual(row[3], 42)
        total = next(row for row in rows if row[0] == 'Total Aged Receivable')
        self.assertEqual(total[8], 42)
        html, _ = self.env['ir.actions.report'].with_company(self.company).with_context(allowed_company_ids=[self.company.id])._render_qweb_html(
            'baseer_report_engine.report_pdf', docids=self.engine._definition('aged_receivable').ids,
            data={'report_code': 'aged_receivable', 'options': options})
        self.assertIn(item['name'], html.decode())

    def test_page_query_count_does_not_grow_with_items_or_partners(self):
        partner = self.env['res.partner'].create({'name': 'Page scaling'})
        engine = self.engine.with_context(baseer_gl_page_size=1)
        options = self._options()
        def add(p):
            move = self._entry(self.company, self.journal, '2041-04-01', self.receivable, self.other, 1)
            move.line_ids.filtered(lambda line: line.account_id == self.receivable).partner_id = p
        def count():
            engine.get_ledger_lines('aged_receivable', options, partner.id)
            start = self.cr.sql_log_count
            engine.get_ledger_lines('aged_receivable', options, partner.id)
            return self.cr.sql_log_count - start
        add(partner)
        small = count()
        for index in range(12):
            add(partner)
            add(self.env['res.partner'].create({'name': 'Other page %s' % index}))
        large = count()
        self.assertLessEqual(large, small + 3, (small, large))

    def test_rpc_paging_and_future_attribution(self):
        from odoo.service.model import call_kw
        partner = self.env['res.partner'].create({'name': 'Future attribution'})
        self.receivable.reconcile = True
        payment = self._entry(self.company, self.journal, '2041-06-01', self.other, self.receivable, 10)
        invoice = self._entry(self.company, self.journal, '2041-07-01', self.receivable, self.other, 10)
        payment_line = payment.line_ids.filtered(lambda item: item.account_id == self.receivable)
        invoice_line = invoice.line_ids.filtered(lambda item: item.account_id == self.receivable)
        invoice_line.partner_id = partner
        (payment_line | invoice_line).reconcile()
        engine = self.engine.with_context(baseer_gl_page_size=1)
        options = self._options(partner_ids=[partner.id])
        payload = call_kw(engine, 'get_report', ['aged_receivable', options], {})
        row = next(r for r in payload['lines'] if r.get('partner_id') == partner.id)
        self.assertEqual(float(row['amounts'][-1]['value']), -10)
        page = call_kw(engine, 'get_ledger_lines', ['aged_receivable', options, partner.id], {})
        self.assertEqual(page['rows'][0]['id'], payment_line.id)
        second = self._entry(self.company, self.journal, '2041-05-01', self.receivable, self.other, 5)
        second.line_ids.filtered(lambda item: item.account_id == self.receivable).partner_id = partner
        page = engine.get_ledger_lines('aged_receivable', options, partner.id)
        self.assertTrue(page['has_more'])
        self.assertEqual(engine.get_ledger_lines('aged_receivable', options, partner.id, offset=1)['rows'][0]['id'], payment_line.id)

    def test_grouped_and_batch_match_per_line_with_future_attribution(self):
        from collections import defaultdict
        from decimal import Decimal

        partners = self.env['res.partner'].create([{'name': 'Aged batch A'}, {'name': 'Aged batch B'}])
        self.receivable.reconcile = True
        invoice = self._entry(self.company, self.journal, '2041-01-01', self.receivable, self.other, 100, posted=False)
        invoice.invoice_date = '2041-02-01'
        invoice.action_post()
        before = self._entry(self.company, self.journal, '2041-03-01', self.other, self.receivable, 30)
        later = self._entry(self.company, self.journal, '2041-07-01', self.other, self.receivable, 20)
        direct = invoice.line_ids.filtered(lambda line: line.account_id == self.receivable)
        (direct | before.line_ids.filtered(lambda line: line.account_id == self.receivable) |
         later.line_ids.filtered(lambda line: line.account_id == self.receivable)).partner_id = partners[0]
        (direct | before.line_ids | later.line_ids).filtered(lambda line: line.account_id == self.receivable).reconcile()
        payment = self._entry(self.company, self.journal, '2041-05-01', self.other, self.receivable, 25)
        future = self._entry(self.company, self.journal, '2041-07-02', self.receivable, self.other, 15)
        payment_line = payment.line_ids.filtered(lambda line: line.account_id == self.receivable)
        future_line = future.line_ids.filtered(lambda line: line.account_id == self.receivable)
        future_line.partner_id = partners[1]
        (payment_line | future_line).reconcile()
        direct.date_maturity = '2041-06-15'
        engine = self.engine.with_context(baseer_gl_page_size=1)
        for basis in ('due_date', 'invoice_date'):
            for filters in ({}, {'partner_ids': partners.ids}):
                options = self._options(aging_basis=basis, **filters)
                report = engine._definition('aged_receivable')
                normalized = engine._normalize_options(report, options)
                expected = defaultdict(lambda: [Decimal(0)] * 7)
                for pid, _line, bucket, value in engine._aged_entries(normalized):
                    expected[pid][bucket] += value
                    expected[pid][6] += value
                self.assertEqual(dict(engine._aged_grouped(normalized)), dict(expected))
                batch = engine.get_partner_items_batch('aged_receivable', options)
                self.assertEqual(set(batch), set(expected))
                for pid, page in batch.items():
                    single = engine.get_ledger_lines('aged_receivable', options, pid)
                    self.assertEqual(page['items'], single['rows'])
                    self.assertEqual(page['has_more'], single['has_more'])
                    self.assertEqual(page['next_offset'], single['next_offset'])
                payload = engine._export_payload('aged_receivable', dict(options, unfold_all=True))
                for row in (row for row in payload['lines'] if row.get('foldable')):
                    single = engine.with_context(baseer_gl_export=True)._aged_page(normalized, row['partner_id'], 0, None)
                    self.assertEqual(row['ledger'], single)

    def test_aged_batch_query_count_does_not_grow_with_partners(self):
        engine = self.engine.with_context(baseer_gl_page_size=1)
        options = self._options()
        def add(index):
            partner = self.env['res.partner'].create({'name': 'Batch query %s' % index})
            move = self._entry(self.company, self.journal, '2041-04-01', self.receivable, self.other, 1)
            move.line_ids.filtered(lambda line: line.account_id == self.receivable).partner_id = partner
        def count():
            engine.get_partner_items_batch('aged_receivable', options)
            start = self.cr.sql_log_count
            engine.get_partner_items_batch('aged_receivable', options)
            return self.cr.sql_log_count - start
        add(0)
        small = count()
        for index in range(1, 12):
            add(index)
        large = count()
        self.assertLessEqual(large, small + 2, (small, large))
