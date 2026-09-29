"""Exclusive sales clone; real commits confined to named audit DB only.

The approved fixture is retained in the disposable clone because application
history is immutable. The original product type is restored after races.
"""
assert env.cr.dbname == 'baseer_audit_sales_20260909'
import json,traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import perf_counter
from odoo import api,Command
from odoo.service.model import retrying
from odoo.exceptions import UserError
registry=env.registry;uid=env.ref('base.user_admin').id
ctx={'allowed_company_ids':[6],'lang':'en_US'}
results=[];product_id=29; original_type=None
def race(label,callbacks,expected_success):
    barrier=Barrier(2)
    def worker(fn):
        with registry.cursor() as cr:
            assert cr.dbname=='baseer_audit_sales_20260909'
            e=api.Environment(cr,uid,ctx);attempts=[]
            barrier.wait(timeout=20)
            start=perf_counter()
            def attempt():attempts.append(1);return fn(e)
            try:
                value=retrying(attempt,e)
                return {'ok':True,'attempts':len(attempts),'value':value,'seconds':perf_counter()-start}
            except UserError as exc:
                cr.rollback();return {'ok':False,'attempts':len(attempts),'error':str(exc)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,fn) for fn in callbacks]
        rows=[f.result(timeout=120) for f in futures]
    results.append({'case':label,'requests':rows})
    assert sum(r['ok'] for r in rows)==expected_success,results[-1]
try:
    with registry.cursor() as cr:
        e=api.Environment(cr,uid,ctx)
        assert not e['baseer.pos.summary'].search_count([('company_id','=',6),('business_date','in',['2026-06-18','2026-06-19','2026-06-20'])])
        original_type=e['product.product'].browse(product_id).type
        e['product.product'].browse(product_id).write({'type':'service'})
        draft=e['baseer.pos.summary'].create({'config_id':1,'business_date':'2026-06-18','customer_count':10,
            'external_reference':'AUDIT CONCURRENT APPROVAL','allocation_ids':[Command.create({'payment_method_id':1,'amount':115})]})
        draft_id=draft.id
        closure=e['baseer.pos.closure'].create({'date_from':'2026-06-20','date_to':'2026-06-20','reason':'maintenance'})
        closure_id=closure.id
        cr.commit()
    race('two concurrent approvals one summary',[lambda e:e['baseer.pos.summary'].browse(draft_id).action_approve()]*2,2)
    def create(e,day,scope='all'):
        return e['baseer.pos.summary'].create({'config_id':1,'business_date':day,'period_scope':scope,'customer_count':10,
            'external_reference':'AUDIT CONCURRENT OVERLAP','allocation_ids':[Command.create({'payment_method_id':1,'amount':115})]}).id
    race('all day versus morning creation',[lambda e:create(e,'2026-06-19','all'),lambda e:create(e,'2026-06-19','morning')],1)
    race('closure confirm versus sales creation',[lambda e:e['baseer.pos.closure'].browse(closure_id).action_confirm(),lambda e:create(e,'2026-06-20')],1)
    with registry.cursor() as cr:
        e=api.Environment(cr,uid,ctx)
        draft=e['baseer.pos.summary'].browse(draft_id)
        assert draft.state=='approved' and len(draft.session_id.order_ids)==1
        assert e['pos.order'].search_count([('baseer_summary_id','=',draft_id)])==1
        assert e['pos.session'].search_count([('baseer_summary_id','=',draft_id)])==1
        retained={'summary_id':draft_id,'order_id':draft.order_id.id,'session_id':draft.session_id.id,'move_ids':draft._native_moves().ids}
        result={'status':'passed','cases':results,'retained_audit_clone_fixture':retained,'product_fixture_original_type':original_type}
except Exception as exc:result={'status':'failed','cases':results,'error':str(exc),'traceback':traceback.format_exc()}
finally:
    if original_type:
        with registry.cursor() as cr:
            e=api.Environment(cr,uid,ctx)
            e['product.product'].browse(product_id).write({'type':original_type})
            cr.commit()
    env.cr.rollback()
Path('/mnt/qa-evidence/sales-concurrency-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
