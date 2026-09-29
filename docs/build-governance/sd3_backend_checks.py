"""SD3 category reporting delta; QA SQL fixtures only, never native posting.

Every fixture rolls back. Existing SD2 evidence covers unchanged financial,
permission, date-range, capacity and allocation validation paths.
"""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

assert env.cr.dbname == 'baseer_reports_qa_20260907'
checks, summary_ids, allocation_ids = [], [], []
result = {'status': 'FAIL', 'scope': 'QA reporting simulations, not native posting', 'rollback': False}


def check(name, condition):
    assert condition, name
    checks.append(name)


def number(card):
    return Decimal(card['value']) if card['available'] else None


def stamp():
    value = {}
    for table in ('baseer_pos_summary', 'baseer_pos_summary_allocation', 'account_move',
                  'account_move_line', 'account_payment', 'pos_payment', 'pos_payment_method',
                  'baseer_pos_payment_category'):
        env.cr.execute("SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM " + table + ' t')
        value[table] = env.cr.fetchone()
    return value


try:
    qa = env(context=dict(env.context, allowed_company_ids=[6], lang='en_US', tz='Asia/Riyadh'))
    dashboard = qa.ref('baseer_sales_dashboard.dashboard_sales_summary')
    config = qa['pos.config'].search([('company_id', '=', 6), ('baseer_summary_only', '=', True)], limit=1)
    platform = config.payment_method_ids.filtered(lambda method: method.baseer_category_id.kind == 'platform')[:2]
    cash = config.payment_method_ids.filtered(lambda method: method.baseer_category_id.kind == 'cash')[:1]
    assert len(platform) == 2 and cash and platform[0].baseer_category_id == platform[1].baseer_category_id
    assert not qa['baseer.pos.summary'].search_count([
        ('company_id', '=', 6), ('business_date', '>=', '2014-01-01'), ('business_date', '<=', '2014-01-07')])
    original = stamp()

    def add(day, amount):
        env.cr.execute('''INSERT INTO baseer_pos_summary(name,company_id,business_date,period_scope,day_schedule,
            state,config_id,customer_count,zero_sales,is_archived,amount_gross,amount_net,amount_tax,
            create_uid,write_uid,create_date,write_date)
            VALUES ('SD3-ROLLBACK',6,%s,'all','all','approved',%s,10,%s,false,%s,%s,0,%s,%s,NOW(),NOW()) RETURNING id''',
            [day, config.id, Decimal(amount) == 0, amount, amount, env.uid, env.uid])
        record_id = env.cr.fetchone()[0]
        summary_ids.append(record_id)
        return record_id

    def allocation(record_id, method, amount):
        env.cr.execute('''INSERT INTO baseer_pos_summary_allocation(summary_id,company_id,business_date,period_scope,
            state,payment_method_id,category_id,amount,sequence,create_uid,write_uid,create_date,write_date)
            SELECT id,company_id,business_date,period_scope,state,%s,%s,%s,10,%s,%s,NOW(),NOW()
            FROM baseer_pos_summary WHERE id=%s RETURNING id''',
            [method.id, method.baseer_category_id.id, amount, env.uid, env.uid, record_id])
        allocation_ids.append(env.cr.fetchone()[0])

    def fetch(first, last=None):
        qa.invalidate_all()
        return dashboard.get_baseer_sales_metrics({'native': {'type': 'range', 'from': first, 'to': last or first}})['payment_performance']

    first = add('2014-01-01', '100.00')
    allocation(first, platform[0], '10.01')
    allocation(first, platform[1], '20.02')
    allocation(first, cash, '69.97')
    second = add('2014-01-02', '0.07')
    allocation(second, platform[0], '0.07')
    add('2014-01-03', '50.00')
    add('2014-01-04', '0.00')
    zero = add('2014-01-05', '0.00')
    allocation(zero, cash, '0.00')
    mismatch = add('2014-01-06', '10.00')
    allocation(mismatch, cash, '9.99')
    before = stamp()

    full = fetch('2014-01-01', '2014-01-02')
    categories = {row['category_id']: row for row in full['categories']}
    check('Two methods sharing category become one category row', len(full['rows']) == 3 and len(categories) == 2)
    check('Category sums exact cents across methods and summaries', number(categories[platform[0].baseer_category_id.id]['sales']) == Decimal('30.10'))
    check('Cash category retains independent allocation', number(categories[cash.baseer_category_id.id]['sales']) == Decimal('69.97'))
    check('Category sum equals methods and covered sales', sum((number(row['sales']) for row in full['categories']), Decimal(0)) == sum((number(row['sales']) for row in full['rows']), Decimal(0)) == number(full['coverage']['covered_sales']) == Decimal('100.07'))
    check('Categories sorted by authoritative id', list(categories) == sorted(categories))
    check('Category identity and kind remain authoritative', all(categories[method.baseer_category_id.id]['name'] == method.baseer_category_id.name and categories[method.baseer_category_id.id]['kind'] == method.baseer_category_id.kind for method in platform | cash))
    check('Category amounts formatted on backend', categories[platform[0].baseer_category_id.id]['sales']['display'] == '30.10')
    partial = fetch('2014-01-01', '2014-01-03')
    check('Missing allocations never distributed into categories', partial['categories'] == full['categories'] and not partial['coverage']['complete'] and number(partial['coverage']['uncovered_sales']) == Decimal('50.00'))
    missing = fetch('2014-01-03')
    check('Only missing allocations yields empty categories', missing['categories'] == [] and missing['coverage']['missing_summary_count'] == 1)
    blank_zero = fetch('2014-01-04')
    check('Approved zero without allocations invents no category', blank_zero['categories'] == [] and blank_zero['coverage']['complete'])
    actual_zero = fetch('2014-01-05')
    check('Explicit zero allocation remains a genuine zero category', len(actual_zero['categories']) == 1 and number(actual_zero['categories'][0]['sales']) == Decimal(0))
    invalid = fetch('2014-01-06')
    check('Mismatched summary produces no category amount', invalid['categories'] == [] and invalid['coverage']['mismatched_summary_count'] == 1)
    empty = fetch('2014-01-07')
    check('Empty period remains empty categories', empty['categories'] == [] and empty['rows'] == [])
    check('Endpoint changes no reporting masterdata or ledger rows', before == stamp())
    result.update(status='PASS', passed=len(checks), checks=checks, no_endpoint_writes=True,
                  fixtures={'summaries': len(summary_ids), 'allocations': len(allocation_ids)})
except Exception as error:
    result.update(passed=len(checks), checks=checks, error=type(error).__name__ + ': ' + str(error))
    raise
finally:
    env.cr.rollback()
    remaining = {}
    for table, ids in [('baseer_pos_summary', summary_ids), ('baseer_pos_summary_allocation', allocation_ids)]:
        env.cr.execute('SELECT count(*) FROM ' + table + ' WHERE id IN %s', [tuple(ids) or (0,)])
        remaining[table] = env.cr.fetchone()[0]
    result['remaining_fixture_rows'] = remaining
    result['rollback'] = not any(remaining.values())
    if 'original' in locals():
        result['existing_rows_preserved'] = original == stamp()
    if not result['rollback'] or result.get('existing_rows_preserved') is False:
        result['status'] = 'FAIL'
    env.cr.rollback()
    result['backend_sha256'] = hashlib.sha256(Path('/mnt/sales-dashboard-addons/baseer_sales_dashboard/models/dashboard.py').read_bytes()).hexdigest()
    Path('/mnt/qa-evidence/sd3-backend-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('SD3_BACKEND=' + json.dumps(result, ensure_ascii=False), flush=True)
