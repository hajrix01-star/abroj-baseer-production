"""Independent 50-person payroll generation and posting; synthetic, rolled back."""
import json,time
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
assert env.cr.dbname=='baseer_fix_core_20260909'
E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'lang':'en_US','tracking_disable':True,'mail_create_nolog':True,'mail_create_nosubscribe':True,'mail_notify_force_send':False},su=False)
try:
 with patch.object(type(E['mail.mail']),'send',lambda *a,**k:False),patch.object(type(E['mail.template']),'send_mail',lambda *a,**k:False):
  C=E.company
  E['hr.employee'].search([('company_id','=',C.id),('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
  C.baseer_proration='calendar'
  employees=E['hr.employee'].create([{'name':'FA2 CAPACITY '+str(i+1),'company_id':C.id} for i in range(50)])
  employees.version_id.write({'date_version':'2031-01-01','contract_date_start':'2031-01-01','wage':2000,'baseer_salary_mode':'fixed','baseer_allowance_total':0})
  for employee in employees:
   if not employee.work_contact_id:employee.work_contact_id=E['res.partner'].create({'name':employee.name,'company_id':C.id})
   employee.work_contact_id.with_company(C).property_account_payable_id=C.baseer_salary_payable_id
  employees.baseer_payroll_enabled=True
  started=time.monotonic()
  run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2031-01-01'})
  generation=time.monotonic()-started
  assert len(run.slip_ids)==50
  assert all(Decimal(str(s.baseer_gross))==Decimal('2000') and Decimal(str(s.baseer_net))==Decimal('2000') for s in run.slip_ids)
  started=time.monotonic();run.action_approve();posting=time.monotonic()-started
  moves=run.slip_ids.move_id
  assert len(moves)==50 and all(m.state=='posted' for m in moves)
  assert all(abs(sum(m.line_ids.mapped('balance')))<0.001 for m in moves)
  expense=sum(Decimal(str(l.balance)) for l in moves.line_ids if l.account_id==C.baseer_salary_expense_id)
  payable=sum(Decimal(str(l.balance)) for l in moves.line_ids if l.account_id==C.baseer_salary_payable_id)
  assert expense==Decimal('100000') and payable==Decimal('-100000')
  result={'status':'passed','employees':50,'generation_seconds':round(generation,3),'generation_target_seconds':15,
   'generation_target_met':generation<=15,'posting_seconds':round(posting,3),'posted_moves':len(moves),'expense':str(expense),'payable':str(payable),'rolled_back':True}
  Path('/mnt/qa-evidence/core-payroll-capacity.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
  print(json.dumps(result))
finally:env.cr.rollback()
