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

clone = 'baseer_fix_payroll_20260909'
assert clone and 'fix' in clone and env.cr.dbname == clone
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
    a=employee('ABA advance',3000,'2040-01-01')
    loan=E['baseer.hr.loan'].create({'employee_id':a.id,'amount':1000,'installment_count':2,
        'date':'2040-01-01','first_due_date':'2040-01-31','journal_id':bank.id});loan.action_disburse()
    old=E['baseer.payroll.correction'].create({'loan_id':loan.id,'kind':'advance','date':'2040-02-01','reason':'Opened before recovery cycle','reviewed':True})
    repayment=E['baseer.hr.loan.repay'].create({'loan_id':loan.id,'amount':100,'date':'2040-01-02','journal_id':cash.id});repayment.action_confirm()
    reversal=E['baseer.payroll.correction'].create({'loan_id':loan.id,'kind':'repayment','date':'2040-01-03','reason':'Review recovery correction','reviewed':True});reversal.action_confirm()
    check('ABA balance returned to same amount',q(1000),q(loan.balance))
    blocked('ABA history invalidates old wizard',old.action_confirm)
    blocked('fake loan reversal write tokenTrue',lambda:loan.with_context(baseer_payroll_internal=True).write({'reversal_move_id':loan.move_id.id}))
    blocked('fake loan reversal create default tokenTrue',lambda:E['baseer.hr.loan'].with_context(baseer_payroll_internal=True,default_reversal_move_id=loan.move_id.id).create({
        'employee_id':a.id,'amount':100,'date':'2040-01-01','first_due_date':'2040-01-31','journal_id':bank.id}))
    blocked('fake correction snapshot tokenTrue',lambda:E['baseer.payroll.correction'].with_context(baseer_payroll_internal=True).create({
        'loan_id':loan.id,'kind':'advance','date':'2040-02-01','reason':'Injected','source_snapshot':{'move':loan.move_id.id}}))
    blocked('fake native correction source default tokenTrue',lambda:E['account.move'].with_context(baseer_payroll_internal=True,
        default_baseer_correction_source_id=loan.move_id.id).create({'move_type':'entry','journal_id':C.baseer_payroll_journal_id.id,'date':'2040-01-31'}))
    run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2040-01-01'});run.action_approve();slip=run.slip_ids
    blocked('fake original net stored compute',lambda:slip.with_context(baseer_payroll_internal=True).write({'baseer_original_net':1}))
    blocked('fake recovery reversal write tokenTrue',lambda:loan.allocation_ids.with_context(baseer_payroll_internal=True).write({'reversal_move_id':loan.move_id.id}))
    # A loan returned to full principal can be corrected once with a fresh review.
    reverse_payroll=E['baseer.payroll.correction'].create({'slip_id':slip.id,'kind':'payroll_recovery','date':'2040-02-01','reason':'Fresh source evidence','reviewed':True});reverse_payroll.action_confirm()
    fresh=E['baseer.payroll.correction'].create({'loan_id':loan.id,'kind':'advance','date':'2040-02-02','reason':'Fresh source evidence','reviewed':True});fresh.action_confirm()
    check('cancelled schedule outstanding zero',q(0),q(sum(loan.line_ids.mapped('balance'))))
    check('cancelled schedule retained amount',q(1000),q(sum(loan.line_ids.mapped('amount'))))
    check('cancelled schedule states',{'cancel'},set(loan.line_ids.mapped('state')))
    blocked('reversed advance cannot disburse again',loan.action_disburse)
    blocked('reversed source cannot reopen correction',lambda:E['baseer.payroll.correction'].create({'loan_id':loan.id,'kind':'advance','date':'2040-02-02','reason':'Replay','reviewed':True}))
    R['status']='completed'
    assert all(c['pass'] for c in R['checks'])
    assert all(o.get('blocked',True) for o in R['observations'])

except Exception:
    R['status']='execution_error';R['error']=traceback.format_exc()
finally:
    env.cr.rollback()
    R['rolled_back']=True
    Path('/mnt/qa-evidence/payroll-security-result.json').write_text(json.dumps(R,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
    print('PAYROLL_AUDIT_RESULT='+json.dumps(R,ensure_ascii=False,default=str))
