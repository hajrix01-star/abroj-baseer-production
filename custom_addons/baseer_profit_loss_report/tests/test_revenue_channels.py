"""Small deterministic allocation tests, no database or new environment."""
from decimal import Decimal
from datetime import date
from odoo.tests.common import TransactionCase, tagged
from odoo.fields import Domain
from types import SimpleNamespace
from ..models.profit_loss import BaseerProfitLossReport
from ..models.revenue_channels import (
    allocate_channels, UNALLOCATED, tender_matches_order, reconcile_order_amounts,
    noorix_gross_channels,
)


@tagged('post_install', '-at_install')
class TestRevenueChannels(TransactionCase):
    def test_noorix_gross_channels_use_named_original_funding_only(self):
        class Records(list):
            def filtered(self, predicate):
                return Records(item for item in self if predicate(item))

            def mapped(self, name):
                return Records({getattr(item, name).id: getattr(item, name) for item in self}.values())

            @property
            def id(self):
                return self[0].id

        company = SimpleNamespace(currency_id=object())
        income = SimpleNamespace(id=1, account_type='income', internal_group='income')
        cash = SimpleNamespace(id=2, account_type='asset_cash', internal_group='asset')
        bank = SimpleNamespace(id=3, account_type='asset_cash', internal_group='asset')
        def line(name, account, balance):
            return SimpleNamespace(name=name, account_id=account, balance=balance,
                                   company_id=company, currency_id=company.currency_id)
        cash_line = line('Noorix sales cash 2026-11-01', cash, '15.00')
        bank_line = line('Noorix sales bank 2026-11-01', bank, '100.00')
        move = SimpleNamespace(date=date(2026, 11, 1), line_ids=Records([
            line('Sales', income, '-100.00'), cash_line, bank_line,
        ]))
        event = {'original': True, 'move': move, 'amount': Decimal('115.00')}
        self.assertEqual(noorix_gross_channels(event, company),
                         (1, {'cash': Decimal('15.00'), 'bank': Decimal('100.00')}, {'cash': 2, 'bank': 3}))
        self.assertIsNone(noorix_gross_channels({**event, 'amount': Decimal('114.99')}, company))
        self.assertIsNone(noorix_gross_channels({**event, 'original': False}, company))
        bank_line.name = 'unrecognised funding'
        self.assertIsNone(noorix_gross_channels(event, company))
        bank_line.name = 'Noorix sales bank 2026-11-01'
        move.line_ids.append(line('Noorix sales cash 2026-11-01', bank, '1.00'))
        self.assertIsNone(noorix_gross_channels({**event, 'amount': Decimal('116.00')}, company))

    def test_identity_census_empty_deduplicated_and_bounded_chunks(self):
        calls = []
        class Model:
            def flush_model(self, fields):
                pass
        class Cursor:
            def execute(self, query, args):
                calls.append((query, list(args[0])))
            def fetchmany(self, limit):
                self_limit = limit
                assert self_limit == 1000
                return []
        class Env(dict):
            cr = Cursor()
        report = SimpleNamespace(env=Env({'pos.order.line': Model(), 'pos.payment': Model()}))
        collect = BaseerProfitLossReport._channel_child_ids
        self.assertEqual(collect(report, SimpleNamespace(ids=[])), {'lines': {}, 'payments': {}})
        self.assertEqual(calls, [])
        ids = list(range(1, 1002)) + [1, 2, 1001]
        result = collect(report, SimpleNamespace(ids=ids))
        self.assertEqual(len(calls), 4)
        self.assertEqual([len(chunk) for _query, chunk in calls], [1000, 1000, 1, 1])
        self.assertEqual(set(result['lines']), set(ids))
        self.assertEqual(set(result['payments']), set(ids))
        self.assertTrue(all(not values for section in result.values() for values in section.values()))

    def test_posted_rounding_residual_preserves_ledger(self):
        unit = Decimal('.01')
        for sign in (Decimal('1'), Decimal('-1')):
            source = [('order', Decimal('46.08') * sign)]
            posted = Decimal('46.09') * sign
            adjusted = reconcile_order_amounts(source, posted, unit)
            self.assertEqual(adjusted, [('order', posted)])
            self.assertEqual(source, [('order', Decimal('46.08') * sign)])
            payments = [('bank', 'Bank', Decimal('53') * sign)]
            self.assertEqual(allocate_channels(adjusted[0][1], payments, unit),
                             {'bank': ('Bank', posted)})

    def test_rounding_limit_is_per_account_not_per_order(self):
        source = [('a', Decimal('15.65')), ('b', Decimal('30.43'))]
        adjusted = reconcile_order_amounts(source, Decimal('46.09'), Decimal('.01'))
        self.assertEqual(adjusted, [('a', Decimal('15.65')), ('b', Decimal('30.44'))])
        self.assertEqual(sum(value for _order, value in adjusted), Decimal('46.09'))
        for posted in (Decimal('46.10'), Decimal('-46.08'), Decimal('0')):
            self.assertIsNone(reconcile_order_amounts(source, posted, Decimal('.01')))
        self.assertIsNone(reconcile_order_amounts([], Decimal('0'), Decimal('.01')))
        self.assertIsNone(reconcile_order_amounts([('a', Decimal('0'))],
                                                Decimal('.01'), Decimal('.01')))

    def test_order_adapter_currency_and_partial_fallback(self):
        class Records(list):
            def check_access(self, _mode):
                pass
            def sorted(self, _field):
                return self
        class Cursor:
            def execute(self, *_args):
                pass
            def fetchall(self):
                return [(1,)]
        class Model:
            def flush_model(self, _fields):
                pass
        currency = SimpleNamespace(rounding=.01)
        company = SimpleNamespace(currency_id=currency)
        method = SimpleNamespace(id=1, name='Cash', company_id=company)
        tenders = Records([SimpleNamespace(id=1, payment_method_id=method, amount=50)])
        tenders.ids = [1]
        tenders.payment_method_id = Records([method])
        order = SimpleNamespace(id=5, company_id=company, currency_id=currency,
            payment_ids=tenders, amount_total=115, is_refund=False,
            check_access=lambda _mode: None)
        class Env(dict):
            cr = Cursor()
        report = SimpleNamespace(env=Env({'pos.payment': Model()}),
                                 _decimal=lambda value: Decimal(str(value)))
        call = BaseerProfitLossReport._order_channels
        self.assertEqual(call(report, order, Decimal('100'), company),
                         {UNALLOCATED: ('', Decimal('100'))})
        tenders[0].amount = 115
        self.assertEqual(call(report, order, Decimal('100'), company),
                         {'payment_1': ('Cash', Decimal('100'))})
        order.currency_id = SimpleNamespace(rounding=.05)
        self.assertEqual(call(report, order, Decimal('100'), company),
                         {UNALLOCATED: ('', Decimal('100'))})

    def test_partial_tender_not_sale_channel(self):
        self.assertFalse(tender_matches_order([('a', 'Cash', 50)], Decimal('115'), Decimal('.01')))
        self.assertTrue(tender_matches_order([('a', 'Cash', 50), ('b', 'Card', 65)],
                                            Decimal('115'), Decimal('.01')))
        self.assertFalse(tender_matches_order([('a', 'Cash', -115)], Decimal('115'), Decimal('.01')))

    def allocate(self, amount, payments):
        return allocate_channels(Decimal(amount), payments, Decimal('.01'))

    def test_mixed_penny_residual(self):
        result = self.allocate('.05', [('a', 'Cash', 1), ('b', 'Card', 1)])
        self.assertEqual(result['a'][1], Decimal('.03'))
        self.assertEqual(result['b'][1], Decimal('.02'))
        self.assertEqual(sum(x[1] for x in result.values()), Decimal('.05'))

    def test_change_netted_in_same_method(self):
        result = self.allocate('80', [('a', 'Cash', 100), ('a', 'Cash', -20)])
        self.assertEqual(result['a'][1], Decimal('80'))

    def test_signed_refund(self):
        result = self.allocate('-50', [('a', 'Cash', -20), ('b', 'Card', -30)])
        self.assertEqual(result['a'][1], Decimal('-20'))
        self.assertEqual(result['b'][1], Decimal('-30'))

    def test_sale_against_refund_payments_falls_back(self):
        self.assertEqual(self.allocate('50', [('a', 'Cash', -50)]),
                         {UNALLOCATED: ('', Decimal('50'))})
        self.assertEqual(self.allocate('-50', [('a', 'Cash', 50)]),
                         {UNALLOCATED: ('', Decimal('-50'))})

    def test_zero_or_unproved_falls_back(self):
        for payments in ([], [('a', 'Cash', 10), ('b', 'Card', -10)],
                         [('a', 'Cash', 10), ('b', 'Card', -2)]):
            self.assertEqual(self.allocate('7.17', payments),
                             {UNALLOCATED: ('', Decimal('7.17'))})

    def test_source_order_does_not_change_rounding(self):
        payments = [('b', 'Card', 1), ('a', 'Cash', 1)]
        self.assertEqual(self.allocate('.05', payments),
                         self.allocate('.05', list(reversed(payments))))
