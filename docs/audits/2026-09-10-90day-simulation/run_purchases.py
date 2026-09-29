import json, traceback
from pathlib import Path
from decimal import Decimal
from odoo import api
assert env.cr.dbname=='baseer_sim90_20260910'
root=Path('/tmp/sim90'); info=json.loads((root/'context.json').read_text(encoding='utf8'))
local=api.Environment(env.cr,info['user_id'],{'allowed_company_ids':[info['company_id']],'lang':'en_US','tz':'Asia/Riyadh','tracking_disable':True,'mail_create_nolog':True,'mail_create_nosubscribe':True,'mail_notify_force_send':False},su=False)
ctx=dict(info,company=local['res.company'].browse(info['company_id']),cash_journal=local['account.journal'].browse(info['cash_journal_id']),bank_journal=local['account.journal'].browse(info['bank_journal_id']),cashier_id=info['roles']['cashier'])
scope={};exec(compile((root/'seed_purchases.py').read_bytes(),'seed_purchases.py','exec'),scope)
try:
    result=scope['seed_purchases'](local,ctx)
    assert result['counts']['approved_batches']==90
    local.flush_all(); checks=[]
    for row in result['manifest']:
        rec=local[row['model']].browse(row['id'])
        for field,expected in row['expected'].items():
            actual=rec[field]
            passed=Decimal(str(actual)).quantize(Decimal('.01'))==Decimal(str(expected)).quantize(Decimal('.01'))
            checks.append({'model':row['model'],'id':row['id'],'field':field,'expected':str(expected),'actual':str(actual),'passed':passed})
    result['seed_checks']=checks
    failures=[c for c in checks if not c['passed']]
    (root/'purchases.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    assert not failures,failures[:10]
    env.cr.commit()
    print('SIM90_PURCHASES_COMPLETE',result['counts'],'checks',len(checks),flush=True)
except Exception:
    env.cr.rollback();(root/'purchase-error.txt').write_text(traceback.format_exc(),encoding='utf8');raise
