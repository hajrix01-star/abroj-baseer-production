"""Read-only target baseline; private data saved locally, never printed."""
import json
import subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[3]
code='''
import json
D=env['ir.model.data'].search([('module','=','baseer_legacy_hr_import'),('model','=','hr.employee')])
E=env['hr.employee'].with_context(active_test=False).browse(sorted(set(D.mapped('res_id'))))
rows={}
for e in E:
    v=e.version_id;c=v.resource_calendar_id
    rows[str(e.id)]={'version_id':v.id,'date_version':str(v.date_version),'version_write_date':str(v.write_date),
        'employee_write_date':str(e.write_date),'job_id':e.job_id.id,'job_title':e.job_title or False,
        'note':e.additional_note or '', 'wage':v.wage,'allowance':v.baseer_allowance_total,
        'calendar_id':c.id,'calendar_write_date':str(c.write_date),'hours':c.hours_per_day,
        'pending':c==env.ref('baseer_legacy_hr_import.pending_schedule_company_'+str(e.company_id.id))}
print('BASELINE='+json.dumps(rows,ensure_ascii=False,default=str))
env.cr.rollback()
'''
args=['docker','exec','-i','baseer_odoo_dev-odoo-1','/entrypoint.sh','odoo','shell',
      '--config=/etc/odoo/odoo.local.conf',
      '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
      '--database=baseer_dev','--no-http','--max-cron-threads=0','--log-level=critical']
r=subprocess.run(args,input=code,encoding='utf8',capture_output=True,check=True)
data=json.loads(next(s.split('=',1)[1] for s in r.stdout.splitlines() if s.startswith('BASELINE=')))
assert len(data)==49
(root/'.local-backups/hr-import-20260909/salary-target-before.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
print('TARGET_BASELINE_SAVED',len(data),'ASSIGNED_SCHEDULES',sum(not r['pending'] for r in data.values()))
