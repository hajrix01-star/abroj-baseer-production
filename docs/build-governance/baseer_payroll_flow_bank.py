"""Audited QA demonstration clearing only; BP_FLOW_COMMIT must be supplied by operator."""
import json, traceback
from pathlib import Path
from decimal import Decimal
from odoo.addons.baseer_payroll.models.common import money

assert env.cr.dbname=='baseer_reports_qa_20260907'
commit=bool(globals().get('BP_FLOW_COMMIT',False))
E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'tracking_disable':True},su=False)
plan=json.loads(Path('/mnt/qa-evidence/baseer_payroll_flow_bank_plan.json').read_text())
out={'simulation_only':True,'committed':False,'clearing':[]}
try:
    journal=E['account.journal'].browse(132); method=E['account.payment.method.line'].browse(110)
    assert journal.company_id.id==10 and journal.type=='bank' and journal.default_account_id.id==1415
    assert journal.default_account_id.account_type=='asset_cash' and journal.company_id in journal.default_account_id.company_ids
    assert method in journal.outbound_payment_method_line_ids and method.payment_account_id.id in (False,1415)
    for row in plan['payments']:
        E.cr.execute('SELECT id FROM account_payment WHERE id=%s FOR UPDATE',(row['id'],))
        payment=E['account.payment'].browse(row['id']); payment.invalidate_recordset()
        line=E['account.move.line'].browse(row['line_id']); line.invalidate_recordset()
        ref='BP-S2 QA bank settlement / '+str(payment.id)
        existing=E['account.move'].search([('ref','=',ref),('company_id','=',10)])
        if existing:
            assert len(existing)==1 and existing.state=='posted' and money(line.amount_residual)==0 and payment.state=='paid'
            out['clearing'].append({'payment':payment.id,'move':existing.id,'already_done':True});continue
        assert payment.company_id.id==10 and payment.journal_id==journal and payment.move_id.id==row['move_id']
        assert payment.state=='in_process' and payment.outstanding_account_id.id==1423 and money(payment.amount)==money(row['amount'])
        assert line.move_id==payment.move_id and line.account_id.id==1423 and not line.move_id.baseer_payslip_id
        assert money(line.amount_residual)==money(row['amount_residual']) and line.amount_residual<0
        amount=-money(line.amount_residual)
        move=E['account.move'].create({'move_type':'entry','journal_id':journal.id,'date':plan['planned_date'],'ref':ref,'line_ids':[
            (0,0,{'name':payment.name,'account_id':1423,'partner_id':payment.partner_id.id,'debit':float(amount),'credit':0}),
            (0,0,{'name':payment.name,'account_id':1415,'partner_id':payment.partner_id.id,'debit':0,'credit':float(amount)})]})
        move.action_post()
        (line|move.line_ids.filtered(lambda l:l.account_id.id==1423)).reconcile()
        payment.invalidate_recordset()
        assert payment.state=='paid' and money(line.amount_residual)==0
        out['clearing'].append({'payment':payment.id,'move':move.id,'amount':float(amount),'state':payment.state})
    method.write({'payment_account_id':1415})
    out['configured_method']=110
    out['status']='passed'
    if commit: env.cr.commit();out['committed']=True
except Exception:
    out['status']='failed';out['error']=traceback.format_exc()
finally:
    if not out['committed']: env.cr.rollback()
    Path('/mnt/qa-evidence/baseer_payroll_flow_bank_'+('commit' if commit else 'trial')+'.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))
