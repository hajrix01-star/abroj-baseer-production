"""Final review regressions against QA preview; transaction is rolled back."""
import json, traceback
from pathlib import Path
from odoo.exceptions import UserError, ValidationError, AccessError
p=json.loads(Path('/mnt/qa-evidence/baseer_payroll_concurrency.json').read_text(encoding='utf-8'))['preview']
E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[p['company']],'tracking_disable':True},su=False)
run=E['hr.payslip.run'].browse(p['march_draft']); slip=run.slip_ids.filtered(lambda s:s.employee_id.id==p['employee_ids'][0])
loan=E['baseer.hr.loan'].browse(p['loan'])
checks=[]
def rejects(name, setup, action):
    try:
        with env.cr.savepoint():
            setup()
            try: action()
            except (UserError,ValidationError,AccessError): raise Expected()
    except Expected: checks.append({'name':name,'passed':True})
    else: raise AssertionError(name)
class Expected(Exception): pass
try:
    rejects('new_midmonth_version_after_draft',lambda:slip.version_id.copy({'date_version':'2026-03-15','wage':3500}),lambda:run.action_approve())
    rejects('changed_period_after_draft',lambda:slip.write({'date_to':'2026-03-20'}),lambda:run.action_approve())
    def lock():
        env['res.company'].browse(p['company']).write({'fiscalyear_lock_date':'2026-03-31'})
    rejects('payroll_locked_date',lock,lambda:run.action_approve())
    def repayment():
        E['baseer.hr.loan.repay'].create({'loan_id':loan.id,'amount':10,'date':'2026-03-15','journal_id':loan.journal_id.id}).action_confirm()
    rejects('repayment_locked_date',lock,repayment)
    def disburse():
        E['baseer.hr.loan'].create({'employee_id':loan.employee_id.id,'amount':100,'date':'2026-03-15','first_due_date':'2026-03-31','journal_id':loan.journal_id.id}).action_disburse()
    rejects('disbursement_locked_date',lock,disburse)
    result={'status':'passed','checks':checks}
except Exception:
    result={'status':'failed','checks':checks,'error':traceback.format_exc()}
finally:
    env.cr.rollback(); result['rolled_back']=True
    Path('/mnt/qa-evidence/baseer_payroll_focused.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
