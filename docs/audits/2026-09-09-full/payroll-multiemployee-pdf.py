"""Read existing clone-only synthetic run and export native multiemployee PDF."""
import json
from pathlib import Path
assert env.cr.dbname=='baseer_audit_payroll_20260909'
R={}
try:
    E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'lang':'en_US'},su=False)
    candidates=E['hr.payslip.run'].search([('company_id','=',10),('baseer_managed','=',True),('state','=','done')],order='date_start desc,id desc')
    run=candidates.filtered(lambda r:len(r.slip_ids)>1)[:1]
    assert run
    R={'run':run.id,'month':str(run.date_start),'employees':run.slip_ids.employee_id.ids,'slips':run.slip_ids.ids,
       'net':run.baseer_net,'paid':run.baseer_paid,'residual':run.baseer_residual}
    for lang in ['ar_001','en_US']:
        data,_=E['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf('baseer_payroll.action_report_baseer_payslips',res_ids=run.slip_ids.ids)
        Path('/mnt/qa-evidence/payroll-multiemployee-'+lang+'.pdf').write_bytes(data)
finally:
    env.cr.rollback()
    R['rolled_back']=True
    Path('/mnt/qa-evidence/payroll-multiemployee-result.json').write_text(json.dumps(R,indent=2),encoding='utf-8')
    print(json.dumps(R))
