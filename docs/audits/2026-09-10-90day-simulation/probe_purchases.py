import json
from pathlib import Path
from odoo import api
assert env.cr.dbname=='baseer_sim90_20260910'
root=Path('/tmp/sim90');info=json.loads((root/'context.json').read_text())
local=api.Environment(env.cr,info['user_id'],{'allowed_company_ids':[2],'lang':'en_US','tz':'Asia/Riyadh','tracking_disable':True,'mail_create_nolog':True},su=False)
ctx=dict(info,company=local['res.company'].browse(2),cash_journal=local['account.journal'].browse(info['cash_journal_id']),bank_journal=local['account.journal'].browse(info['bank_journal_id']),cashier_id=7,daily_count=3)
scope={};exec(compile((root/'seed_purchases.py').read_bytes(),'seed_purchases.py','exec'),scope)
try:
    data=scope['seed_purchases'](local,ctx)
    print('PURCHASE_WORKFLOW_PROBE_PASS',data['counts'],flush=True)
finally:
    env.cr.rollback()
