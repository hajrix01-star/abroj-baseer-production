"""BP-S2 six-month settlement, history and boundary checks; all fixtures roll back."""
import calendar,json,traceback
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
from odoo.exceptions import UserError,AccessError,ValidationError
from odoo.addons.baseer_payroll.models.common import money

R={'checks':[],'months':[]}
def check(name, ok):
    R['checks'].append({'name':name,'passed':bool(ok)})
    assert ok,name
def blocked(name, fn):
    try:
        with env.cr.savepoint(): fn()
    except (UserError,AccessError,ValidationError): check(name,True)
    else: check(name,False)

try:
    E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'tracking_disable':True},su=False)
    bank=E['account.journal'].browse(132)
    cash=E['account.journal'].search([('company_id','=',10),('type','=','cash')],limit=1)
    for j in bank|cash:
        j.default_account_id.reconcile=False
        j.outbound_payment_method_line_ids.write({'payment_account_id':j.default_account_id.id})
    E['hr.employee'].search([('company_id','=',10),('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    def employee(name,wage):
        e=E['hr.employee'].create({'name':'BP-S2 '+name,'company_id':10,'baseer_payroll_enabled':True})
        e.version_id.write({'date_version':'2027-01-01','contract_date_start':'2027-01-01','wage':wage})
        if not e.work_contact_id: e.work_contact_id=E['res.partner'].create({'name':e.name,'company_id':10})
        return e
    a=employee('A',3000);b=employee('B',2000)
    la=E['baseer.hr.loan'].create({'employee_id':a.id,'amount':1200,'installment_count':6,'date':'2027-01-01','first_due_date':'2027-01-31','journal_id':bank.id});la.action_disburse()
    expected=[(200,1000),(0,850),(250,600),(200,400),(200,200),(200,0)]
    all_slips=E['hr.payslip']
    for month in range(1,7):
        start=f'2027-{month:02d}-01';end=f'2027-{month:02d}-{calendar.monthrange(2027,month)[1]}'
        if month==2:
            E['baseer.hr.loan.repay'].create({'loan_id':la.id,'amount':150,'date':start,'journal_id':cash.id}).action_confirm()
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':start})
        sa=run.slip_ids.filtered(lambda s:s.employee_id==a)
        deduction=Decimal(25 if month%2 else 50)
        sa.write({'baseer_deduction':float(deduction),'baseer_deduction_reason':'QA monthly deduction','baseer_defer_loan':month==2})
        check('draft_'+str(month),run.baseer_payment_state=='draft')
        run.action_approve()
        check('approved_'+str(month),run.baseer_payment_state=='awaiting')
        check('loan_month_'+str(month),money(sa.baseer_loan_amount)==expected[month-1][0] and money(la.balance)==expected[month-1][1])
        action=run.action_pay();w=E[action['res_model']].browse(action['res_id'])
        check('review_defaults_'+str(month),len(w.line_ids)==2 and money(w.amount_total)==money(run.baseer_net))
        w.write({'journal_id':bank.id,'payment_method_line_id':bank.outbound_payment_method_line_ids[:1].id,'payment_date':end})
        for line in w.line_ids: line.amount=500
        stale=E['baseer.payroll.settlement'].create({'run_id':run.id,'journal_id':bank.id,'payment_method_line_id':bank.outbound_payment_method_line_ids[:1].id,'payment_date':end})
        result=w.action_confirm()
        check('partial_return_'+str(month),result['res_id']==run.id and result['res_model']=='hr.payslip.run' and run.baseer_payment_state=='partial' and money(run.baseer_paid)==1000)
        check('native_paid_'+str(month),len(w.payment_ids)==2 and all(p.state=='paid' for p in w.payment_ids))
        ids=w.payment_ids.ids;w.action_confirm()
        check('replay_'+str(month),set(w.payment_ids.ids)==set(ids) and money(run.baseer_paid)==1000)
        blocked('stale_'+str(month),stale.action_confirm)
        second=E['baseer.payroll.settlement'].create({'run_id':run.id,'journal_id':cash.id,'payment_method_line_id':cash.outbound_payment_method_line_ids[:1].id,'payment_date':end})
        second.action_confirm()
        check('fully_paid_'+str(month),run.baseer_payment_state=='paid' and money(run.baseer_residual)==0 and all(s.baseer_payment_state=='paid' for s in run.slip_ids))
        check('history_no_double_count_'+str(month),len(run._baseer_payment_rows())==4 and money(run._baseer_payment_total())==money(run.baseer_net) and run.baseer_payment_count==4)
        blocked('no_second_full_payment_'+str(month),run.action_pay)
        R['months'].append({'month':month,'gross':run.baseer_gross,'deduction':float(deduction),'loan':sa.baseer_loan_amount,'paid':run.baseer_paid,'remaining':run.baseer_residual,'stage':run.baseer_payment_state})
        all_slips|=run.slip_ids
    check('employee_history_six_months',len(a.baseer_financial_slip_ids)==6 and all(s.employee_id==a for s in a.baseer_financial_slip_ids))
    sample=a.baseer_financial_slip_ids[:1]
    check('employee_history_navigation',sample.action_open_finance()['res_id']==sample.id and sample.action_open_run()['res_id']==sample.payslip_run_id.id)
    run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2027-07-01'});run.action_approve()
    def wizard(): return E['baseer.payroll.settlement'].create({'run_id':run.id,'journal_id':bank.id,'payment_method_line_id':bank.outbound_payment_method_line_ids[:1].id,'payment_date':'2027-07-31'})
    w=wizard();line=w.line_ids[:1]
    blocked('negative_amount',lambda:line.write({'amount':-1}))
    blocked('overprecision',lambda:line.write({'amount':1.001}))
    def overpay(): line.amount=line.remaining+1;w.action_confirm()
    blocked('overpayment',overpay)
    def zero(): w.line_ids.write({'amount':0});w.action_confirm()
    blocked('all_zero',zero)
    blocked('foreign_company',lambda:w.with_context(allowed_company_ids=[6]).action_confirm())
    blocked('forged_results',lambda:E['baseer.payroll.settlement'].with_context(default_payment_ids=[(6,0,[272])]).create({'run_id':run.id}))
    blocked('forged_state',lambda:E['baseer.payroll.settlement'].with_context(default_state='done').create({'run_id':run.id}))
    blocked('manual_child',lambda:E['baseer.payroll.settlement.line'].create({'settlement_id':w.id,'slip_id':line.slip_id.id,'remaining':100,'amount':100}))
    blocked('child_source_write',lambda:line.write({'slip_id':run.slip_ids[-1].id}))
    blocked('parent_replace_rows',lambda:w.write({'line_ids':[(5,0,0)]}))
    other=wizard()
    blocked('foreign_child_update',lambda:w.write({'line_ids':[(1,other.line_ids[:1].id,{'amount':1})]}))
    def unpaidconfig(): bank.outbound_payment_method_line_ids[:1].payment_account_id=False;w.action_confirm()
    blocked('outstanding_configuration',unpaidconfig)
    def reconcilablecash(): bank.default_account_id.reconcile=True;w.action_confirm()
    before_reconcilable=E['account.payment'].search_count([])
    blocked('reconcilable_treasury_configuration',reconcilablecash)
    check('reconcilable_treasury_no_payment',E['account.payment'].search_count([])==before_reconcilable and w.state=='draft')
    def lockeddate(): E.company.fiscalyear_lock_date='2027-07-31';w.action_confirm()
    blocked('locked_date',lockeddate)
    def atomicfailure():
        payments_before=E['account.payment'].search_count([])
        cls=type(E['account.payment.register']);original=cls._create_payments;count=[0]
        def fail_second(reg):
            count[0]+=1
            if count[0]==2: raise ValidationError('QA second employee failure')
            return original(reg)
        blocked('atomic_second_employee_failure',lambda:invoke_patch(cls,fail_second,w))
        check('atomic_no_payment_left',E['account.payment'].search_count([])==payments_before and money(run.baseer_paid)==0)
    def invoke_patch(cls,fn,wiz):
        with patch.object(cls,'_create_payments',fn): wiz.action_confirm()
    atomicfailure()
    # Skip a zero employee; subsequent screen still offers that employee.
    w.line_ids[-1].amount=0;w.action_confirm()
    check('zero_employee_skipped',len(w.payment_ids)==1 and run.baseer_payment_state=='partial')
    blocked('completed_row_edit',lambda:w.line_ids[:1].write({'amount':1}))
    # Native shared payment across two periods must be allocated per source, not duplicated.
    august=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2027-08-01'});august.action_approve()
    remaining_slip=run.slip_ids.filtered(lambda s:s.baseer_residual>0)
    august_slip=august.slip_ids.filtered(lambda s:s.employee_id==remaining_slip.employee_id)
    combined=remaining_slip|august_slip
    act=combined.action_pay()
    reg=E['account.payment.register'].with_context(**act['context']).create({'journal_id':bank.id,'payment_method_line_id':bank.outbound_payment_method_line_ids[:1].id,'payment_date':'2027-08-31','group_payment':True})
    pay=reg._create_payments()
    check('one_native_shared_payment',len(pay)==1)
    check('shared_payment_allocation',money(run._baseer_payment_total())==money(run.baseer_net) and money(august._baseer_payment_total())==money(august_slip.baseer_net))
    zero_run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2027-09-01'})
    for slip in zero_run.slip_ids: slip.write({'baseer_deduction':slip.baseer_gross,'baseer_deduction_reason':'QA zero net'})
    zero_run.action_approve()
    check('zero_net_no_payment',zero_run.baseer_payment_state=='paid' and zero_run.baseer_payment_count==0)
    basic=env['res.users'].create({'name':'BP-S2 basic','login':'bps2-basic@example.invalid','company_id':10,'company_ids':[(6,0,[10])],'group_ids':[(6,0,[env.ref('base.group_user').id])]})
    blocked('basic_employee_financial_access',lambda:a.with_user(basic).read(['baseer_financial_slip_ids']))
    blocked('basic_settlement_access',lambda:w.with_user(basic).read(['payment_ids']))
    R['status']='passed'
except Exception:
    R['status']='failed';R['error']=traceback.format_exc()
finally:
    env.cr.rollback();R['rolled_back']=True
    Path('/mnt/qa-evidence/baseer_payroll_flow_checks.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(R,ensure_ascii=False,indent=2))
