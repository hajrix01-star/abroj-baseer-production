"""Resume the stopped seed deployment after removing verified rollback-only sequences."""
import json
import re
import sys
import time
import urllib.request
import payment_seed_release as r
b = r.b
assert not b.inspect(b.MAIN_CONTAINER)['State']['Running']
candidate=json.loads((r.OUT/'candidate.json').read_text())
assert all(b.sha(r.SOURCE/p)==h for p,h in candidate['files'].items())
with (r.OUT/'main-install.log').open('ab') as log:
 if '--verify-only' not in sys.argv:
    b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','run','--rm','--no-deps','-T','odoo','odoo',
        '--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
        '--database='+b.MAIN,'--update='+r.MODULE,'--stop-after-init','--no-http','--max-cron-threads=0'],stdout=log,stderr=log)
cols=json.loads((r.OUT/'protected-columns.json').read_text())
before=json.loads((r.OUT/'protected-before.json').read_text())
after=r.projection(cols)
b.save(r.OUT/'protected-after.json',after)
changed=[x['name'] for x,y in zip(before,after) if x!=y]
assert changed in ([],['res_partner']),'Protected transactions or HR changed'
partner_changes=[]
if changed:
    info=json.loads((r.OUT/'main-backup.json').read_text())
    with (b.Path(info['directory'])/'database.dump').open('rb') as stream:
        data=b.run(['docker','exec','-i',b.DB,'pg_restore','--data-only','--table=res_partner','--file=-'],stdin=stream,capture_output=True,text=True,encoding='utf8').stdout
    copy=re.search(r'COPY public\.res_partner .*?\n\\\.\n',data,re.S).group(0).replace('COPY public.res_partner','COPY seed_before_partner',1)
    query="BEGIN; CREATE TEMP TABLE seed_before_partner (LIKE res_partner);\n"+copy+"\nSELECT coalesce(json_agg(d),'[]') FROM (SELECT p.id,a.key,b.value AS before,a.value AS after FROM res_partner p JOIN seed_before_partner q USING(id) CROSS JOIN LATERAL jsonb_each(to_jsonb(p)) a JOIN LATERAL jsonb_each(to_jsonb(q)) b ON b.key=a.key WHERE a.value IS DISTINCT FROM b.value)d; ROLLBACK;"
    raw=b.sql(b.MAIN,query)
    partner_changes=json.JSONDecoder().raw_decode(raw[raw.index('['):])[0]
    contacts={int(i) for i in b.sql(b.MAIN,'SELECT partner_id FROM res_company').splitlines()}
    assert partner_changes and all(d['key']=='write_date' and d['id'] in contacts for d in partner_changes)
    assert next(x for x in before if x['name']=='res_partner')['rows']==next(x for x in after if x['name']=='res_partner')['rows']
    b.save(r.OUT/'partner-metadata-changes.json',partner_changes)
masters=json.loads((r.OUT/'masters-before.json').read_text())
after_masters=r.master_projection(masters)
b.save(r.OUT/'masters-after.json',after_masters)
assert masters==after_masters,'Existing masters changed'
b.save(r.OUT/'main-preservation.json',{'protected_tables':len(cols),'financial_and_hr_rows_exact':True,
    'company_partner_metadata_only':partner_changes,'existing_account_journal_payment_method_rows_exact':True,'candidate':candidate['commit']})
helper=b.ROOT/'docs/build-governance/environment_backups.py'
helper.write_text(helper.read_text(encoding='utf8').replace('2026-09-09-unified-time-picker','2026-09-09-pos-payment-seed')
    .replace('unified-time-picker-20260909','pos-payment-seed-20260909'),encoding='utf8')
b.save(b.OUT/'latest-main-backup.json',json.loads((r.OUT/'main-backup.json').read_text()))
b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','up','-d','--no-deps','odoo'],capture_output=True)
for attempt in range(30):
    try:
        if urllib.request.urlopen('http://127.0.0.1:18069/web/login',timeout=3).status==200: break
    except OSError: pass
    time.sleep(2)
else: raise RuntimeError('MAIN healthcheck failed')
r.verify_runtime()
print('PUBLISHED_PRESERVATION_EXACT',flush=True)
