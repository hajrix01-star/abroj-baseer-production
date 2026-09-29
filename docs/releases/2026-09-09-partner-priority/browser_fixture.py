"""Only isolated PP1 clone: shared synthetic contacts and temporary QA login."""
import json
import secrets
from pathlib import Path
from odoo import Command
assert env.cr.dbname == 'baseer_partner_priority_qa_20260909'
companies = env['res.company'].search([],order='id')
a,b = companies[:2]
P = env['res.partner'].with_company(a)
fixtures = P.create([
    {'name':'PP1 ألفا للتوريد | Alpha Supply', 'supplier_rank':1, 'is_company':True},
    {'name':'PP1 المورد المفضل | Favorite Supply', 'supplier_rank':1, 'is_company':True, 'baseer_is_favorite':True},
])
fixtures[0].with_company(b).baseer_is_favorite = True
password = secrets.token_urlsafe(24)
user = env['res.users'].with_context(no_reset_password=True).create({
    'name':'PP1 QA', 'login':'pp1.qa', 'password':password, 'lang':'ar_001', 'tz':'Asia/Riyadh',
    'company_id':a.id, 'company_ids':[Command.set(companies.ids)],
    'group_ids':[Command.set([env.ref('account.group_account_manager').id,env.ref('purchase.group_purchase_manager').id,
                           env.ref('sales_team.group_sale_manager').id,env.ref('base.group_partner_manager').id])],
})
Path('/tmp/pp1-qa-login.json').write_text(json.dumps({'login':user.login,'password':password}))
Path('/mnt/pp1-evidence/browser-fixture.json').write_text(json.dumps({'user':user.id,'partners':fixtures.ids,
    'companies':[{'id':p.id,'name':p.name} for p in companies],
    'supplier_action':env.ref('account.res_partner_action_supplier').id,
    'batch_action':env.ref('baseer_purchase_batch.action_purchase_batches').id},ensure_ascii=False,indent=2))
env.cr.commit()
print('Isolated browser fixtures ready')
