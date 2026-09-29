"""Independent native EOS/leave journeys, disposable audit clone and rollback only."""
import json, traceback
from pathlib import Path
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import patch
from odoo.exceptions import UserError, ValidationError, AccessError
assert env.cr.dbname=='baseer_audit_payroll_20260909'
R={'checks':[],'observations':[]}
def q(x): return Decimal(str(x)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
def check(n,e,a): R['checks'].append({'name':n,'expected':str(e),'actual':str(a),'pass':e==a})
def blocked(n,fn):
    try:
        with env.cr.savepoint():fn()
    except (UserError,ValidationError,AccessError) as ex:
        R['observations'].append({'name':n,'blocked':True,'message':str(ex)})
    else:R['observations'].append({'name':n,'blocked':False})
try:
  with patch.object(type(env['mail.mail']),'send',lambda *a,**k:False),patch.object(type(env['mail.template']),'send_mail',lambda *a,**k:False):
    E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'tracking_disable':True,
        'mail_create_nosubscribe':True,'mail_notify_force_send':False,'lang':'en_US'},su=False)
    C=E.company
    E['hr.employee'].search([('company_id','=',10),('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    C.baseer_proration='calendar'
    bank=E['account.journal'].search([('company_id','=',10),('type','=','bank')],limit=1)
    cash=E['account.journal'].search([('company_id','=',10),('type','=','cash')],limit=1)
    for j in bank|cash:
        j.default_account_id.reconcile=False
        j.outbound_payment_method_line_ids.write({'payment_account_id':j.default_account_id.id})
    def employee(name,start,wage=3000):
        emp=E['hr.employee'].create({'name':'INDEPENDENT '+name,'company_id':10})
        emp.version_id.write({'date_version':start,'contract_date_start':start,'wage':wage,
            'baseer_salary_mode':'fixed','baseer_allowance_total':400})
        if not emp.work_contact_id:emp.work_contact_id=E['res.partner'].create({'name':emp.name,'company_id':10})
        emp.work_contact_id.with_company(C).property_account_payable_id=C.baseer_salary_payable_id
        return emp
    eos=employee('EOS exact year','2023-01-01')
    request=E['baseer.hr.eos'].create({'employee_id':eos.id,'service_start':'2023-01-01','service_end':'2024-01-01','reason':'termination'})
    request.action_calculate()
    check('one exact year award',q(1500),q(request.award_amount))
    check('estimate no bill',False,bool(request.bill_id))
    departure=E['hr.departure.wizard'].with_context(employee_termination=True).create({'employee_ids':[(6,0,eos.ids)],
        'departure_reason_id':E.ref('hr.departure_fired').id,'departure_date':'2024-01-01','set_date_end':True,'remove_related_user':False})
    departure.action_register_departure()
    request.action_calculate()
    request.write({'evidence_reference':'Independent test only','approval_confirmed':True})
    request.action_approve();bill=request.bill_id;request.action_approve()
    check('one EOS bill after approval replay',1,E['account.move'].search_count([('baseer_eos_id','=',request.id)]))
    check('EOS bill expense debit',q(1500),q(sum(bill.line_ids.filtered(lambda l:l.account_id==C.baseer_eos_expense_id).mapped('debit'))))
    check('EOS bill zero VAT',q(0),q(bill.amount_tax))
    check('EOS unpaid receipt is statement',False,request._report_row()['is_final'])
    for journal,amount in [(bank,444.44),(cash,1055.56)]:
        reg=E['account.payment.register'].with_context(active_model='account.move',active_ids=bill.ids).create({
            'journal_id':journal.id,'payment_method_line_id':journal.outbound_payment_method_line_ids[:1].id,
            'payment_date':'2024-01-01','amount':amount,'payment_difference_handling':'open'})
        reg._create_payments()
        check('EOS residual after '+str(amount),q(1055.56 if amount==444.44 else 0),q(bill.amount_residual))
        check('EOS confirmed cash after '+str(amount),q(444.44 if amount==444.44 else 1500),q(request.received_amount))
    row=request._report_row();row2=request._report_row()
    check('EOS final receipt ready',True,row['is_final'])
    check('EOS report reprint exact data',row,row2)
    check('EOS report confirmed total','1,500.00',row['paid'])
    for lang in ['ar_001','en_US']:
        payload,_=E['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf('baseer_payroll.action_report_baseer_end_service',res_ids=request.ids)
        Path('/mnt/qa-evidence/payroll-eos-final-'+lang+'.pdf').write_bytes(payload)
    duplicate=E['baseer.hr.eos'].create({'employee_id':eos.id,'service_start':'2023-01-01','service_end':'2024-01-01','reason':'termination'})
    duplicate.action_calculate();duplicate.write({'evidence_reference':'Duplicate probe','approval_confirmed':True})
    blocked('duplicate award before reversal',duplicate.action_approve)
    reverse=bill._reverse_moves([{'date':date(2024,1,1),'invoice_date':date(2024,1,1),'ref':'Independent reviewed reversal'}],cancel=True)
    check('EOS native posted reversal exists',True,bool(reverse.filtered(lambda r:r.state=='posted')))
    check('EOS receipt final invalid after reversal',False,request._report_row()['is_final'])
    blocked('duplicate award after reversal',duplicate.action_approve)
    # Full-day unpaid leave follows calendar-day proration. Half day must be explicitly
    # tested as a blocked real journey; the prior suite only tested whole days.
    emp=employee('Partial-day unpaid leave','2034-01-01');emp.baseer_payroll_enabled=True
    unpaid=E['hr.leave.type'].create({'name':'INDEPENDENT hourly unpaid','requires_allocation':False,
        'leave_validation_type':'no_validation','baseer_unpaid':True,'request_unit':'half_day'})
    leave=E['hr.leave'].create({'name':'Independent half-day','employee_id':emp.id,'holiday_status_id':unpaid.id,
            'request_date_from':'2034-04-03','request_date_to':'2034-04-03','request_date_from_period':'am','request_date_to_period':'am'})
    if leave.state!='validate':leave.action_validate()
    R['observations'].append({'name':'validated partial leave fixture','state':leave.state,'half':leave.request_unit_half,'hours':leave.request_unit_hours,'days':leave.number_of_days})
    blocked('managed payroll with approved half-day leave',lambda:E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2034-04-01'}))
    R['status']='completed'
except Exception:
    R['status']='execution_error';R['error']=traceback.format_exc()
finally:
    env.cr.rollback();R['rolled_back']=True
    Path('/mnt/qa-evidence/payroll-eos-leave-result.json').write_text(json.dumps(R,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('PAYROLL_EOS_RESULT='+json.dumps(R,ensure_ascii=False,default=str))
