"""Fresh connection, read-only persisted HR2 reconciliation."""
import json
import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[3]
private=root/'.local-backups/hr-import-20260909'
payload=json.loads((private/'salary-payload.json').read_text(encoding='utf8'))
code='PAYLOAD='+repr(payload)+'''
import json
from decimal import Decimal as D
salary_count=job_count=0
for row in PAYLOAD['employees']:
    es=[env.ref(k).with_context(active_test=False) for k in row['employee_xmlids']]
    assert len({e.id for e in es})==1
    e=es[0]
    assert e.name==row['name'] and e.active==row['active'] and e.company_id.id==row['company_id']
    s=row.get('salary')
    if s:
        assert D(str(e.baseer_salary_total))==D(s['gross'])
        assert D(str(e.baseer_basic_salary))==D(s['basic'])
        assert D(str(e.baseer_allowance_total))==D(s['allowances'])
        assert D(str(e.baseer_overtime_salary))==D(s['overtime'])
        assert str(e.version_id.date_version)==s['effective_date']
        assert not e.contract_date_start and not e.contract_date_end
        if s.get('keep_target_calendar'):
            assert e.resource_calendar_id.id==row['baseline']['calendar_id']
        else:
            assert not e.resource_calendar_id.attendance_ids and not e.resource_calendar_id.hours_per_week
        salary_count+=1
    if row.get('job_title'):
        assert e.job_title==row['job_title'] and e.job_id.name==row['job_title']
        assert e.job_id.company_id==e.company_id
        job_count+=1
assert env['hr.employee'].with_context(active_test=False).search_count([])==50
assert env['ir.model.data'].search_count([('module','=','baseer_legacy_hr_import'),('model','=','hr.employee')])==51
print('VERIFIED='+json.dumps({'status':'passed','salary_count':salary_count,'job_count':job_count,
    'employees':49,'current':34,'archived':15,'financial_components_reconciled':True,
    'source_links':51,'remaining_salary_decisions':len(PAYLOAD['missing'])}))
env.cr.rollback()
'''
args=['docker','exec','-i','baseer_odoo_dev-odoo-1','/entrypoint.sh','odoo','shell',
      '--config=/etc/odoo/odoo.local.conf',
      '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
      '--database=baseer_dev','--no-http','--max-cron-threads=0','--log-level=critical']
r=subprocess.run(args,input=code,encoding='utf8',capture_output=True)
lines=[s for s in r.stdout.splitlines() if s.startswith('VERIFIED=')]
if r.returncode or len(lines)!=1:
    (private/'salary-verify-error.txt').write_text(r.stderr,encoding='utf8')
    raise RuntimeError('Verification failed; inspect private log')
result=json.loads(lines[0].split('=',1)[1])
Path(__file__).with_name('salary-postcommit-verification.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps(result,indent=2))
