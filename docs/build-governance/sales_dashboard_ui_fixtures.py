"""Explicit QA UI fixtures; never financial posting or MAIN data.

Default mode creates 12 reporting rows in 2025 and 12 in 2024, then commits
only those synthetic rows. Set SD1_UI_MODE='cleanup' before execution to
validate and delete the exact recorded IDs. No native posting is performed.
"""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA database only'
mode = globals().get('SD1_UI_MODE', 'create')
assert mode in ('create', 'cleanup')
tag = 'SD1-UI-20260909-YEARS-v1'
evidence = Path('/mnt/qa-evidence/sales-dashboard-ui-fixtures.json')
company_id = 6

try:
    if mode == 'cleanup':
        payload = json.loads(evidence.read_text())
        assert payload['database'] == env.cr.dbname and payload['tag'] == tag and payload['company_id'] == company_id
        ids = payload['summary_ids']
        assert len(ids) == 24 and len(set(ids)) == 24
        env.cr.execute('''SELECT id,name,company_id,order_id,session_id,replaces_id,replacement_id
            FROM baseer_pos_summary WHERE id IN %s ORDER BY id FOR UPDATE''', [tuple(ids)])
        rows = env.cr.fetchall()
        assert len(rows) == 24, 'Cleanup must not silently accept missing or changed fixture rows'
        assert all(row[1] == tag and row[2] == company_id and not any(row[3:]) for row in rows), 'Fixture identity or native/source links changed'
        env.cr.execute('SELECT count(*) FROM baseer_pos_summary_allocation WHERE summary_id IN %s',[tuple(ids)])
        assert env.cr.fetchone()[0] == 0, 'Fixture acquired payment allocations'
        env.cr.execute('DELETE FROM baseer_pos_summary WHERE id IN %s',[tuple(ids)])
        assert env.cr.rowcount == 24
        env.cr.commit()
        payload['cleaned'] = True
        payload['cleanup_rows_deleted'] = 24
        evidence.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print('SD1_UI_FIXTURES_CLEANED=24',flush=True)
    else:
        env.cr.execute('''SELECT count(*) FROM baseer_pos_summary
            WHERE company_id=%s AND business_date BETWEEN '2024-01-01' AND '2025-12-31' ''',[company_id])
        assert env.cr.fetchone()[0] == 0, 'Historical QA period already contains data; choose another period without editing it'
        env.cr.execute('''SELECT count(*) FROM baseer_pos_closure WHERE company_id=%s
            AND date_from<='2025-12-31' AND date_to>='2024-01-01' AND state='confirmed' ''',[company_id])
        assert env.cr.fetchone()[0] == 0, 'Historical QA period contains operating closures'
        env.cr.execute('SELECT id FROM pos_config WHERE company_id=%s AND baseer_summary_only ORDER BY id LIMIT 1',[company_id])
        config_id = env.cr.fetchone()[0]
        current = [1150,2300,3450,4600,2875,5175,5750,4025,6900,6325,7475,8625]
        ids, samples = [], []
        for year in (2024,2025):
            for month, gross in enumerate(current,1):
                amount = Decimal(gross) if year == 2025 else Decimal(gross)*Decimal('0.80')
                customers = 20+month if year == 2025 else 40+month
                day = date(year,month,15)
                env.cr.execute('''INSERT INTO baseer_pos_summary
                    (name,company_id,business_date,period_scope,day_schedule,state,config_id,
                     customer_count,zero_sales,is_archived,amount_gross,amount_net,amount_tax,
                     create_uid,write_uid,create_date,write_date)
                    VALUES (%s,%s,%s,'all','all','approved',%s,%s,false,false,%s,%s,0,%s,%s,NOW(),NOW()) RETURNING id''',
                    [tag,company_id,day,config_id,customers,str(amount),str(amount),env.uid,env.uid])
                record_id = env.cr.fetchone()[0]
                ids.append(record_id)
                samples.append({'id':record_id,'date':str(day),'gross':str(amount.quantize(Decimal('0.01'))),'customers':customers})
        env['baseer.pos.summary'].invalidate_model()
        dashboard = env.ref('baseer_sales_dashboard.dashboard_sales_summary').with_context(allowed_company_ids=[company_id],lang='en_US')
        payload_metrics = dashboard.get_baseer_sales_metrics({'preset':'last_year'})
        assert payload_metrics['filters']['date_from'] == '2025-01-01', 'UI fixture preset assumes current year 2026'
        assert payload_metrics['cards']['sales']['comparison']['direction'] == 'up'
        assert payload_metrics['cards']['customers']['comparison']['direction'] == 'down'
        assert payload_metrics['cards']['average_bill']['comparison']['direction'] == 'up'
        assert len(payload_metrics['timeline']['points']) == 12
        env.cr.commit()
        payload = {'database':env.cr.dbname,'company_id':company_id,'config_id':config_id,'tag':tag,
                   'summary_ids':ids,'samples':samples,'created':True,'cleaned':False,
                   'scope':'QA-only synthetic approved reporting rows; no native accounting/POS posting',
                   'ui_preset':'last_year','ui_current_period':'2025-01-01..2025-12-31',
                   'ui_comparison_period':'2024-01-01..2024-12-31',
                   'cards':payload_metrics['cards'],
                   'cleanup':'Execute this file in the same QA Odoo shell with SD1_UI_MODE="cleanup"; exact identity-checked IDs only'}
        evidence.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        print('SD1_UI_FIXTURES='+json.dumps({'ids':ids,'preset':'last_year','cards':payload_metrics['cards']},ensure_ascii=False),flush=True)
except Exception:
    env.cr.rollback()
    raise
