"""SD1 QA-only endpoint contract checks, with rollback-only aggregation fixtures.

Run inside the isolated Odoo shell with an `env`. SQL fixtures intentionally
simulate the already-approved reporting rows, NOT native POS posting. This
suite verifies the new read API and shared aggregation policy. It does not
recertify accounting, tax posting, or production capacity.
"""
import hashlib
import json
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError


assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA database only'
checks = []
profiles = []
fixture_ids = []
closure_ids = []
started = time.monotonic()
result = {'status': 'FAIL', 'database': env.cr.dbname,
          'scope': 'Read endpoint and shared aggregation; SQL reporting fixtures, not native posting tests',
          'rollback': False}


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    checks.append(label)


def denied(label, callback):
    try:
        with env.cr.savepoint():
            callback()
    except (AccessError, UserError, ValidationError, ValueError, TypeError):
        checks.append(label)
    else:
        raise AssertionError(label)


def num(card):
    return Decimal(str(card['value'])) if card['available'] else None


def fingerprint():
    env.flush_all()
    tables = ('account_move', 'account_move_line', 'account_payment',
              'pos_order', 'pos_order_line', 'pos_session', 'pos_payment',
              'baseer_pos_summary', 'baseer_pos_closure',
              'baseer_pos_daily_report', 'baseer_pos_daily_report_line')
    answer = {}
    for table in tables:
        env.cr.execute("SELECT count(*), md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY id), '')) FROM " + table + ' t')
        answer[table] = env.cr.fetchone()
    return answer


try:
    company = env['res.company'].browse(6).exists()
    other = env['res.company'].browse(7).exists()
    assert company and other, 'QA companies 6 and 7 are required'
    qa = env(context=dict(env.context, allowed_company_ids=[company.id], lang='en_US', tz='Asia/Riyadh'))
    config = qa['pos.config'].search([('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
    assert config, 'QA source company needs its dedicated POS config'
    dashboard = qa.ref('baseer_sales_dashboard.dashboard_sales_summary')
    for fixture_start, fixture_end in [('2020-05-31','2020-06-09'),('2023-01-01','2024-12-31'),
                                      ('2029-12-30','2030-01-02'),('2034-01-01','2035-12-31')]:
        assert not qa['baseer.pos.summary'].search_count([
            ('company_id', '=', company.id), ('business_date', '>=', fixture_start), ('business_date', '<=', fixture_end)]), 'Fixture dates must be unused; do not overwrite QA history'
        assert not qa['baseer.pos.closure'].search_count([
            ('company_id', '=', company.id), ('date_from', '<=', fixture_end), ('date_to', '>=', fixture_start)]), 'Fixture closure dates must be unused'

    def summary(day, amount, customers, schedule='all', period='all', state='approved', archived=False):
        day = fields.Date.to_date(day)
        env.cr.execute('''INSERT INTO baseer_pos_summary
            (name,company_id,business_date,period_scope,day_schedule,state,config_id,
             customer_count,zero_sales,is_archived,amount_gross,amount_net,amount_tax,
             create_uid,write_uid,create_date,write_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,NOW(),NOW()) RETURNING id''',
            ['SD1 rollback aggregation fixture', company.id, day, period, schedule,
             state, config.id, customers, Decimal(str(amount)) == 0, archived,
             str(amount), str(amount), env.uid, env.uid])
        record_id = env.cr.fetchone()[0]
        fixture_ids.append(record_id)
        qa['baseer.pos.summary'].invalidate_model()
        return record_id

    def closure(day, scope='all', state='confirmed'):
        day = fields.Date.to_date(day)
        env.cr.execute('''INSERT INTO baseer_pos_closure
            (name,company_id,date_from,date_to,period_scope,reason,state,is_archived,
             create_uid,write_uid,create_date,write_date)
            VALUES (%s,%s,%s,%s,%s,'other',%s,false,%s,%s,NOW(),NOW()) RETURNING id''',
            ['SD1 rollback closure fixture', company.id, day, day, scope, state, env.uid, env.uid])
        closure_ids.append(env.cr.fetchone()[0])
        qa['baseer.pos.closure'].invalidate_model()

    def fetch(first=None, last=None, preset='custom', today=None, record=None):
        filters = {'preset': preset}
        if first is not None:
            filters.update(date_from=str(first), date_to=str(last or first))
        if today:
            with patch.object(fields.Date, 'context_today', return_value=fields.Date.to_date(today)):
                return (record or dashboard).get_baseer_sales_metrics(filters)
        return (record or dashboard).get_baseer_sales_metrics(filters)

    def card_is(payload, key, value, label):
        check(label, num(payload['cards'][key]) == Decimal(str(value)))

    empty = fetch('2030-01-01', '2030-01-02')
    check('Empty API has five contract cards', set(empty['cards']) == {'sales', 'customers', 'daily_sales', 'daily_customers', 'average_bill'})
    check('Empty periods do not manufacture comparisons', all(not row['comparison']['available'] for row in empty['cards'].values()))
    check('No operating-day average on missing dates', not empty['cards']['daily_sales']['available'] and not empty['cards']['average_bill']['available'])
    check('Missing dates are null chart points', len(empty['timeline']['points']) == 2 and all(p['sales'] is None and p['customers'] is None for p in empty['timeline']['points']))

    # Ratio of sums must differ from the unweighted average of per-day ratios.
    summary('2024-01-01', '115.00', 5)
    summary('2024-01-02', '345.00', 3)
    simple = fetch('2024-01-01', '2024-01-02')
    for key, value in [('sales', 460), ('customers', 8), ('daily_sales', 230), ('daily_customers', 4), ('average_bill', '57.50')]:
        card_is(simple, key, value, 'Two-day ratio contract: ' + key)
    check('Financial values are exact decimal strings', all(isinstance(simple['cards'][key]['value'], str) for key in ('sales', 'daily_sales', 'average_bill')))
    check('Count card preserves integer type', isinstance(simple['cards']['customers']['value'], int))

    summary('2024-01-03', 100, 10, 'split', 'morning')
    summary('2024-01-03', 200, 20, 'split', 'evening')
    summary('2024-01-04', 70, 7, 'split', 'morning')
    draft_id = summary('2024-01-04', 999, 99, 'split', 'evening', 'draft')
    summary('2024-01-05', 50, 5, 'split', 'morning')
    closure('2024-01-05', 'evening')
    closure('2024-01-06')
    summary('2024-01-07', 0, 0)
    summary('2024-01-09', 999, 99, state='draft')
    cancelled_id = summary('2024-01-10', 1000, 100, state='cancelled')
    summary('2024-01-10', 230, 10)
    archived_id = summary('2024-01-11', 80, 4, archived=True)
    full = fetch('2024-01-01', '2024-01-11')
    check('Split day, closure and missing coverage', full['coverage'] == {'operating_days': 7, 'incomplete_days': 1, 'closed_days': 1, 'missing_days': 2})
    for key, value in [('sales',1190), ('customers',64), ('daily_sales',160), ('daily_customers','8.14'), ('average_bill','18.59')]:
        card_is(full,key,value,'Mixed coverage amount: '+key)
    points = {point['key']: point for point in full['timeline']['points']}
    check('Split shifts are one complete day', points['2024-01-03']['status'] == 'complete' and Decimal(points['2024-01-03']['sales']) == 300)
    check('Approved part of draft day is visible and incomplete', points['2024-01-04']['status'] == 'incomplete' and Decimal(points['2024-01-04']['sales']) == 70)
    check('Confirmed half closure completes the operated shift', points['2024-01-05']['status'] == 'complete')
    check('Full closure is a gap', points['2024-01-06']['status'] == 'closed' and points['2024-01-06']['sales'] is None)
    check('Approved no-sales operation remains real zero', points['2024-01-07']['status'] == 'complete' and Decimal(points['2024-01-07']['sales']) == 0)
    action = full['source_action']
    sources = qa[action['res_model']].with_context(active_test=False).search(action['domain'])
    check('Drilldown includes archived approved history', archived_id in sources.ids)
    check('Drilldown excludes draft and cancelled sources', draft_id not in sources.ids and cancelled_id not in sources.ids and all(s.state == 'approved' for s in sources))
    helper = qa['baseer.pos.daily.report']._aggregate_days(company.with_env(qa), '2024-01-01', '2024-01-11')
    check('Shared helper authority preserved', num(full['cards']['sales']) == helper['totals']['recorded_sales'] and num(full['cards']['daily_sales']) == helper['totals']['average_daily_sales'])

    summary('2024-01-12', 20, 0)
    missing = fetch('2024-01-01', '2024-01-12')
    check('Positive complete-day sales without customers are diagnosed', bool(missing['issues']['missing_customers']) and bool(missing['issues']['missing_complete_customers']))
    check('Missing complete customers suppress both ratio cards', not missing['cards']['daily_customers']['available'] and not missing['cards']['average_bill']['available'])
    summary('2024-02-01', 50, 5)
    summary('2024-02-02', 20, 0, 'split', 'morning')
    partial = fetch('2024-02-01', '2024-02-02')
    check('Partial-only missing customers do not invalidate complete-day customer mean', partial['cards']['daily_customers']['available'] and not partial['cards']['average_bill']['available'] and not partial['issues']['missing_complete_customers'])
    closure('2024-02-03', 'morning')
    half = fetch('2024-02-03')
    check('Half closure without the other shift remains missing', half['coverage']['missing_days'] == 1)
    summary('2024-02-04', 42, 2, 'morning', 'morning')
    check('Morning-only schedule is a complete operating date', fetch('2024-02-04')['coverage']['operating_days'] == 1)
    closure('2024-02-05', state='draft')
    check('Draft closure does not close a reporting date', fetch('2024-02-05')['coverage']['missing_days'] == 1)

    # Month bucketing aggregates the approved daily values, preserving gaps.
    summary('2024-03-01', 0, 0)
    monthly = fetch('2024-01-01', '2024-04-30')
    check('Long custom period is monthly', monthly['timeline']['granularity'] == 'month' and len(monthly['timeline']['points']) == 4)
    check('Month sums match current recorded totals', sum((Decimal(p['sales']) for p in monthly['timeline']['points'] if p['sales'] is not None), Decimal(0)) == num(monthly['cards']['sales']))
    check('Monthly customers preserve recorded total', sum(p['customers'] or 0 for p in monthly['timeline']['points']) == num(monthly['cards']['customers']))
    check('Explicit zero month differs from absent month', Decimal(monthly['timeline']['points'][2]['sales']) == 0 and monthly['timeline']['points'][3]['sales'] is None)
    check('31-day custom uses daily points', fetch('2024-01-01','2024-01-31')['filters']['granularity'] == 'day')
    check('32-day custom uses monthly points', fetch('2024-01-01','2024-02-01')['filters']['granularity'] == 'month')

    # Deterministic preset boundary checks, including leap-day clipping.
    periods = [
        ('this_month','2024-03-31','2024-03-01','2024-03-31','2024-02-01','2024-02-29','day'),
        ('last_month','2024-03-31','2024-02-01','2024-02-29','2024-01-01','2024-01-31','day'),
        ('this_year','2024-02-29','2024-01-01','2024-02-29','2023-01-01','2023-02-28','month'),
        ('this_year','2024-01-15','2024-01-01','2024-01-15','2023-01-01','2023-01-15','month'),
        ('last_year','2025-01-01','2024-01-01','2024-12-31','2023-01-01','2023-12-31','month'),
        ('last_30_days','2024-03-01','2024-02-01','2024-03-01','2024-01-02','2024-01-31','day'),
    ]
    for preset,today,first,last,prior_first,prior_last,grain in periods:
        data = fetch(preset=preset,today=today)
        check('Preset boundaries '+preset+' at '+today,
              data['filters']['date_from'] == first and data['filters']['date_to'] == last and data['filters']['granularity'] == grain
              and data['comparison_period']['date_from'] == prior_first and data['comparison_period']['date_to'] == prior_last)
    custom = fetch('2024-01-01','2024-01-02')
    check('Custom comparison is immediately preceding equal-duration range', custom['comparison_period'] == {'date_from':'2023-12-30','date_to':'2023-12-31'})
    check('Inclusive 366-day range accepted', fetch('2024-01-01','2024-12-31')['filters']['date_to'] == '2024-12-31')
    for label, filters in [
        ('367 days',{'preset':'custom','date_from':'2024-01-01','date_to':'2025-01-01'}),
        ('reversed dates',{'preset':'custom','date_from':'2024-02-02','date_to':'2024-02-01'}),
        ('bad date',{'preset':'custom','date_from':'2024-02-30','date_to':'2024-03-01'}),
        ('missing date',{'preset':'custom','date_from':'2024-01-01'}),
        ('unsupported preset',{'preset':'forever'}),
        ('injected company',{'preset':'this_month','company_id':other.id}),
        ('injected totals',{'preset':'this_month','sales':999}),
        ('list filter',[]), ('string filter','this_month'),
        ('boolean date',{'preset':'custom','date_from':True,'date_to':'2024-01-01'}),
    ]:
        denied('Reject '+label, lambda filters=filters: dashboard.get_baseer_sales_metrics(filters))

    # Independent comparison examples; neither missing dates nor unavailable
    # customer ratios may be converted into a synthetic percentage change.
    for day,amount,customers in [
        ('2020-06-01',100,2), ('2020-06-02',200,4), ('2020-06-03',100,2), ('2020-06-04',100,2),
        ('2020-06-05',0,0), ('2020-06-06',0,0), ('2020-06-07',100,2), ('2020-06-08',50,0),
    ]:
        summary(day,amount,customers)
    for day,direction,display in [('2020-06-02','up','100.00'),('2020-06-03','down','50.00'),('2020-06-04','flat','0.00'),('2020-06-05','down','100.00'),('2020-06-06','flat','0.00')]:
        comparison = fetch(day)['cards']['sales']['comparison']
        check('Comparison '+direction+' '+day, comparison['direction'] == direction and comparison['available'] and display in comparison['display'])
    fresh = fetch('2020-06-07')
    check('Positive after explicit zero is new, never infinity', fresh['cards']['sales']['comparison']['direction'] == 'new' and 'inf' not in json.dumps(fresh).lower())
    check('Unchanged ratio stays flat although sales grew', fetch('2020-06-02')['cards']['average_bill']['comparison']['direction'] == 'flat')
    check('Missing previous sample cannot imply growth from zero', not fetch('2020-06-01')['cards']['sales']['comparison']['available'])
    check('Invalid current customer ratio has no comparison', not fetch('2020-06-08')['cards']['average_bill']['comparison']['available'])
    check('Zero customer denominator cannot invent average bill', not fetch('2020-06-06')['cards']['average_bill']['available'])
    summary('2020-06-09','999999999.99',10000000,'split','morning')
    summary('2020-06-09','999999999.99',10000000,'split','evening')
    maximum = fetch('2020-06-09')
    card_is(maximum,'sales','1999999999.98','Two maximum valid shifts preserve every cent')
    card_is(maximum,'customers',20000000,'Maximum source counts add as integers')
    card_is(maximum,'average_bill','100.00','Maximum-range ratio has backend cent rounding')
    check('Large monetary display uses Western group and decimal separators',maximum['cards']['sales']['display'] == '1,999,999,999.98')

    # All principal roles use actual ORM environments (not spoofed uid context).
    group_field = 'group_ids' if 'group_ids' in env['res.users']._fields else 'groups_id'
    pos_group = env.ref('point_of_sale.group_pos_user')
    internal_group = env.ref('base.group_user')
    def user(label, groups, companies):
        return env['res.users'].with_context(no_reset_password=True).create({
            'name':'SD1 rollback '+label, 'login':'sd1-rollback-'+label,
            'company_id':companies[0].id, 'company_ids':[Command.set([c.id for c in companies])],
            group_field:[Command.set(groups.ids)], 'lang':'en_US'})
    pos_user = user('pos',internal_group | pos_group,[company,other])
    plain = user('plain',internal_group,[company])
    outsider = user('outside',internal_group | pos_group,[other])
    as_pos = dashboard.with_user(pos_user).with_context(allowed_company_ids=[company.id])
    check('Ordinary POS reader receives own-company totals', num(fetch('2024-01-01','2024-01-02',record=as_pos)['cards']['sales']) == 460)
    second = fetch('2024-01-01','2024-01-02',record=as_pos.with_context(allowed_company_ids=[other.id,company.id]))
    check('Company switch scopes active company only', second['company']['id'] == other.id and num(second['cards']['sales']) in (Decimal(0),None))
    denied('Internal non-POS reader denied', lambda: fetch('2024-01-01',record=dashboard.with_user(plain).with_context(allowed_company_ids=[company.id])))
    denied('Public user denied', lambda: fetch('2024-01-01',record=dashboard.with_user(env.ref('base.public_user')).with_context(allowed_company_ids=[company.id])))
    denied('Unauthorized active company denied', lambda: fetch('2024-01-01',record=dashboard.with_user(outsider).with_context(allowed_company_ids=[company.id])))
    ordinary = qa['spreadsheet.dashboard'].search([('id','!=',dashboard.id)],limit=1)
    assert ordinary, 'An ordinary native dashboard is needed for ownership denial'
    denied('Endpoint rejects unrelated dashboard',lambda: fetch('2024-01-01',record=ordinary))
    denied('Endpoint rejects multi-record call',lambda: fetch('2024-01-01',record=dashboard|ordinary))
    english = fetch('2024-01-01','2024-01-02')
    arabic = fetch('2024-01-01','2024-01-02',record=dashboard.with_context(lang='ar_001'))
    check('AR/EN retain same numeric values', all(arabic['cards'][k]['value'] == english['cards'][k]['value'] for k in english['cards']))
    check('Arabic presentation retains Western digits', not any(ch in json.dumps(arabic,ensure_ascii=False) for ch in '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹'))

    # Two full years, two summaries/day: compare against the existing one-company
    # scope. The benchmark is serial QA latency, not a concurrent production SLA.
    day = date(2034,1,1)
    while day <= date(2035,12,31):
        summary(day,'100.01',3,'split','morning')
        summary(day,'200.02',5,'split','evening')
        day += timedelta(days=1)
    fetch('2035-01-01','2035-12-31')
    before = fingerprint()
    for iteration in range(3):
        # New HTTP calls get fresh ORM caches. Warm the registry/rule machinery,
        # but do not benchmark a repeated in-memory recordset instead of a read.
        env.invalidate_all()
        tick = time.monotonic()
        annual = fetch('2035-01-01','2035-12-31',record=as_pos)
        profiles.append(round(time.monotonic()-tick,6))
    after = fingerprint()
    check('Endpoint preserves source, ledger and transient rows exactly', before == after)
    card_is(annual,'sales','109510.95','Annual two-shift gross total')
    card_is(annual,'customers',2920,'Annual customer count')
    card_is(annual,'daily_sales','300.03','Daily average remains daily under monthly graph')
    check('Annual monthly graph stays bounded', len(annual['timeline']['points']) == 12)
    check('Warm year request completes within local 2-second target', max(profiles) <= 2)
    result.update(status='PASS',passed=len(checks),checks=checks,seconds=round(time.monotonic()-started,3),
        fixtures={'summaries':len(fixture_ids),'closures':len(closure_ids),'method':'SQL aggregate-only simulation; never native accounting approval'},
        profile={'warm_seconds':profiles,'current_days':365,'comparison_days':365,'summaries_per_day':2,'concurrency':1,
                 'actor':'ordinary POS reader','cache':'warm registry, ORM cache invalidated before each timed request',
                 'scope':'isolated QA; no production capacity certification'},
        no_endpoint_writes=before == after)
except Exception as error:
    result.update(error=type(error).__name__+': '+str(error),passed=len(checks),checks=checks)
    raise
finally:
    env.cr.rollback()
    if fixture_ids:
        env.cr.execute('SELECT count(*) FROM baseer_pos_summary WHERE id IN %s',[tuple(fixture_ids)])
        remaining_summaries = env.cr.fetchone()[0]
    else:
        remaining_summaries = 0
    if closure_ids:
        env.cr.execute('SELECT count(*) FROM baseer_pos_closure WHERE id IN %s',[tuple(closure_ids)])
        remaining_closures = env.cr.fetchone()[0]
    else:
        remaining_closures = 0
    result['rollback'] = remaining_summaries == remaining_closures == 0
    if not result['rollback']:
        result.update(status='FAIL',error='QA fixture rollback verification failed')
    result['remaining_fixture_rows'] = {'summaries':remaining_summaries,'closures':remaining_closures}
    env.cr.rollback()
    root = Path('/mnt/sales-dashboard-addons/baseer_sales_dashboard')
    if root.exists():
        result['source_sha256'] = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    Path('/mnt/qa-evidence/sales-dashboard-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('SD1_CHECKS='+json.dumps(result,ensure_ascii=False),flush=True)
