"""Three balanced treasury transfers; pure internal transfers are excluded from cash flow."""
import json
from pathlib import Path
from odoo import api, Command
assert env.cr.dbname=='baseer_sim90_20260910'
root=Path('/tmp/sim90');info=json.loads((root/'context.json').read_text())
data=json.loads((root/'purchases.json').read_text())
assert not data.get('internal_transfers')
actor=api.Environment(env.cr,info['user_id'],{'allowed_company_ids':[2],'lang':'en_US','tracking_disable':True,'mail_create_nolog':True},su=False)
bank=actor['account.journal'].browse(info['bank_journal_id']);cash=actor['account.journal'].browse(info['cash_journal_id'])
ids=[]
for month in (1,2,3):
    day=f'2026-{month:02d}-15';amount=15000
    move=actor['account.move'].create({'company_id':2,'journal_id':actor.company.baseer_payroll_journal_id.id,'move_type':'entry','date':day,'ref':f'SIM90/INTERNAL-TRANSFER/{month}','line_ids':[Command.create({'name':'تمويل صندوق من البنك','account_id':cash.default_account_id.id,'debit':amount,'credit':0}),Command.create({'name':'تمويل صندوق من البنك','account_id':bank.default_account_id.id,'debit':0,'credit':amount})]})
    move.action_post();ids.append(move.id)
    data['events'].append({'key':f'SIM90/INTERNAL-TRANSFER/{month}','date':day,'kind':'internal_transfer','model':'account.move','id':move.id,'company_id':2,'move_ids':move.ids,'expected_cash_in':'0','expected_cash_out':'0','expected_operational_in':'0','bank_credit':str(amount),'cash_debit':str(amount)})
data['internal_transfers']=ids;data['counts']['internal_transfers']=3
env.cr.commit()
(root/'purchases.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
print('SIM90_INTERNAL_TRANSFERS',ids,flush=True)
