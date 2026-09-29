"""Bounded 1/10/25-method native approvals, every case rolled back."""
import json
from pathlib import Path
from time import perf_counter
from odoo import Command

assert env.cr.dbname=='baseer_reports_qa_20260907'
qa=env(context=dict(env.context,allowed_company_ids=[6],lang='en_US'))
config=qa['pos.config'].browse(1)
cash=qa['pos.payment.method'].browse(1)
bank=qa['pos.payment.method'].browse(2)
class ProbeRollback(Exception): pass
results=[]
try:
    for size in [1,10,25]:
        try:
            with qa.cr.savepoint():
                methods=cash
                for n in range(size-1):
                    methods |= qa['pos.payment.method'].create({'name':f'QA capacity bank {n}', 'company_id':6,
                        'journal_id':bank.journal_id.id,'outstanding_account_id':bank.outstanding_account_id.id,
                        'receivable_account_id':bank.receivable_account_id.id,'baseer_category_id':bank.baseer_category_id.id,'payment_method_type':'none'})
                config.write({'payment_method_ids':[Command.set(methods.ids)]})
                start=perf_counter()
                row=qa['baseer.pos.summary'].create({'business_date':'2026-07-23','external_reference':f'QA-CAPACITY-{size}','customer_count':size,
                    'allocation_ids':[Command.create({'payment_method_id':m.id,'amount':115}) for m in methods]})
                row.action_approve()
                seconds=perf_counter()-start
                assert row.state=='approved' and row.amount_gross==size*115 and row.amount_tax==size*15 and row.average_per_customer==115
                assert len(row.order_id.payment_ids)==size and all(m.date==row.business_date for m in row._native_moves())
                results.append({'methods':size,'seconds':seconds,'gross':row.amount_gross,'tax':row.amount_tax,'native_moves':len(row._native_moves()),'passed':True})
                raise ProbeRollback()
        except ProbeRollback: pass
    Path('/mnt/qa-evidence/pos_summary_capacity.json').write_text(json.dumps({'results':results,'environment':'local QA only; single approvals, not a production load certification'},indent=2))
    print('POS_SUMMARY_CAPACITY_OK',results)
finally:
    env.cr.rollback()
