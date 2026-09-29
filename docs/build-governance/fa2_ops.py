"""FA2 exclusive clones, immutable baseline sources, and evidence collection."""
import hashlib,json,subprocess,sys,time,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import om_payroll_ops as o
import full_audit_ops as audit
OUT=o.ROOT/'docs/releases/2026-09-09-fa2-remediation'
BACK=o.ROOT/'.local-backups/fa2-20260909'
SCOPES=('core','payroll','sales','security')
OWNERS={
 'payroll':['custom_addons/baseer_payroll'],
 'sales':['custom_addons/baseer_pos_summary'],
 'security':['custom_addons/baseer_payroll/security/security.xml','custom_addons/baseer_service_seed/models/purchase_batch.py',
  'third_party_addons/odoomates_19/om_hr_payroll/wizard/hr_payroll_contribution_register_report.py',
  'third_party_addons/odoomates_19/om_hr_payroll/report/report_contribution_register.py'],
 'core':['custom_addons','third_party_addons']}
def save(name,value):
 OUT.mkdir(parents=True,exist_ok=True)
 (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def db(scope):
 assert scope in SCOPES or scope=='main'
 return 'baseer_fix_'+scope+'_20260909'
def source(scope):
 db(scope)
 if scope=='main':scope='core'
 return '/tmp/fa2-source-'+scope
def addons(scope):
 p=source(scope)
 return '/usr/lib/python3/dist-packages/odoo/addons,'+p+'/custom_addons,'+p+'/third_party_addons/erp_heritage_19,'+p+'/third_party_addons/odoomates_19'
def capture(scope,name,args,script=None):
 started=time.monotonic()
 r=subprocess.run(args,input=script,text=True,encoding='utf-8',capture_output=True,cwd=o.ROOT)
 (OUT/(scope+'-'+name+'-stdout.txt')).write_text(r.stdout+'\nSTDERR:\n'+r.stderr,encoding='utf-8')
 dest=OUT/(scope+'-runtime');dest.mkdir(exist_ok=True)
 o.run(['docker','cp',o.CONTAINER+':/tmp/fa2-evidence-'+scope+'/.',str(dest)],capture_output=True)
 print(r.stdout[-9000:]);print(r.stderr[-2000:]);print('Elapsed',round(time.monotonic()-started,2),'exit',r.returncode)
 assert r.returncode==0,'See '+scope+'-'+name+'-stdout.txt'
def prepare():
 OUT.mkdir(parents=True,exist_ok=True);BACK.mkdir(parents=True,exist_ok=False)
 for s in SCOPES:assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+db(s)+"'")=='0'
 save('qa-before.json',audit.snapshot(o.QA));save('main-before.json',audit.snapshot('baseer_dev'))
 modules=json.loads(o.sql(o.QA,"SELECT json_agg(t) FROM (SELECT name,state,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)t"))
 save('modules-before.json',modules)
 started=time.monotonic()
 o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/fa2-before.dump'])
 o.run(['docker','cp',o.DB+':/tmp/fa2-before.dump',str(BACK/'database.dump')],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'tar','-C','/var/lib/odoo/filestore','-cf','/tmp/fa2-filestore.tar',o.QA],capture_output=True)
 o.run(['docker','cp',o.CONTAINER+':/tmp/fa2-filestore.tar',str(BACK/'filestore.tar')],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'mkdir','-p','/tmp/fa2-filestore-snapshot'])
 o.run(['docker','exec',o.CONTAINER,'tar','-C','/tmp/fa2-filestore-snapshot','-xf','/tmp/fa2-filestore.tar'])
 o.run(['docker','cp',str(audit.OUT/'candidate-source.zip'),o.CONTAINER+':/tmp/fa2-baseline-source.zip'],capture_output=True)
 def restore(s):
  began=time.monotonic()
  o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" '+db(s)],capture_output=True)
  o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" --no-owner -d '+db(s)+' /tmp/fa2-before.dump'],capture_output=True)
  o.run(['docker','exec',o.CONTAINER,'mkdir','-p','/var/lib/odoo/filestore/'+db(s),'/tmp/fa2-evidence-'+s,source(s)])
  o.run(['docker','exec',o.CONTAINER,'cp','-a','/tmp/fa2-filestore-snapshot/'+o.QA+'/.','/var/lib/odoo/filestore/'+db(s)+'/'])
  o.run(['docker','exec',o.CONTAINER,'python3','-m','zipfile','-e','/tmp/fa2-baseline-source.zip',source(s)])
  return {'scope':s,'database':db(s),'restore_seconds':round(time.monotonic()-began,2)}
 with ThreadPoolExecutor(max_workers=4) as ex:restored=list(ex.map(restore,SCOPES))
 save('clones.json',{'source':o.QA,'module_count':len(modules),'clones':restored,'backup_seconds_total':round(time.monotonic()-started,2),
   'database_sha256':hashlib.sha256((BACK/'database.dump').read_bytes()).hexdigest(),
   'filestore_sha256':hashlib.sha256((BACK/'filestore.tar').read_bytes()).hexdigest(),'backup_directory':str(BACK)})
 print('Ready',json.dumps(restored))
def stage(scope):
 paths=OWNERS[scope];files={}
 for rel in paths:
  p=o.ROOT/rel
  if p.is_dir():
   target=source(scope)+'/'+rel
   o.run(['docker','exec',o.CONTAINER,'mkdir','-p',target])
   o.run(['docker','cp',str(p)+'/.',o.CONTAINER+':'+target],capture_output=True)
   candidates=[x for x in p.rglob('*') if x.is_file() and '__pycache__' not in x.parts]
  else:
   o.run(['docker','cp',str(p),o.CONTAINER+':'+source(scope)+'/'+rel],capture_output=True)
   candidates=[p]
  for x in candidates:files[x.relative_to(o.ROOT).as_posix()]=hashlib.sha256(x.read_bytes()).hexdigest()
 save(scope+'-source.json',{'database':db(scope),'overlay':paths,'sha256':files})
 print('Staged',scope,len(files))
def upgrade(scope):
 names={'payroll':['baseer_payroll'],'sales':['baseer_pos_summary'],'security':['baseer_payroll','baseer_service_seed','om_hr_payroll'],
  'core':[m['name'] for m in json.loads((OUT/'modules-before.json').read_text()) if m['name'].startswith('baseer_')]+['om_hr_payroll']}
 if scope=='main':names[scope]=names['core']
 extra=['--init='+','.join(names[scope])] if scope=='main' else []
 capture(scope,'upgrade',['docker','exec',o.CONTAINER,'/entrypoint.sh','odoo','--config=/etc/odoo/odoo.local.conf',
 '--addons-path='+addons(scope),'--database='+db(scope),'--update='+','.join(names[scope]),'--stop-after-init','--no-http','--max-cron-threads=0',
 '--logfile=/tmp/fa2-evidence-'+scope+'/upgrade.log']+extra)

def prepare_main():
 target=db('main');assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+target+"'")=='0'
 before=audit.snapshot('baseer_dev');save('main-rehearsal-before.json',before)
 save('main-modules-before.json',json.loads(o.sql('baseer_dev',"SELECT json_agg(t) FROM (SELECT name,state,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)t")))
 started=time.monotonic()
 o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc baseer_dev -f /tmp/fa2-main-before.dump'])
 o.run(['docker','cp',o.DB+':/tmp/fa2-main-before.dump',str(BACK/'main-database.dump')],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'tar','-C','/var/lib/odoo/filestore','-cf','/tmp/fa2-main-filestore.tar','baseer_dev'])
 o.run(['docker','cp',o.CONTAINER+':/tmp/fa2-main-filestore.tar',str(BACK/'main-filestore.tar')],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'mkdir','-p','/tmp/fa2-main-restore','/tmp/fa2-evidence-main','/var/lib/odoo/filestore/'+target])
 o.run(['docker','exec',o.CONTAINER,'tar','-C','/tmp/fa2-main-restore','-xf','/tmp/fa2-main-filestore.tar'])
 o.run(['docker','exec',o.CONTAINER,'cp','-a','/tmp/fa2-main-restore/baseer_dev/.','/var/lib/odoo/filestore/'+target+'/'])
 o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" '+target])
 o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" --no-owner -d '+target+' /tmp/fa2-main-before.dump'],capture_output=True)
 restored=audit.snapshot(target)
 save('main-restore-result.json',{'database':target,'business_rows_match':restored==before,'elapsed_seconds':round(time.monotonic()-started,2),'filestore_copied':True})
 assert before==restored
 print('Main rehearsal clone ready',target)
def run(scope,path):
 p=(o.ROOT/path).resolve();assert p.is_relative_to(o.ROOT/'docs')
 script=p.read_text(encoding='utf-8-sig').replace(o.QA,db(scope))
 for s in SCOPES:
  script=script.replace('baseer_audit_'+s+'_20260909',db(scope))
  script=script.replace('baseer_fix_'+s+'_20260909',db(scope))
 script=script.replace('/mnt/qa-evidence','/tmp/fa2-evidence-'+scope)
 script="assert env.cr.dbname=="+repr(db(scope))+"\n"+script
 capture(scope,p.stem,['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf',
 '--addons-path='+addons(scope),'--database='+db(scope),'--no-http','--max-cron-threads=0','--logfile=/tmp/fa2-evidence-'+scope+'/'+p.stem+'.log'],script)
if __name__=='__main__':
 mode=sys.argv[1]
 if mode=='prepare':prepare()
 elif mode=='prepare-main':prepare_main()
 elif mode=='stage':stage(sys.argv[2])
 elif mode=='upgrade':upgrade(sys.argv[2])
 elif mode=='run':run(sys.argv[2],sys.argv[3])
