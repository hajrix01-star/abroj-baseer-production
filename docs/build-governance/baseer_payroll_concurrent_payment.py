"""QA preview only: verify February approval/defer and partial payment replay."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
from odoo import api
from odoo.service.model import retrying
assert env.cr.dbname=='baseer_reports_qa_20260907'
path=Path('/mnt/qa-evidence/baseer_payroll_concurrency.json')
evidence=json.loads(path.read_text(encoding='utf-8'))
p=evidence['preview']; company=env['res.company'].browse(p['company'])
admin=env.ref('base.user_admin')
ctx={'allowed_company_ids':company.ids,'tracking_disable':True}
E=env(user=admin.id,context=ctx,su=False)
run=E['hr.payslip.run'].browse(p['february_draft'])
assert run.state=='draft'
def concurrent(fn):
    barrier=Barrier(2)
    def operation(i):
        with env.registry.cursor() as cr:
            isolated=api.Environment(cr,admin.id,ctx)
            barrier.wait(timeout=15)
            return retrying(lambda:fn(isolated),isolated)
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(operation,range(2)))
env.cr.commit()
concurrent(lambda e:e['hr.payslip.run'].browse(run.id).action_approve())
env.invalidate_all()
loan=E['baseer.hr.loan'].browse(p['loan'])
assert len(loan.defer_ids)==1 and len(loan.allocation_ids)==2 and loan.balance==850
slip=run.slip_ids.filtered(lambda s:s.employee_id.id==p['employee_ids'][0])
bank=E['account.journal'].search([('company_id','=',company.id),('type','=','bank')],limit=1)
wizard=E['account.payment.register'].with_context(**slip.action_pay()['context']).create({'journal_id':bank.id,'payment_date':'2026-02-28','amount':1000})
env.cr.commit()
ids=concurrent(lambda e:e['account.payment.register'].browse(wizard.id)._create_payments().ids)
env.invalidate_all()
assert ids[0]==ids[1] and len(ids[0])==1
assert slip.baseer_paid==1000 and slip.baseer_residual==2000
march=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2026-03-01'})
env.cr.commit()
evidence['concurrent_deferral']={'passed':True,'defer_history_rows':1,'balance':850}
evidence['concurrent_partial_salary_payment']={'passed':True,'payment_ids':ids,'paid':1000,'remaining':2000}
evidence['preview']['march_draft']=march.id
path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False))
