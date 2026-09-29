"""PB2 isolated integration runner; live QA update remains a root-only later step."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
import om_payroll_ops as o
import full_audit_ops as audit
OUT=o.ROOT/'docs/releases/2026-09-09-pb2-readiness'
BACK=o.ROOT/'.local-backups/pb2-20260909'
TEST='baseer_pb2_test_20260909'
ADDONS=audit.ADDONS
def save(name,data):
 OUT.mkdir(exist_ok=True,parents=True)
 (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
def prepare():
 assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+TEST+"'")=='0'
 o.OUT=OUT;o.BACK=BACK
 save('main-before.json',audit.snapshot('baseer_dev'))
 save('qa-full-before.json',audit.snapshot(o.QA))
 o.backup()
 o.run(['docker','start',o.CONTAINER],capture_output=True)
 print('Coherent backup complete; QA baseline restarted, safe to edit source',flush=True)
 began=time.monotonic()
 o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" '+TEST],capture_output=True)
 o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" --no-owner -d '+TEST+' /tmp/om-payroll-before.dump'],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'mkdir','-p','/tmp/pb2-evidence','/var/lib/odoo/filestore/'+TEST,'/tmp/pb2-restore'])
 o.run(['docker','cp',str(BACK/'preinstall/filestore.tar.gz'),o.CONTAINER+':/tmp/pb2-filestore.tar.gz'],capture_output=True)
 o.run(['docker','exec',o.CONTAINER,'tar','-xzf','/tmp/pb2-filestore.tar.gz','-C','/tmp/pb2-restore'])
 o.run(['docker','exec',o.CONTAINER,'cp','-a','/tmp/pb2-restore/'+o.QA+'/.','/var/lib/odoo/filestore/'+TEST+'/'])
 save('clone.json',{'database':TEST,'filestore':True,'restore_seconds':round(time.monotonic()-began,2)})
 print('Test clone ready',TEST,flush=True)
def execute(name,script=None,upgrade=False):
 args=['docker','exec']+(['-i'] if script else [])+[o.CONTAINER,'/entrypoint.sh','odoo']+([] if upgrade else ['shell'])
 args+=['--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+TEST,'--no-http','--max-cron-threads=0','--logfile=/tmp/pb2-evidence/'+name+'.log']
 if upgrade:args+=['--update=baseer_payroll','--stop-after-init']
 started=time.monotonic()
 r=subprocess.run(args,input=script,text=True,encoding='utf8',capture_output=True,cwd=o.ROOT)
 (OUT/(name+'-stdout.txt')).write_text(r.stdout+'\n'+r.stderr,encoding='utf8')
 runtime=OUT/'runtime';runtime.mkdir(exist_ok=True)
 o.run(['docker','cp',o.CONTAINER+':/tmp/pb2-evidence/.',str(runtime)],capture_output=True)
 print(r.stdout[-8000:]);print(r.stderr[-1500:]);print('elapsed',round(time.monotonic()-started,2),'exit',r.returncode)
 assert r.returncode==0
def run(path):
 p=(o.ROOT/path).resolve();assert p.is_relative_to(o.ROOT/'docs')
 script=p.read_text(encoding='utf-8-sig').replace('/mnt/qa-evidence','/tmp/pb2-evidence')
 execute(p.stem,"assert env.cr.dbname=="+repr(TEST)+"\n"+script)
if __name__=='__main__':
 if sys.argv[1]=='prepare':prepare()
 elif sys.argv[1]=='upgrade':execute('upgrade',upgrade=True)
 elif sys.argv[1]=='run':run(sys.argv[2])
