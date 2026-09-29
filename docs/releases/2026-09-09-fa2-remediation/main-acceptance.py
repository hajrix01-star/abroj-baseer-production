"""Non-mutating smoke acceptance after installing the candidate on a main clone."""
import json
from pathlib import Path
assert env.cr.dbname=='baseer_fix_main_20260909'
checks=[]
def check(name,ok):
 checks.append({'name':name,'passed':bool(ok)})
 if not ok:raise AssertionError(name)
names=['baseer_cash_categories','baseer_category_display','baseer_company_setup','baseer_hr_services','baseer_legion_compat',
 'baseer_payroll','baseer_pos_summary','baseer_purchase_batch','baseer_report_layout','baseer_service_seed','baseer_web_navigation']
for name in names:
 mod=env['ir.module.module'].search([('name','=',name)],limit=1)
 check(name+' installed',mod.state=='installed')
for model in ('baseer.purchase.batch','baseer.hr.service','baseer.hr.loan','baseer.hr.eos','hr.payslip.run','hr.employee','baseer.pos.summary','baseer.pos.day.entry'):
 view=env[model].get_view(view_type='form')
 check(model+' resolved form',bool(view['arch']))
companies=env['res.company'].search([('active','=',True),('parent_id','=',False),('chart_template','=','sa'),('currency_id.name','=','SAR')])
check('eligible Saudi companies',bool(companies))
for company in companies:
 c=company.with_company(company)
 c._baseer_check_payroll_configuration()
 check('company payroll configuration '+str(c.id),True)
 check('company EOS journal '+str(c.id),bool(c.baseer_eos_journal_id) and c.baseer_eos_journal_id.company_id==c)
 check('company EOS expense '+str(c.id),bool(c.baseer_eos_expense_id) and c.baseer_eos_expense_id.account_type=='expense')
 check('company purchase mappings '+str(c.id),bool(env['baseer.purchase.category.map'].search_count([('company_id','=',c.id)])))
provider=env.ref('baseer_service_seed.provider_water')
check('shared water provider',not provider.company_id)
check('contribution report namespace',bool(env.ref('om_hr_payroll.action_contribution_register')) and 'report.om_hr_payroll.report_contribution_register' in env)
Path('/mnt/qa-evidence/main-acceptance-result.json').write_text(json.dumps({'status':'passed','checks':checks,'database':env.cr.dbname},indent=2),encoding='utf-8')
env.cr.rollback()
print('Main-clone acceptance',len(checks),'checks passed')
