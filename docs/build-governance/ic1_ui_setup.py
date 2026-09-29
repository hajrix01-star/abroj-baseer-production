"""Persist visibly labelled IC1 fixtures only in the isolated QA database."""
import json
from pathlib import Path
from odoo import Command, fields
assert env.cr.dbname == 'baseer_ic1_20260910' and env.su
company = env['res.company'].search([('currency_id.name','=','SAR')], limit=1)
admin = env(context={'allowed_company_ids':company.ids, 'tracking_disable':True,
                     'no_reset_password':True, 'mail_create_nolog':True, 'lang':'en_US'})
actors = {}
for role in ('owner','accountant','cashier'):
    login = 'ic1-ui-' + role
    user = admin['res.users'].search([('login','=',login)])
    if not user:
        user = admin['res.users'].create({'name':'IC1 QA '+role,'login':login,
            'password':'IC1-isolated-ui-2026!', 'company_id':company.id,
            'company_ids':[Command.set(company.ids)], 'baseer_access_role':role, 'lang':'ar_001'})
    actors[role] = user.id
partner = admin['res.partner'].create({'name':'IC1 QA supplier — correction preview', 'company_id':company.id})
private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_loan_account_id | company.baseer_deduction_account_id
expense = admin['account.account'].search([('company_ids','in',company.ids),('account_type','=','expense'),('id','not in',private.ids)],limit=1)
journal = admin['account.journal'].search([('company_id','=',company.id),('type','=','purchase')],limit=1)
move = admin['account.move'].create({'move_type':'in_invoice','company_id':company.id,
    'journal_id':journal.id,'partner_id':partner.id, 'invoice_date':fields.Date.today(),
    'ref':'IC1 QA UI 400 to 500', 'invoice_line_ids':[Command.create({'name':'IC1 QA entered amount',
        'quantity':1, 'price_unit':400,'account_id':expense.id, 'tax_ids':[Command.clear()]})]})
move.action_post()
env.cr.commit()
Path('/mnt/qa-evidence/ic1-ui-fixtures.json').write_text(json.dumps({'database':env.cr.dbname,
    'company_id':company.id,'user_ids':actors,'move_id':move.id,'partner_id':partner.id}),encoding='utf-8')
print('IC1 QA UI fixtures ready: '+str(move.id))
