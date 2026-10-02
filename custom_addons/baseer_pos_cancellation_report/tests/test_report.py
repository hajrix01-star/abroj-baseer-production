import json
from pathlib import Path
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import SQL

from ..models.report_query import REPORT_QUERY


@tagged('post_install', '-at_install')
class TestCancellationReport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env['baseer.pos.cancellation.report'].with_context(tz='Asia/Riyadh')
        cls.cashier = cls.env['res.users'].create({
            'name': 'Report test cashier', 'login': 'baseer-report-test-cashier',
            'company_id': cls.env.company.id, 'company_ids': [Command.set(cls.env.companies.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id,
                                      cls.env.ref('point_of_sale.group_pos_user').id])],
        })
        cls.manager = cls.env['res.users'].create({
            'name': 'Report test manager', 'login': 'baseer-report-test-manager',
            'company_id': cls.env.company.id, 'company_ids': [Command.set(cls.env.companies.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id,
                                      cls.env.ref('point_of_sale.group_pos_manager').id])],
        })

    def test_cashier_cannot_call_report_or_read(self):
        report = self.report.with_user(self.cashier)
        with self.assertRaises(AccessError):
            report.get_report({})
        with self.assertRaises(AccessError):
            report.search([])
        with self.assertRaises(AccessError):
            report.get_session_details({}, {})

    def test_report_frontend_translations_are_registered(self):
        self.assertIn('baseer_pos_cancellation_report',
                      self.env['ir.http']._get_translation_frontend_modules_name())

    def test_arabic_backend_labels(self):
        payload = self.report.with_user(self.manager).with_context(lang='ar_001').get_report(
            {'preset': 'day', 'day': '1999-01-01'})
        self.assertEqual(payload['kpis'][0]['label'], 'عمليات استبدال الأصناف')

    def test_report_is_read_only_even_for_system(self):
        for action in (lambda: self.report.create({}), lambda: self.report.write({}), lambda: self.report.unlink()):
            with self.assertRaises(AccessError):
                action()

    def test_manager_empty_payload_contract(self):
        payload = self.report.with_user(self.manager).get_report({'preset': 'day', 'day': '1999-01-01'})
        self.assertEqual(payload['pagination']['total'], 0)
        self.assertEqual(payload['details'], [])
        self.assertTrue(payload['kpis'])
        self.assertEqual(payload['session_days'], [])
        self.assertEqual(payload['group_pagination'], {'offset': 0, 'limit': 50, 'total': 0})
        for key in ('reasons', 'shifts', 'cashiers', 'registers', 'timeline'):
            self.assertEqual(payload[key], [])

    def test_riyadh_period_and_exclusive_endpoint(self):
        result, start, end, m, e, zone = self.report._normalize_filters({
            'preset': 'custom', 'date_from': '2026-10-01T00:00', 'date_to': '2026-10-02T00:00'})
        self.assertEqual(start.isoformat(), '2026-09-30T21:00:00')
        self.assertEqual(end.isoformat(), '2026-10-01T21:00:00')
        self.assertEqual(result['date_to'], '2026-10-02T00:00')
        self.assertEqual((m, e), (360, 1080))

    def test_invalid_filters(self):
        base = dict(preset='custom', date_from='2026-10-01T00:00', date_to='2026-10-02T00:00')
        for patch in ({'date_to': '2026-10-01T00:00'}, {'limit': 101}, {'limit': True},
                      {'morning_start': '25:00'}, {'morning_start': '18:00'},
                      {'shift': 'unknown'}, {'cashier_id': -1}, {'review_only': 'false'},
                      {'date_from': '2026-10-01T00:00+03:00'}, {'group_limit': 101},
                      {'group_limit': True}, {'group_offset': -1}, {'group_offset': 10000001}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                self.report._normalize_filters(dict(base, **patch))

    def test_unavailable_company_context_is_rejected(self):
        other = self.env['res.company'].create({'name': 'Report inaccessible company'})
        with self.assertRaises(AccessError):
            self.report.with_user(self.manager).with_context(allowed_company_ids=[other.id]).get_report({})

    def _projection_fixture(self):
        """Temporary source tables and view; no operational audit records are edited."""
        fixture = (Path(__file__).with_name('projection_fixture.sql')).read_text(encoding='utf-8')
        fixture = fixture.replace('BEGIN;\n', '', 1).replace('\nROLLBACK;', '')
        fixture = fixture.replace('-- REPORT_VIEW_PLACEHOLDER',
                                  'CREATE TEMP VIEW report_test AS ' + REPORT_QUERY + ';')
        self.env.cr.execute(fixture)
        self.env.cr.execute('CREATE TEMP VIEW baseer_pos_cancellation_report AS SELECT * FROM report_test')
        other = self.env['res.company'].create({'name': 'Projection other company'})
        for table in ('baseer_pos_substitution', 'baseer_pos_protected_item_cancellation',
                      'baseer_print_preparation_event', 'baseer_print_cancellation'):
            self.env.cr.execute(SQL('UPDATE %s SET company_id = CASE WHEN company_id=1 THEN %s ELSE %s END',
                                    SQL.identifier(table), self.env.company.id, other.id))
        return other

    def test_nonempty_report_orm_counts_pagination_and_company_rule(self):
        other = self._projection_fixture()
        report = self.report.with_user(self.manager).with_context(allowed_company_ids=[self.env.company.id])
        payload = report.get_report({'preset': 'day', 'day': '2026-10-01', 'limit': 2})
        kpis = {item['key']: item['value'] for item in payload['kpis']}
        self.assertEqual(payload['pagination'], {'offset': 0, 'limit': 2, 'total': 12})
        self.assertEqual(len(payload['details']), 2)
        self.assertEqual(kpis['substitutions'], '1')
        self.assertEqual(kpis['cancellations'], '9')
        self.assertEqual(kpis['reductions'], '1')
        self.assertEqual(kpis['review_orders'], '1')
        self.assertEqual(kpis['replacement_cancellations'], '3')
        self.assertEqual(kpis['cancelled_quantity'], '15.00')
        for key in ('cashiers', 'registers'):
            self.assertEqual(len(payload[key]), 1)
            self.assertEqual(payload[key][0]['substitutions'], '1')
            self.assertEqual(payload[key][0]['cancellations'], '9')
            self.assertEqual(payload[key][0]['reviews'], '1')
        self.assertFalse(report.search([('company_id', '=', other.id)]))
        next_page = report.get_report(dict(payload['filters'], offset=2))
        self.assertEqual(next_page['kpis'], payload['kpis'])
        self.assertTrue(set(row['id'] for row in payload['details']).isdisjoint(
            row['id'] for row in next_page['details']))
        for source in (payload, next_page):
            self.assertTrue(all(row['company_id'] == self.env.company.id for row in source['details']))

    def test_stale_page_and_decimal_quantities(self):
        self._projection_fixture()
        self.env.cr.execute('UPDATE baseer_pos_protected_item_cancellation SET source_quantity=2.005 WHERE id=1')
        report = self.report.with_user(self.manager).with_context(allowed_company_ids=[self.env.company.id])
        payload = report.get_report({'preset': 'day', 'day': '2026-10-01', 'limit': 2, 'offset': 999})
        self.assertEqual(payload['pagination'], {'offset': 10, 'limit': 2, 'total': 12})
        self.assertEqual(len(payload['details']), 2)
        self.assertEqual(payload['filters']['offset'], 10)
        self.assertEqual(next(row['value'] for row in payload['kpis'] if row['key']=='cancelled_quantity'), '15.01')
        self.assertTrue(all(isinstance(row['event_at'], str) for row in payload['details']))
        empty = report.get_report({'preset': 'day', 'day': '1999-01-01', 'offset': 999})
        self.assertEqual(empty['pagination']['offset'], 0)
        self.assertEqual(empty['details'], [])

    def test_shift_boundaries_and_review_context_through_orm(self):
        self._projection_fixture()
        report = self.report.with_user(self.manager).with_context(allowed_company_ids=[self.env.company.id])
        base = dict(preset='day', day='2026-10-01')
        self.assertEqual(report.get_report(dict(base, shift='evening'))['pagination']['total'], 0)
        overnight = report.get_report(dict(base, shift='evening', morning_start='18:00', evening_start='06:00'))
        self.assertEqual(overnight['pagination']['total'], 12)
        payload = report.get_report(dict(base, review_only=True))
        exact = next(row for row in payload['details'] if row['id'] == 5)
        self.assertEqual(exact['prior_substitution_id'], 1)
        self.assertIn('2026-09-30 15:00:00', exact['review_context'])
        self.assertFalse(any(row['event_type'] == 'quantity_reduce' for row in payload['details']))

    def _session_projection_fixture(self):
        other = self._projection_fixture()
        self.env.cr.execute('UPDATE baseer_pos_substitution SET session_id=102 WHERE id=3')
        self.env.cr.execute('UPDATE baseer_pos_protected_item_cancellation SET session_id=101')
        self.env.cr.execute("""
            UPDATE baseer_print_preparation_event SET session_id=CASE
                WHEN id IN (1,2,3) THEN 101 WHEN id IN (4,6) THEN 102
                WHEN id=7 THEN 104 ELSE NULL END;
            UPDATE baseer_print_preparation_event SET create_date='2026-10-01 21:05' WHERE id=4;
            UPDATE baseer_print_cancellation SET session_id=103;
        """)
        report = self.report.with_user(self.manager).with_context(allowed_company_ids=[self.env.company.id])
        return report, other

    @staticmethod
    def _session_groups(payload):
        return [group for day in payload['session_days'] for group in day['groups']]

    def test_session_group_counts_local_days_deleted_order_and_unknown_session(self):
        report, other = self._session_projection_fixture()
        payload = report.get_report({'preset': 'month', 'month': '2026-10', 'limit': 1})
        self.assertEqual(payload['group_pagination'], {'offset': 0, 'limit': 50, 'total': 5})
        self.assertEqual([day['date'] for day in payload['session_days']], ['2026-10-02', '2026-10-01'])
        groups = self._session_groups(payload)
        self.assertEqual([(group['date'], group['session_id']) for group in groups], [
            ('2026-10-02', 102), ('2026-10-01', 103), ('2026-10-01', False),
            ('2026-10-01', 102), ('2026-10-01', 101)])
        self.assertEqual(len({group['key'] for group in groups}), 5)
        self.assertTrue(all(group['company_id'] == self.env.company.id for group in groups))
        multi_line = next(group for group in groups if group['session_id'] == 101)
        self.assertEqual((multi_line['operations'], multi_line['cancellations'],
                          multi_line['reductions'], multi_line['detail_count']), ('2', '1', '1', 3))
        self.assertEqual(sum(group['detail_count'] for group in groups), 12)
        unknown = next(group for group in groups if group['session_id'] is False)
        self.assertEqual(unknown['session_name'], 'Session not recorded')
        original_names = report._names
        with patch.object(type(report), '_names', side_effect=lambda model, ids:
                          {101: '/', 102: '', 103: '   '} if model == 'pos.session' else original_names(model, ids)):
            unnamed = self._session_groups(report.get_report(payload['filters']))
        for item in unnamed:
            self.assertEqual(item['session_name'],
                             'Session %s' % item['session_id'] if item['session_id'] else 'Session not recorded')
        deleted = report.get_session_details(payload['filters'], groups[0])
        self.assertEqual([row['id'] for row in deleted['details']], [18])
        self.assertEqual(deleted['details'][0]['order_identity'], 10)
        self.assertEqual(deleted['details'][0]['event_at'], '2026-10-02 00:05:00')
        self.assertIn('2026-09-30 15:00:00', deleted['details'][0]['review_context'])
        self.assertEqual([row['id'] for row in report.get_session_details(
            payload['filters'], unknown)['details']], [22])

    def test_group_paging_keeps_complete_counts_and_existing_kpis(self):
        report, other = self._session_projection_fixture()
        first = report.get_report({'preset': 'month', 'month': '2026-10', 'group_limit': 2, 'limit': 1})
        second = report.get_report(dict(first['filters'], group_offset=2))
        self.assertEqual(first['group_pagination'], {'offset': 0, 'limit': 2, 'total': 5})
        self.assertEqual(second['group_pagination'], {'offset': 2, 'limit': 2, 'total': 5})
        self.assertEqual(first['kpis'], second['kpis'])
        self.assertEqual(first['pagination'], second['pagination'])
        self.assertTrue({group['key'] for group in self._session_groups(first)}.isdisjoint(
            group['key'] for group in self._session_groups(second)))
        stale = report.get_report(dict(first['filters'], group_offset=999))
        self.assertEqual(stale['group_pagination'], {'offset': 4, 'limit': 2, 'total': 5})
        self.assertEqual(stale['filters']['group_offset'], 4)
        self.assertEqual(self._session_groups(stale)[0]['detail_count'], 3)
        empty = report.get_report({'preset': 'day', 'day': '1999-01-01', 'group_offset': 999})
        self.assertEqual(empty['group_pagination']['offset'], 0)
        self.assertEqual(empty['session_days'], [])

    def test_session_details_paging_scope_and_formatter_reuse(self):
        report, other = self._session_projection_fixture()
        payload = report.get_report({'preset': 'month', 'month': '2026-10'})
        group = next(group for group in self._session_groups(payload) if group['session_id'] == 101)
        group = dict(group, operations='9999', detail_count=9999, session_name='Untrusted label')
        first = report.get_session_details(payload['filters'], group, limit=2)
        second = report.get_session_details(payload['filters'], group, offset=2, limit=2)
        self.assertEqual(first['pagination'], {'offset': 0, 'limit': 2, 'total': 3})
        self.assertEqual(second['pagination'], {'offset': 2, 'limit': 2, 'total': 3})
        self.assertEqual([row['id'] for row in first['details'] + second['details']], [14, 10, 5])
        full_details = {row['id']: row for row in payload['details']}
        self.assertEqual(first['details'], [full_details[14], full_details[10]])
        stale = report.get_session_details(payload['filters'], group, offset=999, limit=2)
        self.assertEqual(stale['pagination']['offset'], 2)
        self.assertEqual(stale['details'], second['details'])
        wrong_date = report.get_session_details(payload['filters'], dict(group, date='2026-10-02'))
        self.assertEqual(wrong_date, {'details': [], 'pagination': {'offset': 0, 'limit': 50, 'total': 0}})
        reduced = report.get_session_details(dict(payload['filters'], event_type='quantity_reduce'), group)
        self.assertEqual([row['id'] for row in reduced['details']], [14])
        reviewed = report.get_session_details(dict(payload['filters'], review_only=True), group)
        self.assertEqual([row['id'] for row in reviewed['details']], [10, 5])
        evening = report.get_session_details(dict(payload['filters'], shift='evening'), group)
        self.assertEqual(evening['pagination']['total'], 0)
        other_cashier = report.get_session_details(dict(payload['filters'], cashier_id=2147483647), group)
        self.assertEqual(other_cashier['pagination']['total'], 0)
        other_register = report.get_session_details(dict(payload['filters'], pos_config_id=2147483647), group)
        self.assertEqual(other_register['pagination']['total'], 0)

    def test_unknown_session_and_point_are_exact_null_groups(self):
        report, other = self._session_projection_fixture()
        self.env.cr.execute('UPDATE baseer_print_preparation_event SET pos_config_id=NULL WHERE id=5')
        payload = report.get_report({'preset': 'month', 'month': '2026-10'})
        group = next(group for group in self._session_groups(payload) if group['session_id'] is False)
        self.assertIs(group['pos_config_id'], False)
        self.assertEqual(group['pos_name'], 'Not recorded')
        details = report.get_session_details(payload['filters'], group)
        self.assertEqual([row['id'] for row in details['details']], [22])
        self.assertEqual(report.get_session_details(payload['filters'], dict(group, pos_config_id=1))['details'], [])
        self.assertEqual(report.get_session_details(payload['filters'], dict(group, session_id=102))['details'], [])

    def test_session_details_reject_invalid_selector_company_and_paging(self):
        report, other = self._session_projection_fixture()
        filters = {'preset': 'month', 'month': '2026-10'}
        group = {'date': '2026-10-01', 'company_id': self.env.company.id, 'session_id': 101, 'pos_config_id': 1}
        for patch in ({'date': '20261001'}, {'date': '2026-02-30'}, {'date': False}, {'date': '2026-10-01 OR true'},
                      {'session_id': True}, {'session_id': 0}, {'session_id': -1}, {'session_id': '101'},
                      {'session_id': None}, {'pos_config_id': True}, {'company_id': False}, {'company_id': '1'}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                report.get_session_details(filters, dict(group, **patch))
        with self.assertRaises(ValidationError):
            report.get_session_details(filters, [])
        with self.assertRaises(AccessError):
            report.get_session_details(filters, dict(group, company_id=other.id))
        for patch in ({'offset': -1}, {'offset': True}, {'offset': 10000001}, {'limit': 101}, {'limit': True}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                report.get_session_details(filters, group, **patch)
        with self.assertRaises(AccessError):
            report.with_context(allowed_company_ids=[other.id]).get_session_details(filters, dict(group, company_id=other.id))

    def test_session_groups_partition_company_and_stable_equal_timestamps(self):
        report, other = self._session_projection_fixture()
        self.manager.write({'company_ids': [Command.set([self.env.company.id, other.id])]})
        report = report.with_context(allowed_company_ids=[self.env.company.id, other.id])
        self.env.cr.execute("UPDATE baseer_print_preparation_event SET session_id=101,pos_config_id=1 WHERE id=7")
        payload = report.get_report({'preset': 'month', 'month': '2026-10'})
        groups = self._session_groups(payload)
        same_session = [group for group in groups if group['session_id'] == 101]
        self.assertEqual(len(same_session), 2)
        self.assertEqual({group['company_id'] for group in same_session}, {self.env.company.id, other.id})
        other_group = next(group for group in same_session if group['company_id'] == other.id)
        self.assertEqual([row['id'] for row in report.get_session_details(payload['filters'], other_group)['details']], [30])
        self.assertEqual([group['key'] for group in groups],
                         [group['key'] for group in self._session_groups(report.get_report(payload['filters']))])
        self.assertEqual(sum(group['detail_count'] for group in groups), payload['pagination']['total'])

    def _session_money_fixture(self):
        report, other = self._session_projection_fixture()
        sar = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'SAR')], limit=1)
        usd = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'USD')], limit=1)
        self.assertTrue(sar and usd)
        self.env.cr.execute('UPDATE baseer_pos_substitution SET source_gross=10,currency_id=%s', [sar.id])
        self.env.cr.execute('UPDATE baseer_pos_protected_item_cancellation SET source_gross=0,currency_id=%s', [sar.id])
        # Preparation and full-order snapshots never become monetary evidence.
        for table in ('baseer_print_preparation_event', 'baseer_print_cancellation'):
            self.env.cr.execute(SQL('UPDATE %s SET source_gross=9999,currency_id=%s', SQL.identifier(table), sar.id))
        self.env.cr.execute("""
            INSERT INTO baseer_pos_substitution
                (id,company_id,order_id,pos_config_id,cashier_id,event_at,order_reference,
                 source_snapshot,replacement_snapshot,source_quantity,reason_note,source_line_uuid,
                 session_id,source_gross,currency_id)
            SELECT x.id,s.company_id,1000+x.id,s.pos_config_id,s.cashier_id,s.event_at,'MONEY/'||x.id,
                s.source_snapshot,s.replacement_snapshot,x.quantity,s.reason_note,'money-'||x.id,
                s.session_id,x.amount,x.currency_id
            FROM baseer_pos_substitution s CROSS JOIN (VALUES
                (100,1::numeric,10::numeric,%s),(101,1,10,%s),(102,2.005,12.345,%s),
                (103,0,0,%s),(104,NULL,NULL,%s),(105,1,9,NULL),(106,1,19,2147483647)
            ) AS x(id,quantity,amount,currency_id) WHERE s.id=3
        """, [sar.id, sar.id, usd.id, sar.id, sar.id])
        return report, other, sar, usd

    @staticmethod
    def _metric(group, key):
        return next(metric for metric in group['metrics'] if metric['key'] == key)

    def test_session_money_exact_sums_multiple_currencies_and_missing_evidence(self):
        report, other, sar, usd = self._session_money_fixture()
        payload = report.get_report({'preset': 'month', 'month': '2026-10', 'limit': 1})
        groups = self._session_groups(payload)
        group = next(group for group in groups if group['date']=='2026-10-01' and group['session_id']==102)
        self.assertEqual([metric['key'] for metric in group['metrics']], ['substitution', 'cancellation', 'reduction'])
        metric = self._metric(group, 'substitution')
        self.assertEqual(metric['operations'], '8')
        self.assertIs(metric['has_operations'], True)
        self.assertEqual(metric['quantity'], '7.01')
        self.assertEqual(metric['quantity_missing'], '1')
        self.assertIs(metric['has_quantity_missing'], True)
        self.assertEqual(metric['amounts'], [
            {'currency_id': sar.id, 'currency': 'SAR', 'amount': '30.00'},
            {'currency_id': usd.id, 'currency': 'USD', 'amount': '12.35'}])
        self.assertEqual(metric['missing_amounts'], '3')
        self.assertIs(metric['has_missing_amounts'], True)
        # A currency absent from the permitted ORM lookup must add its known rows to missing evidence.
        self.assertNotIn(2147483647, [amount['currency_id'] for amount in metric['amounts']])
        self.assertTrue(all('gross_amount' not in row for row in payload['details']))
        details = report.get_session_details(payload['filters'], group, limit=2)
        self.assertTrue(all('gross_amount' not in row for row in details['details']))
        json.dumps(payload)
        json.dumps(details)

    def test_session_money_known_zero_dedup_and_missing_quantities(self):
        report, other, sar, usd = self._session_money_fixture()
        self.env.cr.execute('UPDATE baseer_print_preparation_event SET delta_quantity=NULL WHERE id=3')
        payload = report.get_report({'preset': 'month', 'month': '2026-10'})
        groups = self._session_groups(payload)
        group = next(group for group in groups if group['session_id']==101)
        cancellation = self._metric(group, 'cancellation')
        self.assertEqual(cancellation['operations'], '1')
        self.assertEqual(cancellation['quantity'], '5.00')
        self.assertEqual(cancellation['amounts'], [{'currency_id': sar.id, 'currency': 'SAR', 'amount': '0.00'}])
        self.assertEqual(cancellation['missing_amounts'], '1')
        self.assertEqual(cancellation['quantity_missing'], '0')
        reduction = self._metric(group, 'reduction')
        self.assertEqual(reduction['operations'], '1')
        self.assertEqual(reduction['quantity'], 'Not recorded')
        self.assertEqual(reduction['quantity_missing'], '1')
        self.assertEqual(reduction['missing_amounts'], '1')
        self.assertEqual(reduction['amounts'], [])
        empty = self._metric(group, 'substitution')
        self.assertEqual(empty, dict(key='substitution',operations='0',has_operations=False,quantity='0.00',
                                    quantity_missing='0',has_quantity_missing=False,amounts=[],
                                    missing_amounts='0',has_missing_amounts=False))
        full_order = self._metric(next(group for group in groups if group['session_id']==103), 'cancellation')
        self.assertEqual(full_order['quantity'], '5.00')
        self.assertEqual(full_order['quantity_missing'], '4')
        self.assertEqual(full_order['missing_amounts'], '5')
        self.assertEqual(full_order['amounts'], [])
        self.env.cr.execute('SELECT gross_amount,currency_id FROM report_test WHERE source_model=%s',
                            ['baseer.print.preparation.event'])
        self.assertTrue(all(amount is None and currency is None for amount,currency in self.env.cr.fetchall()))
        self.env.cr.execute('SELECT gross_amount,currency_id FROM report_test WHERE source_model=%s',
                            ['baseer.print.cancellation'])
        self.assertTrue(all(amount is None and currency is None for amount,currency in self.env.cr.fetchall()))

    def test_session_money_filters_and_pages_keep_full_scope(self):
        report, other, sar, usd = self._session_money_fixture()
        payload = report.get_report({'preset': 'month', 'month': '2026-10', 'group_limit': 2, 'limit': 1})
        next_page = report.get_report(dict(payload['filters'], group_offset=2))
        group = next(group for group in self._session_groups(next_page) if group['session_id']==102)
        whole = report.get_report(dict(payload['filters'], group_limit=50, limit=100))
        whole_group = next(item for item in self._session_groups(whole) if item['key']==group['key'])
        self.assertEqual(group['metrics'], whole_group['metrics'])
        report.get_session_details(whole['filters'], group, offset=2, limit=2)
        after_details = report.get_report(next_page['filters'])
        self.assertEqual(group['metrics'], next(item['metrics'] for item in self._session_groups(after_details)
                                             if item['key']==group['key']))
        self.assertEqual(payload['kpis'], whole['kpis'])
        only_substitutions = report.get_report(dict(whole['filters'], event_type='substitution'))
        filtered = next(item for item in self._session_groups(only_substitutions) if item['session_id']==102)
        self.assertEqual(self._metric(filtered, 'substitution'), self._metric(group, 'substitution'))
        self.assertEqual(self._metric(filtered, 'cancellation')['operations'], '0')
        self.assertTrue(all(item['company_id']==self.env.company.id for item in self._session_groups(whole)))
        outside = report.get_report(dict(whole['filters'], cashier_id=2147483647))
        self.assertEqual(outside['session_days'], [])
        outside = report.get_report(dict(whole['filters'], pos_config_id=2147483647))
        self.assertEqual(outside['session_days'], [])
        outside = report.get_report(dict(whole['filters'], shift='evening', preset='day', day='2026-10-01'))
        self.assertEqual(outside['session_days'], [])
