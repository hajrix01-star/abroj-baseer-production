"""Print a C1 producer fixture without importing/running Odoo.

Runs the real backend plan/calendar/serialization functions with synthetic source
seams. This verifies producer/consumer wire compatibility, NOT financial parity,
source ACLs, source capacity or actual ORM/HTTP behavior. Does not write files.
"""
import ast
import calendar
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace


def fixture():
    module_root = Path(__file__).resolve().parents[1]
    helpers = ast.parse((module_root / 'contracts.py').read_text(encoding='utf-8'))
    helpers.body = [node for node in helpers.body if not (
        isinstance(node, ast.ImportFrom) and node.module.startswith('odoo'))]
    namespace = {'ProtocolError': ValueError, 'ValidationError': ValueError}
    exec(compile(helpers, 'contracts.py', 'exec'), namespace)
    source = ast.parse((module_root / 'models/leadership.py').read_text(encoding='utf-8'))
    producer = next(node for node in source.body if isinstance(node, ast.ClassDef))
    names = {'_leadership', '_leadership_plan', '_leadership_calendar',
             '_leadership_observations', '_leadership_company_rows',
             '_leadership_sales', '_leadership_spending', '_leadership_reconcile'}
    producer.bases = []
    producer.body = [node for node in producer.body if isinstance(node, ast.FunctionDef) and node.name in names]
    now = datetime(2026, 10, 19, 9)
    namespace.update(api=SimpleNamespace(model=lambda function: function),
        fields=SimpleNamespace(Date=SimpleNamespace(context_today=lambda *args, **kwargs: now.date()),
            Datetime=SimpleNamespace(now=lambda: now, to_datetime=lambda value: value)))
    exec(compile(ast.Module(body=[producer], type_ignores=[]), 'leadership.py', 'exec'), namespace)
    Service = namespace['LeadershipService']

    def sales_for_day(day):
        return Decimal('0.00') if day.day == 1 else Decimal('100.00')

    class Source:
        def get_baseer_sales_metrics(self, filters):
            bounds = filters['native']
            cursor, last = date.fromisoformat(bounds['from']), date.fromisoformat(bounds['to'])
            total = Decimal(0)
            while cursor <= last:
                total += sales_for_day(cursor)
                cursor += timedelta(days=1)
            return {'cards': {'sales': {'value': str(total)}}}

        def _baseer_purchase_domain(self, company, first, last):
            return first, last

        def _baseer_purchase_totals(self, bounds, currency):
            return (Decimal((bounds[1] - bounds[0]).days + 1) * Decimal(20), 0, 0, 0)

        def get_baseer_heat_calendar(self, month):
            first = date.fromisoformat(month + '-01')
            rows = []
            for day in range(1, calendar.monthrange(first.year, first.month)[1] + 1):
                when = first.replace(day=day)
                complete = when < now.date()
                rows.append({'date': when.isoformat(), 'day': day, 'weekday': when.weekday(),
                    'status': 'complete' if complete else 'incomplete',
                    'status_label': 'Complete' if complete else 'Incomplete',
                    'has_sales': True, 'sales_value': str(sales_for_day(when)),
                    'target_value': '100.00', 'basis_value': '100.00', 'basis_kind': 'target'})
            return {'weeks': [rows]}

    service = Service()
    service.env = SimpleNamespace(_=lambda text, **values: text % values if values else text)
    service.with_context = lambda **kwargs: service
    company = SimpleNamespace(id=7, name='Synthetic wire fixture', currency_id=SimpleNamespace(name='SAR'))
    service._leadership_companies = lambda company_id: [company]
    source = Source()
    service._leadership_reports = lambda company: (service, {'sales': source, 'spending': source, 'heat': source})
    service._leadership_preflight = lambda companies, plan: None
    selection = {'company_id': 7, 'month': '2026-10', 'period': 'month',
                 'first': date(2026, 10, 1), 'last': date(2026, 10, 31),
                 'calendar_first': date(2026, 10, 1)}
    return service._leadership(selection, as_of=now)


if __name__ == '__main__':
    print(json.dumps(fixture(), ensure_ascii=False))
