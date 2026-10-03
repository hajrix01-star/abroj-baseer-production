"""POS fixtures exist only inside TransactionCase and never post accounting.

Direct SQL deliberately bypasses POS create/payment/session closing hooks: this
suite tests the read-only projection of persisted orders, not POS posting.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import SQL

from ..models.executive import _resolve_period, _utc_at, MAX_ORDERS


@tagged('post_install', '-at_install')
class ExecutivePosCase(TransactionCase):
    NOW = datetime(2026, 10, 4, 6)  # 09:00 Riyadh, October 3 ended.

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env.ref('baseer_sales_dashboard.dashboard_executive_center')
        cls.company = cls.env['res.company'].create({
            'name': 'EC POS | نقاط البيع', 'currency_id': cls.env.ref('base.SAR').id})
        cls.other = cls.env['res.company'].create({
            'name': 'EC other', 'currency_id': cls.env.ref('base.SAR').id})
        cls.reader = new_test_user(cls.env, login='ec_pos_reader',
            groups='base.group_user,point_of_sale.group_pos_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.env.flush_all()
        picking = cls.env['stock.picking.type'].search([('code', '=', 'outgoing')], limit=1)
        if not picking:
            picking = cls.env['stock.picking.type'].create({'name': 'EC fixture', 'code': 'outgoing', 'sequence_code': 'EC'})
        cls.config = cls._insert('pos.config', {
            'name': 'نقطة | Till', 'company_id': cls.company.id,
            'currency_id': cls.env.ref('base.SAR').id, 'picking_type_id': picking.id,
            'iface_tax_included': 'total', 'picking_policy': 'direct', 'active': True})
        cls.other_config = cls._insert('pos.config', {
            'name': 'Forbidden till', 'company_id': cls.other.id,
            'currency_id': cls.env.ref('base.SAR').id, 'picking_type_id': picking.id,
            'iface_tax_included': 'total', 'picking_policy': 'direct', 'active': True})
        cls.session_a = cls._session('EC A', cls.config)
        cls.session_b = cls._session('EC B', cls.config, state='closed')
        cls.other_session = cls._session('EC other', cls.other_config)

    @classmethod
    def _insert(cls, model, values):
        cls.env.cr.execute(SQL('INSERT INTO %s (%s) VALUES (%s) RETURNING id',
            SQL.identifier(cls.env[model]._table),
            SQL(', ').join(SQL.identifier(key) for key in values),
            SQL(', ').join(SQL('%s', value) for value in values.values())))
        return cls.env[model].browse(cls.env.cr.fetchone()[0])

    @classmethod
    def _session(cls, name, config, state='opened'):
        return cls._insert('pos.session', {
            'name': name, 'config_id': config.id, 'user_id': cls.env.uid, 'state': state})

    def _order(self, local, amount, session=None, state='paid', company=None):
        session = session or self.session_a
        company = company or self.company
        stamp = datetime.fromisoformat(local) - timedelta(hours=3)
        return self._insert('pos.order', {
            'name': 'EC fixture', 'date_order': stamp, 'state': state,
            'amount_total': Decimal(amount), 'amount_tax': 0, 'amount_paid': Decimal(amount),
            'amount_return': 0, 'company_id': company.id, 'session_id': session.id,
            'config_id': session.config_id.id, 'currency_rate': 1})

    def _cards(self, period='custom', first='2026-10-02', last='2026-10-03', dashboard=None, now=None):
        dashboard = dashboard or self.dashboard.with_user(self.reader)
        with patch('odoo.fields.Datetime.now', return_value=now or self.NOW):
            return dashboard.get_baseer_executive_cards(
                self.company.ids, period, first if period == 'custom' else None,
                last if period == 'custom' else None)['cards'][0]

    def test_windows_gaps_midnight_states_refunds_and_cross_day_sessions(self):
        self._order('2026-10-02 06:59:59', '999')  # prior gap, outside selection
        self._order('2026-10-02 07:00:00', '100')
        self._order('2026-10-03 00:01:00', '20', self.session_b, 'done')
        self._order('2026-10-03 04:59:59', '-10')
        self._order('2026-10-03 05:00:00', '3')
        self._order('2026-10-03 06:59:59', '4')
        self._order('2026-10-03 07:00:00', '50', self.session_a, 'invoiced')
        self._order('2026-10-04 04:59:59', '10', self.session_b)
        self._order('2026-10-04 05:00:00', '5')  # final gap included in warning
        self._order('2026-10-04 06:59:59', '6')
        self._order('2026-10-04 07:00:00', '800')  # next day excluded
        self._order('2026-10-03 13:00:00', '1000', state='draft')
        self._order('2026-10-03 14:00:00', '2000', state='cancel')
        self._order('2026-10-03 15:00:00', '5000', self.other_session, company=self.other)
        card = self._cards()
        self.assertEqual(card['total']['value'], '170.00')
        self.assertEqual(card['daily']['value'], '60.00')
        self.assertEqual(card['order_count'], 5)
        self.assertEqual(card['session_count'], 2)
        self.assertEqual(card['outside_hours'], {'count': 4, 'total': {'value': '18.00', 'display': '18.00', 'available': True}})
        sessions = {row['session_id']: row for row in card['sessions']['rows']}
        self.assertEqual(sessions[self.session_a.id]['sales']['value'], '140.00')
        self.assertEqual(sessions[self.session_b.id]['sales']['value'], '30.00')
        self.assertEqual(card['latest_sale_at'], '2026-10-04 07:00:00')
        self.assertEqual([row['value'] for row in card['timeline']], ['110.00', '60.00'])

    def test_server_clock_current_and_gap_cap(self):
        self._order('2026-10-03 07:00:00', '10')
        self._order('2026-10-04 04:30:00', '20')
        self._order('2026-10-04 05:30:00', '3')
        self._order('2026-10-04 06:30:00', '4')
        self._order('2026-10-04 07:00:00', '50')
        current = self._cards('current_day', now=datetime(2026, 10, 4, 1))  # local 04:00
        self.assertEqual(current['date'], '2026-10-03')
        self.assertEqual(current['period']['status'], 'current')
        self.assertEqual(current['total']['value'], '10.00')
        self.assertFalse(current['daily_change']['available'])
        gap = self._cards('current_day', now=datetime(2026, 10, 4, 3))  # local 06:00
        self.assertEqual(gap['date'], '2026-10-03')
        self.assertEqual(gap['period']['status'], 'closed_gap')
        self.assertEqual(gap['total']['value'], '30.00')
        self.assertEqual(gap['outside_hours']['total']['value'], '3.00')
        after = self._cards('current_day', now=datetime(2026, 10, 4, 5))
        self.assertEqual(after['date'], '2026-10-04')
        self.assertEqual(after['total']['value'], '50.00')

    def test_period_resolution_strict_dates_and_366_day_limit(self):
        self.assertEqual(_utc_at(date(2026, 10, 3), 7), datetime(2026, 10, 3, 4))
        for hour, complete, active, status in ((1, '2026-10-02', '2026-10-03', 'current'),
                                              (2, '2026-10-03', '2026-10-03', 'closed_gap'),
                                              (4, '2026-10-03', '2026-10-04', 'current')):
            now = datetime(2026, 10, 4, hour)
            self.assertEqual(_resolve_period('last_complete_day', None, None, now)['to'], complete)
            current = _resolve_period('current_day', None, None, now)
            self.assertEqual(current['to'], active)
            self.assertEqual(current['status'], status)
        month = _resolve_period('this_month', None, None, self.NOW)
        self.assertEqual((month['from'], month['to']), ('2026-10-01', '2026-10-03'))
        self.assertEqual(_resolve_period('last_month', None, None, self.NOW)['to'], '2026-09-30')
        self.assertEqual(_resolve_period('last_30_days', None, None, self.NOW)['from'], '2026-09-04')
        for preset, first, last in (('custom', None, None), ('custom', '2026-1-01', '2026-10-01'),
                ('custom', '2026-10-03', '2026-10-02'), ('custom', '2026-10-04', '2026-10-05'),
                ('custom', '2025-10-01', '2026-10-02'), ('invalid', None, None),
                ('this_month', '2026-10-01', None)):
            with self.assertRaises(ValidationError):
                _resolve_period(preset, first, last, self.NOW)
        self.assertEqual(_resolve_period('custom', '2025-10-03', '2026-10-03', self.NOW)['from'], '2025-10-03')
        with self.assertRaises(ValidationError):
            _resolve_period('this_month', None, None, datetime(2026, 10, 1, 0))

    def test_money_precision_empty_and_fourteen_day_chart(self):
        for amount in ('0.10', '0.20', '0.30', '-0.10'):
            self._order('2026-10-03 10:00:00', amount)
        card = self._cards(first='2026-09-01')
        self.assertEqual(card['total']['value'], '0.50')
        self.assertEqual(len(card['timeline']), 14)
        self.assertEqual(card['timeline'][0]['date'], '2026-09-20')
        self.assertEqual(card['timeline'][-1]['bar_height'], '100.00')
        self.assertEqual(card['timeline'][0]['status'], 'no_orders')
        empty = self._cards(first='2026-09-01', last='2026-09-02')
        self.assertEqual(empty['reason'], 'no_sales')
        self.assertEqual(empty['total']['value'], '0.00')
        self.assertEqual(empty['sessions']['rows'], [])

    def test_session_paging_only_contributing_sessions(self):
        self._session('No orders', self.config)
        for index in range(51):
            session = self._session('Page %02d' % index, self.config)
            self._order('2026-10-03 12:00:00', '1.01', session)
        card = self._cards()
        self.assertEqual(card['session_count'], 51)
        self.assertEqual(len(card['sessions']['rows']), 50)
        self.assertTrue(card['sessions']['has_next'])
        dashboard = self.dashboard.with_user(self.reader)
        with patch('odoo.fields.Datetime.now', return_value=self.NOW):
            page = dashboard.get_baseer_executive_sessions(self.company.id, 'custom', '2026-10-02', '2026-10-03', page=2)
            self.assertEqual(len(page['rows']), 1)
            self.assertFalse(page['has_next'])
            self.assertEqual(page['rows'][0]['sales']['value'], '1.01')
            for invalid in (0, True, '2', 1.5, -1, 3, 1000000):
                with self.assertRaises(ValidationError):
                    dashboard.get_baseer_executive_sessions(self.company.id, 'custom', '2026-10-02', '2026-10-03', page=invalid)

    def test_acl_on_orders_sessions_and_forged_context(self):
        visible = self._order('2026-10-03 12:00:00', '10')
        hidden = self._order('2026-10-03 13:00:00', '20', self.session_b)
        self._order('2026-10-03 14:00:00', '100', self.other_session, company=self.other)
        dashboard = self.dashboard.with_user(self.reader).with_context(
            allowed_company_ids=self.other.ids, active_test=False, arbitrary='forged')
        self.assertEqual(self._cards(dashboard=dashboard)['total']['value'], '30.00')
        with self.assertRaises(AccessError):
            dashboard.get_baseer_executive_cards(self.other.ids)
        with self.assertRaises(AccessError):
            dashboard.get_baseer_executive_sessions(self.other.id)
        rule = self.env['ir.rule'].create({'name': 'EC hide persisted order',
            'model_id': self.env['ir.model']._get_id('pos.order'),
            'domain_force': "[('id', '!=', %d)]" % hidden.id})
        self.assertEqual(self._cards(dashboard=dashboard)['total']['value'], '10.00')
        rule.unlink()
        self.env['ir.rule'].create({'name': 'EC hide session',
            'model_id': self.env['ir.model']._get_id('pos.session'),
            'domain_force': "[('id', '!=', %d)]" % self.session_b.id})
        self.assertEqual(self._cards(dashboard=dashboard)['total']['value'], '10.00')
        self.assertEqual(visible.amount_total, 10)

    def test_source_models_actual_read_permission_required(self):
        dashboard = self.dashboard.with_user(self.reader)
        for model in ('pos.order', 'pos.session'):
            original = type(self.env[model]).check_access
            def deny(record, operation, original=original, model=model):
                if record._name == model and operation == 'read':
                    raise AccessError('Fixture denies actual POS model')
                return original(record, operation)
            with patch.object(type(self.env[model]), 'check_access', deny), self.assertRaises(AccessError):
                dashboard.get_baseer_executive_companies()

    def test_reads_never_create_write_unlink_or_read_manual_summaries(self):
        self._order('2026-10-03 12:00:00', '12.34')
        self.env.flush_all()
        def forbidden(*args, **kwargs):
            raise AssertionError('Executive reads must not mutate operational data or read manual summaries')
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name in ('pos.order', 'pos.session'):
                for method in ('create', 'write', 'unlink'):
                    stack.enter_context(patch.object(type(self.env[name]), method, forbidden))
            for name in ('baseer.pos.summary', 'baseer.pos.closure', 'baseer.pos.summary.allocation'):
                stack.enter_context(patch.object(type(self.env[name]), '_search', forbidden))
            self.assertEqual(self._cards()['total']['value'], '12.34')

    def test_original_currency_unsupported_without_source_read(self):
        company = self.env['res.company'].create({'name': 'EC USD', 'currency_id': self.env.ref('base.USD').id})
        period = _resolve_period('last_complete_day', None, None, self.NOW)
        with patch.object(type(self.dashboard), '_baseer_executive_capacity') as read:
            card = self.dashboard._baseer_executive_card(company, period, self.NOW)
        read.assert_not_called()
        self.assertEqual(card['reason'], 'unsupported_currency')
        self.assertIsNone(card['total']['value'])

    def test_100000_orders_limit_rejects_without_truncation(self):
        self.env.cr.execute(SQL('''
            INSERT INTO pos_order (name, date_order, state, amount_tax, amount_total,
                amount_paid, amount_return, company_id, session_id, config_id, currency_rate)
            SELECT 'EC capacity', %s, 'paid', 0, 0.01, 0.01, 0, %s, %s, %s, 1
            FROM generate_series(1, %s)
        ''', datetime(2026, 10, 3, 9), self.company.id, self.session_a.id, self.config.id, MAX_ORDERS))
        period = _resolve_period('last_complete_day', None, None, self.NOW)
        scoped = self.dashboard.with_user(self.reader)._baseer_executive_scope(self.company.id)
        scoped._baseer_executive_capacity(period, self.NOW)
        self._order('2026-10-03 12:30:00', '0.01')
        with self.assertRaises(ValidationError):
            scoped._baseer_executive_capacity(period, self.NOW)
