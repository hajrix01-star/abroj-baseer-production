"""Actual ORM parity with native Sales invoices/POS in the isolated test DB.

Reuse source-fixture helpers, without inheriting or rerunning the canonical suite.
The approval and native payment hooks execute only in TransactionCase rollback.
"""
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.baseer_sales_dashboard.tests import test_unified_sales as source_fixtures
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import new_test_user, tagged

from . import test_heat_pos as pos_fixtures


@tagged('post_install', '-at_install')
class TestHeatUnifiedSales(AccountTestInvoicingCommon):
    _sale = source_fixtures.TestUnifiedSales._sale
    _invoice = source_fixtures.TestUnifiedSales._invoice
    _pos = source_fixtures.TestUnifiedSales._pos
    _approved_manual_fixture = source_fixtures.TestUnifiedSales._approved_manual_fixture
    _insert = classmethod(pos_fixtures.HeatPosCase._insert.__func__)
    _session = classmethod(pos_fixtures.HeatPosCase._session.__func__)
    _order = pos_fixtures.HeatPosCase._order
    _summary = pos_fixtures.HeatPosCase._summary
    NOW = datetime(2026, 10, 20, 9)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sar = cls.env.ref('base.SAR')
        sar.active = True
        cls.company = cls.env.company
        cls.company.currency_id = sar
        cls.env.user.group_ids |= (cls.env.ref('point_of_sale.group_pos_manager')
                                  | cls.env.ref('sales_team.group_sale_manager'))
        cls.dashboard = cls.env.ref('baseer_sales_dashboard.dashboard_sales_summary')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Heat unified actual customer',
            'property_account_receivable_id': cls.company_data['default_account_receivable'].id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Heat unified service', 'type': 'service', 'invoice_policy': 'order',
            'available_in_pos': True, 'list_price': 100, 'taxes_id': [Command.clear()],
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
        })
        cls.unified_deposit_product = cls.product
        cls.method = cls.env['pos.payment.method'].create({
            'name': 'Heat unified bank', 'company_id': cls.company.id,
            'journal_id': cls.company_data['default_journal_bank'].id,
            'receivable_account_id': cls.company_data['default_account_receivable'].id,
            'outstanding_account_id': cls.company_data['default_account_receivable'].id,
        })
        cls.config = cls.env['pos.config'].create({
            'name': 'Heat unified ordinary POS', 'company_id': cls.company.id,
            'journal_id': cls.company_data['default_journal_sale'].id,
            'invoice_journal_id': cls.company_data['default_journal_sale'].id,
            'payment_method_ids': [Command.set(cls.method.ids)],
            'down_payment_product_id': cls.product.id,
        })
        cls.config.open_ui()
        cls.session = cls.config.current_session_id
        cls.session.set_opening_control(0, 'Heat unified fixture')
        cls.session.start_at = datetime(2026, 10, 1, 15)
        cls.summary_config = cls._insert('pos.config', {
            'name': 'Heat unified summary bridge', 'company_id': cls.company.id,
            'currency_id': sar.id, 'picking_type_id': cls.config.picking_type_id.id,
            'baseer_summary_only': True, 'iface_tax_included': 'total',
            'picking_policy': 'direct', 'active': True})
        cls.heat = cls._heat_for_company(cls.company)

    @classmethod
    def _heat_for_company(cls, company):
        return cls.env['spreadsheet.dashboard'].create({
            'name': 'Heat unified parity',
            'dashboard_group_id': cls.env.ref(
                'spreadsheet_dashboard.spreadsheet_dashboard_group_sales').id,
            'baseer_dashboard_kind': 'sales_heat_calendar', 'is_published': True,
            'company_ids': [Command.set(company.ids)],
        }).with_company(company).with_context(allowed_company_ids=company.ids, lang='en_US')

    def _days(self, heat=None, now=None):
        with patch('odoo.fields.Datetime.now', return_value=now or self.NOW):
            payload = (heat if heat is not None else self.heat).get_baseer_heat_calendar('2026-10')
        return payload, {day['date']: day for week in payload['weeks'] for day in week if day}

    def _assert_headline_parity(self, heat=None, summary_dashboard=None):
        payload, days = self._days(heat=heat)
        dashboard = summary_dashboard if summary_dashboard is not None else self.dashboard
        headline = dashboard.get_baseer_sales_metrics({
            'preset': 'custom', 'date_from': '2026-10-01', 'date_to': '2026-10-31',
        })['cards']['sales']['value']
        self.assertEqual(sum((Decimal(day['sales_value']) for day in days.values()
                              if day['sales_value'] is not None), Decimal('0')), Decimal(headline))
        for day in days.values():
            daily = dashboard.get_baseer_sales_metrics({
                'preset': 'custom', 'date_from': day['date'], 'date_to': day['date'],
            })['cards']['sales']['value']
            self.assertEqual(Decimal(day['sales_value'] or '0'), Decimal(daily))
        return payload, days

    def test_all_four_sources_signed_credits_and_daily_headline_parity(self):
        self._summary('2026-10-02', customers=7)
        self._pos(price=40, guests=2)
        restaurant = self.config.copy({'name': 'Heat restaurant', 'module_pos_restaurant': True})
        restaurant.open_ui()
        session = restaurant.current_session_id
        session.set_opening_control(0, 'Heat restaurant fixture')
        session.start_at = datetime(2026, 10, 1, 15)
        self._pos(price=60, guests=3, session=session)
        invoice = self._invoice(self._sale())
        credit = invoice._reverse_moves([{'date': '2026-10-03', 'invoice_date': '2026-10-03'}], cancel=False)
        credit.action_post()
        _, days = self._assert_headline_parity()
        self.assertEqual(days['2026-10-01']['source_kinds'], ['pos', 'restaurant'])
        self.assertEqual(days['2026-10-02']['source_kinds'], ['manual', 'sales'])
        self.assertEqual(days['2026-10-02']['sales_value'], '215.00')
        self.assertEqual(days['2026-10-03']['sales_value'], '-100.00')
        for key in ('2026-10-02', '2026-10-03'):
            self.assertIsNone(days[key]['customers_value'])
            self.assertEqual(days[key]['customers_display'], '—')
        self.assertEqual(days['2026-10-02']['status'], 'complete')
        self.assertEqual(len(days['2026-10-02']['source_actions']), 2)

    def test_native_pos_invoice_and_global_reversal_chain_are_not_duplicated(self):
        order = self._pos(self._sale(), price=100, invoice=True, guests=1)
        self.assertTrue(order.account_move)
        credit = order.account_move._reverse_moves([
            {'date': '2026-09-30', 'invoice_date': '2026-09-30'}], cancel=False)
        credit.action_post()
        restored = credit._reverse_moves([
            {'date': '2026-10-04', 'invoice_date': '2026-10-04'}], cancel=False)
        restored.action_post()
        _, days = self._assert_headline_parity()
        self.assertEqual(days['2026-10-01']['sales_value'], '100.00')
        self.assertIsNone(days['2026-10-04']['sales_value'])

    def test_native_summary_approval_date_and_bridge_count_once(self):
        dashboard, summary = self._approved_manual_fixture()
        heat = self._heat_for_company(summary.company_id)
        _, days = self._assert_headline_parity(heat=heat, summary_dashboard=dashboard)
        self.assertEqual(days['2026-10-02']['sales_value'], '115.00')
        self.assertEqual(days['2026-10-02']['source_kinds'], ['manual'])

    def test_future_invoice_is_preserved_with_target_but_never_evaluated(self):
        self._invoice(self._sale(), date='2026-10-25')
        self.env['baseer.heat.calendar.target'].create({
            'company_id': self.company.id, 'year': 2026, 'month': 10,
            'weekday': date(2026, 10, 25).weekday(), 'target_amount': 200,
        })
        payload, days = self._assert_headline_parity()
        future = days['2026-10-25']
        self.assertEqual(future['sales_value'], '100.00')
        self.assertEqual(future['status'], 'incomplete')
        self.assertEqual(future['target_value'], '200.00')
        self.assertIsNone(future['ratio_value'])
        self.assertTrue(all(item['sample_count'] == 0 for item in payload['weekdays']))

    def test_pos_group_does_not_grant_sales_source_acl(self):
        reader = new_test_user(self.env, login='heat_unified_insufficient',
            groups='base.group_user,point_of_sale.group_pos_user',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)])
        with self.assertRaises(AccessError):
            self.heat.with_user(reader).get_baseer_heat_calendar('2026-10')

    def test_real_invoice_targets_use_only_active_exact_scope_without_changing_sales(self):
        self._invoice(self._sale(), date='2026-10-02')
        self._invoice(self._sale(), date='2026-10-03')
        Target = self.env['baseer.heat.calendar.target']
        Target.create({'company_id': self.company.id, 'year': 2026, 'month': 10,
                       'weekday': 4, 'target_amount': 200})
        Target.create({'company_id': self.company.id, 'year': 2026, 'month': 10,
                       'weekday': 5, 'target_amount': 999, 'active': False})
        Target.create({'company_id': self.company.id, 'year': 2026, 'month': 9,
                       'weekday': 5, 'target_amount': 888})
        _, days = self._assert_headline_parity()
        self.assertEqual(days['2026-10-02']['target_value'], '200.00')
        self.assertEqual(days['2026-10-02']['ratio_value'], '50.00')
        self.assertEqual(days['2026-10-02']['basis_kind'], 'target')
        self.assertIsNone(days['2026-10-03']['target_value'])
        self.assertEqual(days['2026-10-03']['basis_kind'], 'none')
        self.assertEqual(days['2026-10-02']['sales_value'], '100.00')
        self.assertEqual(days['2026-10-03']['sales_value'], '100.00')
        _, current = self._days(now=datetime(2026, 10, 2, 9))
        self.assertEqual(current['2026-10-02']['status'], 'incomplete')
        self.assertIsNone(current['2026-10-02']['ratio_value'])

    def test_full_window_guards_run_before_reader_and_report_subtotal_must_match(self):
        model = type(self.heat)
        calls = []
        access, capacity = model._baseer_unified_access, model._baseer_check_capacity
        def checked_access(record):
            calls.append('access')
            return access(record)
        def checked_capacity(record, company, periods):
            calls.append(('capacity', periods))
            return capacity(record, company, periods)
        def unavailable(*args, **kwargs):
            self.assertIn('access', calls)
            self.assertIn(('capacity', [(date(2026, 8, 6), date(2026, 10, 31))]), calls)
            raise ValidationError('Fixture stops before materialization')
        with patch.object(model, '_baseer_unified_access', checked_access), patch.object(
                model, '_baseer_check_capacity', checked_capacity), patch.object(
                model, '_baseer_unified_period', unavailable), self.assertRaises(ValidationError):
            self._days()
        report_model = type(self.env['baseer.pos.daily.report'])
        aggregate = report_model._aggregate_days
        def inconsistent(report, company, first, last):
            result = aggregate(report, company, first, last)
            result['totals']['recorded_sales'] += Decimal('0.01')
            return result
        with patch.object(report_model, '_aggregate_days', inconsistent), self.assertRaises(ValidationError):
            self._days()
