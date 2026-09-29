"""Read-only monthly financial/source/export regression. QA only.

No committed ledger/configuration writes. Vendor execution audits can persist.
"""
import calendar
import json
import time
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from openpyxl import load_workbook
from odoo.exceptions import AccessError, UserError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
c = env['res.company'].browse(9).exists()
assert c.name == 'QA الفئات النقدية'
scoped = env(context=dict(env.context, allowed_company_ids=c.ids, lang='en_US'))
report = scoped['eh.account.dynamic.report'].search([('code', '=', 'baseer_cash_categories')], limit=1)
root = Path('/mnt/qa-evidence')
checks, timings = [], []
options = {'date': {'mode': 'range', 'date_from': '2026-09-01', 'date_to': '2026-09-30'},
           'company_ids': c.ids, 'posted_only': True, 'baseer_include_tax': True}

def check(ok, name, **data):
    assert ok, (name, data)
    checks.append(dict(check=name, passed=True, **data))

def dec(value):
    return Decimal(str(value)).quantize(Decimal('.01'))

def cell(row, expression):
    return next(v for v in row['columns'] if v['expression_label'] == expression)

def rows(payload):
    return {v['id']: v for v in payload['lines']}

def render(opts):
    start = time.monotonic()
    result = report.render(opts, use_cache=False)
    timings.append({'months': opts.get('baseer_months'), 'seconds': round(time.monotonic()-start, 3)})
    return result

def records(action):
    model = scoped[action['res_model']]
    result = model.browse(action['res_id']).exists() if action.get('res_id') else model.search(action['domain'])
    check(all(r.company_id == c for r in result), 'source company isolation')
    return result

try:
    for inclusive in (True, False):
        opts = dict(options, baseer_months=['2026-07', '2026-09'], baseer_include_tax=inclusive)
        payload = render(opts)
        by_id = rows(payload)
        expected = {'receipts': 460 if inclusive else 400, 'payments': -731 if inclusive else -677,
                    'actual_net_movement': -271, 'displayed_net_movement': -271 if inclusive else -277,
                    'balance_check': 0}
        for key, value in expected.items():
            check(dec(payload['totals'][key]) == dec(value), 'selected-month total '+key, inclusive=inclusive)
        check(len(by_id) == len(payload['lines']), 'unique monthly canonical IDs')
        check([col['expression_label'] for col in payload['columns'][1:]] ==
              ['month_2026_07', 'month_2026_09', 'amount', 'receipt_share'], 'selected months only, ordered columns')
        for ident in ('receipts', 'payments'):
            check(dec(cell(by_id[ident], 'month_2026_07')['value']) == 0, 'empty July is zero '+ident)
            check(dec(cell(by_id[ident], 'month_2026_09')['value']) == dec(expected[ident]), 'September correct '+ident)
        pct = cell(by_id['payments'], 'receipt_share')
        expected_pct = (abs(Decimal(str(expected['payments']))) / Decimal(str(expected['receipts'])) * 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        check(dec(pct['value']) == expected_pct, 'percentage uses selected VAT basis', inclusive=inclusive)
        check(pct['display_value'] == str(expected_pct)+'%', 'percentage formatted by backend')
        for ident in ('baseer-total-opening_cash_balance', 'baseer-total-closing_cash_balance'):
            check(cell(by_id[ident], 'amount')['value'] is None, 'snapshot total unavailable '+ident)
        check(dec(cell(by_id['baseer-total-opening_cash_balance'], 'month_2026_09')['value']) == 1000,
              'September opening preserved despite skipped August')
        legacy = rows(render(dict(options, baseer_include_tax=inclusive)))
        for ident, row in by_id.items():
            if ident not in legacy or not row.get('meta', {}).get('baseer_source_drilldown'):
                continue
            for expression in ('month_2026_09', 'amount'):
                if cell(row, expression)['value'] is None:
                    continue
                action = report.get_drilldown_for_line(dict(opts, baseer_drill_column=expression), ident)
                actual = records(action)
                prior = records(report.get_drilldown_for_line(dict(options, baseer_include_tax=inclusive), ident))
                check(actual._name == prior._name and set(actual.ids) == set(prior.ids),
                      'month/total native provenance '+ident+' '+expression)
        empty_action = report.get_drilldown_for_line(dict(opts, baseer_drill_column='month_2026_07'), 'payments')
        check(not records(empty_action), 'empty month never opens unrelated operations')
        percent_action = report.get_drilldown_for_line(dict(opts, baseer_drill_column='receipt_share'), 'payments')
        check(bool(records(percent_action)), 'percentage opens outgoing evidence')
        xlsx = report.render_xlsx(opts, use_cache=False)
        wb = load_workbook(BytesIO(xlsx))
        check(any(v.value == float(expected_pct) and v.number_format == '0.00"%"'
                  for row in wb.active for v in row), 'Excel percentage points retain literal percent format')
        (root / ('cash_monthly_%s.json' % ('gross' if inclusive else 'net'))).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    august = rows(render(dict(options, baseer_months=['2026-08'])))
    check(dec(cell(august['receipts'], 'amount')['value']) == 1000, 'opening capital remains cash receipt')
    check(cell(august['payments'], 'receipt_share')['value'] is None, 'capital is not sales; zero denominator unavailable')
    both = rows(render(dict(options, baseer_months=['2026-08', '2026-09'])))
    check(dec(cell(both['receipts'], 'amount')['value']) == 1460, 'August+September cash receipts combined')
    check(dec(cell(both['payments'], 'receipt_share')['value']) == Decimal('158.91'), 'capital excluded from percentage denominator')
    year = render(dict(options, baseer_months=['2026-%02d' % m for m in range(1, 13)]))
    check(len(year['columns']) == 15, '12 selected months plus label/total/percent')
    check(dec(year['totals']['actual_net_movement']) == 729, '12 month cash movement correct')

    for mutation in [dict(baseer_months=[]), dict(baseer_months=['2026-13']),
                     dict(baseer_months=['2026-09', '2026-09']),
                     dict(baseer_months=['2023-01', '2026-09']),
                     dict(baseer_months=['2026-09'], company_ids=[6, 9])]:
        try:
            render(dict(options, **mutation))
        except (UserError, AccessError, ValueError):
            check(True, 'invalid monthly options rejected', mutation=mutation)
        else:
            raise AssertionError(('invalid options accepted', mutation))
    for expression in ('month_2026_08', 'forged', '__proto__'):
        try:
            report.get_drilldown_for_line(dict(options, baseer_months=['2026-09'], baseer_drill_column=expression), 'payments')
        except (UserError, AccessError, ValueError):
            check(True, 'forged/nonselected column rejected', expression=expression)
        else:
            raise AssertionError(('invalid column accepted', expression))
    (root / 'cash_monthly_checks.json').write_text(json.dumps({'checks': checks, 'timings': timings}, indent=2), encoding='utf-8')
    print('MONTHLY_CHECKS_SUCCESS', len(checks), 'checks', timings)
finally:
    env.cr.rollback()
