"""SD2 QA native-date/shifts/payment reporting checks; all fixtures roll back.

Reporting rows and allocations are SQL simulations of the reporting boundary.
No native posting, financial mutation, or MAIN access is performed.
"""
import hashlib
import json
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.baseer_sales_dashboard.models import dashboard as backend

assert env.cr.dbname == 'baseer_reports_qa_20260907'
checks, summary_ids, allocation_ids, closure_ids, timings = [], [], [], [], []
result = {'status':'FAIL','rollback':False,'scope':'QA reporting SQL fixtures, not native posting or production capacity tests'}

def check(name, value):
    assert value, name
    checks.append(name)

def rejected(name, callback):
    try:
        with env.cr.savepoint():
            callback()
    except (ValidationError,AccessError,UserError):
        checks.append(name)
    else:
        raise AssertionError(name)

def number(card):
    return Decimal(str(card['value'])) if card['available'] else None

def stamp():
    result = {}
    for table in ('baseer_pos_summary','baseer_pos_summary_allocation','baseer_pos_closure',
                  'baseer_pos_daily_report','baseer_pos_daily_report_line','account_move',
                  'account_move_line','account_payment','pos_order','pos_payment','pos_session'):
        env.cr.execute("SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM "+table+' t')
        result[table] = env.cr.fetchone()
    return result

try:
    qa = env(context=dict(env.context,allowed_company_ids=[6],lang='en_US',tz='Asia/Riyadh'))
    company = qa['res.company'].browse(6)
    dashboard = qa.ref('baseer_sales_dashboard.dashboard_sales_summary')
    config = qa['pos.config'].search([('company_id','=',6),('baseer_summary_only','=',True)],limit=1)
    methods = config.payment_method_ids[:2]
    assert len(methods)==2
    other_method = env['pos.config'].search([('company_id','=',7),('baseer_summary_only','=',True)],limit=1).payment_method_ids[:1]
    assert other_method
    assert not qa['baseer.pos.summary'].search_count([('company_id','=',6),('business_date','>=','2000-01-01'),('business_date','<=','2013-12-31')]), 'Never overwrite existing QA periods'

    def add(day,amount,customers,period='all',schedule='all',state='approved',archived=False):
        env.cr.execute('''INSERT INTO baseer_pos_summary(name,company_id,business_date,period_scope,day_schedule,
            state,config_id,customer_count,zero_sales,is_archived,amount_gross,amount_net,amount_tax,
            create_uid,write_uid,create_date,write_date)
            VALUES ('SD2-ROLLBACK',6,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,NOW(),NOW()) RETURNING id''',
            [day,period,schedule,state,config.id,customers,Decimal(str(amount))==0,archived,str(amount),str(amount),env.uid,env.uid])
        record_id=env.cr.fetchone()[0]
        summary_ids.append(record_id)
        return record_id

    def allocation(summary_id,method,amount):
        env.cr.execute('''INSERT INTO baseer_pos_summary_allocation(summary_id,company_id,business_date,period_scope,
            state,payment_method_id,category_id,amount,sequence,create_uid,write_uid,create_date,write_date)
            SELECT id,company_id,business_date,period_scope,state,%s,%s,%s,10,%s,%s,NOW(),NOW()
            FROM baseer_pos_summary WHERE id=%s RETURNING id''',
            [method.id,method.baseer_category_id.id,str(amount),env.uid,env.uid,summary_id])
        allocation_ids.append(env.cr.fetchone()[0])

    def fetch(value, today=None, record=None):
        qa.invalidate_all()
        if today:
            with patch.object(fields.Date,'context_today',return_value=fields.Date.to_date(today)):
                return (record or dashboard).get_baseer_sales_metrics({'native':value})
        return (record or dashboard).get_baseer_sales_metrics({'native':value})

    def ranged(first,last):
        return fetch({'type':'range','from':first,'to':last})

    current = [
        ({'type':'relative','period':'today'},'2024-03-31','2024-03-31','2024-03-31'),
        ({'type':'relative','period':'yesterday'},'2024-03-31','2024-03-30','2024-03-30'),
        ({'type':'relative','period':'last_7_days'},'2024-03-31','2024-03-25','2024-03-31'),
        ({'type':'relative','period':'last_30_days'},'2024-03-31','2024-03-02','2024-03-31'),
        ({'type':'relative','period':'last_90_days'},'2024-03-31','2024-01-02','2024-03-31'),
        ({'type':'relative','period':'month_to_date'},'2024-03-31','2024-03-01','2024-03-31'),
        ({'type':'relative','period':'last_month'},'2024-03-31','2024-02-01','2024-02-29'),
        ({'type':'relative','period':'year_to_date'},'2024-02-29','2024-01-01','2024-02-29'),
        ({'type':'relative','period':'last_12_months'},'2026-09-09','2025-09-01','2026-08-31'),
        ({'type':'relative','period':'last_12_months'},'2026-09-30','2025-10-01','2026-09-30'),
        ({'type':'month','month':2,'year':2024},'2024-03-31','2024-02-01','2024-02-29'),
        ({'type':'quarter','quarter':1,'year':2024},'2024-03-31','2024-01-01','2024-03-31'),
        ({'type':'year','year':2024},'2024-01-15','2024-01-01','2024-12-31'),
    ]
    for value,today,first,last in current:
        payload=fetch(value,today)
        check('Native dates '+str(value)+' at '+today,payload['filters']['date_from']==first and payload['filters']['date_to']==last)
    quarter=fetch({'type':'quarter','quarter':1,'year':2024})
    check('Quarter comparison is previous full calendar quarter',quarter['comparison_period']=={'date_from':'2023-10-01','date_to':'2023-12-31'})
    month=fetch({'type':'month','month':3,'year':2024})
    check('Native month compares full previous month',month['comparison_period']=={'date_from':'2024-02-01','date_to':'2024-02-29'})
    year=fetch({'type':'year','year':2024},'2024-01-15')
    check('Explicit year retains full year and monthly intent',year['filters']['granularity']=='month' and len(year['timeline']['points'])==12)
    ytd=fetch({'type':'relative','period':'year_to_date'},'2024-02-29')
    check('Leap YTD comparison clips previous February',ytd['comparison_period']=={'date_from':'2023-01-01','date_to':'2023-02-28'})
    mtd=fetch({'type':'relative','period':'month_to_date'},'2024-03-31')
    check('Month-to-date comparison clips short previous month',mtd['comparison_period']['date_to']=='2024-02-29')
    for value in [False,[],{'type':'year','year':True},{'type':'month','year':2024,'month':13},
                  {'type':'quarter','year':2024,'quarter':0},{'type':'relative','period':'forever'},
                  {'type':'range','from':'2024-02-30','to':'2024-03-01'},
                  {'type':'range','from':'2024-03-01','to':'2024-02-01'},
                  {'type':'range','from':False,'to':''},{'type':'year','year':2024,'company_id':7}]:
        rejected('Reject malformed native '+str(value),lambda value=value:fetch(value))
    rejected('Reject mixed native and legacy',lambda:dashboard.get_baseer_sales_metrics({'native':None,'preset':'this_year'}))
    rejected('Reject over 100 calendar years',lambda:ranged('2000-01-01','2100-01-01'))
    rejected('Reject leap-century overflow',lambda:ranged('2000-02-29','2100-02-28'))
    check('100-year budget accepts exact shorter boundary',dashboard._baseer_check_capacity(company,[(date(2000,1,1),date(2099,12,31))]) is None)

    morning=add('2010-01-01',100,10,'morning','split')
    evening=add('2010-01-01',300,15,'evening','split')
    whole=add('2010-01-02',200,10,archived=True)
    for record,amounts in [(morning,[40,60]),(evening,[100,200]),(whole,[200,0])]:
        for method,amount in zip(methods,amounts):
            allocation(record,method,amount)
    original=add('2010-01-02',999,99,state='cancelled')
    allocation(original,methods[0],999)
    draft=add('2010-01-03',999,99,state='draft')
    allocation(draft,methods[0],999)
    data=ranged('2010-01-01','2010-01-03')
    shifts={row['key']:row for row in data['shift_performance']['rows']}
    check('All-summary action carries explicit native views',data['source_action']['views']==[(False,'list'),(False,'form')])
    check('Exactly three source period scopes',set(shifts)=={'morning','evening','all'})
    for key,amount,customers,average in [('morning',100,10,10),('evening',300,15,20),('all',200,10,20)]:
        row=shifts[key]
        check('Shift source totals '+key,number(row['cards']['sales'])==amount and number(row['cards']['customers'])==customers and number(row['cards']['average_bill'])==average)
    check('Shifts sum to total without splitting full day',sum(number(r['cards']['sales']) for r in shifts.values())==number(data['cards']['sales'])==600)
    for key,row in shifts.items():
        check('Shift action carries explicit native views '+key,row['source_action']['views']==[(False,'list'),(False,'form')])
        found=qa['baseer.pos.summary'].search(row['source_action']['domain'])
        check('Shift drilldown '+key,all(s.period_scope==key and s.state=='approved' and s.company_id.id==6 for s in found))
    payments=data['payment_performance']
    check('Fully covered actual allocations',payments['coverage']['complete'] and payments['coverage']['covered_summary_count']==3)
    check('Methods retain exact identities and sums',{r['method_id']:number(r['sales']) for r in payments['rows']}=={methods[0].id:Decimal(340),methods[1].id:Decimal(260)})
    check('Payment ratios come from covered full sales',[number(r['share']) for r in payments['rows']]==[Decimal('56.67'),Decimal('43.33')])
    check('Covered plus uncovered is total',number(payments['coverage']['covered_sales'])+number(payments['coverage']['uncovered_sales'])==600)
    for row in payments['rows']:
        check('Payment action carries explicit native views '+str(row['method_id']),row['source_action']['views']==[(False,'list'),(False,'form')])
        lines=qa['baseer.pos.summary.allocation'].search(row['source_action']['domain'])
        check('Payment drilldown exact original method '+str(row['method_id']),sum(Decimal(str(line.amount)) for line in lines)==number(row['sales']) and all(line.payment_method_id.id==row['method_id'] and line.summary_id.state=='approved' for line in lines))
    absent=ranged('2010-01-03','2010-01-03')
    check('Draft-only shift remains absent, not a zero sale',all(not row['has_data'] and not row['cards']['sales']['available'] for row in absent['shift_performance']['rows']))
    zero=add('2010-01-04',0,0)
    zeros=ranged('2010-01-04','2010-01-04')
    check('Declared zero preserves shift zero and undefined ratio',number(zeros['shift_performance']['rows'][2]['cards']['sales'])==0 and not zeros['shift_performance']['rows'][2]['cards']['average_bill']['available'])
    check('Zero without allocations creates no imaginary payment method',zeros['payment_performance']['rows']==[] and zeros['payment_performance']['coverage']['complete'])
    missing=add('2010-01-05',150,0,'morning','morning')
    partial=ranged('2010-01-01','2010-01-05')
    check('Missing allocation fixture exposes uncovered amount',partial['payment_performance']['coverage']['missing_summary_count']==1 and number(partial['payment_performance']['coverage']['uncovered_sales'])==150)
    check('Incomplete payment coverage suppresses all percentages',all(not row['share']['available'] for row in partial['payment_performance']['rows']))
    check('Missing customer in one shift suppresses only its average',not partial['shift_performance']['rows'][0]['cards']['average_bill']['available'] and partial['shift_performance']['rows'][1]['cards']['average_bill']['available'])
    mismatch=add('2010-01-06',100,5)
    allocation(mismatch,methods[0],90)
    negative=add('2010-01-07',100,5)
    allocation(negative,methods[0],-10)
    allocation(negative,methods[1],110)
    foreign=add('2010-01-08',100,5)
    allocation(foreign,other_method,100)
    broken=ranged('2010-01-06','2010-01-08')['payment_performance']
    check('Mismatch, negative and foreign method excluded despite gross equality',broken['coverage']['mismatched_summary_count']==3 and broken['rows']==[] and number(broken['coverage']['uncovered_sales'])==300)

    # Boundary day 366 and 367: one closure spanning both chunks counts once
    # per calendar date, not once per overlapping query.
    for day,amount in [('2012-01-01',10),('2012-12-30',20),('2013-01-01',90)]:
        add(day,amount,1,'morning','morning')
    env.cr.execute('''INSERT INTO baseer_pos_closure(name,company_id,date_from,date_to,period_scope,reason,state,is_archived,
        create_uid,write_uid,create_date,write_date) VALUES ('SD2-ROLLBACK',6,'2012-12-31','2013-01-01','evening','other','confirmed',false,%s,%s,NOW(),NOW()) RETURNING id''',[env.uid,env.uid])
    closure_ids.append(env.cr.fetchone()[0])
    long=ranged('2012-01-01','2013-01-01')
    check('367 days processed without truncation',number(long['cards']['sales'])==120 and long['coverage']['operating_days']==3)
    check('Combined average uses numerators not chunk means',number(long['cards']['daily_sales'])==40)
    check('Chunk coverage partitions all calendar dates once',sum(long['coverage'].values())==367)
    check('Monthly timeline includes final chunk source',number(long['cards']['sales'])==sum((Decimal(p['sales']) for p in long['timeline']['points'] if p['sales'] is not None),Decimal(0)))
    alltime=fetch(None)
    env.cr.execute("SELECT min(business_date),max(business_date),sum(round(amount_gross::numeric,2))::text FROM baseer_pos_summary WHERE company_id=6 AND state='approved'")
    first,last,gross=env.cr.fetchone()
    gross=Decimal(gross)
    result['alltime_oracle']={'first':str(first),'last':str(last),'gross':str(gross),
                              'actual_filters':alltime['filters'],'actual_gross':str(number(alltime['cards']['sales']))}
    check('All time resolves complete visible approved history',alltime['filters']['date_from']==str(first) and alltime['filters']['date_to']==str(last) and number(alltime['cards']['sales'])==gross)
    check('All time has no invented prior comparison',all(v is None for v in alltime['comparison_period'].values()) and all(not card['comparison']['available'] for card in alltime['cards'].values()))
    since=fetch({'type':'range','from':'2012-01-01','to':''})
    check('Open range extends to true latest source without comparison',since['filters']['date_to']==str(last) and not since['cards']['sales']['comparison']['available'])
    until=fetch({'type':'range','from':'','to':'2010-01-08'})
    check('Open range begins at true earliest source',until['filters']['date_from']==str(first))
    empty=fetch({'type':'range','from':'2090-01-01','to':''})
    check('Open range beyond known history is genuinely empty',empty['filters']['date_from'] is None and empty['timeline']['points']==[] and not empty['has_data'])
    other=fetch({'type':'range','from':'2010-01-01','to':'2013-01-01'},record=dashboard.with_context(allowed_company_ids=[7,6]))
    check('Active company isolates sources, shifts and payments',other['company']['id']==7 and not other['has_data'] and other['payment_performance']['rows']==[])
    with patch.object(backend,'MAX_SOURCE_ROWS',2):
        rejected('Combined source budget rejects explicitly before aggregation',lambda:ranged('2010-01-01','2010-01-02'))
    with patch.object(backend,'MAX_SOURCE_ROWS',8):
        # 3 approved + 1 cancelled summaries, 6 valid allocations and one
        # cancelled allocation: counting payment rows must exceed this budget.
        rejected('Allocation rows participate in source budget',lambda:ranged('2010-01-01','2010-01-02'))

    # A ten-year dataset, two summaries per day, uses the real helper and API.
    env.cr.execute('''INSERT INTO baseer_pos_summary(name,company_id,business_date,period_scope,day_schedule,state,
        config_id,customer_count,zero_sales,is_archived,amount_gross,amount_net,amount_tax,create_uid,write_uid,create_date,write_date)
        SELECT 'SD2-ROLLBACK',6,d::date,p,'split','approved',%s,CASE WHEN p='morning' THEN 3 ELSE 5 END,false,false,
            CASE WHEN p='morning' THEN 100.01 ELSE 200.02 END,CASE WHEN p='morning' THEN 100.01 ELSE 200.02 END,0,%s,%s,NOW(),NOW()
        FROM generate_series('2000-01-01'::date,'2009-12-31'::date,'1 day') d CROSS JOIN (VALUES ('morning'),('evening')) x(p) RETURNING id''',[config.id,env.uid,env.uid])
    benchmark_ids=[row[0] for row in env.cr.fetchall()]
    summary_ids.extend(benchmark_ids)
    before=stamp()
    for iteration in range(3):
        qa.invalidate_all()
        tick=time.monotonic()
        ten=ranged('2000-01-01','2009-12-31')
        timings.append(round(time.monotonic()-tick,6))
    after=stamp()
    check('Endpoint never changes source ledger or transient rows',before==after)
    check('Ten-year helper handles every leap date',ten['coverage']['operating_days']==3653 and len(ten['timeline']['points'])==120)
    check('Ten-year source sum retains cents',number(ten['cards']['sales'])==Decimal('300.03')*3653)
    check('Ten-year local serial target under two seconds',max(timings)<=2)
    result.update(status='PASS',passed=len(checks),checks=checks,profile={'ten_year_seconds':timings,'current_days':3653,'previous_days':3653,
        'current_summaries':len(benchmark_ids),'previous_summaries':0,'concurrency':1,'cache':'ORM cache invalidated before each timed request',
        'scope':'Local QA latency, not certification of 100-year or concurrent production capacity'},no_endpoint_writes=before==after,
        fixtures={'summaries':len(summary_ids),'allocations':len(allocation_ids),'closures':len(closure_ids)})
except Exception as error:
    result.update(passed=len(checks),checks=checks,error=type(error).__name__+': '+str(error))
    raise
finally:
    env.cr.rollback()
    remaining={}
    for table,ids in [('baseer_pos_summary',summary_ids),('baseer_pos_summary_allocation',allocation_ids),('baseer_pos_closure',closure_ids)]:
        if ids:
            env.cr.execute('SELECT count(*) FROM '+table+' WHERE id IN %s',[tuple(ids)])
            remaining[table]=env.cr.fetchone()[0]
        else:
            remaining[table]=0
    env.cr.rollback()
    result['rollback']=not any(remaining.values())
    result['remaining_fixture_rows']=remaining
    if not result['rollback']:
        result['status']='FAIL'
    source=Path('/mnt/sales-dashboard-addons/baseer_sales_dashboard/models/dashboard.py')
    result['backend_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    Path('/mnt/qa-evidence/sd2-backend-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('SD2_BACKEND='+json.dumps(result,ensure_ascii=False),flush=True)
