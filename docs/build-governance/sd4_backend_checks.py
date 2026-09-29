"""SD4 category reporting delta; QA SQL fixtures only, never native posting.

Every fixture rolls back. Existing SD2 evidence covers unchanged financial,
permission, date-range, capacity and allocation validation paths.
"""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

assert env.cr.dbname == 'baseer_reports_qa_20260907'
checks, summary_ids, allocation_ids, category_ids, method_ids = [], [], [], [], []
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
        ('company_id', '=', 6), ('business_date', '>=', '2015-01-01'), ('business_date', '<=', '2015-01-07')])
    original = stamp()

    def add(day, amount, scope='all'):
        env.cr.execute('''INSERT INTO baseer_pos_summary(name,company_id,business_date,period_scope,day_schedule,
            state,config_id,customer_count,zero_sales,is_archived,amount_gross,amount_net,amount_tax,
            create_uid,write_uid,create_date,write_date)
            VALUES ('SD4-ROLLBACK',6,%s,%s,%s,'approved',%s,10,%s,false,%s,%s,0,%s,%s,NOW(),NOW()) RETURNING id''',
            [day, scope, 'all' if scope == 'all' else 'split', config.id, Decimal(amount) == 0, amount, amount, env.uid, env.uid])
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

    category = qa['baseer.pos.payment.category'].create({'name': 'SD4-ROLLBACK-APPLICATION', 'company_id': 6, 'kind': 'platform'})
    category_ids.append(category.id)
    extra = qa['pos.payment.method'].create({'name': 'SD4-ROLLBACK-METHOD', 'company_id': 6, 'baseer_category_id': category.id})
    method_ids.append(extra.id)
    qa.flush_all()
    morning = add('2015-01-01', '1000.00', 'morning')
    allocation(morning, platform[0], '100.00')
    allocation(morning, platform[1], '200.00')
    allocation(morning, cash, '700.00')
    evening = add('2015-01-01', '3447.00', 'evening')
    allocation(evening, extra, '300.00')
    allocation(evening, cash, '3147.00')
    cash_only = add('2015-01-02', '500.00')
    allocation(cash_only, cash, '500.00')
    add('2015-01-03', '50.00')
    add('2015-01-04', '0.00')
    mismatch = add('2015-01-05', '10.00')
    allocation(mismatch, platform[0], '9.99')
    before = stamp()

    full = fetch('2015-01-01')
    check('Two platform methods plus a second platform category yield 600 / 4447 = 13.49%', number(full['application_share']) == Decimal('13.49') and full['application_share']['display'] == '13.49' and sum(number(row['sales']) for row in full['categories'] if row['kind'] == 'platform') == Decimal('600.00'))
    check('Morning and evening are included once in denominator', full['coverage']['summary_count'] == 2 and number(full['coverage']['covered_sales']) == Decimal('4447.00'))
    cash_result = fetch('2015-01-02')
    check('Complete positive sales without applications are actual zero percent', number(cash_result['application_share']) == Decimal('0.00'))
    combined = fetch('2015-01-01', '2015-01-02')
    check('Changing date range recomputes ratio of sums', number(combined['application_share']) == Decimal('12.13'))
    incomplete = fetch('2015-01-01', '2015-01-03')
    check('Incomplete payment coverage hides percentage', not incomplete['application_share']['available'] and incomplete['application_share']['value'] is None and incomplete['application_share']['display'] == '—')
    check('Zero denominator hides percentage', not fetch('2015-01-04')['application_share']['available'])
    check('Mismatched allocations hide percentage', not fetch('2015-01-05')['application_share']['available'])
    check('Empty range hides percentage', not fetch('2015-01-06')['application_share']['available'])
    check('Endpoint preserves source masterdata and ledger rows', before == stamp())
    result.update(status='PASS', passed=len(checks), checks=checks, no_endpoint_writes=True,
                  fixtures={'summaries': len(summary_ids), 'allocations': len(allocation_ids), 'categories': len(category_ids), 'methods': len(method_ids)})
except Exception as error:
    result.update(passed=len(checks), checks=checks, error=type(error).__name__ + ': ' + str(error))
    raise
finally:
    env.cr.rollback()
    remaining = {}
    for table, ids in [('baseer_pos_summary', summary_ids), ('baseer_pos_summary_allocation', allocation_ids), ('baseer_pos_payment_category', category_ids), ('pos_payment_method', method_ids)]:
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
    Path('/mnt/qa-evidence/sd4-backend-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('SD4_BACKEND=' + json.dumps(result, ensure_ascii=False), flush=True)
