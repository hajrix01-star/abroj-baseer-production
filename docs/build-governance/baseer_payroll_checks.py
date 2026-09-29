"""Six-month synthetic payroll acceptance. Everything rolls back; no external mail."""
import json, traceback, calendar, time
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.baseer_payroll.models.common import money, INTERNAL
R={'checks':[],'months':[]}
def check(name, condition, detail=None):
    R['checks'].append({'name':name,'passed':bool(condition),'detail':detail})
    assert condition, name+': '+str(detail)
def blocked(name, fn):
    try:
        with env.cr.savepoint(): fn()
    except (AccessError,UserError,ValidationError): check(name,True)
    else: check(name,False)
try:
  with patch.object(type(env['mail.mail']),'send',lambda *a,**k:False),patch.object(type(env['mail.template']),'send_mail',lambda *a,**k:False):
    C=env['res.company'].search([('currency_id.name','=','SAR')],limit=1)
    E=env(context=dict(env.context,allowed_company_ids=C.ids,tracking_disable=True,mail_create_nolog=True))
    E.user.write({'group_ids':[(4,E.ref('account.group_account_user').id),(4,E.ref('om_hr_payroll.group_hr_payroll_manager').id)]})
    def account(code,name,kind,reconcile=False):
        return E['account.account'].create({'code':code,'name':'BP QA '+name,'account_type':kind,'reconcile':reconcile,'company_ids':[(6,0,C.ids)]})
    expense=account('997801','salary expense','expense')
    payable=account('997802','salary payable','liability_payable',True)
    recovery=account('997803','deduction recovery','expense')
    receivable=account('997804','advance receivable','asset_receivable',True)
    treasury=account('997805','bank','asset_cash',True)
    cashaccount=account('997806','cash','asset_cash',True)
    general=E['account.journal'].create({'name':'BP QA Payroll','code':'BPQA','type':'general','company_id':C.id})
    bank=E['account.journal'].create({'name':'BP QA Bank','code':'BPQB','type':'bank','company_id':C.id,'default_account_id':treasury.id})
    cash=E['account.journal'].create({'name':'BP QA Cash','code':'BPQC','type':'cash','company_id':C.id,'default_account_id':cashaccount.id})
    # Native payment registers use these configured outstanding accounts.
    for j in bank|cash:
        j.outbound_payment_method_line_ids.write({'payment_account_id':j.default_account_id.id})
        j.inbound_payment_method_line_ids.write({'payment_account_id':j.default_account_id.id})
    C.with_env(E).write({'baseer_salary_expense_id':expense.id,'baseer_salary_payable_id':payable.id,'baseer_deduction_account_id':recovery.id,'baseer_loan_account_id':receivable.id,'baseer_payroll_journal_id':general.id,'baseer_structure_id':False})
    C.with_env(E)._baseer_structure()
    manager=E['res.users'].create({'name':'BP QA Payroll Manager','login':'bp-qa-manager@example.invalid','company_id':C.id,'company_ids':[(6,0,C.ids)],'group_ids':[(6,0,[E.ref(g).id for g in ['base.group_user','om_hr_payroll.group_hr_payroll_manager','hr.group_hr_manager','account.group_account_user']])]})
    E=env(user=manager.id,context=dict(env.context,allowed_company_ids=C.ids,tracking_disable=True,mail_create_nolog=True),su=False)
    def employee(name,wage,start='2026-01-01'):
        emp=E['hr.employee'].create({'name':'BP QA '+name,'company_id':C.id,'baseer_payroll_enabled':True})
        emp.version_id.write({'date_version':start,'contract_date_start':start,'wage':wage})
        if not emp.work_contact_id:
            emp.work_contact_id=E['res.partner'].create({'name':emp.name,'company_id':C.id})
        return emp
    a=employee('Employee A',3000)
    b=employee('Employee B',2000)
    b.version_id.write({'baseer_salary_mode':'inclusive','baseer_daily_hours':12,'baseer_work_days':30,'baseer_allowance_total':200})
    parts=b.version_id._baseer_split()
    check('salary_split_conserves_inclusive_total',sum(parts)==Decimal('2000.00'),list(map(str,parts)))
    def loan(emp,amount,count,first='2026-01-31'):
        rec=E['baseer.hr.loan'].create({'employee_id':emp.id,'amount':amount,'installment_count':count,'date':'2026-01-01','first_due_date':first,'journal_id':bank.id})
        rec.action_disburse()
        initial=rec.move_id
        rec.action_disburse()
        check('loan_disbursement_replay',rec.move_id==initial)
        return rec
    la=loan(a,1200,6)
    lb=loan(b,600,3)
    check('initial_employee_balances',money(a.baseer_loan_balance)==1200 and money(b.baseer_loan_balance)==600)
    def pay(slip,amount,journal,date):
        act=slip.action_pay()
        wizard=E['account.payment.register'].with_context(**act['context']).create({'journal_id':journal.id,'payment_date':date,'amount':amount})
        payments=wizard._create_payments()
        again=wizard._create_payments()
        check('salary_payment_wizard_replay',payments==again)
        return payments
    expected=[(200,200,50,1000,400),(0,150,0,850,200),(250,0,100,600,200),(200,200,0,400,0),(200,0,25,200,0),(200,0,0,0,0)]
    allslips=E['hr.payslip']
    for month in range(1,7):
        start=f'2026-{month:02d}-01'; end=f'2026-{month:02d}-{calendar.monthrange(2026,month)[1]}'
        if month==2:
            # A cash repayment clears January/future remainder before deferring February.
            rep=E['baseer.hr.loan.repay'].create({'loan_id':la.id,'amount':150,'date':'2026-02-05','journal_id':cash.id})
            rep.action_confirm(); original=rep.move_id; rep.action_confirm()
            check('partial_repayment_replay',rep.move_id==original)
            repb=E['baseer.hr.loan.repay'].create({'loan_id':lb.id,'amount':50,'date':'2026-02-05','journal_id':cash.id}); repb.action_confirm()
        wiz=E['baseer.payroll.create'].create({'baseer_month':start})
        act=wiz.action_create(); run=E['hr.payslip.run'].browse(act['res_id'])
        sa=run.slip_ids.filtered(lambda s:s.employee_id==a); sb=run.slip_ids.filtered(lambda s:s.employee_id==b)
        check(f'm{month}_auto_employees',len(run.slip_ids)==2)
        if month==2: sa.write({'baseer_defer_loan':True})
        if month==3: sb.write({'baseer_defer_loan':True})
        deduction=expected[month-1][2]
        if deduction: sa.write({'baseer_deduction':deduction,'baseer_deduction_reason':'QA approved deduction'})
        run.action_approve()
        check(f'm{month}_balanced',all(m.state=='posted' and money(sum(m.line_ids.mapped('balance')))==0 for m in run.slip_ids.move_id))
        moves=run.slip_ids.move_id; allocations=(la|lb).allocation_ids
        run.action_approve(); run.slip_ids.action_payslip_done()
        check(f'm{month}_approval_replay',moves==run.slip_ids.move_id and allocations==(la|lb).allocation_ids)
        # Record native partial bank and remaining cash salary settlements.
        pay(sa,1000,bank,end)
        check(f'm{month}_partial_salary',money(sa.baseer_paid)==1000)
        pay(sa,float(money(sa.baseer_residual)),cash,end)
        pay(sb,float(money(sb.baseer_net)),bank,end)
        check(f'm{month}_salary_fully_paid',money(run.baseer_residual)==0 and money(run.baseer_paid)==money(run.baseer_net))
        row={'month':month,'a_loan':sa.baseer_loan_amount,'b_loan':sb.baseer_loan_amount,'deduction':sa.baseer_deduction,'a_balance':la.balance,'b_balance':lb.balance,'net':run.baseer_net}
        R['months'].append(row)
        actual=tuple(money(row[k]) for k in ['a_loan','b_loan','deduction','a_balance','b_balance'])
        check(f'm{month}_exact_expected',actual==tuple(map(money,expected[month-1])),row)
        allslips |= run.slip_ids
    check('loans_fully_recovered',la.state=='closed' and lb.state=='closed')
    check('immutable_deferral_history',len(la.defer_ids)==1 and len(lb.defer_ids)==1)
    check('all_recoveries_equal_principal',money(sum((la|lb).allocation_ids.mapped('amount')))==1800)
    blocked('posted_slip_edit',lambda:allslips[:1].write({'date_to':'2026-01-20'}))
    blocked('posted_slip_delete',lambda:allslips[:1].unlink())
    blocked('posted_slip_cancel',lambda:allslips[:1].action_payslip_cancel())
    blocked('posted_line_edit',lambda:allslips[:1].line_ids[:1].write({'amount':1}))
    blocked('loan_history_edit',lambda:la.allocation_ids[:1].write({'amount':1}))
    blocked('loan_reverse',lambda:la.move_id._reverse_moves())
    blocked('salary_reverse',lambda:allslips[:1].move_id._reverse_moves())
    blocked('double_month',lambda:E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2026-01-01'}))
    blocked('salary_unreconcile',lambda:allslips[:1].move_id.line_ids.remove_move_reconcile())
    blocked('loan_unreconcile',lambda:la.move_id.line_ids.remove_move_reconcile())
    blocked('forged_loan_balance',lambda:la.write({'balance':99}))
    blocked('negative_deduction',lambda:allslips[:1].write({'baseer_deduction':-1}))
    blocked('loan_overpayment',lambda:E['baseer.hr.loan.repay'].create({'loan_id':la.id,'amount':1,'journal_id':cash.id}).action_confirm())
    other=env['res.company'].search([('id','!=',C.id)],limit=1)
    foreign=env['res.users'].create({'name':'BP QA foreign manager','login':'bp-qa-foreign@example.invalid','company_id':other.id,'company_ids':[(6,0,other.ids)],'group_ids':[(6,0,[env.ref('base.group_user').id,env.ref('om_hr_payroll.group_hr_payroll_manager').id])]})
    for model,record in [('hr.payslip',allslips[:1]),('hr.payslip.run',run),('baseer.hr.loan',la),('baseer.hr.loan.allocation',la.allocation_ids[:1])]:
        scoped=record.with_user(foreign).with_context(allowed_company_ids=other.ids)
        check('company_isolation_'+model,not scoped.search([('id','=',record.id)]))
    plain=env['res.users'].create({'name':'BP QA basic employee','login':'bp-qa-staff@example.invalid','company_id':C.id,'company_ids':[(6,0,C.ids)],'group_ids':[(6,0,[env.ref('base.group_user').id])]})
    blocked('staff_cannot_read_loans',lambda:la.with_user(plain).read(['amount']))
    blocked('staff_cannot_read_salary',lambda:a.with_user(plain).read(['baseer_salary_total']))
    blocked('staff_cannot_approve',lambda:run.with_user(plain).action_approve())
    # Calendar-day proration: start on June 16 gives exactly fifteen of thirty days.
    late=employee('Late joiner',3000,'2026-06-16')
    blocked('fractional_cent_input',lambda:E['baseer.hr.loan'].create({'employee_id':late.id,'amount':1.001,'journal_id':cash.id}))
    july=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2026-07-01'})
    late_slip=july.slip_ids.filtered(lambda s:s.employee_id==late)
    # Contract ends July 15: fifteen of thirty-one calendar days.
    late.version_id.write({'contract_date_end':'2026-07-15'})
    late_slip.compute_sheet()
    check('partial_contract_15_days',late_slip.baseer_days==15 and money(late_slip.baseer_gross)==Decimal('1451.61'))
    # Protected inputs cannot bypass snapshot values through child model APIs.
    blocked('managed_input_create',lambda:E['hr.payslip.input'].create({'payslip_id':late_slip.id,'name':'forged','code':'X','amount':999,'version_id':late.version_id.id}))
    july.unlink()
    check('draft_run_delete',not july.exists())
    blocked('context_forged_slip',lambda:E['hr.payslip'].with_context(default_baseer_managed=True).create({'employee_id':a.id,'company_id':C.id,'version_id':a.version_id.id,'struct_id':C.baseer_structure_id.id,'journal_id':general.id}))
    blocked('context_forged_loan',lambda:E['baseer.hr.loan'].with_context(default_balance=77).create({'employee_id':a.id,'amount':100,'journal_id':bank.id}))
    blocked('context_forged_payroll_line',lambda:E['hr.payslip.line'].with_context(default_slip_id=allslips[0].id).create({'name':'forged'}))
    blocked('context_forged_payroll_input',lambda:E['hr.payslip.input'].with_context(default_payslip_id=allslips[0].id).create({'name':'forged'}))
    blocked('context_forged_salary_ledger_line',lambda:E['account.move.line'].with_context(default_move_id=allslips[0].move_id.id).create({'name':'forged'}))
    blocked('context_forged_loan_ledger_line',lambda:E['account.move.line'].with_context(default_move_id=la.move_id.id).create({'name':'forged'}))
    native=E['hr.payslip'].create({'name':'QA unprotected draft','employee_id':a.id,'company_id':C.id,'version_id':a.version_id.id,'struct_id':C.baseer_structure_id.id,'journal_id':general.id,'date_from':'2026-08-01','date_to':'2026-08-31'})
    line_vals=allslips[0].line_ids[0].copy_data()[0]
    line_vals.pop('parent_rule_id',None)
    line_vals.update(slip_id=native.id,employee_id=a.id,version_id=a.version_id.id)
    native_line=E['hr.payslip.line'].create(line_vals)
    blocked('payroll_line_reparent',lambda:native_line.write({'slip_id':allslips[0].id}))
    native.unlink()
    for rec in [C.with_env(E).baseer_structure_id,C.with_env(E).baseer_structure_id.rule_ids[0],C.with_env(E).baseer_structure_id.rule_ids[0].category_id]:
        blocked('foreign_config_write_'+rec._name,lambda rec=rec:rec.with_user(foreign).with_context(allowed_company_ids=other.ids).write({'name':'forged'}))
    def changed_mapping():
        env['res.company'].browse(C.id).write({'baseer_salary_expense_id':recovery.id})
        C.with_env(E)._baseer_structure()
    blocked('changed_account_mapping',changed_mapping)
    # Protected reconciliation defaults cannot bypass the workflow.
    partial=E['account.partial.reconcile'].search([('debit_move_id.move_id','=',la.move_id.id)],limit=1)
    blocked('default_loan_reconciliation',lambda:E['account.partial.reconcile'].with_context(default_debit_move_id=partial.debit_move_id.id,default_credit_move_id=partial.credit_move_id.id).create({'amount':1,'debit_amount_currency':1,'credit_amount_currency':1}))
    salary_partial=E['account.partial.reconcile'].search([('credit_move_id.move_id','=',allslips[0].move_id.id)],limit=1)
    blocked('default_salary_reconciliation',lambda:E['account.partial.reconcile'].with_context(default_debit_move_id=salary_partial.debit_move_id.id,default_credit_move_id=salary_partial.credit_move_id.id).create({'amount':99999,'debit_amount_currency':99999,'credit_amount_currency':99999}))
    # No unpaid leave is deducted unless it is explicitly flagged and approved.
    returned=employee('Returned from unpaid leave',3000)
    absent=employee('Full month unpaid leave',3000)
    env['res.users'].browse(manager.id).write({'group_ids':[(4,env.ref('hr_holidays.group_hr_holidays_manager').id)]})
    unpaid=E['hr.leave.type'].create({'name':'BP QA unpaid','requires_allocation':False,'leave_validation_type':'no_validation','baseer_unpaid':True})
    for emp,until in [(returned,'2026-09-15'),(absent,'2026-09-30')]:
        leave=E['hr.leave'].create({'name':'BP QA leave','employee_id':emp.id,'holiday_status_id':unpaid.id,'request_date_from':'2026-09-01','request_date_to':until})
        if leave.state!='validate': leave.action_validate()
    september=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2026-09-01'})
    rs=september.slip_ids.filtered(lambda s:s.employee_id==returned)
    check('unpaid_leave_return_15_days',rs.baseer_days==15 and money(rs.baseer_gross)==1500)
    check('full_month_unpaid_employee_excluded',not september.slip_ids.filtered(lambda s:s.employee_id==absent))
    # Fixed salary rounding keeps overtime zero at a fractional-month boundary.
    returned.version_id.write({'wage':1,'baseer_allowance_total':.5})
    rs.compute_sheet()
    check('fixed_salary_rounding_no_overtime',rs.baseer_overtime==0 and money(rs.baseer_basic+rs.baseer_allowance)==money(rs.baseer_gross))
    september.unlink()
    E['hr.employee'].search([('company_id','=',C.id),('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    for i in range(100): employee('Capacity '+str(i),3000)
    started=time.monotonic()
    capacity=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2026-12-01'})
    seconds=round(time.monotonic()-started,3)
    check('capacity_100_employee_calculation',len(capacity.slip_ids)==100 and money(capacity.baseer_gross)==300000,{'seconds':seconds,'target_seconds':30})
    R['capacity_seconds']=seconds
    for lang in ['ar_001','en_US']:
        data,_=E['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf('baseer_payroll.action_report_baseer_payslips',res_ids=allslips[:2].ids)
        check('bulk_signature_pdf_'+lang,data.startswith(b'%PDF'))
        Path('/mnt/qa-evidence/baseer_payroll_'+lang+'.pdf').write_bytes(data)
    R['status']='passed'
except Exception:
    R['status']='failed'; R['error']=traceback.format_exc()
finally:
    env.cr.rollback(); R['rolled_back']=True
    Path('/mnt/qa-evidence/baseer_payroll_checks.json').write_text(json.dumps(R,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(R,ensure_ascii=False,indent=2,default=str))
