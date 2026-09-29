import json
from pathlib import Path
from odoo import api, Command

assert env.cr.dbname == 'baseer_sim90_20260910'
out=Path('/tmp/sim90')
out.mkdir(exist_ok=True)
assert not env['account.move'].search_count([]), 'Bootstrap requires an empty business ledger'
country=env.ref('base.sa')
sar=env.ref('base.SAR')
company=env['res.company'].search([('name','=','بصير التجريبية — محاكاة 90 يوماً')],limit=1)
if not company:
    company=env['res.company'].create({'name':'بصير التجريبية — محاكاة 90 يوماً','country_id':country.id,'currency_id':sar.id,'email':'simulation@example.invalid','phone':'0000000000'})
company._baseer_prepare_accounting()
other=env['res.company'].create({'name':'بصير — اختبار عزل الشركة','country_id':country.id,'currency_id':sar.id,'email':'isolation@example.invalid'})
other._baseer_prepare_accounting()
admin=env.ref('base.user_admin')
admin.write({'company_ids':[Command.set(env['res.company'].search([]).ids)],'company_id':company.id})
owner=env['res.users'].with_context(no_reset_password=True).create({'name':'مدير محاكاة بصير','login':'sim90.owner','password':'Sim90-Local-QA-2026!','email':'owner@example.invalid','baseer_access_role':'owner','company_id':company.id,'lang':'en_US','tz':'Asia/Riyadh'})
roles={}
for role,title in [('accountant','محاسب'),('cashier','كاشير')]:
    user=env['res.users'].with_context(no_reset_password=True).create({'name':title+' محاكاة بصير','login':'sim90.'+role,'password':'Sim90-Local-QA-2026!','email':role+'@example.invalid','baseer_access_role':role,'company_id':company.id,'company_ids':[Command.set(company.ids)],'lang':'en_US','tz':'Asia/Riyadh'})
    roles[role]=user.id
local=api.Environment(env.cr,owner.id,{'allowed_company_ids':company.ids,'lang':'en_US','tz':'Asia/Riyadh','tracking_disable':True,'mail_create_nolog':True},su=False)
company=local['res.company'].browse(company.id)
journals={}
for kind in ('cash','bank'):
    journal=local['account.journal'].search([('company_id','=',company.id),('type','=',kind)],limit=1)
    assert journal and journal.default_account_id
    for method in journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids:
        if method.code=='manual': method.payment_account_id=journal.default_account_id
    journals[kind+'_journal_id']=journal.id
info={'database':env.cr.dbname,'company_id':company.id,'other_company_id':other.id,'user_id':owner.id,'roles':roles,'start_date':'2026-01-01','end_date':'2026-03-31','prefix':'SIM90',**journals}
env['ir.cron'].with_context(active_test=False).search([]).write({'active':False})
env['ir.mail_server'].search([]).write({'active':False})
env.cr.commit()
(out/'context.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
print('SIM90_BOOTSTRAP',json.dumps(info),flush=True)
