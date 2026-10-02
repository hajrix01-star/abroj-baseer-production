from pathlib import Path

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
                      {'date_from': '2026-10-01T00:00+03:00'}):
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
