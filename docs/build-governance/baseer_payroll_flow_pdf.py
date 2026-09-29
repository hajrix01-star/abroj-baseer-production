"""Render the final QA payment statement and salary slips in both languages."""
import json
from pathlib import Path
assert env.cr.dbname=='baseer_reports_qa_20260907'
E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10]},su=False)
run=E['hr.payslip.run'].browse(107)
assert run.company_id.id==10 and run.baseer_payment_state=='paid'
R={'status':'passed','run_id':107,'total_paid':run._baseer_payment_total(),'rows':run._baseer_payment_rows(),'files':[]}
assert R['total_paid']==4400 and len(R['rows'])==4
for lang in ['ar_001','en_US']:
    for name,report,ids in [('statement','baseer_payroll.action_report_baseer_payment_receipt',run.ids),('payslips','baseer_payroll.action_report_baseer_payslips',run.slip_ids.ids)]:
        data,_=E['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf(report,res_ids=ids)
        assert data.startswith(b'%PDF')
        path=Path('/mnt/qa-evidence/baseer_payroll_flow_'+name+'_'+lang+'.pdf');path.write_bytes(data)
        R['files'].append({'file':path.name,'bytes':len(data)})
Path('/mnt/qa-evidence/baseer_payroll_flow_pdf.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
env.cr.rollback()
print(json.dumps(R,ensure_ascii=False))
