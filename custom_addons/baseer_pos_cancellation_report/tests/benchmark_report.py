"""100k synthetic audit projection on temporary tables; no persistent load data."""
import json
import time
from pathlib import Path

from odoo.tools import SQL
from odoo.addons.baseer_pos_cancellation_report.models.report_query import REPORT_QUERY

assert env.cr.dbname == 'baseer_cancellation_report_test_20261002'
module = Path('/mnt/baseer-addons/baseer_pos_cancellation_report')
fixture = (module/'tests/projection_fixture.sql').read_text()
fixture = fixture.replace('BEGIN;\n','',1).replace('\nROLLBACK;','')
fixture = fixture.replace('-- REPORT_VIEW_PLACEHOLDER','CREATE TEMP VIEW report_test AS '+REPORT_QUERY+';')
env.cr.execute(fixture)
env.cr.execute('CREATE TEMP VIEW baseer_pos_cancellation_report AS SELECT * FROM report_test')
manager=env['res.users'].search([('login','=','baseer-cancellation-local-preview')],limit=1)
config=env['pos.config'].search([('name','=','معاينة الإلغاءات — بيانات اختبار فقط')],limit=1)
assert manager and config
for table in ('baseer_pos_substitution','baseer_pos_protected_item_cancellation',
              'baseer_print_preparation_event','baseer_print_cancellation'):
    env.cr.execute(SQL('CREATE INDEX ON %s (order_id)',SQL.identifier(table)))
    env.cr.execute(SQL('CREATE INDEX ON %s (company_id)',SQL.identifier(table)))
    date_column='event_at' if table.startswith('baseer_pos_') else 'create_date'
    env.cr.execute(SQL('CREATE INDEX ON %s (%s)',SQL.identifier(table),SQL.identifier(date_column)))
    if table == 'baseer_print_preparation_event':
        env.cr.execute(SQL('CREATE INDEX ON %s (company_id, create_date DESC, id DESC)',SQL.identifier(table)))
env.cr.execute('CREATE INDEX ON baseer_pos_protected_item_cancellation (order_id,action_uuid)')
env.cr.execute("""
 INSERT INTO baseer_pos_substitution
 SELECT x, %s, x, %s, %s, timestamp '2026-10-01 08:00' + (x %% 28) * interval '1 day',
        'BENCH/'||x, '{"product_name":"Synthetic original"}'::jsonb,
        jsonb_build_array(jsonb_build_object('line_uuid','replacement-'||x,'product_name','Synthetic replacement')),
        1, NULL, 'original-'||x
 FROM generate_series(100,60099) x
""", [env.company.id,config.id,manager.id])
env.cr.execute("""
 INSERT INTO baseer_print_preparation_event
 SELECT x, %s, x, %s, %s, timestamp '2026-10-01 09:00' + (x %% 28) * interval '1 day',
        'BENCH/'||x, 'cancel', 'action-'||x, 'replacement-'||x,
        jsonb_build_object('line',jsonb_build_object('name','Synthetic replacement'),'order',jsonb_build_object('id',x)),
        -1, 'customer_cancelled', NULL
 FROM generate_series(100,40099) x
""", [env.company.id,config.id,manager.id])
for table in ('baseer_pos_substitution','baseer_pos_protected_item_cancellation',
              'baseer_print_preparation_event','baseer_print_cancellation'):
    env.cr.execute(SQL('UPDATE %s SET pos_config_id=%s',SQL.identifier(table),config.id))
    env.cr.execute(SQL('ANALYZE %s',SQL.identifier(table)))
report=env['baseer.pos.cancellation.report'].with_user(manager).with_context(allowed_company_ids=[env.company.id],tz='Asia/Riyadh')
env.cr.execute("SET LOCAL statement_timeout='15s'")
samples=[]
for attempt in range(3):
    started=time.perf_counter()
    result=report.get_report({'preset':'month','month':'2026-10'})
    samples.append(round(time.perf_counter()-started,3))
assert result['pagination']['total'] >= 100000
print('BENCHMARK_JSON='+json.dumps({'synthetic_events':100000,'details':result['pagination']['total'],
    'single_user_seconds':samples,'monthly_target_seconds':2,'within_target':max(samples)<2,
    'concurrency_tested':False,'production_data_tested':False}))
env.cr.rollback()
