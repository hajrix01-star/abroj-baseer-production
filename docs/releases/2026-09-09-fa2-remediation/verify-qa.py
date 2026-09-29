"""Read-only post-deployment checks; no test financial records on live QA."""
import json,subprocess,sys,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
script='''
import json
assert env.cr.dbname=='baseer_reports_qa_20260907'
checks=[]
def check(name,ok):
 checks.append({'name':name,'passed':bool(ok)})
 assert ok,name
for name,version in [('baseer_payroll','19.0.1.4.0'),('baseer_pos_summary','19.0.1.4.0'),('baseer_service_seed','19.0.1.1.1')]:
 m=env['ir.module.module'].search([('name','=',name)],limit=1)
 check(name+' installed version',m.state=='installed' and m.latest_version==version)
check('no pending module operations',not env['ir.module.module'].search_count([('state','in',['to install','to upgrade','to remove'])]))
for model in ['hr.employee','hr.payslip.run','hr.payslip','baseer.hr.loan','baseer.hr.eos','baseer.payroll.correction','baseer.purchase.batch','baseer.hr.service','baseer.pos.summary','baseer.pos.day.entry']:
 check(model+' Arabic form',bool(env[model].with_context(lang='ar_001').get_view(view_type='form')['arch']))
fields=env['baseer.payroll.correction'].with_context(lang='ar_001').fields_get(['slip_id','kind','date','reason'])
for name,label in [('slip_id','كشف الراتب'),('kind','نوع التصحيح'),('date','التاريخ'),('reason','السبب')]:check(name+' Arabic label',fields[name]['string']==label)
check('native contribution report handler','report.om_hr_payroll.report_contribution_register' in env.registry)
env.cr.execute("SELECT count(*) FROM (SELECT move_id FROM account_move_line JOIN account_move ON account_move.id=move_id WHERE account_move.state='posted' GROUP BY move_id HAVING abs(sum(balance))>0.01)t")
check('all posted native entries balanced',env.cr.fetchone()[0]==0)
env.cr.rollback()
print('FA2_QA_RESULT='+json.dumps({'checks':checks,'count':len(checks),'passed':True,'read_only':True},ensure_ascii=False))
'''
r=subprocess.run(['docker','exec','-i',f.o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf',
 '--addons-path='+f.audit.ADDONS,'--database='+f.o.QA,'--no-http','--max-cron-threads=0','--logfile=/tmp/fa2-post-verify.log'],input=script,capture_output=True,text=True,encoding='utf8')
(f.OUT/'qa-post-verify-stdout.txt').write_text(r.stdout+'\n'+r.stderr,encoding='utf8')
assert r.returncode==0,'Post-upgrade smoke failed'
lines=[x for x in r.stdout.splitlines() if x.startswith('FA2_QA_RESULT=')]
assert len(lines)==1,r.stdout[-1000:]
result=json.loads(lines[0].split('=',1)[1])
with urllib.request.urlopen('http://127.0.0.1:18070/web/login',timeout=30) as response:result['http_status']=response.status
assert result['http_status']==200
result['main_unchanged']=f.audit.snapshot('baseer_dev')==json.loads((f.OUT/'main-before.json').read_text())
assert result['main_unchanged']
f.save('qa-post-verify.json',result)
print('QA read-only checks passed',result['count'],'HTTP',result['http_status'],'main preserved')
