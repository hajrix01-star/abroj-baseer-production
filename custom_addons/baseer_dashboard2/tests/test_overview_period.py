from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.month_names import month_label
from ..models.sections import expenses_ex_purchases


@tagged('post_install', '-at_install', 'overview_period_v6')
class TestOverviewPeriod(TransactionCase):
    def _service(self):
        service = self.env['baseer.dashboard2.service']
        company = self.env.company
        self.env['ir.config_parameter'].set_param('baseer_dashboard2.company_map', '%s:Test' % company.id)
        return service, company

    def test_default_period_is_today(self):
        service, company = self._service()
        meta = service.get_meta()
        today = fields.Date.to_string(fields.Date.context_today(service))
        previous = (fields.Date.context_today(service).replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        self.assertEqual(meta['default_month'], previous)
        self.assertEqual(meta['default_period']['mode'], 'today')
        self.assertEqual(meta['default_period']['date'], today)
        self.assertEqual(meta['today'], today)
        self.assertNotIn(54, [c.get('id') for c in meta['companies']])
        self.assertNotIn(56, [c.get('id') for c in meta['companies']])

    def test_period_modes(self):
        service, _company = self._service()
        today = fields.Date.context_today(service)
        self.assertEqual(service._period({'mode': 'today'}), (today, today))
        yesterday = today - timedelta(days=1)
        self.assertEqual(service._period({'mode': 'yesterday'}), (yesterday, yesterday))
        self.assertEqual(service._period({'mode': 'date', 'date': '2026-11-15'}), (date(2026, 11, 15), date(2026, 11, 15)))
        october = service._period({'mode': 'month', 'month': '2026-10'})
        self.assertEqual(october, (date(2026, 10, 1), date(2026, 10, 31)))
        year = service._period({'mode': 'year', 'year': 2025})
        self.assertEqual(year, (date(2025, 1, 1), date(2025, 12, 31)))
        if today.year == 2026 and today.month == 11:
            current = service._period({'mode': 'month', 'month': '2026-11'})
            self.assertEqual(current, (date(2026, 11, 1), today))
            ytd = service._period({'mode': 'year', 'year': 2026})
            self.assertEqual(ytd, (date(2026, 1, 1), today))
        with self.assertRaises(UserError):
            service._period({'mode': 'week'})
        prev = service._comparison_bounds(date(2026, 11, 27), date(2026, 11, 27), 'date', 'previous_period')
        self.assertEqual(prev, (date(2026, 10, 27), date(2026, 10, 27)))
        prev_yesterday = service._comparison_bounds(yesterday, yesterday, 'yesterday', 'previous_period')
        self.assertEqual(prev_yesterday, service._comparison_bounds(yesterday, yesterday, 'date', 'previous_period'))
        year_bounds = service._comparison_bounds(date(2026, 11, 1), date(2026, 11, 27), 'month', 'previous_year')
        self.assertEqual(year_bounds, (date(2025, 11, 1), date(2025, 11, 27)))

    def test_overview_cards_and_sales_line(self):
        service, company = self._service()
        key = str(company.id)
        month = service.get_section('overview', {'company_key': key, 'period': {'mode': 'month', 'month': '2026-10'}})
        self.assertTrue(month['available'])
        self.assertIn('cards', month)
        self.assertIn('sales_line', month)
        cards = month['cards']
        self.assertEqual(cards['mode'], 'month')
        for name in ('today_sales', 'period_sales', 'net', 'purchases', 'expenses'):
            self.assertIn(name, cards, name)
            self.assertIn('previous', cards[name])
            self.assertIn('previous_year', cards[name])
        self.assertEqual(cards['expenses']['value'], expenses_ex_purchases(month['current']))
        self.assertAlmostEqual(
            cards['expenses']['value'] + (month['current']['categories'].get('food_cost') or 0),
            sum(month['current']['categories'].get(k, 0) for k in (
                'food_cost', 'salaries', 'rent', 'utilities', 'marketing', 'commissions',
                'other_opex', 'depreciation', 'non_operating', 'zakat_tax',
            )),
            places=2,
        )
        self.assertEqual(month['sales_line']['granularity'], 'day')
        self.assertEqual(len(month['sales_line']['points']), 31)
        self.assertEqual(month['sales_line']['points'][0]['label'], '1')
        self.assertIn('previous_year', month['sales'])
        self.assertIn('apps', month['sales']['previous_year'])
        self.assertIn('customers', month['sales']['previous_year'])
        if month['sales_line'].get('peak'):
            self.assertIn('day', month['sales_line']['peak'])
        today = service.get_section('overview', {'company_key': key, 'period': {'mode': 'today'}})
        self.assertTrue(today['available'])
        self.assertEqual(today['cards']['mode'], 'today')
        self.assertEqual(today['period']['date_from'], today['period']['date_to'])
        year = service.get_section('overview', {'company_key': key, 'period': {'mode': 'year', 'year': 2026}})
        self.assertTrue(year['available'])
        self.assertNotIn('today_sales', year['cards'])
        self.assertEqual(year['cards']['period_sales']['kind'], 'ytd')
        self.assertEqual(year['sales_line']['granularity'], 'month')
        self.assertEqual(len(year['sales_line']['points']), 12)
        self.assertEqual(year['sales_line']['points'][0]['label'], month_label('2026-01', short=True))
        self.assertEqual(year['sales_line']['points'][11]['label'], 'Dec')

    def test_yesterday_cards_match_single_day(self):
        service, company = self._service()
        key = str(company.id)
        today = fields.Date.context_today(service)
        yesterday = today - timedelta(days=1)
        section = service.get_section('overview', {'company_key': key, 'period': {'mode': 'yesterday'}})
        self.assertTrue(section['available'])
        self.assertEqual(section['cards']['mode'], 'yesterday')
        self.assertEqual(section['period']['date_from'], str(yesterday))
        self.assertEqual(section['period']['date_to'], str(yesterday))
        self.assertEqual(section['cards']['today_sales']['date'], str(yesterday))
        for name in ('today_sales', 'period_sales', 'net', 'purchases', 'expenses'):
            self.assertIn(name, section['cards'], name)
        self.assertEqual(section['cards']['period_sales']['kind'], 'mtd')
        # Same five-card layout as today: day sales + MTD + net/purchases/expenses for that day.
        today_section = service.get_section('overview', {'company_key': key, 'period': {'mode': 'today'}})
        self.assertEqual(set(section['cards']) & {'today_sales', 'period_sales', 'net', 'purchases', 'expenses'},
                         set(today_section['cards']) & {'today_sales', 'period_sales', 'net', 'purchases', 'expenses'})
        self.assertNotIn(54, [c.get('id') for c in service.get_meta()['companies']])
        self.assertNotIn(56, [c.get('id') for c in service.get_meta()['companies']])

    def test_english_month_labels_stay_english(self):
        self.assertEqual(month_label(date(2026, 11, 1)), 'November')
        self.assertEqual(month_label('2026-11', short=True), 'Nov')


    def test_xml_templates_avoid_string_number_globals(self):
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / 'static' / 'src'
        # OWL does not expose String/Number on the template ctx (unlike Math/Date).
        forbidden = re.compile(r'(?<![\w.])(?:String|Number)\s*\(')
        offenders = []
        for path in root.rglob('*.xml'):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if forbidden.search(line):
                    offenders.append('%s:%s: %s' % (path.name, number, line.strip()))
        self.assertFalse(offenders, '\n'.join(offenders))
