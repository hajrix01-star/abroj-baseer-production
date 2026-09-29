import json, hashlib, importlib
from pathlib import Path
from decimal import Decimal
from odoo import api
assert env.cr.dbname in ('baseer_sim90_20260910','baseer_ic1_20260910')
env.cr.rollback();env.cr.execute('SET TRANSACTION READ ONLY')
root=Path('/tmp/sim90');info=json.loads((root/'context.json').read_text(encoding='utf8'))
local=api.Environment(env.cr,info['user_id'],{'allowed_company_ids':[info['company_id']],'lang':'en_US'},su=False)
counts={}
for model in ['account.move','account.move.line','account.payment','pos.order','pos.session','baseer.pos.summary','baseer.purchase.batch','baseer.purchase.batch.line','purchase.order','stock.picking','hr.employee','hr.payslip.run','hr.payslip','baseer.hr.loan','baseer.hr.service','baseer.hr.eos','hr.attendance','hr.leave','baseer.financial.correction.audit']:
    obj=local[model].with_context(active_test=False)
    domain=[('company_id','=',info['company_id'])] if 'company_id' in obj._fields else []
    counts[model]=obj.search_count(domain)
moves=local['account.move'].search([('company_id','=',info['company_id']),('state','=','posted')])
posted={kind:len(moves.filtered(lambda x:x.move_type==kind)) for kind in moves.mapped('move_type')}
monthly={}
for month in ['2026-01','2026-02','2026-03']:
    m=moves.filtered(lambda x:str(x.date).startswith(month))
    monthly[month]={'posted_moves':len(m),'debit':str(sum((Decimal(str(l.debit)) for l in m.line_ids),Decimal(0))),'credit':str(sum((Decimal(str(l.credit)) for l in m.line_ids),Decimal(0)))}
modules=local['ir.module.module'].search([('state','=','installed')])
result={'database':env.cr.dbname,'company_id':info['company_id'],'company_name':local.company.name,'counts':counts,'posted_document_types':posted,'posted_min_date':str(min(moves.mapped('date'))),'posted_max_date':str(max(moves.mapped('date'))),'distinct_posted_days':len(set(moves.mapped('date'))),'monthly':monthly,'installed_modules':{m.name:m.latest_version for m in modules},'read_only':True,'su':False}
sources={}
for mod in modules.filtered(lambda m:m.name.startswith('baseer_')):
    folder=Path(importlib.import_module('odoo.addons.'+mod.name).__file__).parent
    files={str(path.relative_to(folder)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(folder.rglob('*')) if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc'}
    sources[mod.name]={'path':str(folder),'files':len(files),'sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}
result['custom_runtime_source']=sources
env.cr.rollback()
(root/'dataset-inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print('SIM90_INVENTORY',json.dumps(result,ensure_ascii=False),flush=True)
