"""Actual two-connection approval race; only in disposable HRS1 clone."""
import json,time,traceback
from pathlib import Path
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
import psycopg2
from odoo import api

assert env.cr.dbname=='baseer_hr_services_race','Disposable clone only'
R={'status':'started','checks':[]}
registry=env.registry
uid=env.ref('base.user_admin').id
def E(cr): return api.Environment(cr,uid,{'allowed_company_ids':[10],'lang':'en_US','tracking_disable':True})
def check(name,result):
    R['checks'].append({'name':name,'passed':bool(result)})
    assert result,name
try:
    with registry.cursor() as cr:
        C=E(cr)
        employee=C['hr.employee'].create({'name':'HRS1 approval race fixture','company_id':10})
        service=C['baseer.hr.service'].create({'employee_id':employee.id,'service_type':'iqama_issue',
            'partner_id':C.ref('baseer_service_seed.provider_passports_company_10').id,
            'issue_date':'2026-08-20','invoice_date':'2026-08-20','gross_amount':100})
        sid=service.id;cr.commit()
    barrier=Barrier(2)
    def approve():
        retries=[];start=time.monotonic();pid=None
        for attempt in range(5):
            try:
                with registry.cursor() as cr:
                    C=E(cr);service=C['baseer.hr.service'].browse(sid)
                    if attempt==0:
                        assert service.state=='draft' and not service.bill_id
                        cr.execute('SELECT pg_backend_pid()');pid=cr.fetchone()[0]
                        barrier.wait(timeout=20)
                    service.action_approve();C.flush_all()
                    bill=service.bill_id.id;cr.commit()
                    return {'pid':pid,'bill':bill,'retries':retries,'seconds':round(time.monotonic()-start,4)}
            except psycopg2.Error as exc:
                if exc.pgcode not in ('40001','40P01'): raise
                retries.append(exc.pgcode)
                if attempt==4:raise
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(approve) for _ in range(2)]
        results=[f.result(timeout=50) for f in futures]
    R['workers']=results
    check('independent_connections',results[0]['pid']!=results[1]['pid'])
    check('one_bill_from_both_approvals',results[0]['bill']==results[1]['bill'])
    check('actual_mvcc_retry_observed',any(r['retries'] for r in results))
    with registry.cursor() as cr:
        C=E(cr);service=C['baseer.hr.service'].browse(sid)
        check('one_persisted_native_bill',C['account.move'].search_count([('baseer_hr_service_id','=',sid)])==1)
        check('posted_correct_amount',service.bill_id.state=='posted' and service.bill_id.amount_total==100)
        check('no_automatic_payment',not service.bill_id._get_reconciled_payments())
    R['status']='passed'
except Exception:
    R['status']='failed';R['traceback']=traceback.format_exc()
finally:
    R['check_count']=len(R['checks'])
    Path('/mnt/qa-evidence/hr_services_concurrency.json').write_text(json.dumps(R,indent=2),encoding='utf-8')
    print(json.dumps(R))
