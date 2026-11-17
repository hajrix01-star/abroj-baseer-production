from odoo.addons.baseer_report_engine.tests.common import EngineCase
from odoo.addons.point_of_sale.tests.common import CommonPosTest
from odoo.tests import tagged


class TobaccoReportCase(EngineCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Tobacco test', 'currency_id': cls.env.ref('base.SAR').id})
        cls.env.user.write({'company_ids': [(4, cls.company.id)]})

    def test_opening_and_manual_reconciliation(self):
        import base64
        import io
        import zipfile
        from odoo.service.model import call_kw

        company = self.company
        fee = self._account(company, '201021', 'liability_current')
        other = self._account(company, '101099', 'asset_current')
        journal = self._journal(company, 'TST')
        self._entry(company, journal, '2040-12-31', other, fee, 30)
        move = self._entry(company, journal, '2041-02-01', other, fee, 20)
        payload = self._engine(company).get_report('tobacco_service_fee', self._options())
        section = payload['tobacco_sections'][0]
        self.assertEqual(section['opening'], 30)
        self.assertEqual(section['movement'], 20)
        self.assertEqual(section['difference'], -20)
        self.assertIn(move.id, section['manual_move_ids'])
        self.assertEqual(payload['report']['report_kind'], 'tobacco')
        self.assertTrue(self._engine(company).export_xlsx('tobacco_service_fee', self._options())['content'])
        self.assertTrue(self._engine(company).export_pdf('tobacco_service_fee', self._options()))
        for lang in ('en_US', 'ar_001'):
            self.env['res.lang']._activate_lang(lang)
            self.env['ir.module.module']._load_module_terms(['baseer_report_engine_tobacco'], [lang], overwrite=True)
            localized = self._engine(company).with_context(lang=lang)
            payload = localized._export_payload('tobacco_service_fee', self._options())
            rows = payload['tobacco_sections'][0]['export_rows']
            self.assertIn(-20, [values[1] for values, kind in rows if len(values) == 2 and isinstance(values[1], (int, float))])
            xlsx = localized.export_xlsx('tobacco_service_fee', self._options())['content']
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(xlsx))) as archive:
                strings = archive.read('xl/sharedStrings.xml').decode()
                self.assertIn('Difference' if lang == 'en_US' else 'الفرق', strings)
                self.assertIn('Total for period' if lang == 'en_US' else 'إجمالي الفترة', strings)
            html, _ = self.env['ir.actions.report'].with_company(company).with_context(lang=lang, allowed_company_ids=[company.id])._render_qweb_html(
                'baseer_report_engine.report_pdf', docids=localized._definition('tobacco_service_fee').ids, data={'report_code': 'tobacco_service_fee', 'options': self._options()})
            self.assertIn(('Difference' if lang == 'en_US' else 'الفرق').encode(), html)
            self.assertIn(b'-20.00', html)
        action = self._engine(company).get_tobacco_source_action(self._options(), 'account.move', move.id)
        self.assertEqual((action['res_model'], action['res_id'], action['view_mode']), ('account.move', move.id, 'form'))
        ledger = self._engine(company).get_tobacco_ledger_action(self._options(), fee.id, company.id)
        self.assertEqual(ledger['context']['report_code'], 'general_ledger')
        self.assertEqual(ledger['context']['baseer_options']['unfolded_accounts'], [[fee.id, company.id]])
        engine = self._engine(company)
        call = lambda method, args: call_kw(engine, method, args, {'context': engine.env.context})
        self.assertEqual(call('get_report', ['tobacco_service_fee', self._options()])['tobacco_sections'][0]['difference'], -20)
        self.assertEqual(call('get_tobacco_source_action', [self._options(), 'account.move', move.id])['res_id'], move.id)
        self.assertEqual(call('get_tobacco_ledger_action', [self._options(), fee.id, company.id])['context']['report_code'], 'general_ledger')
        self.assertTrue(call('export_xlsx', ['tobacco_service_fee', self._options()])['content'])
        self.assertTrue(call('export_pdf', ['tobacco_service_fee', self._options()])['type'])

    def test_draft_accounting_option(self):
        company = self.company
        fee = self._account(company, '201021', 'liability_current')
        other = self._account(company, '101099', 'asset_current')
        journal = self._journal(company, 'TST')
        move = self._entry(company, journal, '2041-02-01', other, fee, 20, posted=False)
        engine = self._engine(company)
        posted = engine.get_report('tobacco_service_fee', self._options())['tobacco_sections'][0]
        included = engine.get_report('tobacco_service_fee', self._options(posted_only=False))['tobacco_sections'][0]
        self.assertEqual(posted['movement'], 0)
        self.assertEqual(included['difference'], -20)
        self.assertIn(move.id, included['manual_move_ids'])

    def test_menu_translation(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine_tobacco'], ['ar_001'], overwrite=True)
        menu = self.env.ref('baseer_report_engine_tobacco.menu_tobacco')
        self.assertEqual(menu.with_context(lang='ar_001').name, 'رسوم خدمة التبغ (جديد)')

    def test_account_discovery_and_company_sections(self):
        from odoo import Command

        company = self.company
        fee = self._account(company, '209001', 'liability_current')
        extra = self._account(company, '209002', 'liability_current')
        fallback = self._account(company, '201021', 'liability_current')
        group = self.env['account.tax.group'].create({
            'name': 'رسوم خدمة التبغ', 'company_id': company.id,
            'country_id': self.env.ref('base.sa').id,
        })
        tax = self.env['account.tax'].create({
            'name': 'Other name', 'type_tax_use': 'sale', 'tax_group_id': group.id,
            'country_id': self.env.ref('base.sa').id, 'amount_type': 'fixed',
            'amount': 25, 'company_id': company.id,
        })
        (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(
            lambda rep: rep.repartition_type == 'tax').account_id = fee
        self.env['ir.config_parameter'].sudo().set_param(
            'baseer_report_engine.tobacco_fee_accounts', str(extra.id))
        engine = self._engine(company)
        self.assertEqual(set(engine._tobacco_accounts(company).ids), set((fee | extra | fallback).ids))

        second = self.env['res.company'].create({'name': 'Second tobacco company',
                                                  'currency_id': self.env.ref('base.SAR').id})
        self.env.user.write({'company_ids': [Command.link(second.id)]})
        self._account(second, '201021', 'liability_current')
        sections = engine.with_context(allowed_company_ids=[company.id, second.id]).get_report(
            'tobacco_service_fee', self._options())['tobacco_sections']
        self.assertEqual({section['company_id'] for section in sections}, {company.id, second.id})


class TobaccoPosCase(EngineCase):
    def test_custom_formula_branches(self):
        # The formula tax is supplied by the optional account_tax_python addon;
        # the register deliberately does not depend on it.
        if 'formula' not in self.env['account.tax']._fields:
            self.skipTest('Install account_tax_python to exercise custom formula taxes')
        from uuid import uuid4
        from odoo import Command

        company = self.env.company
        company.write({'currency_id': self.env.ref('base.SAR').id, 'country_id': self.env.ref('base.sa').id})
        self.env['account.chart.template'].try_loading('generic_coa', company=company, install_demo=False)
        company.currency_id = self.env.ref('base.SAR')
        account = self._account(company, '201021', 'liability_current')
        group = self.env['account.tax.group'].create({'name': 'Tobacco service fee', 'company_id': company.id, 'country_id': company.account_fiscal_country_id.id})
        tax = self.env['account.tax'].create({'name': 'Tobacco service fee', 'type_tax_use': 'sale',
            'tax_group_id': group.id, 'country_id': company.account_fiscal_country_id.id,
            'amount_type': 'code', 'formula': 'max(base / 2.3, 25 * quantity)', 'company_id': company.id})
        (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(
            lambda rep: rep.repartition_type == 'tax').account_id = account
        product = self.env['product.product'].create({'name': 'Formula product', 'available_in_pos': True,
            'taxes_id': [Command.set(tax.ids)]})
        config = self.env['pos.config'].create({'name': 'Formula test', 'company_id': company.id})
        config.open_ui()
        session = config.current_session_id
        session.state = 'opened'
        for price, qty in [(230, 1), (10, 2), (230, -1)]:
            order = self.env['pos.order'].create({'company_id': company.id, 'session_id': session.id,
                'source': 'pos', 'amount_tax': 0, 'amount_total': 0, 'amount_paid': 0, 'amount_return': 0,
                'lines': [Command.create({'uuid': str(uuid4()), 'product_id': product.id,
                    'tax_ids': [Command.set(tax.ids)], 'qty': qty, 'price_unit': price,
                    'price_subtotal': price * qty, 'price_subtotal_incl': price * qty,
                    'full_product_name': product.name})]})
            order._compute_prices()
            order.write({'date_order': '2041-02-04 12:00:00', 'state': 'paid'})
        section = self._engine(company).get_report('tobacco_service_fee',
            self._options(date_from='2041-02-04', date_to='2041-02-04'))['tobacco_sections'][0]
        self.assertEqual(sorted(row['net'] for row in section['rows']), [-100, 50, 100])
        self.assertEqual(section['net'], 50)
        from odoo.service.model import call_kw
        engine = self._engine(company)
        opts = self._options(date_from='2041-02-04', date_to='2041-02-04')
        args = [opts, company.id, account.id, '2041-02-04']
        first = call_kw(engine, 'get_tobacco_day', args + [0, 2], {'context': engine.env.context})
        second = call_kw(engine, 'get_tobacco_day', args + [first['next_offset'], 2], {'context': engine.env.context})
        self.assertTrue(first['has_more'])
        self.assertFalse(second['has_more'])
        self.assertEqual(len(first['items']) + len(second['items']), 3)
        self.assertEqual(second['items'][-1]['cumulative'], 50)

    def test_native_pos_fee_and_riyadh_boundary(self):
        from uuid import uuid4
        from odoo import Command

        company = self.env.company
        company.write({'currency_id': self.env.ref('base.SAR').id, 'country_id': self.env.ref('base.sa').id})
        self.env['account.chart.template'].try_loading('generic_coa', company=company, install_demo=False)
        company.currency_id = self.env.ref('base.SAR')
        account = self._account(company, '201021', 'liability_current')
        group = self.env['account.tax.group'].create({'name': 'Tobacco service fee', 'company_id': company.id, 'country_id': company.account_fiscal_country_id.id})
        tax = self.env['account.tax'].create({'name': 'Tobacco service fee', 'type_tax_use': 'sale',
            'tax_group_id': group.id, 'country_id': company.account_fiscal_country_id.id, 'amount_type': 'fixed', 'amount': 25, 'company_id': company.id})
        (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(
            lambda rep: rep.repartition_type == 'tax').account_id = account
        product = self.env['product.product'].create({'name': 'Test product', 'available_in_pos': True,
            'list_price': 55, 'taxes_id': [Command.set(tax.ids)]})
        config = self.env['pos.config'].create({'name': 'Tobacco test', 'company_id': company.id})
        config.open_ui()
        session = config.current_session_id
        session.state = 'opened'
        for utc, state in [('2041-01-31 20:30:00', 'paid'), ('2041-01-31 21:30:00', 'paid'),
                           ('2041-01-31 20:45:00', 'draft'), ('2041-01-31 20:50:00', 'cancel')]:
            order = self.env['pos.order'].create({'company_id': company.id, 'session_id': session.id,
                'source': 'pos', 'amount_tax': 0, 'amount_total': 0, 'amount_paid': 0, 'amount_return': 0,
                'lines': [Command.create({'uuid': str(uuid4()), 'product_id': product.id,
                    'tax_ids': [Command.set(tax.ids)], 'qty': 1, 'price_unit': 55,
                    'price_subtotal': 55, 'price_subtotal_incl': 80, 'full_product_name': product.name})]})
            order._compute_prices()
            order.write({'date_order': utc, 'state': state})
        options = self._options(date_from='2041-01-31', date_to='2041-01-31')
        section = self._engine(company).get_report('tobacco_service_fee', options)['tobacco_sections'][0]
        self.assertEqual(len(section['rows']), 1)
        self.assertEqual(section['net'], 25)
        self.assertEqual(section['difference'], 25)
        self.assertIn(session.id, section['open_sessions'])
        action = self._engine(company).get_tobacco_source_action(options, 'pos.session', session.id)
        self.assertEqual((action['res_model'], action['res_id'], action['view_mode']), ('pos.session', session.id, 'form'))
        import base64, io, zipfile
        for show in (False, True):
            export_options = dict(options, show_products=show)
            payload = self._engine(company)._export_payload('tobacco_service_fee', export_options)
            rows = payload['tobacco_sections'][0]['export_rows']
            self.assertEqual(any('Test product × 1' in values for values, kind in rows), show)
            content = self._engine(company).export_xlsx('tobacco_service_fee', export_options)['content']
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(content))) as archive:
                self.assertEqual('Test product × 1' in archive.read('xl/sharedStrings.xml').decode(), show)
            html, _ = self.env['ir.actions.report'].with_company(company).with_context(allowed_company_ids=[company.id])._render_qweb_html(
                'baseer_report_engine.report_pdf', docids=self._engine(company)._definition('tobacco_service_fee').ids,
                data={'report_code': 'tobacco_service_fee', 'options': export_options})
            self.assertEqual('Test product × 1'.encode() in html, show)

        for qty, taxes in [(-1, tax), (1, self.env['account.tax'])]:
            order = self.env['pos.order'].create({'company_id': company.id, 'session_id': session.id,
                'source': 'pos', 'amount_tax': 0, 'amount_total': 0, 'amount_paid': 0, 'amount_return': 0,
                'lines': [Command.create({'uuid': str(uuid4()), 'product_id': product.id,
                    'tax_ids': [Command.set(taxes.ids)], 'qty': qty, 'price_unit': 55,
                    'price_subtotal': 55 * qty, 'price_subtotal_incl': 80 * qty,
                    'full_product_name': product.name})]})
            order._compute_prices()
            order.write({'date_order': '2041-02-03 12:00:00', 'state': 'paid'})
        refund_section = self._engine(company).get_report('tobacco_service_fee',
            self._options(date_from='2041-02-03', date_to='2041-02-03'))['tobacco_sections'][0]
        self.assertEqual(len(refund_section['rows']), 1)
        self.assertEqual(refund_section['net'], -25)
        self.assertEqual(refund_section['rows'][0]['type'], 'Refund')

        partner = self.env['res.partner'].create({'name': 'Invoice customer'})
        for move_type in ('out_invoice', 'out_refund'):
            move = self.env['account.move'].with_company(company).create({
                'move_type': move_type, 'partner_id': partner.id,
                'invoice_date': '2041-02-02', 'date': '2041-02-02',
                'invoice_line_ids': [Command.create({'product_id': product.id, 'quantity': 1,
                    'price_unit': 55, 'tax_ids': [Command.set(tax.ids)]})],
            })
            move.action_post()
        invoice_section = self._engine(company).get_report('tobacco_service_fee',
            self._options(date_from='2041-02-02', date_to='2041-02-02'))['tobacco_sections'][0]
        self.assertEqual({row['type'] for row in invoice_section['rows']}, {'Invoice', 'Credit Note'})
        self.assertEqual(sorted(row['net'] for row in invoice_section['rows']), [-25, 25])
        self.assertEqual(invoice_section['difference'], 0)

        # A batch of twenty orders should not cause a query per source line.
        def add_order():
            order = self.env['pos.order'].create({'company_id': company.id, 'session_id': session.id,
                'source': 'pos', 'amount_tax': 0, 'amount_total': 0, 'amount_paid': 0, 'amount_return': 0,
                'lines': [Command.create({'uuid': str(uuid4()), 'product_id': product.id,
                    'tax_ids': [Command.set(tax.ids)], 'qty': 1, 'price_unit': 55,
                    'price_subtotal': 55, 'price_subtotal_incl': 80, 'full_product_name': product.name})]})
            order._compute_prices()
            order.write({'date_order': '2041-02-04 12:00:00', 'state': 'paid'})

        engine = self._engine(company)
        batch_options = self._options(date_from='2041-02-04', date_to='2041-02-04')
        def query_count():
            self.env.flush_all()
            self.env.invalidate_all()
            start = self.cr.sql_log_count
            engine.get_report('tobacco_service_fee', batch_options)
            return self.cr.sql_log_count - start

        add_order()
        one = query_count()
        for _index in range(19):
            add_order()
        twenty = query_count()
        self.assertLessEqual(twenty, one + 30, (one, twenty))


@tagged('post_install', '-at_install')
class TobaccoClosedSessionCase(CommonPosTest, EngineCase):
    def test_posted_session_reconciles(self):
        from freezegun import freeze_time
        from odoo import Command

        company = self.env.company
        company.currency_id = self.env.ref('base.SAR')
        fee = self._account(company, '201021', 'liability_current')
        group = self.env['account.tax.group'].create({'name': 'Tobacco service fee',
            'company_id': company.id, 'country_id': company.account_fiscal_country_id.id})
        tax = self.env['account.tax'].create({'name': 'Tobacco service fee', 'type_tax_use': 'sale',
            'tax_group_id': group.id, 'country_id': company.account_fiscal_country_id.id,
            'amount_type': 'fixed', 'amount': 25, 'company_id': company.id})
        (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(
            lambda rep: rep.repartition_type == 'tax').account_id = fee
        product = self.ten_dollars_with_10_incl.product_variant_id
        product.taxes_id = [Command.set(tax.ids)]
        options = self._options(date_from='2041-02-04', date_to='2041-02-04')
        engine = self._engine(company)
        with freeze_time('2041-02-04 12:00:00'):
            self.pos_config_usd.open_ui()
            order, _refund = self.create_backend_pos_order({'line_data': [{'product_id': product.id}],
                'payment_data': [{'payment_method_id': self.bank_payment_method.id}]})
            session = order.session_id
            section = engine.get_report('tobacco_service_fee', options)['tobacco_sections'][0]
            self.assertEqual(section['difference'], 25)
            self.assertIn(session.id, section['open_sessions'])
            session.action_pos_session_closing_control()
            self.assertEqual(session.state, 'closed')
            self.assertEqual(session.move_id.state, 'posted')
            section = engine.get_report('tobacco_service_fee', options)['tobacco_sections'][0]
            self.assertEqual(section['net'], 25)
            self.assertEqual(section['movement'], 25)
            self.assertEqual(section['difference'], 0)
