"""Unmodified Odoo Mates19 characterization; synthetic data always rolled back."""
import json, time, traceback
from pathlib import Path
from unittest.mock import patch
R = {'checks': [], 'mail_intercepted': 0, 'scope': 'QA vendor evaluation; not production acceptance'}
def record(name, value, detail=None):
    R['checks'].append({'name':name, 'result':value, 'detail':detail})
def probe(name, fn):
    try:
        with env.cr.savepoint():
            result=fn()
        record(name, 'observed', result)
    except Exception as exc:
        record(name, 'error', {'type':type(exc).__name__, 'message':str(exc)})
def no_mail(*a,**kw):
    R['mail_intercepted']+=1
    return False
try:
    with patch.object(type(env['mail.template']), 'send_mail', no_mail), patch.object(type(env['mail.mail']), 'send', no_mail):
        C=env['res.company'].search([('currency_id.name','=','SAR')],limit=1)
        E=env(context=dict(env.context,allowed_company_ids=C.ids,tracking_disable=True,mail_create_nolog=True))
        expense=E['account.account'].create({'name':'OM QA expense rollback','code':'998881','account_type':'expense','company_ids':[(6,0,C.ids)]})
        liability=E['account.account'].create({'name':'OM QA liability rollback','code':'998882','account_type':'liability_current','company_ids':[(6,0,C.ids)]})
        journal=E['account.journal'].create({'name':'OM QA payroll rollback','code':'OMQA','type':'general','company_id':C.id,'default_account_id':liability.id})
        employee=E['hr.employee'].create({'name':'OM QA Employee','company_id':C.id,'work_email':'payroll-test@example.invalid'})
        version=employee.version_id
        version.write({'contract_date_start':'2026-09-01','wage':2000})
        category=E['hr.salary.rule.category'].create({'name':'OM QA Net','code':'NET','company_id':C.id})
        rule=E['hr.salary.rule'].create({'name':'OM QA Net salary','code':'NET','category_id':category.id,'company_id':C.id,'amount_select':'fix','amount_fix':2000,'account_debit':expense.id,'account_credit':liability.id})
        structure=E['hr.payroll.structure'].create({'name':'OM QA Structure','code':'OMQA','company_id':C.id,'parent_id':False,'rule_ids':[(6,0,rule.ids)]})
        version.write({'struct_id':structure.id,'journal_id':journal.id})
        batch=E['hr.payslip.run'].create({'name':'OM QA September','date_start':'2026-09-01','date_end':'2026-09-30','journal_id':journal.id})
        vals={'name':'OM QA September Salary','employee_id':employee.id,'company_id':C.id,'version_id':version.id,'struct_id':structure.id,'journal_id':journal.id,'date_from':'2026-09-01','date_to':'2026-09-30','payslip_run_id':batch.id}
        slip=E['hr.payslip'].create(vals)
        probe('employee_version_onchange',lambda: slip.onchange_employee()) if hasattr(slip,'onchange_employee') else None
        probe('calendar_worked_days',lambda: slip.get_worked_day_lines(version,'2026-09-01','2026-09-30'))
        # Ensure onchange-selected structure does not change this controlled fixture.
        slip.write(vals)
        start=time.monotonic()
        slip.compute_sheet()
        record('compute_net_2000',sum(slip.line_ids.filtered(lambda l:l.code=='NET').mapped('total'))==2000,{'seconds':round(time.monotonic()-start,3)})
        slip.action_payslip_done()
        first=slip.move_id
        record('first_approval_balanced_posted',first.state=='posted' and sum(first.line_ids.mapped('debit'))==sum(first.line_ids.mapped('credit'))==2000)
        record('payroll_batch_link',slip in batch.slip_ids)
        for lang in ['en_US','ar_001']:
            def render(lang=lang):
                report=E['ir.actions.report'].with_context(lang=lang)
                data,_=report._render_qweb_pdf('om_hr_payroll.action_report_payslip',res_ids=slip.ids)
                assert data.startswith(b'%PDF')
                Path('/mnt/qa-evidence/om_payroll_'+lang+'.pdf').write_bytes(data)
                return {'bytes':len(data)}
            probe('pdf_'+lang,render)
        other=E['hr.payslip'].create(dict(vals,name='OM QA second draft'))
        other.compute_sheet()
        def batch_pdf():
            data,_=E['ir.actions.report']._render_qweb_pdf('om_hr_payroll.action_report_payslip',res_ids=(slip+other).ids)
            assert data.startswith(b'%PDF')
            Path('/mnt/qa-evidence/om_payroll_batch.pdf').write_bytes(data)
            return {'bytes':len(data),'slips':2}
        probe('batch_pdf',batch_pdf)
        def repeat():
            slip.action_payslip_done()
            return {'duplicate_posted':slip.move_id!=first and first.state=='posted' and slip.move_id.state=='posted'}
        probe('repeat_approval',repeat)
        probe('posted_source_edit',lambda: (slip.write({'date_to':'2026-09-29'}) and {'accepted':str(slip.date_to)=='2026-09-29'}))
        latest=slip.move_id
        def cancel():
            slip.action_payslip_cancel()
            return {'state':slip.state,'latest_exists':bool(latest.exists()),'first_exists':bool(first.exists())}
        probe('cancel_approved',cancel)
        # Payroll-manager role scoped to another company must not read this company's salaries.
        other_company=env['res.company'].search([('id','!=',C.id)],limit=1)
        usr=E['res.users'].create({'name':'OM QA scope reviewer','login':'om-qa-scope@example.invalid','company_id':other_company.id,'company_ids':[(6,0,other_company.ids)],'group_ids':[(6,0,[env.ref('base.group_user').id,env.ref('om_hr_payroll.group_hr_payroll_manager').id])]})
        def company_scope():
            foreign=other.with_user(usr).with_context(allowed_company_ids=other_company.ids)
            rows=foreign.search_read([('id','=',other.id)],['id','company_id','date_from'])
            return {'foreign_slip_visible':bool(rows)}
        probe('company_isolation',company_scope)
        # A payable salary without a partner cannot use native supplier-style settlement.
        payable=E['account.account'].create({'name':'OM QA employee payable rollback','code':'998883','account_type':'liability_payable','reconcile':True,'company_ids':[(6,0,C.ids)]})
        rule.write({'account_credit':payable.id})
        probe('payable_partner_posting',lambda: other.action_payslip_done())
        record('payment_register_action_on_slip',hasattr(slip,'action_register_payment'))
        R['status']='characterization_complete'
except Exception:
    R['status']='fixture_failed'
    R['error']=traceback.format_exc()
finally:
    env.cr.rollback()
    R['rolled_back']=True
    Path('/mnt/qa-evidence/om_payroll_checks.json').write_text(json.dumps(R,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(R,ensure_ascii=False,indent=2,default=str))
