"""Independent accounting audit; only disposable audit clone, always rollback.
Execute from Odoo shell, with AUDIT_CLONE_DB environment variable naming exact clone.
No commits, no real employee fixtures, no external messaging.
"""
import os, json, traceback, calendar
from pathlib import Path
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import patch
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.addons.baseer_payroll.models.end_service import eos_formula

clone = 'baseer_audit_payroll_20260909'
assert clone and 'audit' in clone and env.cr.dbname == clone
R = {'database': env.cr.dbname, 'checks': [], 'months': [], 'observations': []}
def q(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
def check(name, expected, actual):
    R['checks'].append({'name': name, 'expected': str(expected), 'actual': str(actual), 'pass': expected == actual})
def observe(name, fn):
    try:
        with env.cr.savepoint():
            fn()
    except Exception:
        R['observations'].append({'name':name,'error':traceback.format_exc()})
def blocked(name, fn):
    try:
        with env.cr.savepoint(): fn()
    except (UserError, ValidationError, AccessError) as error:
        R['observations'].append({'name':name,'blocked':True,'message':str(error)})
    else:
        R['observations'].append({'name':name,'blocked':False})

try:
  with patch.object(type(env['mail.mail']), 'send', lambda *a, **k: False), patch.object(type(env['mail.template']), 'send_mail', lambda *a, **k: False):
    C = env['res.company'].browse(10).exists()
    assert C and C.currency_id.name == 'SAR'
    E = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids':[C.id], 'tracking_disable':True,
        'mail_create_nolog':True, 'mail_create_nosubscribe':True, 'mail_notify_force_send':False, 'lang':'en_US'}, su=False)
    C = E.company
    E['hr.employee'].search([('company_id','=',C.id),('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    C.baseer_proration = 'calendar'
    bank = E['account.journal'].search([('company_id','=',C.id),('type','=','bank')], limit=1)
    cash = E['account.journal'].search([('company_id','=',C.id),('type','=','cash')], limit=1)
    assert bank and cash
    for j in bank | cash:
        j.default_account_id.reconcile = False
        j.outbound_payment_method_line_ids.write({'payment_account_id':j.default_account_id.id})
    def employee(label, wage=3100, start='2028-01-01'):
        emp = E['hr.employee'].create({'name':'INDEPENDENT AUDIT '+label, 'company_id':C.id})
        emp.version_id.write({'date_version':start, 'contract_date_start':start, 'wage':wage,
            'baseer_salary_mode':'fixed', 'baseer_allowance_total':300})
        if not emp.work_contact_id:
            emp.work_contact_id = E['res.partner'].create({'name':emp.name,'company_id':C.id})
        emp.work_contact_id.with_company(C).property_account_payable_id = C.baseer_salary_payable_id
        emp.baseer_payroll_enabled = True
        return emp
    a = employee('Six months')
    loan = E['baseer.hr.loan'].create({'employee_id':a.id,'amount':1199.99,'installment_count':6,
        'date':'2028-01-01','first_due_date':'2028-01-31','journal_id':bank.id})
    loan.action_disburse()
    check('principal installments total',q('1199.99'),q(sum(loan.line_ids.mapped('amount'))))
    check('final installment absorbs cents',q('199.99'),q(loan.line_ids.sorted('sequence')[-1].amount))
    # Independent schedule: 200, 200, 200, 200, 200, 199.99. Feb direct150.01,
    # Feb remaining49.99 deferred; March49.99+200; Apr/May200; Jun199.99.
    expected_loan = [('200','999.99'),('0','849.98'),('249.99','599.99'),('200','399.99'),('200','199.99'),('199.99','0')]
    for month in range(1,7):
        start = date(2028,month,1)
        end = date(2028,month,calendar.monthrange(2028,month)[1])
        if month == 2:
            repay = E['baseer.hr.loan.repay'].create({'loan_id':loan.id,'amount':150.01,'date':start,'journal_id':cash.id})
            repay.action_confirm(); old = repay.move_id; repay.action_confirm()
            check('direct repay replay same move',old.id,repay.move_id.id)
        run = E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':start})
        slip = run.slip_ids.filtered(lambda s:s.employee_id == a)
        assert len(slip)==1
        deduction = q(str(month*7)+'.13')
        slip.write({'baseer_deduction':float(deduction),'baseer_deduction_reason':'Independent known deduction','baseer_defer_loan':month==2})
        run.action_approve()
        expected_net = q('3100') - q(expected_loan[month-1][0]) - deduction
        check(f'{month} loan deduction',q(expected_loan[month-1][0]),q(slip.baseer_loan_amount))
        check(f'{month} loan ledger residual',q(expected_loan[month-1][1]),q(loan.balance))
        check(f'{month} gross',q('3100'),q(slip.baseer_gross))
        check(f'{month} net',expected_net,q(slip.baseer_net))
        balances = {}
        for line in slip.move_id.line_ids:
            balances[line.account_id.id] = balances.get(line.account_id.id,Decimal(0)) + q(line.balance)
        check(f'{month} salary expense',q('3100'),balances[C.baseer_salary_expense_id.id])
        check(f'{month} salary liability',-expected_net,balances[C.baseer_salary_payable_id.id])
        check(f'{month} deduction recovery',-deduction,balances[C.baseer_deduction_account_id.id])
        check(f'{month} loan recovery credit',-q(expected_loan[month-1][0]),balances.get(C.baseer_loan_account_id.id,Decimal(0)))
        for journal, amount in [(bank,q('731.27')),(cash,expected_net-q('731.27'))]:
            w=E['baseer.payroll.settlement'].create({'run_id':run.id,'journal_id':journal.id,
                'payment_method_line_id':journal.outbound_payment_method_line_ids[:1].id,'payment_date':end})
            w.line_ids.amount=float(amount)
            w.action_confirm(); ids=w.payment_ids.ids; w.action_confirm()
            check(f'{month} {journal.type} payment replay',ids,w.payment_ids.ids)
        check(f'{month} paid',expected_net,q(slip.baseer_paid))
        check(f'{month} salary residual',q(0),q(slip.baseer_residual))
        check(f'{month} receipt allocation',expected_net,q(run._baseer_payment_total()))
        R['months'].append({'month':str(start),'gross':slip.baseer_gross,'loan':slip.baseer_loan_amount,
            'deduction':slip.baseer_deduction,'net':slip.baseer_net,'paid':slip.baseer_paid,
            'residual':slip.baseer_residual,'loan_balance':loan.balance,'journal_balances':{str(k):str(v) for k,v in balances.items()}})
    check('six employee financial records',6,len(a.baseer_financial_slip_ids))
    check('loan allocations conserve principal',q('1199.99'),q(sum(loan.allocation_ids.mapped('amount'))))
    check('loan closed','closed',loan.state)
    check('one deferral',1,len(loan.defer_ids))
    for lang in ['ar_001','en_US']:
        payload,_=E['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf('baseer_payroll.action_report_baseer_payslips',res_ids=a.baseer_financial_slip_ids.ids)
        Path('/mnt/qa-evidence/payroll-six-months-'+lang+'.pdf').write_bytes(payload)
    a.baseer_payroll_enabled = False

    def fixed30_probe():
        b=employee('Fixed30',3000,'2030-01-01'); C.baseer_proration='fixed30'
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2030-02-01'})
        check('full February monthly wage expected full',q(3000),q(run.slip_ids.baseer_gross))
        unpaid=E['hr.leave.type'].create({'name':'INDEPENDENT unpaid','requires_allocation':False,'leave_validation_type':'no_validation','baseer_unpaid':True})
        leave=E['hr.leave'].create({'name':'one whole day','employee_id':b.id,'holiday_status_id':unpaid.id,
            'request_date_from':'2030-03-04','request_date_to':'2030-03-04'})
        if leave.state!='validate': leave.action_validate()
        march=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2030-03-01'})
        check('one unpaid day in March fixed30',q(2900),q(march.slip_ids.baseer_gross))
        b.baseer_payroll_enabled=False; C.baseer_proration='calendar'
    observe('fixed30 arithmetic',fixed30_probe)

    def noncash_probe():
        b=employee('Non cash settlement',3100,'2031-01-01')
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2031-01-01'});run.action_approve();slip=run.slip_ids
        move=E['account.move'].create({'move_type':'entry','date':'2031-01-31','journal_id':C.baseer_payroll_journal_id.id,
            'line_ids':[(0,0,{'name':'Noncash audit clearance','account_id':C.baseer_salary_payable_id.id,'partner_id':b.work_contact_id.id,'debit':3100}),
                        (0,0,{'name':'Noncash audit credit','account_id':C.baseer_deduction_account_id.id,'credit':3100})]})
        move.action_post()
        (slip.move_id.line_ids | move.line_ids).filtered(lambda l:l.account_id==C.baseer_salary_payable_id).reconcile()
        R['observations'].append({'name':'Noncash journal settlement','paid_label':slip.baseer_paid,'stage':slip.baseer_payment_state,
            'residual':slip.baseer_residual,'actual_payments':slip._baseer_payments().ids,'receipt_total':run._baseer_payment_total()})
        b.baseer_payroll_enabled=False
    observe('noncash clearing',noncash_probe)

    def outstanding_probe():
        b=employee('Outstanding payment',3100,'2032-01-01')
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2032-01-01'});run.action_approve();slip=run.slip_ids
        pending=E['account.account'].create({'code':'999871','name':'Audit outstanding','account_type':'asset_current','reconcile':True,'company_ids':[(6,0,C.ids)]})
        bank.outbound_payment_method_line_ids[:1].payment_account_id=pending
        action=slip.action_pay()
        w=E['account.payment.register'].with_context(**action['context']).create({'journal_id':bank.id,
            'payment_method_line_id':bank.outbound_payment_method_line_ids[:1].id,'payment_date':'2032-01-31','amount':3100})
        payments=w._create_payments()
        R['observations'].append({'name':'Outstanding payment before bank matching','paid_label':slip.baseer_paid,'stage':slip.baseer_payment_state,
            'payment_states':payments.mapped('state'),'matched':payments.mapped('is_matched'),'receipt_total':run._baseer_payment_total()})
        b.baseer_payroll_enabled=False
    observe('outstanding payment',outstanding_probe)

    def wrong_account_probe():
        wrong=E['account.account'].create({'code':'999872','name':'Audit inappropriate prepaid asset','account_type':'asset_current','company_ids':[(6,0,C.ids)]})
        C.write({'baseer_salary_expense_id':wrong.id,'baseer_structure_id':False})
        C._baseer_check_payroll_configuration()
        b=employee('Wrong expense type',3100,'2033-01-01')
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2033-01-01'});run.action_approve()
        R['observations'].append({'name':'Salary expense configured as asset','posted':run.slip_ids.move_id.state,
            'account_type':wrong.account_type,'asset_debit':sum(run.slip_ids.move_id.line_ids.filtered(lambda l:l.account_id==wrong).mapped('debit'))})
    observe('wrong salary account classification',wrong_account_probe)

    for start,end in [('2020-01-01','2025-01-01'),('2020-01-01','2024-12-31'),('2024-01-01','2025-12-31')]:
        days,full,factor,award=eos_formula(start,end,3000,'resignation')
        R['observations'].append({'name':'EOS calendar anniversary vs inherited365','start':start,'end':end,'days':days,'factor':str(factor),'award':str(award)})
    R['status']='completed'
except Exception:
    R['status']='execution_error';R['error']=traceback.format_exc()
finally:
    env.cr.rollback()
    R['rolled_back']=True
    Path('/mnt/qa-evidence/payroll-independent-result.json').write_text(json.dumps(R,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
    print('PAYROLL_AUDIT_RESULT='+json.dumps(R,ensure_ascii=False,default=str))
