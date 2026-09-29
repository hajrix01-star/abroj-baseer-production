"""Independent current-shape purchase fixture and actual approval races."""
import json
from pathlib import Path
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
from odoo import api,Command
from odoo.service.model import retrying
from odoo.exceptions import UserError
assert env.cr.dbname=='baseer_audit_core_20260909'
uid=env.ref('base.user_admin').id
registry=env.registry
def E(cr):return api.Environment(cr,uid,{'allowed_company_ids':[10],'lang':'en_US','tracking_disable':True})
C=E(env.cr); company=C.company
provider=C.ref('baseer_service_seed.provider_water')
mapping=C.ref('baseer_service_seed.mapping_water_company_10')
journal=C['account.journal'].search([('company_id','=',10),('type','=','bank'),('active','=',True)],limit=1)
method=journal.outbound_payment_method_line_ids.filtered(lambda m:m.code=='manual')[:1]
assert method and journal.default_account_id
method.payment_account_id=journal.default_account_id
bank_account_id=journal.default_account_id.id
def make(ref):return C['baseer.purchase.batch'].create({'line_ids':[Command.create({'partner_id':provider.id,'category_map_id':mapping.id,'supplier_ref':ref,'gross_amount':115,'tax_id':company.account_purchase_tax_id.id,'invoice_date':'2026-09-01','payment_method_line_id':method.id,'entry_type':'expense'})]})
same=make('FA1 ACCEPTANCE SAME').id
dup=[make('FA1 ACCEPTANCE DUP').id,make('fa1 acceptance dup').id]
separate=[make('FA1 ACCEPTANCE DIFFERENT '+str(i)).id for i in range(2)]
env.cr.commit()
results=[]
def pair(ids,case):
    barrier=Barrier(2)
    def approve(sid):
        with registry.cursor() as cr:
            e=E(cr);attempts=[]
            def run():
                attempts.append(1)
                if len(attempts)==1:barrier.wait(timeout=20)
                return e['baseer.purchase.batch'].browse(sid).action_approve()
            try:
                retrying(run,e)
                return {'batch':sid,'approved':True,'attempts':len(attempts)}
            except UserError as exc:
                cr.rollback();return {'batch':sid,'approved':False,'attempts':len(attempts),'error':str(exc)}
    with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(approve,ids))
    results.append({'case':case,'requests':r});return r
assert all(v['approved'] for v in pair([same,same],'same batch twice'))
assert sum(v['approved'] for v in pair(dup,'same normalized reference'))==1
assert all(v['approved'] for v in pair(separate,'independent bills'))
with registry.cursor() as cr:
    e=E(cr);b=e['baseer.purchase.batch'].browse(same)
    assert len(b.move_ids)==1 and b.payment_count==1
    assert len(e['baseer.purchase.batch'].browse(dup).move_ids)==1
    assert len(e['baseer.purchase.batch'].browse(separate).move_ids)==2
    sources=e['baseer.purchase.batch'].browse([same]+dup+separate).filtered(lambda x:x.state=='approved')
    assert len(sources)==4 and all(x.bill_count==1 and x.payment_count==1 for x in sources)
    assert len(sources.line_ids.move_id)==4 and len(sources.line_ids.payment_id)==4
    assert all(m.state=='posted' and m.amount_total==115 and m.amount_tax==15 for m in sources.move_ids)
    bank_lines=sources.line_ids.payment_id.move_id.line_ids.filtered(lambda x:x.account_id.id==bank_account_id)
    expense_lines=sources.move_ids.invoice_line_ids
    assert round(sum(bank_lines.mapped('balance')),2)==-460
    assert round(sum(expense_lines.mapped('balance')),2)==400
    payable=(sources.move_ids|sources.line_ids.payment_id.move_id).line_ids.filtered(lambda x:x.account_id.account_type=='liability_payable')
    assert round(sum(payable.mapped('balance')),2)==0 and all(x.reconciled for x in payable)
    report=e.ref('baseer_purchase_batch.action_report_purchase_batch')
    pdf,_=report.with_context(lang='ar_001')._render_qweb_pdf(report.report_name,b.ids)
    Path('/mnt/qa-evidence/core-purchase-batch.pdf').write_bytes(pdf)
    cr.rollback()
Path('/mnt/qa-evidence/core-purchase-race.json').write_text(json.dumps({'status':'passed','cases':results,'one_bill_payment_per_source':True,'three_real_races':True,'pdf_bytes':len(pdf),'native_balances':{'bank':-460,'expense':400,'vat':60,'payable':0},'approved_sources':4,'bills':4,'payments':4},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':'passed','cases':results},ensure_ascii=False))
