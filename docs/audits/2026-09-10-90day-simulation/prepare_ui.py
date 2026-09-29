import json
from pathlib import Path
from odoo import api, Command
assert env.cr.dbname=='baseer_sim90_20260910'
root=Path('/tmp/sim90'); info=json.loads((root/'context.json').read_text(encoding='utf8'))
ar=env['res.lang'].with_context(active_test=False).search([('code','=','ar_001')],limit=1)
assert ar
env['base.language.install'].create({'lang_ids':[Command.set(ar.ids)],'overwrite':False}).lang_install()
for uid in [info['user_id'],*info['roles'].values()]:
    env['res.users'].browse(uid).write({'lang':'ar_001','tz':'Asia/Riyadh'})
env['ir.config_parameter'].set_param('web.base.url','http://127.0.0.1:18075')
env['ir.config_parameter'].set_param('web.base.url.freeze','True')
empty=env['res.company'].browse(1)
assert not env['account.move'].search_count([('company_id','=',1)])
empty.write({'name':'بصير — إعدادات النظام بلا معاملات'})
other=api.Environment(env.cr,info['user_id'],{'allowed_company_ids':[info['other_company_id']],'lang':'en_US','tracking_disable':True,'mail_create_nolog':True},su=False)
company=other.company
def account(kind): return other['account.account'].search([('company_ids','in',company.ids),('account_type','=',kind)],limit=1)
partner=other['res.partner'].create({'name':'SIM90 طرف شركة العزل','company_id':company.id,'property_account_receivable_id':account('asset_receivable').id,'property_account_payable_id':account('liability_payable').id})
ids=[]
for kind,amount,typ in [('out_invoice',300,'income'),('in_invoice',700,'expense')]:
    move=other['account.move'].create({'move_type':kind,'company_id':company.id,'partner_id':partner.id,'invoice_date':'2026-02-15','date':'2026-02-15','ref':'SIM90/ISOLATION/'+kind,'invoice_line_ids':[Command.create({'name':'SIM90 عزل حقيقي للشركة','account_id':account(typ).id,'quantity':1,'price_unit':amount,'tax_ids':[Command.clear()]})]})
    move.action_post();ids.append(move.id)
info['isolation_move_ids']=ids
env.cr.commit()
(root/'context.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
print('SIM90_UI_READY',{'language':'ar_001','isolation_documents':ids},flush=True)
