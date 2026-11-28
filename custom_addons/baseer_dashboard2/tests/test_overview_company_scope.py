from datetime import date

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestOverviewCompanyScope(TransactionCase):
    """Dashboard company tabs must work even when the navbar switcher omits that company.

    Production reproduced this on دوحة المستهلك: the user belongs to the company (so the tab
    appears) but allowed_company_ids from the web client only had أرز/الشامي. Overview then
    raised AccessError on account.move inside _tooltip_purchase_months, and the UI showed
    only «Odoo Server Error».
    """

    def setUp(self):
        super().setUp()
        self.company_a = self.env.company
        self.company_b = self.env['res.company'].create({'name': 'Doha-like test company'})
        self.env['ir.config_parameter'].set_param(
            'baseer_dashboard2.company_map',
            '%s:One,%s:Two,54:Forbidden,56:Forbidden' % (self.company_a.id, self.company_b.id),
        )
        self.user = new_test_user(
            self.env, login='bd2_scope_reader', groups='account.group_account_readonly',
            company_id=self.company_a.id,
            company_ids=[(6, 0, [self.company_a.id, self.company_b.id])],
        )
        expense = self.env['account.account'].with_company(self.company_b).create({
            'code': 'D2SCE', 'name': 'Food purchase', 'account_type': 'expense',
            'company_ids': [(6, 0, [self.company_b.id])]})
        payable = self.env['account.account'].with_company(self.company_b).create({
            'code': 'D2SCP', 'name': 'Payable', 'account_type': 'liability_payable', 'reconcile': True,
            'company_ids': [(6, 0, [self.company_b.id])]})
        partner = self.env['res.partner'].create({'name': 'Scope supplier', 'company_id': self.company_b.id})
        journal = self.env['account.journal'].create({
            'name': 'Scope purchase', 'code': 'D2SCP', 'type': 'purchase', 'company_id': self.company_b.id})
        settings = self.env['baseer.dashboard2.settings'].search([('company_id', '=', self.company_b.id)], limit=1)
        if not settings:
            settings = self.env['baseer.dashboard2.settings'].create({'company_id': self.company_b.id})
        settings.pos_cutover_date = False
        settings.food_purchase_account_ids = expense
        today = fields.Date.context_today(self)
        bill_date = date(today.year - 1, 6, 15)
        bill = self.env['account.move'].with_company(self.company_b).create({
            'move_type': 'in_invoice', 'journal_id': journal.id, 'partner_id': partner.id,
            'company_id': self.company_b.id, 'invoice_date': bill_date,
            'invoice_line_ids': [(0, 0, {'name': 'Food', 'account_id': expense.id, 'quantity': 1, 'price_unit': 250})]})
        bill.action_post()
        self.service = self.env['baseer.dashboard2.service'].with_user(self.user).with_context(
            allowed_company_ids=[self.company_a.id])

    def test_overview_yesterday_for_other_company_is_not_access_error(self):
        result = self.service.get_section('overview', {
            'company_key': str(self.company_b.id), 'period': {'mode': 'yesterday'},
            'timeline_mode': 'monthly',
        })
        self.assertTrue(result['available'])
        self.assertEqual(result['cards']['mode'], 'yesterday')
        self.assertIn('period_sales', result['cards'])
        self.assertIn('net', result['cards'])

    def test_overview_today_month_and_all_for_other_company(self):
        for period in ({'mode': 'today'}, {'mode': 'month'}, {'mode': 'yesterday'}):
            if period.get('mode') == 'month':
                period['month'] = fields.Date.context_today(self).strftime('%Y-%m')
            result = self.service.get_section('overview', {
                'company_key': str(self.company_b.id), 'period': period, 'timeline_mode': 'monthly'})
            self.assertTrue(result['available'], period)

        combined = self.service.get_section('overview', {
            'company_key': 'all', 'period': {'mode': 'yesterday'}, 'timeline_mode': 'monthly'})
        self.assertTrue(combined['available'])

    def test_pnl_tax_inclusive_for_other_company(self):
        result = self.service.get_section('pnl', {
            'company_key': str(self.company_b.id),
            'period': {'mode': 'yesterday'},
            'pnl_view': 'month',
            'tax_inclusive': True,
        })
        self.assertTrue(result['available'])
        self.assertEqual(result.get('basis'), 'inclusive')

        exclusive = self.service.get_section('pnl', {
            'company_key': str(self.company_b.id),
            'period': {'mode': 'yesterday'},
            'pnl_view': 'month',
            'tax_inclusive': False,
        })
        self.assertTrue(exclusive['available'])
        self.assertEqual(exclusive.get('basis'), 'exclusive')
