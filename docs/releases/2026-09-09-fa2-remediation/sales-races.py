"""Real separate cursor races; commits only in this disposable FA2 clone."""
assert env.cr.dbname == 'baseer_fix_sales_20260909'
import json, traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import perf_counter
from odoo import api, Command
from odoo.service.model import retrying
from odoo.exceptions import UserError
registry=env.registry;uid=env.ref('base.user_admin').id;ctx={'allowed_company_ids':[6],'lang':'en_US'}
result={'cases':[],'checks':[]}
def check(name,value):
    result['checks'].append({'name':name,'passed':bool(value)});assert value,name
def race(label,functions,successes):
    barrier=Barrier(2)
    def worker(fn):
        with registry.cursor() as cr:
            assert cr.dbname=='baseer_fix_sales_20260909'
            e=api.Environment(cr,uid,ctx);attempts=[];barrier.wait(timeout=20);start=perf_counter()
            def attempt():attempts.append(1);return fn(e)
            try:return {'ok':True,'value':retrying(attempt,e),'attempts':len(attempts),'seconds':perf_counter()-start}
            except UserError as exc:cr.rollback();return {'ok':False,'error':str(exc),'attempts':len(attempts)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,fn) for fn in functions];rows=[f.result(timeout=120) for f in futures]
    result['cases'].append({'case':label,'requests':rows});check(label+' success count',sum(row['ok'] for row in rows)==successes)
    return rows
def correction(e,sid):
    w=e['baseer.pos.summary.correction'].create({'summary_id':sid,'reason':'FA2 concurrent correction'})
    return w.action_correct()['res_id']
try:
    with registry.cursor() as cr:
        e=api.Environment(cr,uid,ctx);cfg=e['pos.config'].browse(1)
        method=cfg.payment_method_ids.filtered(lambda m:m.baseer_category_id.kind=='cash')[:1]
        check('fixture dates empty',not e['baseer.pos.summary'].search_count([('company_id','=',6),('business_date','in',['2026-03-03','2026-03-04'])]))
        sources=[]
        for day in ['2026-03-03','2026-03-04']:
            s=e['baseer.pos.summary'].create({'config_id':1,'business_date':day,'customer_count':10,
                'allocation_ids':[Command.create({'payment_method_id':method.id,'amount':115})]})
            s.action_approve();sources.append(s.id)
        cr.commit()
    rows=race('two corrections same original',[lambda e:correction(e,sources[0])]*2,2)
    replacement=rows[0]['value'];check('both correction callers see same draft',replacement==rows[1]['value'])
    race('two approvals same replacement',[lambda e:e['baseer.pos.summary'].browse(replacement).action_approve()]*2,2)
    def receipt_reverse(e):
        s=e['baseer.pos.summary'].browse(sources[1]);receipt=s._native_moves()-s.move_id
        return e['account.move.reversal'].with_context(active_model='account.move',active_ids=receipt.ids).create({
            'date':s.business_date,'journal_id':receipt.journal_id.id,'reason':'FA2 race receipt correction'}).reverse_moves()
    race('full correction versus receipt reversal',[lambda e:correction(e,sources[1]),receipt_reverse],1)
    with registry.cursor() as cr:
        e=api.Environment(cr,uid,ctx);s=e['baseer.pos.summary'].browse(sources[0]);r=e['baseer.pos.summary'].browse(replacement)
        check('one replacement in chain',e['baseer.pos.summary'].search_count([('replaces_id','=',s.id)])==1)
        check('one reversal each original',len(s.reversal_move_ids)==len(s._native_moves()) and all(len(m.reversal_move_ids)==1 for m in s._native_moves()))
        check('one replacement order and session',e['pos.order'].search_count([('baseer_summary_id','=',r.id)])==e['pos.session'].search_count([('baseer_summary_id','=',r.id)])==1)
        check('source cancelled replacement approved',s.state=='cancelled' and r.state=='approved')
        report=e['baseer.pos.daily.report']._aggregate_days(e.company,'2026-03-03','2026-03-03')['totals']
        check('one live sale115 customers10 day1',report['recorded_sales']==115 and report['recorded_customers']==10 and report['operating_days']==1)
        moves=s._native_moves()|s.reversal_move_ids|r._native_moves()
        check('posted ledger income100 VAT15',-sum(l.balance for l in moves.line_ids if l.account_id.account_type in ('income','income_other'))==100 and -sum(l.balance for l in moves.line_ids if l.tax_line_id)==15)
        check('all own moves posted',all(m.state=='posted' for m in moves))
        s2=e['baseer.pos.summary'].browse(sources[1])
        check('competing receipt has only one reversal',all(len(m.reversal_move_ids)==1 for m in s2._native_moves()-s2.move_id))
        check('competing result coherent',s2.state=='approved' and not s2.replacement_id and not s2.move_id.reversal_move_ids or s2.state=='cancelled' and s2.replacement_id.state=='draft' and len(s2.reversal_move_ids)==len(s2._native_moves()))
        result['retained_clone_fixtures']={'source_ids':sources,'replacement_id':replacement,'moves':moves.ids}
    result['status']='passed'
except Exception as exc:result.update(status='failed',error=str(exc),traceback=traceback.format_exc())
finally:env.cr.rollback()
Path('/mnt/qa-evidence/sales-races.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
