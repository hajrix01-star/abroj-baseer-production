"""Two real cursors using native retry; approved QA preview is retained."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import perf_counter
from pathlib import Path
from odoo import api, Command
from odoo.service.model import retrying
from odoo.exceptions import UserError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
uid=env.ref('base.user_admin').id
registry=env.registry
qa=api.Environment(env.cr,uid,{'allowed_company_ids':[6],'lang':'en_US'})
model=qa['baseer.pos.summary']
ref='QA-PREVIEW-EXTERNAL-20260907'
preview=model.search([('external_reference','=',ref)],limit=1)
if not preview:
    preview=model.create({'business_date':'2026-09-07','external_reference':ref,'customer_count':60,
        'allocation_ids':[Command.create({'payment_method_id':mid,'amount':amount}) for mid,amount in [(1,500),(2,700),(3,600)]]})
preview_id=preview.id
env.cr.commit()
results=[]

def pair(case, functions):
    barrier=Barrier(2)
    def worker(fn):
        with registry.cursor() as cr:
            local=api.Environment(cr,uid,{'allowed_company_ids':[6],'lang':'en_US'})
            barrier.wait(timeout=15)
            start=perf_counter()
            try:
                result=retrying(lambda:fn(local),local)
                return {'ok':True,'result':result,'seconds':perf_counter()-start}
            except UserError as exc:
                cr.rollback()
                return {'ok':False,'error':str(exc),'seconds':perf_counter()-start}
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=[pool.submit(worker,fn) for fn in functions]
        rows=[f.result(timeout=90) for f in pending]
    results.append({'case':case,'requests':rows})
    return rows

same=pair('double approval of the same summary',[lambda e:e['baseer.pos.summary'].browse(preview_id).action_approve()]*2)
assert all(r['ok'] for r in same),same
def make(e,scope):
    return e['baseer.pos.summary'].create({'business_date':'2026-07-22','period_scope':scope,
        'external_reference':'QA-CONCURRENT-OVERLAP','customer_count':1,
        'allocation_ids':[Command.create({'payment_method_id':1,'amount':115})]}).id
overlap=pair('concurrent all-day versus morning creation',[lambda e:make(e,'all'),lambda e:make(e,'morning')])
assert sum(r['ok'] for r in overlap)==1,overlap
with registry.cursor() as cr:
    local=api.Environment(cr,uid,{'allowed_company_ids':[6],'lang':'en_US'})
    record=local['baseer.pos.summary'].browse(preview_id)
    assert record.state=='approved' and len(record.session_id.order_ids)==1 and len(record.order_id.payment_ids)==3
    assert local['pos.order'].search_count([('baseer_summary_id','=',preview_id)])==1
    assert local['pos.session'].search_count([('baseer_summary_id','=',preview_id)])==1
    draft=local['baseer.pos.summary'].search([('external_reference','=','QA-CONCURRENT-OVERLAP')])
    assert len(draft)==1 and draft.state=='draft'
    draft.unlink(); cr.commit()
    preview_data={'summary_id':preview_id,'company_id':6,'order_id':record.order_id.id,'session_id':record.session_id.id,
        'url':f'http://127.0.0.1:18070/odoo/action-490/{preview_id}'}
Path('/mnt/qa-evidence/pos_summary_preview.json').write_text(json.dumps(preview_data,indent=2))
Path('/mnt/qa-evidence/pos_summary_concurrency.json').write_text(json.dumps({'passed':True,'results':results,'preview':preview_data},ensure_ascii=False,indent=2,default=str))
print('POS_SUMMARY_CONCURRENCY_OK',json.dumps(preview_data))
