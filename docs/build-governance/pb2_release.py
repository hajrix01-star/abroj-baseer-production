"""Seal PB2 payroll overlay and apply only after isolated acceptance."""
import ast,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
from lxml import etree
import pb2_ops as p
o=p.o

def account_snapshot(database):
 tables=json.loads(o.sql(database,"SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'account\\_%' ESCAPE '\\'"))
 # Catalog-provided identifiers only, defensively quoted; one read-only SQL statement.
 pieces=[]
 for table in tables:
  quoted='"'+table.replace('"','""')+'"'
  pieces.append("SELECT '"+table.replace("'","''")+"' AS name,json_build_object('count',count(*),'hash',md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),''))) AS value FROM "+quoted+' t')
 return json.loads(o.sql(database,'SELECT json_object_agg(name,value) FROM ('+' UNION ALL '.join(pieces)+') snapshots'))

def version_snapshot(database):
 return o.sql(database,"SELECT json_build_object('count',count(*),'hash',md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),''))) FROM hr_version t")

def payroll_projection(database, columns=None):
 if columns is None:
  columns={t:o.sql(database,"SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' AND table_name='"+t+"'") for t in ('hr_payslip','hr_payslip_run')}
 hashes={t:json.loads(o.sql(database,"SELECT json_build_object('count',count(*),'hash',md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),''))) FROM (SELECT "+cols+' FROM '+t+') t')) for t,cols in columns.items()}
 return {'columns':columns,'hashes':hashes}
def seal():
 baseline=json.loads((o.ROOT/'docs/releases/2026-09-09-fa2-remediation/candidate.json').read_text())
 source=o.ROOT/'custom_addons/baseer_payroll';dest=p.BACK/'candidate/baseer_payroll';dest.mkdir(parents=True,exist_ok=True)
 files={}
 for f in sorted(source.rglob('*')):
  if not f.is_file() or '__pycache__' in f.parts or f.suffix=='.pyc':continue
  data=f.read_bytes();rel=f.relative_to(source)
  if f.suffix=='.py':ast.parse(data.decode('utf-8-sig'))
  if f.suffix=='.xml':etree.fromstring(data)
  target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
  files['baseer_payroll/'+rel.as_posix()]=hashlib.sha256(data).hexdigest()
 actual={'baseer_payroll/'+f.relative_to(dest).as_posix() for f in dest.rglob('*') if f.is_file()}
 assert actual==set(files),'Stale or unexpected file in candidate overlay'
 for rel,sha in baseline['files'].items():
  if not rel.startswith('custom_addons/baseer_payroll/'):
   assert hashlib.sha256((o.ROOT/rel).read_bytes()).hexdigest()==sha,rel+' unrelated source changed'
 archive=p.OUT/'baseer-payroll-pb2.zip'
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
  for rel in files:z.write(p.BACK/'candidate'/rel,rel)
 with zipfile.ZipFile(archive) as z:
  assert set(z.namelist())==set(files)
  assert all(hashlib.sha256(z.read(rel)).hexdigest()==sha for rel,sha in files.items())
 repo=p.BACK/'candidate'
 if not (repo/'.git').exists():o.run(['git','init','--initial-branch=codex/pb2-candidate',str(repo)],capture_output=True)
 o.run(['git','-C',str(repo),'config','core.autocrlf','false'])
 o.run(['git','-C',str(repo),'add','baseer_payroll'])
 dirty=o.run(['git','-C',str(repo),'status','--porcelain'],capture_output=True,text=True).stdout.strip()
 if dirty:o.run(['git','-C',str(repo),'-c','user.name=Codex Release','-c','user.email=codex-release@localhost','commit','-qm','PB2 employee payroll readiness'],capture_output=True)
 commit=o.run(['git','-C',str(repo),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
 p.save('candidate.json',{'commit':commit,'files':files,'zip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
  'version':ast.literal_eval((source/'__manifest__.py').read_text())['version'],'base_release':'FA2','base_archive_sha256':baseline['archive_sha256'],
  'unaffected_source_matches_base':True,'changed_from_base':[r for r,h in files.items() if baseline['files'].get('custom_addons/'+r)!=h],
  'image':baseline['engine']})
 print('Sealed PB2',commit,len(files))
def apply_qa():
 assert (p.OUT/'ACCEPTANCE.md').exists()
 c=json.loads((p.OUT/'candidate.json').read_text())
 source_files={'baseer_payroll/'+f.relative_to(o.ROOT/'custom_addons/baseer_payroll').as_posix() for f in (o.ROOT/'custom_addons/baseer_payroll').rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}
 assert source_files==set(c['files'])
 for rel,h in c['files'].items():assert hashlib.sha256((o.ROOT/'custom_addons'/rel).read_bytes()).hexdigest()==h,rel
 o.OUT=p.OUT/'deployment';o.OUT.mkdir(exist_ok=True);o.BACK=p.BACK/'deployment'
 o.backup()
 before=p.audit.snapshot(o.QA);main=p.audit.snapshot('baseer_dev')
 accounts=account_snapshot(o.QA);versions=version_snapshot(o.QA)
 payroll=payroll_projection(o.QA)
 p.save('payroll-projection-before.json',payroll)
 p.save('account-tables-before.json',accounts)
 p.save('apply-before.json',before)
 employee_flags=o.sql(o.QA,"SELECT json_agg(t ORDER BY id) FROM (SELECT id,baseer_payroll_enabled FROM hr_employee) t")
 p.save('existing-employee-flags.json',json.loads(employee_flags))
 args=['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','run','--rm','--no-deps','reports_qa','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+p.ADDONS,'--database='+o.QA,'--update=baseer_payroll','--no-http','--max-cron-threads=0','--stop-after-init']
 r=subprocess.run(args,cwd=o.ROOT,capture_output=True,text=True,encoding='utf8')
 (p.OUT/'deployment/upgrade.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf8')
 assert r.returncode==0,'Upgrade failed; QA stopped with backup retained'
 after=p.audit.snapshot(o.QA)
 changed=[t for t in before if before[t]!=after[t]]
 assert not any(t.startswith('account_') for t in changed),changed
 assert account_snapshot(o.QA)==accounts,'Account table contents changed'
 assert version_snapshot(o.QA)==versions,'Employee salary/contract versions changed'
 assert before['hr_employee']==after['hr_employee'],'Existing employee records changed'
 assert payroll_projection(o.QA,payroll['columns'])==payroll,'Original payroll data changed'
 assert p.audit.snapshot('baseer_dev')==main
 assert o.sql(o.QA,"SELECT json_agg(t ORDER BY id) FROM (SELECT id,baseer_payroll_enabled FROM hr_employee) t")==employee_flags,'Existing employee flags changed'
 p.save('apply-result.json',{'success':True,'changed_tables':changed,'financial_history_unchanged':True,'main_unchanged':True,'source_commit':c['commit']})
 o.run(['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','up','-d','--no-deps','reports_qa'],capture_output=True)
 print('PB2 applied to QA; main preserved')
if __name__=='__main__':
 if sys.argv[1]=='seal':seal()
 elif sys.argv[1]=='apply-qa':apply_qa()
