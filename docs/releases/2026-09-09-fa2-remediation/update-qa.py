"""Apply accepted FA2 only to QA; never installs or changes the live main database."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
assert sys.argv[1:]==['apply-qa']
assert (f.OUT/'FINAL-INDEPENDENT-ACCEPTANCE.md').exists()
c=json.loads((f.OUT/'candidate.json').read_text())
for path,sha in c['files'].items():assert hashlib.sha256((f.o.ROOT/path).read_bytes()).hexdigest()==sha,path
dest=f.BACK/'before-qa-update';dest.mkdir(exist_ok=False)
main_before=f.audit.snapshot('baseer_dev')
f.o.run(['docker','stop',f.o.CONTAINER],capture_output=True)
assert f.o.sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='"+f.o.QA+"'")=='0'
tables=['account_move','account_move_line','account_payment','account_partial_reconcile','account_full_reconcile','hr_payslip','hr_payslip_run','baseer_pos_summary','baseer_purchase_batch']
def capture_columns():
 out={}
 for table in tables:
  cols=f.o.sql(f.o.QA,"SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' AND table_name='"+table+"' AND column_name NOT IN ('write_date','write_uid')")
  ids=json.loads(f.o.sql(f.o.QA,"SELECT coalesce(json_agg(id ORDER BY id),'[]'::json) FROM "+table))
  metadata=f.o.sql(f.o.QA,"SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM (SELECT id,write_date,write_uid FROM "+table+")t")
  out[table]={'columns':cols,'ids':ids,'audit_metadata_hash':metadata}
 return out
def projection(table,v):
 ids=','.join(map(str,v['ids'])) or 'NULL'
 return f.o.sql(f.o.QA,"SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM (SELECT "+v['columns']+' FROM '+table+' WHERE id IN ('+ids+'))t')
baseline=capture_columns()
for table,v in baseline.items():v['hash']=projection(table,v)
f.save('qa-update-baseline.json',baseline)
f.o.run(['docker','exec',f.o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+f.o.QA+' -f /tmp/fa2-qa-final-before.dump'])
f.o.run(['docker','cp',f.o.DB+':/tmp/fa2-qa-final-before.dump',str(dest/'database.dump')],capture_output=True)
with (dest/'filestore.tar').open('wb') as stream:
 f.o.run(['docker','run','--rm','--volumes-from',f.o.CONTAINER+':ro','--entrypoint','tar',c['engine'],'-cf','-','-C','/var/lib/odoo/filestore',f.o.QA],stdout=stream)
f.save('qa-update-backup.json',{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in dest.iterdir()})
names=[m['name'] for m in json.loads((f.OUT/'modules-before.json').read_text()) if m['name'].startswith('baseer_')]+['om_hr_payroll']
args=['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','run','--rm','--no-deps','reports_qa','odoo','--config=/etc/odoo/odoo.local.conf',
 '--addons-path='+f.audit.ADDONS,'--database='+f.o.QA,'--update='+','.join(names),'--stop-after-init','--no-http','--max-cron-threads=0']
t=time.monotonic();r=subprocess.run(args,cwd=f.o.ROOT,capture_output=True,text=True,encoding='utf-8')
(f.OUT/'qa-update.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf-8')
assert r.returncode==0,'QA stopped; upgrade failed. Follow full rollback procedure.'
changed=[table for table,v in baseline.items() if projection(table,v)!=v['hash']]
assert not any(table.startswith('account_') for table in changed),changed
metadata_changed=[]
for table,v in baseline.items():
 if table.startswith('account_'):
  assert int(f.o.sql(f.o.QA,'SELECT count(*) FROM '+table))==len(v['ids']),table+' added financial rows'
 now=f.o.sql(f.o.QA,"SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM (SELECT id,write_date,write_uid FROM "+table+")t")
 if now!=v['audit_metadata_hash']:metadata_changed.append(table)
assert main_before==f.audit.snapshot('baseer_dev'),'Main changed unexpectedly'
f.save('qa-update-result.json',{'success':True,'database':f.o.QA,'seconds':round(time.monotonic()-t,2),
 'source_archive_sha256':c['archive_sha256'],'preexisting_columns_changed_tables':changed,'accounting_history_unchanged':True,'main_unchanged':True,
 'projection_policy':'All original columns/row IDs except separately recorded write_date/write_uid metadata. No amounts, accounts, posting dates, partners, states or original financial links are excluded.',
 'audit_metadata_changed_tables':metadata_changed,'new_accounting_transactions':0,
 'backup_directory':str(dest),'modules':names})
f.o.run(['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','up','-d','--no-deps','reports_qa'],capture_output=True)
print('QA upgraded; original accounting history and main preserved. Changed projections:',changed)
