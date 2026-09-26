from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from ..models.dashboard import _card
from ..models.executive import _validate_company_ids, _forecast, _coverage


class ExecutiveCardsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env.ref('baseer_sales_dashboard.dashboard_executive_center')

    def test_strict_company_input_and_authority(self):
        for invalid in (None, [], [True], ['1'], [1.0], [0], [1, 1], [1, 2, 3, 4]):
            with self.assertRaises(ValidationError):
                _validate_company_ids(invalid, [1, 2, 3, 4])
        with self.assertRaises(AccessError):
            _validate_company_ids([2], [1])
        _validate_company_ids([3, 1], [1, 2, 3])

    def test_separate_dashboard_and_home(self):
        sales = self.env.ref('baseer_sales_dashboard.dashboard_sales_summary')
        self.assertNotEqual(self.dashboard.id, sales.id)
        self.assertEqual(self.dashboard.baseer_dashboard_kind, 'executive_center')
        self.assertEqual(sales.baseer_dashboard_kind, 'sales_summary')
        self.assertEqual(self.env.ref('baseer_sales_dashboard.action_executive_home').params['dashboard_id'], self.dashboard.id)
        self.dashboard.is_published = False
        with self.assertRaises(AccessError):
            self.dashboard.get_baseer_executive_companies()

    def test_forecast_uses_unrounded_mean_and_guarded_coverage(self):
        data = {'days': [1, 2, 3], 'totals': dict(
            recorded_sales=Decimal('100'), complete_sales=Decimal('100'), operating_days=3,
            closed_days=0, incomplete_days=0, missing_days=0)}
        self.assertEqual(_forecast(data, 2, False)['value'], '166.67')
        self.assertFalse(_forecast(data, 2, True)['available'])
        for key in ('missing_days', 'incomplete_days'):
            data['totals'][key] = 1
            self.assertFalse(_forecast(data, 2, False)['available'])
            data['totals'][key] = 0
        data['totals']['operating_days'] = 0
        self.assertFalse(_forecast(data, 2, False)['available'])
        self.assertEqual(_coverage(data)['days'], 3)

    def test_change_zero_and_missing_are_distinct(self):
        change = self.dashboard._baseer_executive_change
        self.assertEqual(change(_card(0), _card(0), True)['direction'], 'flat')
        self.assertEqual(change(_card(12), _card(0), True)['direction'], 'new')
        result = change(_card(75), _card(100), True)
        self.assertEqual(result['display'], '-25.00%')
        self.assertEqual(result['amount_display'], '-25.00')
        self.assertFalse(change(_card(0), _card(None, False), True)['available'])

    def test_company_context_is_validated_and_replaced(self):
        sar = self.env.ref('base.SAR')
        company = self.env['res.company'].create({'name': 'EC permitted', 'currency_id': sar.id})
        other = self.env['res.company'].create({'name': 'EC forbidden', 'currency_id': sar.id})
        user = new_test_user(self.env, login='ec_reader', groups='base.group_user,point_of_sale.group_pos_user',
                             company_id=company.id, company_ids=[Command.set(company.ids)])
        dashboard = self.dashboard.with_user(user).with_context(
            allowed_company_ids=other.ids, active_test=False, arbitrary='discard')
        allowed = dashboard.get_baseer_executive_companies()
        self.assertEqual([row['id'] for row in allowed['companies']], company.ids)
        with self.assertRaises(AccessError):
            dashboard.get_baseer_executive_cards(other.ids)

        def capture(record, selected):
            self.assertEqual(record.env.company.id, company.id)
            self.assertEqual(record.env.context['allowed_company_ids'], company.ids)
            self.assertNotIn('arbitrary', record.env.context)
            self.assertNotIn('active_test', record.env.context)
            self.assertFalse(record.env.su)
            return {'company_id': selected.id}

        with patch.object(type(dashboard), '_baseer_executive_card', capture):
            self.assertEqual(dashboard.get_baseer_executive_cards(company.ids)['cards'],
                             [{'company_id': company.id}])

    def test_no_pos_permission_is_denied(self):
        user = new_test_user(self.env, login='ec_no_pos', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.dashboard.with_user(user).get_baseer_executive_companies()

    def test_authorized_selection_survives_different_header_company(self):
        sar = self.env.ref('base.SAR')
        companies = self.env['res.company'].create([
            {'name': 'EC header', 'currency_id': sar.id},
            {'name': 'EC selected', 'currency_id': sar.id},
        ])
        user = new_test_user(self.env, login='ec_multi', groups='base.group_user,point_of_sale.group_pos_user',
                             company_id=companies[0].id, company_ids=[Command.set(companies.ids)])
        dashboard = self.dashboard.with_user(user).with_context(allowed_company_ids=companies[0].ids)
        def capture(record, selected):
            self.assertEqual(record.env.company.id, selected.id)
            self.assertFalse(record.env.su)
            return {'id': selected.id}
        with patch.object(type(dashboard), '_baseer_executive_card', capture):
            self.assertEqual(dashboard.get_baseer_executive_cards(companies[1].ids)['cards'],
                             [{'id': companies[1].id}])
        self.dashboard.company_ids = [Command.set(companies[0].ids)]
        with self.assertRaises(AccessError):
            dashboard.get_baseer_executive_cards(companies[1].ids)

    def test_no_complete_day_produces_no_invented_zero(self):
        cls = type(self.dashboard)
        company = self.env['res.company'].create({'name': 'EC empty', 'currency_id': self.env.ref('base.SAR').id})
        with patch.object(cls, '_baseer_check_capacity'), patch.object(
                cls, '_baseer_aggregate_period', return_value={'days': []}):
            result = self.dashboard._baseer_executive_card(company)
        self.assertFalse(result['available'])
        self.assertIsNone(result['date'])
        self.assertIsNone(result['daily']['value'])
        self.assertIsNone(result['month_to_date']['value'])
        self.assertEqual(result['timeline'], [])

    def test_unsupported_currency_has_explicit_unavailable_card(self):
        company = self.env['res.company'].create({'name': 'EC unsupported', 'currency_id': self.env.ref('base.USD').id})
        with patch.object(type(self.dashboard), '_baseer_check_capacity') as source_read:
            result = self.dashboard._baseer_executive_card(company)
        source_read.assert_not_called()
        self.assertFalse(result['available'])
        self.assertEqual(result['reason'], 'unsupported_currency')
        self.assertIsNone(result['daily']['value'])

    def test_complete_card_equal_previous_period_and_fourteen_points(self):
        cutoff = date(2026, 3, 31)
        company = self.env['res.company'].create({'name': 'EC sample', 'currency_id': self.env.ref('base.SAR').id})
        def aggregate(record, company, first, last):
            days = []
            current = first
            while current <= last:
                days.append(dict(business_date=current, date_label=current.isoformat(),
                                 status='complete', has_sales=True, sales=100.0, customers=2))
                current += timedelta(days=1)
            return {'days': days, 'totals': dict(recorded_sales=Decimal(100 * len(days)),
                complete_sales=Decimal(100 * len(days)), operating_days=len(days), closed_days=0,
                incomplete_days=0, missing_days=0)}

        def metrics(record, company, first, last):
            data = aggregate(record, company, first, last)
            return {'data': data, 'has_sample': True, 'cards': {
                'sales': _card(data['totals']['recorded_sales']),
                'daily_sales': _card(100), 'daily_customers': _card(2)}}

        cls = type(self.dashboard)
        with patch('odoo.fields.Date.context_today', return_value=cutoff + timedelta(days=1)), \
                patch.object(cls, '_baseer_check_capacity'), \
                patch.object(cls, '_baseer_aggregate_period', aggregate), \
                patch.object(cls, '_baseer_metrics', metrics), \
                patch.object(cls, '_baseer_payment_performance', return_value={'rows': [], 'coverage': {'complete': True}}):
            result = self.dashboard._baseer_executive_card(company)
        self.assertEqual(result['date'], '2026-03-31')
        self.assertEqual(result['previous_period'], {'from': '2026-01-29', 'to': '2026-02-28'})
        # First day of April: March's latest complete day is not an April bar.
        self.assertEqual(result['timeline'], [])
        self.assertEqual(result['forecast']['value'], '3100.00')
        self.assertEqual(result['month_to_date']['value'], '3100.00')
        self.assertTrue(result['period_change']['available'])

        for today, expected_days in ((date(2026, 9, 2), [1]),
                                     (date(2026, 9, 12), list(range(1, 12))),
                                     (date(2026, 9, 15), list(range(1, 15))),
                                     (date(2026, 9, 21), list(range(7, 21))),
                                     (date(2027, 1, 2), [1])):
            with self.subTest(today=today), \
                    patch('odoo.fields.Date.context_today', return_value=today), \
                    patch.object(cls, '_baseer_check_capacity'), \
                    patch.object(cls, '_baseer_aggregate_period', aggregate), \
                    patch.object(cls, '_baseer_metrics', metrics), \
                    patch.object(cls, '_baseer_payment_performance', return_value={'rows': [], 'coverage': {'complete': True}}):
                result = self.dashboard._baseer_executive_card(company)
            self.assertEqual([int(point['label']) for point in result['timeline']], expected_days)
            self.assertTrue(all(point['date'].startswith(today.strftime('%Y-%m'))
                                for point in result['timeline']))
            self.assertEqual(result['daily']['value'], '100.00')
            self.assertTrue(result['daily_change']['available'])
