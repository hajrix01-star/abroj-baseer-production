"""Owner-requested persistent QA reporting demo. No accounting/POS posting.

Execute in the existing QA Odoo shell. Re-running returns the existing demo.
The evidence file lists exact IDs for later deliberate cleanup.
"""
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA only'
company_id = 6
tag = 'SD1-DEMO-6MONTHS-20260909'
first, last = date(2026, 3, 1), date(2026, 8, 31)
count = (last - first).days + 1
previous = first - timedelta(days=count)
output = Path('/mnt/qa-evidence/sales-dashboard-six-month-demo.json')
env.cr.execute('SELECT id FROM baseer_pos_summary WHERE name=%s ORDER BY id', [tag])
ids = [row[0] for row in env.cr.fetchall()]
if ids:
    assert output.exists(), 'Existing demo without evidence; inspect before changing it'
    data = json.loads(output.read_text())
    assert ids == sorted(data['summary_ids'])
    print('Existing six-month demo preserved:', len(ids))
else:
    env.cr.execute('SELECT count(*) FROM baseer_pos_summary WHERE company_id=%s AND business_date BETWEEN %s AND %s', [company_id, previous, last])
    assert env.cr.fetchone()[0] == 0, 'Do not overwrite existing QA history'
    env.cr.execute("SELECT count(*) FROM baseer_pos_closure WHERE company_id=%s AND state='confirmed' AND date_from<=%s AND date_to>=%s", [company_id, last, previous])
    assert env.cr.fetchone()[0] == 0
    config = env['pos.config'].search([('company_id', '=', company_id), ('baseer_summary_only', '=', True)], limit=1)
    assert config
    tables = ('account_move', 'account_move_line', 'account_payment', 'pos_order', 'pos_payment', 'pos_session')
    def fingerprints():
        values = {}
        for table in tables:
            env.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,\'\' ORDER BY id),\'\')) FROM ' + table + ' t')
            values[table] = env.cr.fetchone()
        return values
    before = fingerprints()
    for offset in range(count * 2):
        day = previous + timedelta(days=offset)
        current = day >= first
        if current:
            base = [4200, 4750, 4400, 5250, 4900, 5850][day.month - 3]
            customers = 64 + (day.day * 7 + day.month * 5) % 39
        else:
            base = 3650 + (day.month % 3) * 190
            customers = 92 + (day.day * 3 + day.month) % 30
        weekday_factor = [96, 90, 92, 105, 128, 118, 101][day.weekday()]
        gross = (Decimal(base * weekday_factor) / 100 + Decimal((day.day * 173) % 760 - 380)).quantize(Decimal('.01'))
        net = (gross / Decimal('1.15')).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        env.cr.execute('''INSERT INTO baseer_pos_summary
            (name,company_id,business_date,period_scope,day_schedule,state,config_id,
             customer_count,zero_sales,is_archived,amount_gross,amount_net,amount_tax,
             create_uid,write_uid,create_date,write_date)
            VALUES (%s,%s,%s,'all','all','approved',%s,%s,false,false,%s,%s,%s,%s,%s,NOW(),NOW()) RETURNING id''',
            [tag, company_id, day, config.id, customers, str(gross), str(net), str(gross-net), env.uid, env.uid])
        ids.append(env.cr.fetchone()[0])
    env['baseer.pos.summary'].invalidate_model()
    dashboard = env.ref('baseer_sales_dashboard.dashboard_sales_summary').with_context(allowed_company_ids=[company_id], lang='ar_001')
    metrics = dashboard.get_baseer_sales_metrics({'preset':'custom', 'date_from':str(first), 'date_to':str(last)})
    assert metrics['coverage']['operating_days'] == count
    assert len(metrics['timeline']['points']) == 6
    assert metrics['cards']['sales']['comparison']['direction'] == 'up'
    assert metrics['cards']['customers']['comparison']['direction'] == 'down'
    assert before == fingerprints(), 'Reporting fixtures must not change native ledger/POS transactions'
    data = dict(database=env.cr.dbname, company_id=company_id, company_name=env['res.company'].browse(company_id).name,
        tag=tag, summary_ids=ids, date_from=str(first), date_to=str(last), comparison_from=str(previous),
        comparison_to=str(first-timedelta(days=1)), daily_rows=count, comparison_daily_rows=count,
        cards=metrics['cards'], monthly_points=metrics['timeline']['points'], native_posting_unchanged=True,
        scope='Synthetic QA reporting rows only; not accounting or actual POS transactions. Retained for owner preview.')
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    env.cr.commit()
    print(json.dumps({k:data[k] for k in ('company_name','date_from','date_to','daily_rows','comparison_daily_rows','cards')}, ensure_ascii=False))
