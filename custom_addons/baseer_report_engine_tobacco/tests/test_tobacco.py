from odoo.addons.baseer_report_engine.tests.common import EngineCase


class TobaccoReportCase(EngineCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Tobacco test', 'currency_id': cls.env.ref('base.SAR').id})
        cls.env.user.write({'company_ids': [(4, cls.company.id)]})

    def test_opening_and_manual_reconciliation(self):
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

    def test_menu_translation(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine_tobacco'], ['ar_001'], overwrite=True)
        menu = self.env.ref('baseer_report_engine_tobacco.menu_tobacco')
        self.assertEqual(menu.with_context(lang='ar_001').name, 'رسوم خدمة التبغ (جديد)')


class TobaccoPosCase(EngineCase):
    def test_native_pos_fee_and_riyadh_boundary(self):
        from uuid import uuid4
        from odoo import Command

        company = self.env.company
        company.write({'currency_id': self.env.ref('base.SAR').id, 'country_id': self.env.ref('base.sa').id})
        self.env['account.chart.template'].try_loading('generic_coa', company=company, install_demo=False)
        company.currency_id = self.env.ref('base.SAR')
        account = self._account(company, '201021', 'liability_current')
        group = self.env['account.tax.group'].create({'name': 'Tobacco service fee', 'company_id': company.id, 'country_id': self.env.ref('base.sa').id})
        tax = self.env['account.tax'].create({'name': 'Tobacco service fee', 'type_tax_use': 'sale',
            'tax_group_id': group.id, 'country_id': self.env.ref('base.sa').id, 'amount_type': 'fixed', 'amount': 25, 'company_id': company.id})
        (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(
            lambda rep: rep.repartition_type == 'tax').account_id = account
        product = self.env['product.product'].create({'name': 'Test product', 'available_in_pos': True,
            'list_price': 55, 'taxes_id': [Command.set(tax.ids)]})
        config = self.env['pos.config'].create({'name': 'Tobacco test', 'company_id': company.id})
        config.open_ui()
        session = config.current_session_id
        session.state = 'opened'
        for utc, state in [('2041-01-31 20:30:00', 'paid'), ('2041-01-31 21:30:00', 'paid'),
                           ('2041-01-31 20:45:00', 'draft')]:
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
