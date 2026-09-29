"""Clearly labelled, synthetic QA preview and real two-transaction replay check."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json, time
from odoo import api
from odoo.service.model import retrying
assert env.cr.dbname=='baseer_reports_qa_20260907'
assert not env['res.company'].search([('name','=','تجربة الرواتب والسلف')])
company=env['res.company'].create({'name':'تجربة الرواتب والسلف','country_id':env.ref('base.sa').id,'currency_id':env.ref('base.SAR').id})
admin=env.ref('base.user_admin')
admin.write({'company_ids':[(4,company.id)],'group_ids':[(4,env.ref('om_hr_payroll.group_hr_payroll_manager').id),(4,env.ref('account.group_account_user').id)]})
E=env(user=admin.id,context={'allowed_company_ids':company.ids,'tracking_disable':True,'mail_create_nolog':True},su=False)
def account(code,name,kind,reconcile=False):
    return E['account.account'].create({'code':code,'name':name,'account_type':kind,'reconcile':reconcile,'company_ids':[(6,0,company.ids)]})
expense=account('910001','رواتب الموظفين','expense')
payable=account('210001','رواتب مستحقة','liability_payable',True)
recovery=account('910002','خصومات الرواتب','expense')
receivable=account('110001','سلف الموظفين','asset_receivable',True)
cashaccount=account('110002','الصندوق التجريبي','asset_cash',True)
bankaccount=account('110003','البنك التجريبي','asset_cash',True)
general=E['account.journal'].create({'name':'الرواتب','code':'PAY','type':'general','company_id':company.id})
cash=E['account.journal'].create({'name':'الكاش التجريبي','code':'CASH','type':'cash','company_id':company.id,'default_account_id':cashaccount.id})
bank=E['account.journal'].create({'name':'البنك التجريبي','code':'BANK','type':'bank','company_id':company.id,'default_account_id':bankaccount.id})
for j in cash|bank:
    (j.outbound_payment_method_line_ids|j.inbound_payment_method_line_ids).write({'payment_account_id':j.default_account_id.id})
company.with_env(E).write({'baseer_salary_expense_id':expense.id,'baseer_salary_payable_id':payable.id,'baseer_deduction_account_id':recovery.id,'baseer_loan_account_id':receivable.id,'baseer_payroll_journal_id':general.id})
company.with_env(E)._baseer_structure()
employees=E['hr.employee']
for name,wage in [('موظف تجريبي — أحمد',3000),('موظف تجريبي — خالد',2000)]:
    emp=E['hr.employee'].create({'name':name,'company_id':company.id,'baseer_payroll_enabled':True})
    emp.version_id.write({'date_version':'2026-01-01','contract_date_start':'2026-01-01','wage':wage})
    employees |= emp
loan=E['baseer.hr.loan'].create({'name':'سلفة تجريبية — ستة أقساط','employee_id':employees[0].id,'amount':1200,'installment_count':6,'date':'2026-01-01','first_due_date':'2026-01-31','journal_id':bank.id})
loan.action_disburse()
run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2026-01-01'})
run.slip_ids.filtered(lambda s:s.employee_id==employees[0]).write({'baseer_deduction':50,'baseer_deduction_reason':'خصم تجريبي'})
env.cr.commit()
barrier=Barrier(2)
def approve(_):
    with env.registry.cursor() as cr:
        isolated=api.Environment(cr,admin.id,{'allowed_company_ids':company.ids,'tracking_disable':True})
        barrier.wait(timeout=15)
        return retrying(lambda:isolated['hr.payslip.run'].browse(run.id).action_approve(),isolated)
started=time.monotonic()
with ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(approve,range(2)))
env.invalidate_all()
assert len(run.slip_ids.move_id)==2
assert E['account.move'].search_count([('baseer_payslip_id','in',run.slip_ids.ids)])==2
assert len(loan.allocation_ids)==1 and loan.balance==1000
evidence={'case':'two_independent_transactions_approve_same_run','results':results,'seconds':round(time.monotonic()-started,3),'payslips':2,'moves':2,'loan_recoveries':1,'passed':True}
# A direct partial recovery followed by a draft February run demonstrates deferral.
repay=E['baseer.hr.loan.repay'].create({'loan_id':loan.id,'amount':150,'date':'2026-02-05','journal_id':cash.id})
repay.action_confirm()
feb=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2026-02-01'})
feb.slip_ids.filtered(lambda s:s.employee_id==employees[0]).write({'baseer_defer_loan':True})
env.cr.commit()
evidence['preview']={'company':company.id,'company_name':company.name,'january':run.id,'february_draft':feb.id,'loan':loan.id,'outstanding':loan.balance,'employee_ids':employees.ids}
Path('/mnt/qa-evidence/baseer_payroll_concurrency.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False,indent=2))
