"""Real ORM sources and ordinary users; tests run only in an isolated Odoo DB."""
from datetime import date, datetime
from contextlib import ExitStack
from decimal import Decimal
from unittest.mock import patch

from odoo import Command, SUPERUSER_ID
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import new_test_user, tagged


@tagged('post_install', '-at_install')
class TestLeadershipOrm(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # AccountTestInvoicingCommon's actor is an accountant, not a Sales or
        # dashboard administrator. Elevation belongs only to rollback fixtures;
        # every report invocation below explicitly uses the ordinary reader.
        cls.fixture_env = cls.env(user=SUPERUSER_ID, context={
            **cls.env.context, 'allowed_company_ids': cls.env.company.ids,
        })
        cls.company = cls.fixture_env.company
        sar = cls.fixture_env.ref('base.SAR')
        sar.active = True
        cls.company.currency_id = sar
        cls.reader = new_test_user(
            cls.fixture_env, login='bwork_leadership_reader',
            groups='base.group_user,point_of_sale.group_pos_user,sales_team.group_sale_salesman_all_leads,account.group_account_invoice',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)],
            bwork_dashboard_view=True,
        )
        cls.service = cls.env['baseer.bchat.service'].with_user(cls.reader).with_context(
            allowed_company_ids=cls.company.ids, tz='Asia/Riyadh')
        cls.partner = cls.fixture_env['res.partner'].create({
            'name': 'BWork real supplier/customer',
            'property_account_receivable_id': cls.company_data['default_account_receivable'].id,
            'property_account_payable_id': cls.company_data['default_account_payable'].id,
        })
        cls.product = cls.fixture_env['product.product'].create({
            'name': 'BWork service', 'type': 'service', 'invoice_policy': 'order',
            'list_price': 115, 'taxes_id': [Command.clear()],
            'property_account_income_id': cls.company_data['default_account_revenue'].id,
            'property_account_expense_id': cls.company_data['default_account_expense'].id,
        })

    def setUp(self):
        super().setUp()
        self.assertFalse(self.service.env.su)
        self.assertFalse(self.reader.with_user(self.reader).has_group('base.group_system'))
        clock = patch('odoo.fields.Datetime.now', return_value=datetime(2026, 10, 19, 9))
        clock.start()
        self.addCleanup(clock.stop)
        local_date = patch('odoo.fields.Date.context_today', return_value=date(2026, 10, 19))
        local_date.start()
        self.addCleanup(local_date.stop)

    def _selection(self, month='2026-10', company=None):
        first = date.fromisoformat(month + '-01')
        from ..contracts import month_end
        return {'company_id': (company or self.company).id, 'month': month,
                'period': 'month', 'first': first, 'last': month_end(first), 'calendar_first': first}

    def _sale_invoice(self, price=115, day='2026-10-02'):
        sale = self.fixture_env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [Command.create({'product_id': self.product.id,
                'product_uom_qty': 1, 'price_unit': price, 'tax_ids': [Command.clear()]})],
        })
        sale.action_confirm()
        invoice = sale._create_invoices()
        invoice.invoice_date = day
        invoice.action_post()
        return invoice

    def _bill(self, price=23, move_type='in_invoice'):
        bill = self.fixture_env['account.move'].create({
            'move_type': move_type, 'partner_id': self.partner.id,
            'invoice_date': '2026-10-02',
            'invoice_line_ids': [Command.create({'product_id': self.product.id,
                'quantity': 1, 'price_unit': price, 'tax_ids': [Command.clear()],
                'account_id': self.company_data['default_account_expense'].id})],
        })
        bill.action_post()
        return bill

    def test_actual_sales_supplier_credit_parity_and_no_goal_writes(self):
        invoice = self._sale_invoice()
        bill, credit = self._bill(), self._bill(3, 'in_refund')
        target = self.fixture_env['baseer.heat.calendar.target'].create({
            'company_id': self.company.id, 'year': 2026, 'month': 10,
            'weekday': 4, 'target_amount': 100,
        })
        before = target.read(['target_amount', 'write_date'])
        target_ids = self.fixture_env['baseer.heat.calendar.target'].search([]).ids
        with (patch.object(type(target), 'create', side_effect=AssertionError('No target create')),
              patch.object(type(target), 'write', side_effect=AssertionError('No target write'))):
            payload = self.service._leadership(self._selection())
        canonical = self.env.ref('baseer_sales_dashboard.dashboard_sales_summary').with_user(
            self.reader).with_context(allowed_company_ids=self.company.ids).get_baseer_sales_metrics(
                {'native': {'type': 'range', 'from': '2026-10-01', 'to': '2026-10-31'}})
        self.assertEqual(payload['overview']['sales']['value'], canonical['cards']['sales']['value'])
        self.assertEqual(Decimal(payload['overview']['sales']['value']), Decimal(str(invoice.amount_total_signed)))
        self.assertEqual(Decimal(payload['overview']['spending']['value']),
                         -Decimal(str(bill.amount_total_signed)) - Decimal(str(credit.amount_total_signed)))
        self.assertEqual(payload['overview']['difference']['value'], '95.00')
        self.assertIn('supplier', payload['overview']['spending_scope'].lower())
        self.assertEqual(payload['calendar']['days'][1]['sales']['value'], '115.00')
        self.assertEqual(payload['calendar']['days'][1]['target']['value'], '100.00')
        self.assertEqual(target.read(['target_amount', 'write_date']), before)
        self.assertEqual(self.fixture_env['baseer.heat.calendar.target'].search([]).ids, target_ids)

    def test_options_switch_revision_source_acl_and_foreign_company(self):
        options = self.service._leadership_options()
        self.assertTrue(options['can_view'])
        self.assertEqual(options['companies'], [{'id': self.company.id, 'name': self.company.name}])
        revision = self.reader.bchat_permission_revision
        self.reader.write({'bwork_dashboard_view': False})
        self.assertGreater(self.reader.bchat_permission_revision, revision)
        self.assertFalse(self.service._leadership_options()['can_view'])
        with self.assertRaises(AccessError):
            self.service._leadership(self._selection())
        with self.assertRaises(AccessError):
            self.reader.with_user(self.reader).write({'bwork_dashboard_view': True})
        self.reader.write({'bwork_dashboard_view': True})
        foreign = self.fixture_env['res.company'].create({'name': 'BWork inaccessible', 'currency_id': self.company.currency_id.id})
        with self.assertRaises(AccessError):
            self.service._leadership(self._selection(company=foreign))
        insufficient = new_test_user(self.fixture_env, login='bwork_no_account',
            groups='base.group_user,point_of_sale.group_pos_user',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
            bwork_dashboard_view=True)
        with self.assertRaises(AccessError):
            self.service.with_user(insufficient)._leadership_options()

    def test_unpublished_or_group_scoped_dashboard_is_denied(self):
        dashboard = self.fixture_env.ref('baseer_sales_dashboard.dashboard_sales_summary')
        dashboard.is_published = False
        with self.assertRaises(AccessError):
            self.service._leadership_options()
        dashboard.is_published = True
        dashboard.group_ids = [Command.set(self.env.ref('base.group_system').ids)]
        with self.assertRaises(AccessError):
            self.service._leadership_options()

    def test_history_does_not_redefine_current_month_and_comparison_is_completed(self):
        self._sale_invoice(115, '2026-10-02')
        self._sale_invoice(50, '2026-09-02')
        self._sale_invoice(999, '2026-10-19')
        payload = self.service._leadership(self._selection('2026-09'))
        current = payload['overview']['current_month']
        self.assertEqual(current['month'], '2026-10')
        self.assertEqual(current['to'], '2026-10-18')
        self.assertEqual(current['sales']['value'], '115.00')
        self.assertEqual(current['previous_sales']['value'], '50.00')
        self.assertFalse(current['forecast']['available'])  # missing daily coverage
        self.assertFalse(current['sales_change']['available'])

    def test_multi_company_target_requires_even_no_sales_company(self):
        # The arithmetic seam consumes real central heat RPC rows in the parity
        # test above; here isolate the all-company no-sales target boundary.
        def payload(target):
            return {'weeks': [[{'date': f'2026-10-{day:02d}', 'day': day,
                'weekday': date(2026, 10, day).weekday(), 'status': 'missing',
                'status_label': 'No entry', 'has_sales': False, 'sales_value': None,
                'target_value': target, 'basis_value': target,
                'basis_kind': 'target' if target else 'none'} for day in range(1, 32)]]}
        calendar = self.service._leadership_calendar(date(2026, 10, 1),
            [payload('100.00'), payload(None)], date(2026, 10, 19), weekdays=True)
        self.assertFalse(calendar['days'][0]['target']['available'])
        self.assertEqual(calendar['days'][0]['heat_level'], 'neutral')
        self.assertEqual(calendar['days'][0]['basis_kind'], 'none')
        calendar = self.service._leadership_calendar(date(2026, 10, 1),
            [payload('100.00'), payload('50.00')], date(2026, 10, 19))
        self.assertEqual(calendar['days'][0]['target']['value'], '150.00')

    def test_real_central_all_company_goals_do_not_omit_no_sales_company(self):
        self._sale_invoice()
        other = self.fixture_env['res.company'].create({'name': 'BWork no sales company',
                                                'currency_id': self.company.currency_id.id})
        self.reader.company_ids = [Command.set((self.company | other).ids)]
        Target = self.fixture_env['baseer.heat.calendar.target']
        Target.create({'company_id': self.company.id, 'year': 2026, 'month': 10,
                       'weekday': 4, 'target_amount': 100})
        selection = self._selection()
        selection['company_id'] = None
        result = self.service._leadership(selection)
        self.assertEqual(len(result['companies']), 2)
        self.assertFalse(result['calendar']['days'][1]['target']['available'])
        second = Target.with_context(allowed_company_ids=(self.company | other).ids).create({
            'company_id': other.id, 'year': 2026, 'month': 10,
            'weekday': 4, 'target_amount': 50})
        result = self.service._leadership(selection)
        self.assertEqual(result['calendar']['days'][1]['target']['value'], '150.00')
        self.assertEqual(result['calendar']['days'][1]['heat_level'], 'neutral')
        second.active = False
        result = self.service._leadership(selection)
        self.assertFalse(result['calendar']['days'][1]['target']['available'])

    def test_combined_capacity_counts_draft_summaries_before_any_materialization(self):
        other = self.fixture_env['res.company'].create({'name': 'BWork budget company',
                                                'currency_id': self.company.currency_id.id})
        self.reader.company_ids = [Command.set((self.company | other).ids)]
        per_company = []
        for company in self.company | other:
            scoped, reports = self.service._leadership_reports(company)
            per_company.append((company, scoped, reports))
        plan = self.service._leadership_plan(self._selection(), date(2026, 10, 19))
        Summary = type(self.env['baseer.pos.summary'])
        with ExitStack() as stack:
            count = stack.enter_context(patch.object(Summary, 'search_count', return_value=60000))
            for model in ('baseer.pos.closure', 'pos.order', 'account.move',
                          'baseer.pos.summary.allocation', 'pos.payment'):
                stack.enter_context(patch.object(type(self.env[model]), 'search_count', return_value=0))
            stack.enter_context(patch.object(type(per_company[0][2]['sales']),
                '_baseer_check_capacity', side_effect=AssertionError('Must fail combined budget first')))
            with self.assertRaises(ValidationError):
                self.service._leadership_preflight(per_company, plan)
        self.assertEqual(count.call_count, 2)
        for call in count.call_args_list:
            self.assertFalse(any(isinstance(term, tuple) and term[0] == 'state'
                                 for term in call.args[0]))

    def test_complete_zero_days_belong_to_daily_mean_but_not_weekday_average(self):
        def payload():
            return {'weeks': [[{'date': f'2026-10-{day:02d}', 'day': day,
                'weekday': date(2026, 10, day).weekday(), 'status': 'complete' if day <= 7 else 'missing',
                'status_label': 'Complete' if day <= 7 else 'No entry',
                'has_sales': day <= 7, 'sales_value': ('0.00' if day == 1 else '70.00') if day <= 7 else None,
                'target_value': None, 'basis_value': None, 'basis_kind': 'none'} for day in range(1, 32)]]}
        calendar = self.service._leadership_calendar(date(2026, 10, 1), [payload()],
                                                     date(2026, 10, 19), weekdays=True)
        samples, complete = self.service._leadership_observations(calendar, (date(2026, 10, 1), date(2026, 10, 7)))
        self.assertTrue(complete)
        self.assertEqual(len(samples), 7)
        self.assertEqual(sum(samples) / Decimal(len(samples)), Decimal('60.00'))
        thursday = next(row for row in calendar['weekdays'] if row['weekday'] == 3)
        self.assertEqual(thursday['sample_count'], 0)
        self.assertFalse(thursday['average']['available'])

    def test_headline_heat_disagreement_fails_closed_including_future_money(self):
        from ..contracts import amount
        calendars = {date(2026, 10, 1): {'days': [
            {'date': '2026-10-18', 'sales': amount(None), 'status': 'missing'},
            {'date': '2026-10-19', 'sales': amount('50.00'), 'status': 'incomplete'},
            {'date': '2026-10-20', 'sales': amount('100.00'), 'status': 'incomplete'},
        ]}}
        bounds = date(2026, 10, 18), date(2026, 10, 20)
        self.service._leadership_reconcile(calendars, bounds, Decimal('150.00'))
        with self.assertRaises(ValidationError):
            self.service._leadership_reconcile(calendars, bounds, Decimal('150.01'))
        with self.assertRaises(ValidationError):
            self.service._leadership_reconcile(calendars,
                (date(2026, 10, 17), date(2026, 10, 20)), Decimal('150.00'))

    def test_company_and_total_source_caps_fail_before_reports(self):
        from ..models.leadership import LeadershipService
        selection = self._selection()
        with patch('odoo.addons.baseer_bwork_dashboard.models.leadership.MAX_COMPANIES', 0):
            with self.assertRaises(ValidationError):
                self.service._leadership(selection)
        with patch('odoo.addons.baseer_bwork_dashboard.models.leadership.MAX_SOURCE_ROWS', 0), \
                patch.object(LeadershipService, '_leadership_sales', side_effect=AssertionError('Materialized before budget')):
            self._sale_invoice()
            with self.assertRaises(ValidationError):
                self.service._leadership(selection)
