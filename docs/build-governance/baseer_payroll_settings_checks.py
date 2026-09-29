"""BP-S1 focused regressions; no fixture or financial mutation is committed."""
import json, traceback
from pathlib import Path
from odoo.exceptions import UserError, AccessError, ValidationError

checks=[]
def check(name, ok):
    checks.append({'name':name,'passed':bool(ok)})
    assert ok, name
def reject(name, action, text=None):
    try:
        with env.cr.savepoint():
            action()
    except (UserError,AccessError,ValidationError) as exc:
        check(name, not text or text in str(exc))
    else:
        check(name, False)

try:
    A=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[6], 'lang':'en_US','tracking_disable':True},su=False)
    B=A(context=dict(A.context,allowed_company_ids=[10]))
    before=A['hr.payslip.run'].search_count([])
    reject('missing_configuration_direct',lambda:A['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2027-01-01'}),'QA ARZ')
    reject('missing_configuration_context_default',lambda:A['hr.payslip.run'].with_context(default_baseer_managed=True).create({'baseer_month':'2027-01-01'}),'Payroll > Settings')
    wizard=A['baseer.payroll.create'].create({'baseer_month':'2027-01-01'})
    reject('missing_configuration_wizard',wizard.action_create,'QA ARZ')
    check('no_run_inserted_on_failure',before==A['hr.payslip.run'].search_count([]))
    reject('stale_wizard_company',lambda:wizard.with_env(B).action_create())
    reject('wrong_company_direct',lambda:B['hr.payslip.run'].create({'baseer_managed':True,'company_id':6,'baseer_month':'2027-01-01'}))
    ar=A(context=dict(A.context,lang='ar_001'))
    reject('arabic_configuration_message',lambda:ar['baseer.payroll.create'].create({'baseer_month':'2027-01-01'}).action_create(),'إعدادات الرواتب غير مكتملة')

    config=B['res.config.settings'].create({})
    check('settings_defaults_active_company',config.company_id==B.company)
    check('settings_reads_company_mapping',config.baseer_payroll_journal_id==B.company.baseer_payroll_journal_id and bool(config.baseer_loan_account_id))
    config.write({'baseer_proration':'fixed30'})
    check('settings_writes_same_company_field',B.company.baseer_proration=='fixed30')
    check('other_company_unchanged',A.company.baseer_proration=='calendar' and not A.company.baseer_payroll_journal_id)
    config.write({'baseer_proration':'calendar'})
    check('settings_returns_calendar',B.company.baseer_proration=='calendar')
    for model in ('hr.payroll.structure','hr.salary.rule','account.move'):
        n=B[model].search_count([])
        B.company._baseer_check_payroll_configuration()
        check('pure_validation_'+model,n==B[model].search_count([]))
    result=B['baseer.payroll.create'].create({'baseer_month':'2027-01-01'}).action_create()
    run=B['hr.payslip.run'].browse(result['res_id'])
    check('configured_wizard_creation',run.company_id==B.company and run.journal_id==B.company.baseer_payroll_journal_id)
    check('configured_employees_loaded',len(run.slip_ids)==2 and run.baseer_gross==5000 and run.baseer_net==run.baseer_gross-run.baseer_loan_amount-run.baseer_deduction)

    def invalid(field, value):
        config.write({field:value})
        B.company._baseer_check_payroll_configuration()
    reject('wrong_journal_type',lambda:invalid('baseer_payroll_journal_id',B['account.journal'].search([('company_id','=',10),('type','=','bank')],limit=1).id))
    reject('wrong_payable_type',lambda:invalid('baseer_salary_payable_id',B.company.baseer_salary_expense_id.id))
    reject('wrong_receivable_type',lambda:invalid('baseer_loan_account_id',B.company.baseer_deduction_account_id.id))
    reject('cross_company_journal',lambda:invalid('baseer_payroll_journal_id',env['account.journal'].search([('company_id','=',6),('type','=','general')],limit=1).id))
    def bad_reconcile():
        B.company.baseer_salary_payable_id.reconcile=False
        B.company._baseer_check_payroll_configuration()
    reject('nonreconcilable_payable',bad_reconcile)
    payload={'status':'passed','checks':checks}
except Exception:
    payload={'status':'failed','checks':checks,'error':traceback.format_exc()}
finally:
    env.cr.rollback()
    payload['rolled_back']=True
    Path('/mnt/qa-evidence/baseer_payroll_settings_checks.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))
