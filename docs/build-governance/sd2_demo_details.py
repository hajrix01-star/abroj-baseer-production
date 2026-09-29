"""Enrich the owner's tagged QA demo only; preserve each day's totals.

Synthetic reporting rows/allocations, never native POS or accounting posting.
Run through the isolated QA Odoo shell after SD2 is installed.
"""
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA only'
ROOT = Path('/mnt/qa-evidence')
OUT = ROOT / 'sd2-demo-details.json'
BEFORE = ROOT / 'sd2-demo-before.json'
tag = 'SD1-DEMO-6MONTHS-20260909'
companion = 'SD2-DEMO-EVENING-20260909'
company_id = 6


def q(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def native_fingerprint():
    result = {}
    for table in ('account_move', 'account_move_line', 'account_payment', 'pos_order', 'pos_payment', 'pos_session'):
        env.cr.execute("SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM " + table + ' t')
        result[table] = env.cr.fetchone()
    return result


if OUT.exists():
    result = json.loads(OUT.read_text())
    env.cr.execute('SELECT id FROM baseer_pos_summary WHERE name IN %s ORDER BY id', [(tag, companion)])
    assert [x[0] for x in env.cr.fetchall()] == sorted(result['summary_ids'])
    print('SD2 demo already enriched; preserved', len(result['summary_ids']))
else:
    original = json.loads((ROOT / 'sales-dashboard-six-month-demo.json').read_text())
    env.cr.execute('SELECT id,business_date,config_id,customer_count,amount_gross,amount_net,amount_tax,period_scope,day_schedule FROM baseer_pos_summary WHERE company_id=%s AND name=%s ORDER BY id', [company_id, tag])
    rows = env.cr.fetchall()
    ids = [r[0] for r in rows]
    assert ids == sorted(original['summary_ids']) and len(ids) == 368
    assert all(r[7:] == ('all', 'all') for r in rows), 'Unexpected previous mutation'
    env.cr.execute('SELECT count(*) FROM baseer_pos_summary_allocation WHERE summary_id IN %s', [tuple(ids)])
    assert env.cr.fetchone()[0] == 0, 'Existing allocation details must not be overwritten'
    env.cr.execute('SELECT count(*) FROM baseer_pos_summary WHERE name=%s', [companion])
    assert env.cr.fetchone()[0] == 0
    assert not BEFORE.exists(), 'Inspect an earlier partial run before retrying'
    BEFORE.write_text(json.dumps({'rows': rows, 'tag': tag}, default=str, indent=2))
    before = native_fingerprint()
    new_ids = []
    for sid, day, config_id, customers, raw_gross, raw_net, raw_tax, _, _ in rows:
        if day.weekday() == 6:
            continue
        gross, net, tax = q(raw_gross), q(raw_net), q(raw_tax)
        ratio = Decimal(32 + day.day % 17) / 100
        first_gross, first_net = q(gross * ratio), q(net * ratio)
        first_tax = first_gross - first_net
        first_customers = int(Decimal(customers) * ratio)
        env.cr.execute("UPDATE baseer_pos_summary SET period_scope='morning',day_schedule='split',customer_count=%s,amount_gross=%s,amount_net=%s,amount_tax=%s WHERE id=%s AND company_id=%s AND name=%s", [first_customers, str(first_gross), str(first_net), str(first_tax), sid, company_id, tag])
        assert env.cr.rowcount == 1
        env.cr.execute('''INSERT INTO baseer_pos_summary
            (name,company_id,business_date,period_scope,day_schedule,state,config_id,
             customer_count,zero_sales,is_archived,amount_gross,amount_net,amount_tax,
             create_uid,write_uid,create_date,write_date)
            VALUES (%s,%s,%s,'evening','split','approved',%s,%s,false,false,%s,%s,%s,%s,%s,NOW(),NOW()) RETURNING id''',
            [companion, company_id, day, config_id, customers-first_customers,
             str(gross-first_gross), str(net-first_net), str(tax-first_tax), env.uid, env.uid])
        new_ids.append(env.cr.fetchone()[0])
    all_ids = ids + new_ids
    methods = env['pos.payment.method'].browse([1, 2, 46, 47, 48])
    assert len(methods.exists()) == 5
    assert all(m.company_id.id == company_id and m.baseer_category_id.company_id.id == company_id for m in methods)
    env.cr.execute('SELECT id,business_date,period_scope,amount_gross,config_id FROM baseer_pos_summary WHERE id IN %s ORDER BY id', [tuple(all_ids)])
    allocation_ids = []
    for sid, day, scope, amount, config_id in env.cr.fetchall():
        assert methods <= env['pos.config'].browse(config_id).payment_method_ids
        gross = q(amount)
        cash = 18 + day.day % 8
        bank = 37 + day.day % 6
        weights = [cash, bank, 16, 12, 100-cash-bank-28]
        allocated = Decimal('0.00')
        for index, (method, weight) in enumerate(zip(methods, weights)):
            value = gross-allocated if index == 4 else q(gross * Decimal(weight) / 100)
            allocated += value
            env.cr.execute('''INSERT INTO baseer_pos_summary_allocation
                (summary_id,company_id,business_date,period_scope,state,sequence,payment_method_id,
                 category_id,amount,pos_payment_id,create_uid,write_uid,create_date,write_date)
                VALUES (%s,%s,%s,%s,'approved',%s,%s,%s,%s,NULL,%s,%s,NOW(),NOW()) RETURNING id''',
                [sid, company_id, day, scope, index*10, method.id, method.baseer_category_id.id, str(value), env.uid, env.uid])
            allocation_ids.append(env.cr.fetchone()[0])
        assert allocated == gross
    env.invalidate_all()
    # Exact per-day reconciliation retains the established demo card totals.
    env.cr.execute('SELECT business_date,sum(customer_count),sum(amount_gross),sum(amount_net),sum(amount_tax) FROM baseer_pos_summary WHERE id IN %s GROUP BY business_date', [tuple(all_ids)])
    actual = {r[0]: (r[1], q(r[2]), q(r[3]), q(r[4])) for r in env.cr.fetchall()}
    for _, day, _, customers, gross, net, tax, _, _ in rows:
        assert actual[day] == (customers, q(gross), q(net), q(tax))
    assert before == native_fingerprint(), 'Native accounting/POS must remain unchanged'
    result = dict(status='passed', database=env.cr.dbname, company_id=company_id,
        summary_ids=all_ids, companion_ids=new_ids, allocation_ids=allocation_ids,
        preserved_daily_totals=True, native_posting_unchanged=True,
        scope='Owner preview only: synthetic reporting allocations, not actual receipts or settlements.')
    env.cr.commit()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('SD2 demo enriched', len(all_ids), 'summaries;', len(allocation_ids), 'allocations')
