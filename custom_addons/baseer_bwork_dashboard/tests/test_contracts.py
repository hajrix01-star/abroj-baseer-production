from datetime import date
from decimal import Decimal
from unittest import TestCase

from odoo.addons.baseer_bchat.contracts import ProtocolError

from ..contracts import amount, change, merge_ranges, parse_query, ratio


class Query(dict):
    """Minimal multi-query shape; actual Werkzeug parsing is covered by HTTP."""
    def __init__(self, values):
        rows = list(values.items()) if isinstance(values, dict) else list(values)
        super().__init__(rows)
        self.counts = {key: sum(name == key for name, _value in rows) for key in self}

    def getlist(self, key):
        return [self[key]] * self.counts.get(key, 0) if key in self else []


class TestLeadershipContract(TestCase):
    def test_exact_money_signed_zero_and_unavailable(self):
        self.assertEqual(amount(Decimal('1.005'))['value'], '1.01')
        self.assertEqual(amount(Decimal('-1.005'))['value'], '-1.01')
        self.assertEqual(amount(Decimal('-0'))['value'], '0.00')
        self.assertEqual(amount(Decimal('10000'))['display'], '10,000.00')
        self.assertFalse(amount(None)['available'])
        self.assertFalse(ratio(Decimal(1), Decimal(0))['available'])
        self.assertEqual(change(Decimal(75), Decimal(100))['value'], '-25.00')

    def test_strict_queries_and_calendar_bounds(self):
        today = date(2026, 10, 19)
        query = Query({'month': '2026-09', 'period': 'today'})
        self.assertEqual(parse_query(query, today)['first'], today)
        query['period'] = 'month'
        self.assertEqual(parse_query(query, today)['last'], date(2026, 9, 30))
        for pairs in (
            [('month', '2026-09'), ('period', 'date'), ('date', '2026-10-01')],
            [('month', '2026-09'), ('period', 'today'), ('date', '2026-09-01')],
            [('month', '2026-09'), ('period', 'month'), ('sudo', '1')],
            [('month', '2026-09'), ('period', 'month'), ('company_id', '0')],
            [('month', '2026-09'), ('period', 'month'), ('period', 'today')],
            [('month', '0001-01'), ('period', 'month')],
            [('month', '1899-12'), ('period', 'month')],
            [('month', '9999-01'), ('period', 'month')],
        ):
            with self.assertRaises(ProtocolError):
                parse_query(Query(pairs), today)
        for month in ('1900-01', '9998-12'):
            self.assertEqual(parse_query(Query({'month': month, 'period': 'month'}), today)['month'], month)

    def test_union_does_not_fill_historical_gap(self):
        a, b, c = date(2025, 1, 1), date(2025, 1, 10), date(2026, 10, 1)
        self.assertEqual(merge_ranges([(a, b), (a, a), (c, c)]), [(a, b), (c, c)])
