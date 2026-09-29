"""Authorized FA2+PB2 promotion; never copy QA business data to MAIN."""
import ast,hashlib,json,shutil,subprocess,sys,time,zipfile
from pathlib import Path
import om_payroll_ops as o
import full_audit_ops as a
ROOT=o.ROOT
OUT=ROOT/'docs/releases/2026-09-09-main-promotion'
BACK=ROOT/'.local-backups/main-promotion-20260909'
TEST='baseer_main_rehearsal_20260909'
MAIN='baseer_dev'
CONTAINER='baseer_odoo_dev-odoo-1'
IMAGE='odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd'
MODS='baseer_cash_categories,baseer_category_display,baseer_company_setup,baseer_hr_services,baseer_legion_compat,baseer_payroll,baseer_pos_summary,baseer_purchase_batch,baseer_report_layout,baseer_service_seed,baseer_web_navigation,om_hr_payroll'
ADDONS=a.ADDONS
def save(name,value):
 OUT.mkdir(parents=True,exist_ok=True)
 (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
def inventory():
 BACK.mkdir(parents=True,exist_ok=False)
 for database in (MAIN,o.QA):
  save(database+'-modules.json',json.loads(o.sql(database,"SELECT json_agg(t) FROM (SELECT name,state,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)t")))
  save(database+'-before.json',a.snapshot(database))
 inspect=json.loads(o.run(['docker','inspect',CONTAINER],capture_output=True,text=True).stdout)[0]
 save('main-runtime.json',{'image':inspect['Config']['Image'],'image_id':inspect['Image'],'mounts':inspect['Mounts'],'command':inspect['Config']['Cmd'],'compose_files':inspect['Config']['Labels'].get('com.docker.compose.project.config_files'),'running':inspect['State']['Running']})
 print('MAIN installed',len(json.loads((OUT/(MAIN+'-modules.json')).read_text())))
 print(o.sql(MAIN,"SELECT json_agg(t) FROM (SELECT id,name FROM res_company ORDER BY id)t"))
 print('Main baseline',json.loads((OUT/(MAIN+'-before.json')).read_text()))
def freeze():
 fa=json.loads((ROOT/'docs/releases/2026-09-09-fa2-remediation/candidate.json').read_text())
 pb=json.loads((ROOT/'docs/releases/2026-09-09-pb2-readiness/candidate.json').read_text())
 files=dict(fa['files']);files.update({'custom_addons/'+r:h for r,h in pb['files'].items()})
 dest=BACK/'candidate';dest.mkdir(exist_ok=True)
 for rel,h in files.items():
  src=ROOT/rel;data=src.read_bytes();assert hashlib.sha256(data).hexdigest()==h,rel
  target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
 archive=OUT/'candidate-source.zip'
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
  for rel in files:z.write(dest/rel,rel)
 o.run(['git','init','--initial-branch=codex/mp3-main',str(dest)],capture_output=True)
 o.run(['git','-C',str(dest),'config','core.autocrlf','false'])
 o.run(['git','-C',str(dest),'add','.'])
 if o.run(['git','-C',str(dest),'status','--porcelain'],capture_output=True,text=True).stdout.strip():
  o.run(['git','-C',str(dest),'-c','user.name=Codex Release','-c','user.email=codex-release@localhost','commit','-qm','Promote accepted FA2 and PB2 to original'],capture_output=True)
 commit=o.run(['git','-C',str(dest),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
 fa_commit=o.run(['git','-C',fa['source_directory'],'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
 save('candidate.json',{'commit':commit,'files':files,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'parents':[fa_commit,pb['commit']],'image':IMAGE,'modules':MODS.split(','),'source_directory':str(dest)})
 # Proven previous installed addon release, not the currently edited shared mount.
 old=json.loads((ROOT/'docs/releases/2026-09-08-main-promotion/manifest.json').read_text())
 prior=BACK/'previous-source';prior.mkdir()
 for row in old['files']:
  rel=row['path'];src=ROOT/'.local-backups/main-promotion-20260908/candidate'/rel
  data=src.read_bytes();assert hashlib.sha256(data).hexdigest()==row['sha256'],rel
  target=prior/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
 installed={r['name']:r['latest_version'] for r in json.loads((OUT/(MAIN+'-modules.json')).read_text())}
 for name,version in old['modules'].items():
  if name in installed:assert installed[name]==version,(name,installed[name],version)
 save('previous-source.json',{'source_directory':str(prior),'files':old['files'],'installed_versions_match':True,'image':IMAGE})
 (prior/'third_party_addons/odoomates_19').mkdir(exist_ok=True)
 print('Frozen',commit,len(files),'previous',len(old['files']))

def table_snapshot(database):
 tables=json.loads(o.sql(database,"SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'account\\_%' ESCAPE '\\' OR tablename LIKE 'baseer\\_%' ESCAPE '\\' OR tablename IN ('hr_employee','hr_version','hr_payslip','hr_payslip_run','pos_order','pos_order_line','pos_payment','pos_session','res_company','res_partner','product_template','product_product','product_category','res_groups_users_rel','res_company_users_rel'))"))
 pieces=[]
 for table in tables:
  quoted='"'+table.replace('"','""')+'"'
  pieces.append("SELECT '"+table.replace("'","''")+"' name,coalesce(json_agg(t),'[]'::json) rows FROM (SELECT * FROM "+quoted+')t')
 return json.loads(o.sql(database,'SELECT json_object_agg(name,rows) FROM ('+' UNION ALL '.join(pieces)+') s'))

def compare(before,after):
 changes=[];added={}
 for table,rows in before.items():
  new=after.get(table,[])
  if rows and 'id' in rows[0]:
   current={r['id']:r for r in new};known={r['id'] for r in rows}
   for row in rows:
    changed=[k for k,v in row.items() if current.get(row['id'],{}).get(k)!=v]
    if changed:changes.append({'table':table,'id':row['id'],'columns':changed})
   added[table]=len([r for r in new if r['id'] not in known])
  elif rows:
   from collections import Counter
   keys=list(rows[0]);fmt=lambda r:json.dumps({k:r.get(k) for k in keys},sort_keys=True)
   old=Counter(map(fmt,rows));now=Counter(map(fmt,new))
   if old-now:changes.append({'table':table,'removed_rows':sum((old-now).values())})
   added[table]=sum((now-old).values())
  else:added[table]=len(new)
 for table in after.keys()-before.keys():added[table]=len(after[table])
 return {'original_changes':changes,'added_rows':{k:v for k,v in added.items() if v}}

def backup(label):
 dest=BACK/label;dest.mkdir(exist_ok=False)
 o.run(['docker','stop',CONTAINER],capture_output=True)
 assert o.sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='baseer_dev'")=='0','Other MAIN writers remain'
 baseline=table_snapshot(MAIN)
 (dest/'rows-before.json').write_text(json.dumps(baseline,ensure_ascii=False),encoding='utf8')
 o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc baseer_dev -f /tmp/mp3-'+label+'.dump'],capture_output=True)
 o.run(['docker','cp',o.DB+':/tmp/mp3-'+label+'.dump',str(dest/'database.dump')],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'tar','-czf','/tmp/mp3-'+label+'-filestore.tar.gz','-C','/var/lib/odoo/filestore','baseer_dev'],capture_output=True)
 o.run(['docker','cp',o.CONTAINER+':/tmp/mp3-'+label+'-filestore.tar.gz',str(dest/'filestore.tar.gz')],capture_output=True)
 for rel in ('compose.yaml','compose.mp3-previous.yaml','compose.main-release.yaml','config/odoo.local.conf','.env'):
  shutil.copy2(ROOT/rel,dest/Path(rel).name)
 save(label+'-backup.json',{'database':MAIN,'coherent':True,'files':{n:{'size':(dest/n).stat().st_size,'sha256':hashlib.sha256((dest/n).read_bytes()).hexdigest()} for n in ('database.dump','filestore.tar.gz')},'private_directory':str(dest),'restoration_source':str(BACK/('candidate' if label=='completed' else 'previous-source'))})
 print('Coherent backup',label,flush=True)

def prepare():
 assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+TEST+"'")=='0'
 backup('rehearsal')
 # Resume old MAIN using its verified previous addon snapshot while rehearsing.
 o.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','-f','compose.mp3-previous.yaml','up','-d','--no-deps','odoo'],capture_output=True)
 o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" '+TEST],capture_output=True)
 o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" --no-owner --exit-on-error -d '+TEST+' /tmp/mp3-rehearsal.dump'],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'mkdir','-p','/tmp/mp3-restore','/var/lib/odoo/filestore/'+TEST],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'tar','-xzf','/tmp/mp3-rehearsal-filestore.tar.gz','-C','/tmp/mp3-restore'],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'cp','-a','/tmp/mp3-restore/baseer_dev/.','/var/lib/odoo/filestore/'+TEST+'/'],capture_output=True)
 before=json.loads((BACK/'rehearsal/rows-before.json').read_text())
 assert compare(before,table_snapshot(TEST))=={'original_changes':[],'added_rows':{}}
 save('restore.json',{'database':TEST,'rows_exact':True,'filestore_restored':True})
 o.run(['docker','exec',o.CONTAINER,'mkdir','-p','/tmp/mp3-source','/tmp/mp3-evidence'])
 o.run(['docker','cp',str(OUT/'candidate-source.zip'),o.CONTAINER+':/tmp/mp3-source.zip'],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'python3','-m','zipfile','-e','/tmp/mp3-source.zip','/tmp/mp3-source'],capture_output=True)
 print('Rehearsal ready',flush=True)

def test_upgrade():
 args=['docker','exec',o.CONTAINER,'/entrypoint.sh','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS.replace('/mnt/baseer-addons','/tmp/mp3-source/custom_addons').replace('/mnt/third-party-addons','/tmp/mp3-source/third_party_addons'),'--database='+TEST,'--init='+MODS,'--update='+MODS,'--without-demo=all','--no-http','--max-cron-threads=0','--stop-after-init']
 r=subprocess.run(args,capture_output=True,text=True,encoding='utf8');(OUT/'rehearsal-upgrade.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf8');assert r.returncode==0
 before=json.loads((BACK/'rehearsal/rows-before.json').read_text())
 result=compare(before,table_snapshot(TEST));save('rehearsal-diff.json',result)
 print('Rehearsal upgrade done',json.dumps(result),flush=True)

def verify(database):
 assert database in (MAIN,TEST)
 candidate=json.loads((OUT/'candidate.json').read_text())
 script=(OUT/'acceptance-checks.py').read_text(encoding='utf8').replace('/mnt/qa-evidence','/tmp/mp3-evidence').replace('807712c3dd78db4bdbec15d6a264b5b72feec951',candidate['commit'])
 paths=ADDONS.replace('/mnt/baseer-addons','/tmp/mp3-source/custom_addons').replace('/mnt/third-party-addons','/tmp/mp3-source/third_party_addons')
 args=['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path='+paths,'--database='+database,'--no-http','--max-cron-threads=0','--logfile=/tmp/mp3-evidence/'+database+'.log']
 r=subprocess.run(args,input=script,capture_output=True,text=True,encoding='utf8')
 (OUT/('verify-'+database+'.txt')).write_text(r.stdout+'\n'+r.stderr,encoding='utf8')
 o.run(['docker','cp',o.CONTAINER+':/tmp/mp3-evidence/acceptance-'+database+'.json',str(OUT)],capture_output=True)
 d=json.loads((OUT/('acceptance-'+database+'.json')).read_text())
 print('Acceptance',database,d['status'],len(d['checks']),[c for c in d['checks'] if not c['passed']],flush=True)
 assert r.returncode==0 and d['status']=='passed'

def verify_candidate():
 c=json.loads((OUT/'candidate.json').read_text());root=BACK/'candidate'
 actual={f.relative_to(root).as_posix() for group in ('custom_addons','third_party_addons') for f in (root/group).rglob('*') if f.is_file()}
 assert actual==set(c['files'])
 assert all(hashlib.sha256((root/rel).read_bytes()).hexdigest()==h for rel,h in c['files'].items())
 assert hashlib.sha256((OUT/'candidate-source.zip').read_bytes()).hexdigest()==c['archive_sha256']
 assert o.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()==c['commit']
 assert not o.run(['git','-C',str(root),'status','--porcelain'],capture_output=True,text=True).stdout.strip()
 return c

def preservation_gate(diff,before,after,database):
 # Accepted native master write metadata only; no financial-column exceptions.
 metadata={'res_company':{1,2,3},'res_partner':{2,3},'hr_employee':{1}}
 fills={4:221,6:399,8:577,10:586}
 accepted=[];forbidden=[]
 for d in diff['original_changes']:
  table=d['table'];ident=d.get('id');cols=set(d.get('columns',[]))
  if ident in metadata.get(table,set()) and cols<= {'write_date','write_uid'}:
   accepted.append(d);continue
  if table=='account_payment_method_line' and ident in fills and cols<= {'payment_account_id','write_date','write_uid'}:
   old=next(r for r in before[table] if r['id']==ident);new=next(r for r in after[table] if r['id']==ident)
   assert old['payment_account_id'] is None and new['payment_account_id']==fills[ident]
   journal=next(r for r in before['account_journal'] if r['id']==old['journal_id'])
   assert journal['default_account_id']==fills[ident] and journal['type'] in ('bank','cash') and journal['active']
   assert old['journal_id']==new['journal_id'] and old['payment_method_id']==new['payment_method_id']
   # Recheck the exact target account, method direction and journal usage live.
   query="SELECT count(*) FROM account_payment_method_line l JOIN account_payment_method m ON m.id=l.payment_method_id JOIN account_journal j ON j.id=l.journal_id JOIN account_account a ON a.id=l.payment_account_id JOIN account_account_res_company_rel r ON r.account_account_id=a.id AND r.res_company_id=j.company_id WHERE l.id="+str(ident)+" AND m.code='manual' AND m.payment_type='outbound' AND a.account_type='asset_cash' AND NOT a.reconcile AND a.active AND l.payment_account_id=j.default_account_id AND NOT EXISTS(SELECT 1 FROM account_move x WHERE x.journal_id=j.id) AND NOT EXISTS(SELECT 1 FROM account_payment x WHERE x.journal_id=j.id) AND NOT EXISTS(SELECT 1 FROM account_bank_statement_line x WHERE x.journal_id=j.id)"
   assert o.sql(database,query)=='1','Unproven payment-account seed fill'
   accepted.append(dict(d,classification='CAS-002: empty unused manual outbound method uses existing journal liquidity account'));continue
  forbidden.append(d)
 assert not forbidden,forbidden
 financial={'account_move','account_move_line','account_payment','account_partial_reconcile','account_full_reconcile','account_bank_statement','account_bank_statement_line','pos_order','pos_order_line','pos_payment','pos_session','hr_payslip','hr_payslip_run','hr_employee','res_company','baseer_hr_service','baseer_hr_loan','baseer_hr_eos','baseer_pos_summary','baseer_purchase_batch','baseer_pos_day_entry','baseer_pos_closure','baseer_payroll_correction','baseer_pos_correction'}
 assert not {t:n for t,n in diff['added_rows'].items() if t in financial},'Unexpected new business records'
 group_id=int(o.sql(database,"SELECT res_id FROM ir_model_data WHERE module='om_hr_payroll' AND name='group_hr_payroll_manager' AND model='res.groups'"))
 users=json.loads(o.sql(database,"SELECT json_agg(res_id ORDER BY res_id) FROM ir_model_data WHERE module='base' AND name IN ('user_root','user_admin') AND model='res.users'"))
 original_acl={(r['uid'],r['gid']) for r in before['res_groups_users_rel']}
 new_acl={(r['uid'],r['gid']) for r in after['res_groups_users_rel']}-original_acl
 assert new_acl=={(uid,group_id) for uid in users},'Unexpected new user role membership'
 assert diff['added_rows'].get('res_company_users_rel',0)==0,'New company access'
 save('preservation-'+database+'.json',{'passed':True,'reviewed_original_changes':accepted,'no_new_business_transactions':True})

def restore_cutover():
 target='baseer_main_restore_20260909'
 assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+target+"'")=='0'
 o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" '+target],capture_output=True)
 o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" --no-owner --exit-on-error -d '+target+' /tmp/mp3-cutover.dump'],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'mkdir','-p','/tmp/mp3-cutover-restore','/var/lib/odoo/filestore/'+target])
 o.run(['docker','exec',o.CONTAINER,'tar','-xzf','/tmp/mp3-cutover-filestore.tar.gz','-C','/tmp/mp3-cutover-restore'],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'cp','-a','/tmp/mp3-cutover-restore/baseer_dev/.','/var/lib/odoo/filestore/'+target+'/'],capture_output=True)
 assert compare(json.loads((BACK/'cutover/rows-before.json').read_text()),table_snapshot(target))=={'original_changes':[],'added_rows':{}}
 rows=json.loads(o.sql(target,"SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT store_fname,checksum,file_size FROM ir_attachment WHERE type='binary' AND store_fname IS NOT NULL)t"))
 code='import hashlib,json\nfrom pathlib import Path\nrows='+repr(rows)+'\nroot=Path("/var/lib/odoo/filestore/'+target+'")\nfor r in rows:\n p=(root/r["store_fname"]).resolve()\n assert p.is_relative_to(root) and p.is_file()\n assert hashlib.sha1(p.read_bytes()).hexdigest()==r["checksum"] and p.stat().st_size==r["file_size"]\nprint(len(rows))\n'
 r=o.run(['docker','exec','-i',o.CONTAINER,'python3','-'],input=code,text=True,capture_output=True)
 save('cutover-restore.json',{'database':target,'original_rows_exact':True,'restored_attachment_references_verified':int(r.stdout.strip()),'restored':True})

def apply_main():
 c=verify_candidate()
 approval=(OUT/'ACCEPTANCE.md').read_text(encoding='utf8')
 assert c['commit'] in approval and 'GO' in approval
 assert json.loads((OUT/('acceptance-'+TEST+'.json')).read_text())['status']=='passed'
 backup('cutover')
 rehearsal_before=json.loads((BACK/'rehearsal/rows-before.json').read_text())
 cutover_before=json.loads((BACK/'cutover/rows-before.json').read_text())
 assert compare(rehearsal_before,cutover_before)=={'original_changes':[],'added_rows':{}},'MAIN changed since rehearsal; rehearse fresh data before proceeding'
 modules=json.loads(o.sql(MAIN,"SELECT json_agg(t) FROM (SELECT name,state,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)t"))
 assert modules==json.loads((OUT/(MAIN+'-modules.json')).read_text()),'MAIN module set changed since rehearsal'
 restore_cutover()
 args=['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','-f','compose.main-release.yaml','run','--rm','--no-deps','odoo','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+MAIN,'--db-filter=^baseer_dev$','--no-database-list','--init='+MODS,'--update='+MODS,'--without-demo=all','--no-http','--max-cron-threads=0','--stop-after-init']
 r=subprocess.run(args,capture_output=True,text=True,encoding='utf8');(OUT/'main-upgrade.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf8');assert r.returncode==0,'MAIN remains stopped; inspect upgrade and use full rollback if required'
 before=json.loads((BACK/'cutover/rows-before.json').read_text());after=table_snapshot(MAIN);diff=compare(before,after);save('main-diff.json',diff)
 preservation_gate(diff,before,after,MAIN)
 assert diff['added_rows']==json.loads((OUT/'rehearsal-diff.json').read_text())['added_rows'],'Seed additions differ from accepted rehearsal'
 verify(MAIN)
 # Persist immutable MAIN source mounts for ordinary future compose up commands.
 path=ROOT/'compose.yaml';text=path.read_text(encoding='utf8')
 for old,new in [('./custom_addons:/mnt/baseer-addons','./.local-backups/main-promotion-20260909/candidate/custom_addons:/mnt/baseer-addons:ro'),('./custom_addons:/mnt/extra-addons','./.local-backups/main-promotion-20260909/candidate/custom_addons:/mnt/extra-addons:ro'),('./third_party_addons:/mnt/third-party-addons:ro','./.local-backups/main-promotion-20260909/candidate/third_party_addons:/mnt/third-party-addons:ro')]:
  assert old in text;text=text.replace(old,new)
 path.write_text(text,encoding='utf8')
 o.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','-f','compose.main-release.yaml','config','--quiet'],capture_output=True)
 backup('completed')
 o.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','-f','compose.main-release.yaml','up','-d','--no-deps','odoo'],capture_output=True)
 save('main-applied.json',{'commit':c['commit'],'success':True,'database':MAIN,'qa_data_not_copied':True,'preservation_passed':True,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
 print('MAIN updated and reopened',c['commit'],flush=True)

def finish():
 import urllib.request
 c=verify_candidate();runtime=json.loads(o.run(['docker','inspect',CONTAINER],capture_output=True,text=True).stdout)[0]
 assert runtime['State']['Running'] and runtime['Config']['Image']==IMAGE
 expected={'/mnt/baseer-addons':'candidate/custom_addons','/mnt/extra-addons':'candidate/custom_addons','/mnt/third-party-addons':'candidate/third_party_addons'}
 for dest,suffix in expected.items():
  mount=next(m for m in runtime['Mounts'] if m['Destination']==dest)
  assert not mount['RW'] and mount['Source'].replace('\\','/').endswith('main-promotion-20260909/'+suffix)
 assert '--database=baseer_dev' in runtime['Config']['Cmd'] and '--db-filter=^baseer_dev$' in runtime['Config']['Cmd']
 http={url:urllib.request.urlopen(url+'/web/login',timeout=30).status for url in ('http://127.0.0.1:18069','http://127.0.0.1:18070')}
 assert all(v==200 for v in http.values())
 assert a.snapshot(o.QA)==json.loads((OUT/(o.QA+'-before.json')).read_text()),'QA business changed'
 save('runtime-final.json',{'commit':c['commit'],'image':runtime['Config']['Image'],'image_id':runtime['Image'],'command':runtime['Config']['Cmd'],'mounts':runtime['Mounts'],'http':http,'qa_business_unchanged':True})
 save('main-modules-final.json',json.loads(o.sql(MAIN,"SELECT json_agg(t) FROM (SELECT name,state,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)t")))
 assert o.sql(MAIN,"SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')")=='0'
 for database in (TEST,'baseer_main_restore_20260909'):
  assert database not in (MAIN,o.QA)
  o.run(['docker','exec',o.DB,'sh','-c','dropdb -U "$POSTGRES_USER" --force '+database],capture_output=True)
  o.run(['docker','exec',o.CONTAINER,'rm','-rf','/var/lib/odoo/filestore/'+database],capture_output=True)
 save('cleanup.json',{'removed_databases':[TEST,'baseer_main_restore_20260909'],'main_and_qa_retained':True,'backups_retained':True})
 print('MAIN verified, QA preserved, isolated clones removed')
if __name__=='__main__':
 if sys.argv[1]=='inventory':inventory()
 elif sys.argv[1]=='freeze':freeze()
 elif sys.argv[1]=='prepare':prepare()
 elif sys.argv[1]=='test-upgrade':test_upgrade()
 elif sys.argv[1]=='verify':verify(sys.argv[2])
 elif sys.argv[1]=='apply-main':apply_main()
 elif sys.argv[1]=='finish':finish()
