"""Read-only heat POS projection against isolated, persisted fixtures.

SQL mirrors the executive POS tests and bypasses approval/payment/accounting
hooks. It is used only inside TransactionCase, never on operational databases.
"""
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import SQL

from odoo.addons.baseer_sales_dashboard.models.executive import MAX_ORDERS


@tagged('post_install', '-at_install')
class HeatPosCase(TransactionCase):
    NOW = datetime(2026, 10, 4, 6)  # 09:00 Riyadh; October 3 has ended.

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Heat POS fixture', 'currency_id': cls.env.ref('base.SAR').id})
        cls.other = cls.env['res.company'].create({
            'name': 'Heat forbidden company', 'currency_id': cls.env.ref('base.SAR').id})
        cls.reader = new_test_user(cls.env, login='heat_native_pos_reader',
            groups='base.group_user,point_of_sale.group_pos_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.dashboard = cls.env['spreadsheet.dashboard'].create({
            'name': 'Heat native POS test',
            'dashboard_group_id': cls.env.ref(
                'spreadsheet_dashboard.spreadsheet_dashboard_group_sales').id,
            'baseer_dashboard_kind': 'sales_heat_calendar', 'is_published': True,
            'group_ids': [Command.set(cls.env.ref('point_of_sale.group_pos_user').ids)],
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.env.flush_all()
        picking = cls.env['stock.picking.type'].search([('code', '=', 'outgoing')], limit=1)
        if not picking:
            picking = cls.env['stock.picking.type'].create({
                'name': 'Heat fixture', 'code': 'outgoing', 'sequence_code': 'HCP'})
        cls.config = cls._insert('pos.config', {
            'name': 'Heat native till', 'company_id': cls.company.id,
            'currency_id': cls.env.ref('base.SAR').id, 'picking_type_id': picking.id,
            'iface_tax_included': 'total', 'picking_policy': 'direct', 'active': True})
        cls.other_config = cls._insert('pos.config', {
            'name': 'Heat other till', 'company_id': cls.other.id,
            'currency_id': cls.env.ref('base.SAR').id, 'picking_type_id': picking.id,
            'iface_tax_included': 'total', 'picking_policy': 'direct', 'active': True})
        cls.session_a = cls._session('Heat A', cls.config)
        cls.session_b = cls._session('Heat B', cls.config, 'closed')
        cls.other_session = cls._session('Heat other', cls.other_config)

    @classmethod
    def _insert(cls, model, values):
        required = [name for name, field in cls.env[model]._fields.items()
                    if field.required and field.store and field.column_type
                    and not field.compute and not field.related and name not in values]
        values = dict(cls.env[model].default_get(required), **values)
        cls.env.cr.execute(SQL('INSERT INTO %s (%s) VALUES (%s) RETURNING id',
            SQL.identifier(cls.env[model]._table),
            SQL(', ').join(SQL.identifier(key) for key in values),
            SQL(', ').join(SQL('%s', value) for value in values.values())))
        return cls.env[model].browse(cls.env.cr.fetchone()[0])

    @classmethod
    def _session(cls, name, config, state='opened'):
        return cls._insert('pos.session', {
            'name': name, 'config_id': config.id, 'user_id': cls.env.uid, 'state': state})

    def _order(self, local, amount, session=None, state='paid', company=None,
               tax='0', summary=None, source=None):
        session, company = session or self.session_a, company or self.company
        values = {
            'name': 'Heat fixture order',
            'date_order': datetime.fromisoformat(local) - timedelta(hours=3),
            'state': state, 'amount_total': Decimal(amount), 'amount_tax': Decimal(tax),
            'amount_paid': Decimal(amount), 'amount_return': 0,
            'company_id': company.id, 'session_id': session.id,
            'config_id': session.config_id.id, 'currency_rate': 1,
        }
        if summary:
            values['baseer_summary_id'] = summary.id
        if source:
            values['source'] = source
        return self._insert('pos.order', values)

    def _summary(self, day, amount='115', customers=7, period='all',
                 schedule='all', state='approved', linked=True):
        summary = self._insert('baseer.pos.summary', {
            'name': 'Heat saved summary', 'company_id': self.company.id,
            'business_date': date.fromisoformat(day), 'config_id': self.config.id,
            'period_scope': period, 'day_schedule': schedule, 'state': state,
            'customer_count': customers, 'zero_sales': Decimal(amount) == 0,
            'amount_gross': Decimal(amount), 'amount_net': Decimal(amount), 'amount_tax': 0,
        })
        if linked and Decimal(amount) and state == 'approved':
            session = self._session('Heat summary %s' % summary.id, self.config, 'closed')
            order = self._order(day + ' 12:00:00', amount, session, state='done',
                                summary=summary, source='baseer_summary')
            self.env.cr.execute(SQL('UPDATE baseer_pos_summary SET order_id = %s, '
                'session_id = %s WHERE id = %s', order.id, session.id, summary.id))
            summary.invalidate_recordset()
        return summary

    def _closure(self, day, period='all'):
        return self._insert('baseer.pos.closure', {
            'name': 'Heat saved closure', 'company_id': self.company.id,
            'date_from': date.fromisoformat(day), 'date_to': date.fromisoformat(day),
            'period_scope': period, 'reason': 'holiday', 'state': 'confirmed'})

    def _scoped(self):
        return self.dashboard.with_user(self.reader).with_context(
            allowed_company_ids=self.company.ids, lang='en_US', tz='Asia/Riyadh')

    def _rows(self, first='2026-10-01', last='2026-10-03', now=None, dashboard=None):
        scoped = dashboard or self._scoped()
        return {row['business_date']: row for row in scoped._heat_aggregate_days(
            scoped.env['res.company'].browse(self.company.id), date.fromisoformat(first),
            date.fromisoformat(last), now or self.NOW)}

    def _payload(self, month='2026-10', now=None, dashboard=None):
        with patch('odoo.fields.Datetime.now', return_value=now or self.NOW):
            return (dashboard or self._scoped()).get_baseer_heat_calendar(month)

    def _days(self, **kwargs):
        return {day['date']: day for week in self._payload(**kwargs)['weeks']
                for day in week if day}

    def _action_records(self, action):
        self.assertEqual(action['type'], 'ir.actions.act_window')
        return self._scoped().env[action['res_model']].search(action['domain'])

    def test_summary_generated_native_order_is_counted_once_and_zero_is_preserved(self):
        summary = self._summary('2026-10-01', customers=17)
        zero = self._summary('2026-10-02', amount='0', customers=0)
        self._summary('2026-10-03', amount='23', customers=3,
                      period='morning', schedule='split')
        rows = self._rows()
        first, second, third = (rows[date(2026, 10, day)] for day in (1, 2, 3))
        self.assertEqual(first['source_kind'], 'summary')
        self.assertEqual(first['sales'], Decimal('115.00'))
        self.assertEqual(first['customers'], 17)
        self.assertEqual(first['order_count'], 1)
        self.assertEqual(first['status'], 'complete')
        self.assertEqual(second['source_kind'], 'summary')
        self.assertTrue(second['has_sales'])
        self.assertEqual(second['sales'], Decimal('0.00'))
        self.assertEqual(second['status'], 'complete')
        self.assertEqual(second['order_count'], 0)
        self.assertEqual(third['status'], 'incomplete')
        self.assertEqual(third['customers'], 3)
        action = first['source_action']
        self.assertEqual(action['res_model'], 'pos.order')
        self.assertEqual(self._action_records(action), summary.order_id)
        self.assertEqual(second['source_action']['res_model'], 'baseer.pos.summary')
        self.assertEqual(self._action_records(second['source_action']), zero)
        days = self._days()
        self.assertEqual(days['2026-10-01']['sales_display'], '115.00')
        self.assertEqual(days['2026-10-01']['customers_display'], '17')
        self.assertEqual(days['2026-10-01']['count_label'], 'Recorded customers')
        self.assertIn('customers', days['2026-10-01']['aria_label'])
        self.assertEqual(days['2026-10-02']['sales_display'], '0.00')

    def test_direct_vat_signed_refunds_boundaries_gaps_states_and_multiple_sessions(self):
        self._order('2026-10-02 06:59:59', '999')  # prior gap excluded
        first = self._order('2026-10-02 07:00:00', '115', tax='15')
        overnight = self._order('2026-10-03 00:01:00', '23', self.session_b, 'done', tax='3')
        refund = self._order('2026-10-03 04:59:59', '-11.50', tax='-1.50')
        self._order('2026-10-03 05:00:00', '3')
        self._order('2026-10-03 06:59:59', '4')
        third = self._order('2026-10-03 07:00:00', '50', state='invoiced')
        last = self._order('2026-10-04 04:59:59', '10', self.session_b)
        self._order('2026-10-04 05:00:00', '5')
        self._order('2026-10-04 06:59:59', '6')
        self._order('2026-10-04 07:00:00', '800')  # next business day
        self._order('2026-10-03 13:00:00', '1000', state='draft')
        self._order('2026-10-03 14:00:00', '2000', state='cancel')
        self._order('2026-10-03 15:00:00', '5000', self.other_session, company=self.other)
        rows = self._rows(first='2026-10-02')
        a, b = rows[date(2026, 10, 2)], rows[date(2026, 10, 3)]
        self.assertEqual((a['source_kind'], a['sales'], a['order_count']),
                         ('direct', Decimal('126.50'), 3))
        self.assertEqual((b['sales'], b['order_count']), (Decimal('60.00'), 2))
        self.assertEqual((a['outside_count'], b['outside_count']), (2, 2))
        self.assertEqual(a['status'], 'complete')
        self.assertEqual(b['status'], 'complete')
        self.assertEqual(set(self._action_records(a['source_action']).ids), {first.id, overnight.id, refund.id})
        self.assertEqual(set(self._action_records(b['source_action']).ids), {third.id, last.id})
        days = self._days()
        self.assertIn('transactions', days['2026-10-02']['aria_label'])
        self.assertEqual(days['2026-10-02']['count_label'], 'POS transactions')
        self.assertEqual(days['2026-10-02']['shift_breakdown'], [])

    def test_gap_only_day_is_missing_and_warned_not_complete_zero(self):
        self._order('2026-10-03 05:30:00', '99')
        row = self._rows()[date(2026, 10, 2)]
        self.assertEqual(row['source_kind'], 'none')
        self.assertEqual(row['status'], 'missing')
        self.assertFalse(row['has_sales'])
        self.assertEqual(row['outside_count'], 1)
        day = self._days()['2026-10-02']
        self.assertEqual(day['sales_display'], '—')
        self.assertEqual(day['heat_level'], 'neutral')
        self.assertEqual(day['outside_count'], 1)
        self.assertTrue(day['outside_warning'])

    def test_server_clock_current_future_and_exact_five_am_completion(self):
        self._order('2026-10-03 07:00:00', '10')
        self._order('2026-10-04 04:30:00', '20')
        self._order('2026-10-04 05:30:00', '3')
        self._order('2026-10-04 06:30:00', '4')
        self._order('2026-10-04 07:00:00', '50')
        current = self._rows(last='2026-10-05', now=datetime(2026, 10, 4, 1))
        self.assertEqual(current[date(2026, 10, 3)]['sales'], Decimal('10.00'))
        self.assertEqual(current[date(2026, 10, 3)]['status'], 'incomplete')
        for day in (4, 5):
            self.assertEqual(current[date(2026, 10, day)]['status'], 'missing')
            self.assertFalse(current[date(2026, 10, day)]['has_sales'])
        completed = self._rows(now=datetime(2026, 10, 4, 2))  # exactly 05:00 local
        self.assertEqual(completed[date(2026, 10, 3)]['sales'], Decimal('30.00'))
        self.assertEqual(completed[date(2026, 10, 3)]['status'], 'complete')
        gap = self._rows(now=datetime(2026, 10, 4, 3))
        self.assertEqual(gap[date(2026, 10, 3)]['outside_count'], 1)

    def test_exact_sql_decimal_survives_large_cancelling_values(self):
        for amount in ('0.10', '0.20', '0.30', '-0.10', '9999999999.99',
                       '0.01', '-9999999999.98'):
            self._order('2026-10-03 10:00:00', amount)
        row = self._rows()[date(2026, 10, 3)]
        self.assertIsInstance(row['sales'], Decimal)
        self.assertEqual(row['sales'], Decimal('0.52'))
        self.assertEqual(self._days()['2026-10-03']['sales_display'], '0.52')

    def test_same_day_source_conflict_hides_sum_and_excludes_baselines_and_average(self):
        for day, amount in (('2026-09-05', '20'), ('2026-09-12', '30'), ('2026-09-19', '40')):
            self._order(day + ' 12:00:00', amount)
        self._summary('2026-09-26', amount='1000')
        self._order('2026-09-26 13:00:00', '2000')
        self._summary('2026-10-03', amount='100')
        self._order('2026-10-03 13:00:00', '10')
        self._order('2026-10-10 12:00:00', '60')
        now = datetime(2026, 10, 11, 6)
        row = self._rows(now=now)[date(2026, 10, 3)]
        self.assertEqual(row['source_kind'], 'conflict')
        self.assertEqual(row['status'], 'conflict')
        self.assertFalse(row['has_sales'])
        self.assertEqual(row['sales'], Decimal('0.00'))
        payload = self._payload(now=now)
        days = {day['date']: day for week in payload['weeks'] for day in week if day}
        conflict = days['2026-10-03']
        self.assertEqual(conflict['sales_display'], '—')
        self.assertEqual(conflict['ratio_display'], '—')
        self.assertEqual(conflict['heat_level'], 'neutral')
        self.assertEqual(conflict['customers_display'], '—')
        self.assertTrue(conflict['warning'])
        self.assertEqual(days['2026-10-10']['baseline_sample_count'], 3)
        self.assertEqual(days['2026-10-10']['basis_display'], '30.00')
        saturday = next(row for row in payload['weekdays'] if row['name'] == 'Saturday')
        self.assertEqual(saturday['average_display'], '60.00')

    def test_full_closure_with_direct_order_is_conflict(self):
        self._closure('2026-10-03')
        self._order('2026-10-03 12:00:00', '25')
        row = self._rows()[date(2026, 10, 3)]
        self.assertEqual(row['source_kind'], 'conflict')
        self.assertNotEqual(row['status'], 'complete')
        self.assertEqual(self._days()['2026-10-03']['sales_display'], '—')

    def test_nonzero_summary_missing_cancelled_mismatched_or_hidden_order_is_unavailable(self):
        summary = self._summary('2026-10-03', linked=False)
        with self.assertRaises(ValidationError):
            self._rows()
        order = self._order('2026-10-03 12:00:00', '115', summary=summary,
                            state='cancel', source='baseer_summary')
        self.env.cr.execute(SQL('UPDATE baseer_pos_summary SET order_id = %s, session_id = %s WHERE id = %s',
                                order.id, self.session_a.id, summary.id))
        summary.invalidate_recordset()
        with self.assertRaises(ValidationError):
            self._rows()
        self.env.cr.execute(SQL("UPDATE pos_order SET state = 'done', source = 'pos' WHERE id = %s", order.id))
        order.invalidate_recordset()
        with self.assertRaises(ValidationError):
            self._rows()
        self.env.cr.execute(SQL("UPDATE pos_order SET source = 'baseer_summary', date_order = %s WHERE id = %s",
                                datetime(2026, 10, 2, 9), order.id))
        order.invalidate_recordset()
        with self.assertRaises(ValidationError):
            self._rows()
        self.env.cr.execute(SQL('UPDATE pos_order SET date_order = %s WHERE id = %s',
                                datetime(2026, 10, 3, 9), order.id))
        order.invalidate_recordset()
        self.assertEqual(self._rows()[date(2026, 10, 3)]['sales'], Decimal('115.00'))
        self.env.cr.execute(SQL('UPDATE pos_order SET baseer_summary_id = NULL WHERE id = %s', order.id))
        order.invalidate_recordset()
        with self.assertRaises(ValidationError):
            self._rows()
        self.env.cr.execute(SQL('UPDATE pos_order SET baseer_summary_id = %s WHERE id = %s', summary.id, order.id))
        order.invalidate_recordset()
        self.env['ir.rule'].create({'name': 'Heat hide generated order',
            'model_id': self.env['ir.model']._get_id('pos.order'),
            'domain_force': "[('id', '!=', %d)]" % order.id})
        with self.assertRaises(ValidationError):
            self._rows()

    def test_generated_order_with_inaccessible_summary_or_orphan_marker_is_unavailable(self):
        summary = self._summary('2026-10-03')
        rule = self.env['ir.rule'].create({'name': 'Heat hide generated metadata',
            'model_id': self.env['ir.model']._get_id('baseer.pos.summary'),
            'domain_force': "[('id', '!=', %d)]" % summary.id})
        with self.assertRaises(ValidationError):
            self._rows()
        rule.unlink()
        self.assertEqual(self._rows()[date(2026, 10, 3)]['source_kind'], 'summary')
        self._order('2026-10-02 12:00:00', '23', source='baseer_summary')
        with self.assertRaises(ValidationError):
            self._rows()

    def test_generated_noon_order_after_now_is_unavailable_not_invented_zero(self):
        self._summary('2026-10-03')
        with self.assertRaises(ValidationError):
            self._rows(now=datetime(2026, 10, 3, 7))  # 10:00 local, source noon is future

    def test_summary_marker_with_null_source_and_unapproved_metadata_is_unavailable(self):
        draft = self._summary('2026-10-03', state='draft', linked=False)
        order = self._order('2026-10-03 12:00:00', '115', summary=draft)
        self.env.cr.execute(SQL('UPDATE pos_order SET source = NULL WHERE id = %s', order.id))
        order.invalidate_recordset()
        with self.assertRaises(ValidationError):
            self._rows()

    def test_order_and_session_rules_intersect_and_company_session_scope_is_enforced(self):
        visible = self._order('2026-10-03 12:00:00', '10')
        hidden = self._order('2026-10-03 13:00:00', '20', self.session_b)
        self._order('2026-10-03 14:00:00', '100', self.other_session, company=self.other)
        self.assertEqual(self._rows()[date(2026, 10, 3)]['sales'], Decimal('30.00'))
        rule = self.env['ir.rule'].create({'name': 'Heat hide persisted order',
            'model_id': self.env['ir.model']._get_id('pos.order'),
            'domain_force': "[('id', '!=', %d)]" % hidden.id})
        self.assertEqual(self._rows()[date(2026, 10, 3)]['sales'], Decimal('10.00'))
        rule.unlink()
        self.env['ir.rule'].create({'name': 'Heat hide session',
            'model_id': self.env['ir.model']._get_id('pos.session'),
            'domain_force': "[('id', '!=', %d)]" % self.session_b.id})
        row = self._rows()[date(2026, 10, 3)]
        self.assertEqual(row['sales'], Decimal('10.00'))
        self.assertEqual(self._action_records(row['source_action']), visible)
        self.reader.sudo().write({'company_ids': [Command.set((self.company | self.other).ids)]})
        with self.assertRaises(AccessError):
            self._payload(dashboard=self._scoped().with_context(allowed_company_ids=self.other.ids))
        # Assigned company B is not enough while the active session remains A.
        with self.assertRaises(AccessError):
            self._scoped()._heat_aggregate_days(self.other, date(2026, 10, 1), date(2026, 10, 3), self.NOW)
        forged = self._scoped().with_context(force_company=self.other.id, arbitrary='forged')
        self.assertEqual(self._days(dashboard=forged)['2026-10-03']['sales_display'], '10.00')

    def test_actual_pos_acl_required_and_reads_never_mutate_operational_models(self):
        self._order('2026-10-03 12:00:00', '12.34')
        for model in ('pos.order', 'pos.session'):
            original = type(self.env[model]).check_access
            def deny(record, operation, original=original, model=model):
                if record._name == model and operation == 'read':
                    raise AccessError('Fixture denies POS source read')
                return original(record, operation)
            with patch.object(type(self.env[model]), 'check_access', deny), self.assertRaises(AccessError):
                self._payload()
        self.env.flush_all()
        def forbidden(*args, **kwargs):
            raise AssertionError('Heat calendar read mutated operational records')
        with ExitStack() as stack:
            for model in ('pos.order', 'pos.session', 'pos.payment', 'baseer.pos.summary',
                          'baseer.pos.summary.allocation', 'baseer.pos.closure', 'account.move'):
                for method in ('create', 'write', 'unlink'):
                    stack.enter_context(patch.object(type(self.env[model]), method, forbidden))
            self.assertEqual(self._days()['2026-10-03']['sales_display'], '12.34')

    def test_non_sar_company_and_foreign_pos_even_only_in_gap_are_rejected(self):
        self.company.currency_id = self.env.ref('base.USD')
        with patch.object(type(self.dashboard), '_baseer_executive_capacity') as aggregate:
            with self.assertRaises(ValidationError):
                self._payload()
        aggregate.assert_not_called()
        self.company.currency_id = self.env.ref('base.SAR')
        config = self._insert('pos.config', {
            'name': 'Heat foreign till', 'company_id': self.company.id,
            'currency_id': self.env.ref('base.USD').id,
            'picking_type_id': self.config.picking_type_id.id,
            'iface_tax_included': 'total', 'picking_policy': 'direct', 'active': True})
        session = self._session('Heat foreign session', config)
        self._order('2026-10-03 12:00:00', '50')
        foreign = self._order('2026-10-03 13:00:00', '10', session)
        with self.assertRaises(ValidationError):
            self._payload()
        self.env.cr.execute(SQL('UPDATE pos_order SET date_order = %s WHERE id = %s',
                                datetime(2026, 10, 4, 2, 30), foreign.id))
        foreign.invalidate_recordset()
        with self.assertRaises(ValidationError):
            self._payload()

    def test_capacity_rejects_100001_orders_without_truncation(self):
        self.env.cr.execute(SQL('''
            INSERT INTO pos_order (name, date_order, state, amount_tax, amount_total,
                amount_paid, amount_return, company_id, session_id, config_id, currency_rate)
            SELECT 'Heat capacity', %s, 'paid', 0, 0.01, 0.01, 0, %s, %s, %s, 1
            FROM generate_series(1, %s)
        ''', datetime(2026, 10, 3, 9), self.company.id, self.session_a.id, self.config.id, MAX_ORDERS))
        self.assertEqual(self._rows()[date(2026, 10, 3)]['sales'], Decimal('1000.00'))
        self._order('2026-10-03 12:30:00', '0.01')
        with self.assertRaises(ValidationError):
            self._rows()

    def test_contributing_sessions_limit_prevents_unbounded_source_action_payload(self):
        for index in range(1000):
            session = self._session('Heat bound %04d' % index, self.config)
            self._order('2026-10-03 12:00:00', '0.01', session)
        row = self._rows()[date(2026, 10, 3)]
        self.assertEqual(row['sales'], Decimal('10.00'))
        session_filter = next(term for term in row['source_action']['domain'] if term[0] == 'session_id')
        self.assertEqual(len(session_filter[2]), 1000)
        extra = self._session('Heat bound overflow', self.config)
        self._order('2026-10-03 12:01:00', '0.01', extra)
        with self.assertRaises(ValidationError):
            self._rows()
