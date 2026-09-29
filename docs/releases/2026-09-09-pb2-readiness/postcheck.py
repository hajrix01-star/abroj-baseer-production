"""Read-only verification after the accepted PB2 QA upgrade."""
import json,sys,subprocess,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import pb2_ops as p
script=r'''
import json
assert env.cr.dbname=='baseer_reports_qa_20260907'
checks={}
checks['version']=env['ir.module.module'].search([('name','=','baseer_payroll')]).installed_version=='19.0.1.5.0'
checks['default_enabled']=env['hr.employee'].default_get(['baseer_payroll_enabled'])['baseer_payroll_enabled'] is True
checks['stored_refresh_field']=env['hr.payslip']._fields['baseer_needs_refresh'].store
checks['readiness_derived']=not env['hr.payslip']._fields['baseer_readiness'].store
checks['default_flag_manager_scope']=env['hr.employee']._fields['baseer_payroll_enabled'].groups=='om_hr_payroll.group_hr_payroll_manager'
for lang in ['en_US','ar_001']:
    arch=env['hr.payslip.run'].with_context(lang=lang).get_view(view_id=env.ref('baseer_payroll.view_baseer_payroll_run_form').id,view_type='form')['arch']
    checks['run_view_'+lang]='baseer_readiness_warning' in arch and 'baseer_pending_setup_count' in arch
    employee=env['hr.employee'].with_context(lang=lang).get_view(view_type='form')['arch']
    checks['contract_hint_'+lang]=('غير محدد المدة' if lang=='ar_001' else 'For an open-ended contract') in employee
    checks['no_baseer_tab_'+lang]='name="baseer_payroll"' not in employee
env.cr.rollback()
print('PB2_POSTCHECK='+json.dumps(checks))
assert all(checks.values()),checks
'''
args=['docker','exec','-i',p.o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path='+p.ADDONS,'--database='+p.o.QA,'--no-http','--max-cron-threads=0','--logfile=/tmp/pb2-postcheck.log']
r=subprocess.run(args,input=script,text=True,encoding='utf8',capture_output=True)
(p.OUT/'postcheck-stdout.txt').write_text(r.stdout+'\n'+r.stderr,encoding='utf8')
print(r.stdout[-4000:]);print(r.stderr[-1500:]);assert r.returncode==0
checks=json.loads(next(line.removeprefix('PB2_POSTCHECK=') for line in r.stdout.splitlines() if line.startswith('PB2_POSTCHECK=')))
checks['qa_http']=urllib.request.urlopen('http://127.0.0.1:18070/web/login',timeout=30).status==200
checks['main_preserved']=p.audit.snapshot('baseer_dev')==json.loads((p.OUT/'main-before.json').read_text())
p.save('postcheck.json',checks);assert all(checks.values())
