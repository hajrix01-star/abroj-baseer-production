"""Run actual pure report helpers without claiming an Odoo ORM integration test."""
import ast
import re
import unittest
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import SimpleNamespace

import pytz


class ValidationError(Exception):
    pass


source = ast.parse((Path(__file__).parents[1] / 'models' / 'report.py').read_text(encoding='utf-8'))
model = next(node for node in source.body if isinstance(node, ast.ClassDef))
selected = {'_number', '_clock', '_integer', '_normalize_filters'}
model.body = [node for node in model.body if isinstance(node, ast.FunctionDef) and node.name in selected]
model.bases = []
module = ast.fix_missing_locations(ast.Module(body=[model], type_ignores=[]))
scope = dict(re=re, date=date, datetime=datetime, time=time, timedelta=timedelta,
             Decimal=Decimal, ROUND_HALF_UP=ROUND_HALF_UP, pytz=pytz, ValidationError=ValidationError, _=lambda value: value)
exec(compile(module, 'actual-report-helpers', 'exec'), scope)
Report = scope['CancellationFollowupReport']


class TestActualFilters(unittest.TestCase):
    def setUp(self):
        self.report = Report()
        self.report.env = SimpleNamespace(context={'tz': 'Asia/Riyadh'}, user=SimpleNamespace(tz=False))
        self.base = dict(preset='custom', date_from='2026-10-01T00:00', date_to='2026-10-02T00:00')

    def test_utc_conversion_and_endpoint(self):
        filters, start, end, m, e, zone = self.report._normalize_filters(self.base)
        self.assertEqual(start.isoformat(), '2026-09-30T21:00:00')
        self.assertEqual(end.isoformat(), '2026-10-01T21:00:00')
        self.assertEqual((m, e), (360,1080))
        self.assertEqual(filters['date_to'], self.base['date_to'])

    def test_december_month_rollover(self):
        filters, start, end, *_ = self.report._normalize_filters({'preset':'month','month':'2026-12'})
        self.assertEqual(filters['date_to'], '2027-01-01T00:00')
        self.assertEqual((end-start).days,31)

    def test_leap_year_month(self):
        filters, start, end, *_ = self.report._normalize_filters({'preset':'month','month':'2028-02'})
        self.assertEqual((end-start).days,29)

    def test_overnight_morning(self):
        _, _, _, m, e, _ = self.report._normalize_filters(dict(self.base, morning_start='18:00', evening_start='06:00'))
        self.assertEqual((m,e), (1080,360))

    def test_bad_filter_matrix(self):
        for patch in ({'date_to':self.base['date_from']}, {'date_to':'2028-01-01T00:00'},
                      {'limit':True},{'limit':101},{'cashier_id':-1},{'morning_start':'25:00'},
                      {'morning_start':'18:00'},{'shift':'bad'},{'review_only':'false'},
                      {'date_from':'2026-10-01T00:00+03:00'},{'day':[]},{'month':'2026-99'}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                self.report._normalize_filters(dict(self.base, **patch))

    def test_dst_ambiguity_and_missing_clock_rejected(self):
        self.report.env.context['tz']='America/New_York'
        for value in ('2026-03-08T02:30','2026-11-01T01:30'):
            with self.assertRaises(ValidationError):
                self.report._normalize_filters(dict(self.base,date_from=value,date_to='2026-11-02T00:00'))

    def test_western_decimal_half_up(self):
        self.assertEqual(self.report._number(Decimal('1.005'),2),'1.01')
        self.assertEqual(self.report._number(1234),'1234')


if __name__ == '__main__':
    unittest.main()
