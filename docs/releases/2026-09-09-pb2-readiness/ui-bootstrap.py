"""Prepare isolated Arabic UI review; credentials never belong to release evidence."""
import json,secrets,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import pb2_ops as p
password=secrets.token_urlsafe(28)
(p.BACK/'ui-credentials.json').write_text(json.dumps({'login':'pb2.review.local','password':password}),encoding='utf8')
script="""
import json
from odoo import Command
assert env.cr.dbname=='baseer_pb2_test_20260909'
env['ir.mail_server'].search([]).write({'active':False})
env['ir.cron'].search([]).write({'active':False})
group_ids=[env.ref(x).id for x in ['base.group_system','om_hr_payroll.group_hr_payroll_manager','account.group_account_manager','hr.group_hr_manager']]
user=env['res.users'].with_context(no_reset_password=True,mail_create_nolog=True,mail_create_nosubscribe=True).create({'name':'PB2 Review','login':'pb2.review.local','password':PASSWORD,'company_id':6,'company_ids':[Command.set([6])],'group_ids':[Command.set(group_ids)],'lang':'ar_001','tz':'Asia/Riyadh'})
local=env(user=user.id,context=dict(env.context,allowed_company_ids=[6],lang='ar_001',tracking_disable=True,mail_create_nolog=True))
run=local['hr.payslip.run'].search([('company_id','=',6),('baseer_managed','=',True),('date_start','=','2026-10-01'),('state','=','draft')],order='id desc',limit=1)
assert run
run.action_load_employees()
assert run.slip_ids.filtered(lambda s:s.employee_id.id==3)
env.cr.commit()
print('PB2_UI='+json.dumps({'user_id':user.id,'run_id':run.id,'employee_id':3,'slip_ids':run.slip_ids.ids}))
""".replace('PASSWORD',repr(password))
p.execute('ui-bootstrap',script)
