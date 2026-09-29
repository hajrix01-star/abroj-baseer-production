"""BP-S3 date defaults and employee navigation; all data rolls back."""
import json,traceback
from pathlib import Path
from odoo.exceptions import UserError,ValidationError
from psycopg2 import IntegrityError
R={'checks':[]}
def check(name,condition):
    R['checks'].append({'name':name,'passed':bool(condition)})
    assert condition,name
def blocked(name,fn):
    try:
        with env.cr.savepoint(): fn();env.flush_all()
    except (ValueError,ValidationError,UserError,IntegrityError):check(name,True)
    else:check(name,False)
try:
    assert env.cr.dbname=='baseer_reports_qa_20260907'
    E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'tracking_disable':True},su=False)
    E['hr.employee'].search([('company_id','=',10),('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    fixture=E['hr.employee'].create({'name':'BP-S3 date fixture','company_id':10,'baseer_payroll_enabled':True})
    fixture.version_id.write({'date_version':'2027-01-01','contract_date_start':'2027-01-01','wage':1000})
    if not fixture.work_contact_id:
        fixture.work_contact_id=E['res.partner'].create({'name':fixture.name,'company_id':10})
    for month,last in [('2027-02-01','2027-02-28'),('2028-02-01','2028-02-29'),('2027-04-01','2027-04-30'),('2027-12-01','2027-12-31')]:
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':month})
        run.action_approve()
        action=run.action_pay();w=E[action['res_model']].browse(action['res_id'])
        check('month_end_'+month,str(w.payment_date)==last)
        actual='2028-01-04' if month=='2027-12-01' else last
        w.payment_date=actual
        check('editable_date_'+month,str(w.payment_date)==actual and str(run.baseer_month)==month)
    run=E['hr.payslip.run'].browse(48)
    w=E['baseer.payroll.settlement'].create({'run_id':run.id,'payment_date':'2026-02-04'})
    check('explicit_date_preserved',str(w.payment_date)=='2026-02-04')
    w=E['baseer.payroll.settlement'].with_context(default_payment_date='2026-02-05').create({'run_id':run.id})
    check('context_date_preserved',str(w.payment_date)=='2026-02-05')
    w=E['baseer.payroll.settlement'].with_context(default_payment_date='2026-02-05').create({'run_id':run.id,'payment_date':'2026-02-04'})
    check('explicit_beats_context',str(w.payment_date)=='2026-02-04')
    blocked('explicit_empty_date_not_replaced',lambda:E['baseer.payroll.settlement'].create({'run_id':48,'payment_date':False}))
    blocked('invalid_month',lambda:E['baseer.payroll.create'].create({'baseer_month':'2026-13-01'}))
    blocked('empty_required_month',lambda:E['baseer.payroll.create'].create({'baseer_month':False}))
    # Actual later payment uses its own date; accrual remains the salary month.
    w.write({'journal_id':132,'payment_method_line_id':110});w.line_ids.write({'amount':1})
    w.action_confirm()
    check('later_month_payment_date',all(str(p.date)=='2026-02-04' and str(p.move_id.date)=='2026-02-04' for p in w.payment_ids))
    check('salary_period_unchanged',str(run.baseer_month)=='2026-01-01' and all(str(s.move_id.date)=='2026-01-31' for s in run.slip_ids))
    emp=E['hr.employee'].browse(31);action=emp.action_view_loans()
    loans=E[action['res_model']].search(action['domain'])
    check('loan_history_employee_scope',bool(loans) and all(l.employee_id==emp and l.company_id.id==10 for l in loans))
    check('repaid_history_visible',13 in loans.ids)
    R['status']='passed'
except Exception:
    R['status']='failed';R['error']=traceback.format_exc()
finally:
    env.cr.rollback();R['rolled_back']=True
    Path('/mnt/qa-evidence/baseer_payroll_month_checks.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(R,ensure_ascii=False,indent=2))
