"""BP-S6 native departure/payment/report checks, temporary fixtures rolled back."""
import io, json, traceback, time
from pathlib import Path
from datetime import date
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.baseer_payroll.models.common import money
from PyPDF2 import PdfReader

R={'checks':[], 'pdfs':{}}
def check(name,value):
    R['checks'].append({'name':name,'passed':bool(value)})
    assert value,name
def blocked(name,fn):
    try:
        with env.cr.savepoint(): fn(); env.flush_all()
    except (AccessError,UserError,ValidationError): check(name,True)
    else: check(name,False)
try:
    assert env.cr.dbname=='baseer_reports_qa_20260907'
    E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10], 'active_test':False,'lang':'en_US','tracking_disable':True,'mail_create_nosubscribe':True,'mail_notify_force_send':False},su=False)
    company=E.company
    purchase=E['account.journal'].search([('company_id','=',10),('type','=','purchase')],limit=1)
    company.write({'baseer_eos_journal_id':purchase.id,'baseer_eos_expense_id':company.baseer_salary_expense_id.id})
    bank=E['account.journal'].browse(132)
    method=E['account.payment.method.line'].browse(110)
    report=E['report.baseer_payroll.report_end_service']
    def person(name,reason='hr.departure_fired',depart=True):
        p=E['hr.employee'].create({'name':name,'company_id':10,'job_title':'مشرف التشغيل وخدمة العملاء','identification_id':'QA-1234567890'})
        p.version_id.write({'date_version':'2018-01-01','contract_date_start':'2018-01-01','wage':3000,'baseer_salary_mode':'fixed','baseer_allowance_total':300})
        p.work_contact_id.with_company(company).property_account_payable_id=company.baseer_salary_payable_id
        if depart:
            E['hr.departure.wizard'].with_context(employee_termination=True).create({'employee_ids':[(6,0,p.ids)],'departure_date':'2026-08-31','departure_reason_id':E.ref(reason).id,'set_date_end':True,'remove_related_user':False}).action_register_departure()
        return p
    def award_for(p):
        action=p.action_open_departure_award()
        return E['baseer.hr.eos'].browse(action['res_id'])
    def approve(a):
        a.approval_confirmed=True
        return a.action_approve_workflow()
    def pay(bills, amount):
        w=E['account.payment.register'].with_context(active_model='account.move',active_ids=bills.ids).create({'payment_date':'2026-08-31','journal_id':bank.id,'payment_method_line_id':method.id,'amount':float(amount),'group_payment':True,'payment_difference_handling':'open'})
        return w._create_payments()
    def pdf(a,label,lang='ar_001'):
        started=time.monotonic()
        content,_=E['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf('baseer_payroll.action_report_baseer_end_service',res_ids=a.ids)
        reader=PdfReader(io.BytesIO(content))
        check(label+'_one_A4_page',len(reader.pages)==1 and abs(float(reader.pages[0].mediabox.width)-595.28)<2 and abs(float(reader.pages[0].mediabox.height)-841.89)<2)
        Path('/mnt/qa-evidence/'+label+'.pdf').write_bytes(content)
        R['pdfs'][label]={'pages':len(reader.pages),'seconds':round(time.monotonic()-started,2),'bytes':len(content)}
    active=person('EW active',depart=False)
    blocked('departure_required',active.action_open_departure_award)
    check('active_button_hidden',not active.baseer_has_departure)
    p=person('عبدالله محمد عبدالرحمن أحمد - موظف تجربة نهاية الخدمة والتوقيع')
    check('native_departure_archived',not p.active and p.baseer_has_departure and p.departure_date==date(2026,8,31))
    count=E['account.move'].search_count([])
    a=award_for(p)
    check('auto_calculated_without_posting',a.source_snapshot and a.award_amount>0 and a.reason=='termination' and not a.bill_id and E['account.move'].search_count([])==count)
    check('button_replay_reuses',award_for(p)==a and len(p.baseer_eos_ids)==1)
    a.evidence_note='مراجعة مكافأة نهاية الخدمة حسب البيانات المسجلة.'
    check('reopen_preserves_review',award_for(p).evidence_note==a.evidence_note)
    check('unpaid_statement',not a._report_row()['is_final'] and a._report_row()['paid']=='0.00')
    blocked('snapshot_forgery',lambda:a.write({'document_snapshot':{'employee_name':'fake'}}))
    blocked('departure_flag_forgery',lambda:a.write({'departure_entry':False}))
    blocked('default_snapshot_forgery',lambda:E['baseer.hr.eos'].with_context(default_document_snapshot={'x':1}).create({'employee_id':p.id,'version_id':p.version_id.id,'service_end':'2026-08-31'}))
    blocked('default_departure_flag_forgery',lambda:E['baseer.hr.eos'].with_context(default_departure_entry=True).create({'employee_id':p.id,'version_id':p.version_id.id,'service_end':'2026-08-31'}))
    pdf(a,'eos_statement_ar')
    action=approve(a)
    bill=a.bill_id
    check('approve_returns_same_workspace',action['res_model']=='baseer.hr.eos' and action['res_id']==a.id and bill.state=='posted')
    check('identity_captured_once',a.document_snapshot['employee_name']==p.name)
    p.name='اسم معدل بعد الاعتماد'
    check('reprint_identity_stable',a._report_row()['employee_name']!=p.name)
    check('approved_reopen_same_bill',award_for(p)==a and a.action_approve_workflow()['res_id']==a.id)
    native=a.action_pay_award()
    check('payment_native_wizard',native['res_model']=='account.payment.register')
    pay(bill,500)
    check('partial_allocated_amount',a._payment_evidence()[0]=='partial' and a._payment_evidence()[1]==500 and not a._report_row()['is_final'])
    pdf(a,'eos_partial_ar')
    extra=E['account.move'].create({'move_type':'in_invoice','company_id':10,'journal_id':purchase.id,'partner_id':p.work_contact_id.id,'invoice_date':'2026-08-31','invoice_line_ids':[(0,0,{'name':'QA extra bill','account_id':company.baseer_salary_expense_id.id,'quantity':1,'price_unit':200,'tax_ids':[(5,0,0)]})]})
    extra.action_post()
    payments=pay(bill|extra,money(bill.amount_residual)+200)
    check('group_payment_allocations_not_full_payment',len(payments)==1 and a._payment_evidence()[1]==money(a.award_amount))
    check('fully_paid_final_receipt',a._payment_evidence()[0]=='paid' and a._report_row()['is_final'] and a._report_row()['remaining']=='0.00')
    before=E['account.move'].search_count([])
    a.action_print_clearance(); a.action_print_clearance()
    check('reprint_no_new_invoice',before==E['account.move'].search_count([]))
    pdf(a,'eos_final_ar')
    pdf(a,'eos_final_en','en_US')
    trusted=report._get_report_values(a.ids,data={'report_rows':[{'is_final':False,'employee_name':'forged'}]})
    check('report_data_cannot_override',trusted['report_rows'][0]['is_final'] and trusted['report_rows'][0]['employee_name']!='forged')
    viewer=E['res.users'].create({'name':'EW viewer','login':'ew-viewer@example.invalid','company_id':10,'company_ids':[(6,0,[10])],'group_ids':[(6,0,E.ref('base.group_user').ids)]})
    blocked('direct_report_requires_role',lambda:report.with_user(viewer)._get_report_values(a.ids))
    blocked('employee_action_requires_role',lambda:p.with_user(viewer).action_open_departure_award())
    blocked('other_active_company',lambda:p.with_context(allowed_company_ids=[6,10]).action_open_departure_award())
    bill._reverse_moves([{'date':date(2026,8,31),'invoice_date':date(2026,8,31),'ref':'EW reversed'}],cancel=True)
    check('reversal_suppresses_final',a._payment_evidence()[0]=='reversed' and not a._report_row()['is_final'])
    blocked('reversed_bill_no_second_payment',a.action_pay_award)
    check('reversed_button_reuses_original',award_for(p)==a)
    pdf(a,'eos_reversed_ar')
    resigned=person('EW resignation',reason='hr.departure_resigned')
    check('native_resignation_mapping',award_for(resigned).reason=='resignation')
    other=person('EW unknown',depart=False)
    unknown=E['hr.departure.reason'].create({'name':'Custom reviewed reason'})
    other.write({'departure_date':'2026-08-31','departure_reason_id':unknown.id})
    unknown_award=award_for(other)
    check('unknown_reason_explicit_review',unknown_award.reason=='review' and not unknown_award.reason_verified)
    blocked('unknown_not_auto_approved',lambda:approve(unknown_award))
    manual_person=person('EW manual')
    manual=E['baseer.hr.eos'].create({'employee_id':manual_person.id,'service_end':'2026-08-31','evidence_reference':'User reference'})
    check('manual_draft_reused_unchanged',award_for(manual_person)==manual and not manual.source_snapshot and manual.evidence_reference=='User reference' and not manual.departure_entry)
    pending=award_for(person('EW pending'))
    approve(pending)
    clearing=E['account.account'].create({'name':'EW outstanding','code':'EW999','account_type':'asset_current','reconcile':True,'company_ids':[(6,0,[10])]})
    method.payment_account_id=clearing
    pending_payment=pay(pending.bill_id,pending.award_amount)
    R['pending_evidence']={'payment_states':pending_payment.mapped('state'),'bill_state':pending.bill_id.payment_state,'residual':pending.bill_id.amount_residual,'workflow':pending._payment_evidence()[0],'paid':str(pending._payment_evidence()[1])}
    check('pending_is_not_receipt',pending._payment_evidence()[0]=='processing' and pending._payment_evidence()[1]==0 and not pending._report_row()['is_final'])
    method.payment_account_id=bank.default_account_id
    noncash=award_for(person('EW noncash'))
    approve(noncash)
    payable=noncash.bill_id.line_ids.filtered(lambda l:l.account_id.account_type=='liability_payable')
    general=E['account.journal'].search([('company_id','=',10),('type','=','general')],limit=1)
    entry=E['account.move'].create({'journal_id':general.id,'date':'2026-08-31','line_ids':[(0,0,{'name':'QA non-cash','account_id':payable.account_id.id,'partner_id':noncash.employee_id.work_contact_id.id,'debit':noncash.award_amount,'credit':0}),(0,0,{'name':'QA non-cash','account_id':company.baseer_salary_expense_id.id,'debit':0,'credit':noncash.award_amount})]})
    entry.action_post()
    (payable|entry.line_ids.filtered(lambda l:l.account_id==payable.account_id)).reconcile()
    check('noncash_reconciliation_not_received',money(noncash.bill_id.amount_residual)==0 and not noncash._report_row()['is_final'] and noncash._payment_evidence()[1]==0)
    mixed=award_for(person('EW payment writeoff'))
    approve(mixed)
    E['account.payment.register'].with_context(active_model='account.move',active_ids=mixed.bill_id.ids).create({'payment_date':'2026-08-31','journal_id':bank.id,'payment_method_line_id':method.id,'amount':100,'group_payment':True,'payment_difference_handling':'reconcile','writeoff_account_id':company.baseer_salary_expense_id.id,'writeoff_label':'QA writeoff'})._create_payments()
    check('payment_writeoff_cannot_be_final_receipt',money(mixed.bill_id.amount_residual)==0 and not mixed._report_row()['is_final'])
    long=award_for(person('عبدالله عبدالرحمن محمد أحمد ' * 10))
    company.write({'name':'شركة الخدمات والتشغيل وإدارة المرافق ' * 7,'street':'شارع الملك عبدالعزيز - حي النخيل ' * 8,'vat':'QA-123456789012345'})
    long.employee_id.job_title='مشرف التشغيل وإدارة الموارد والخدمات ' * 6
    long.evidence_note='تمت مراجعة مكافأة نهاية الخدمة والمستندات المرتبطة واعتماد المبالغ الواردة وفق المعلومات المسجلة. ' * 4
    approve(long)
    pay(long.bill_id,long.award_amount)
    pdf(long,'eos_long_ar')
    pdf(long,'eos_long_en','en_US')
    zero=award_for(person('EW zero'))
    zero.write({'reason':'article80'})
    zero.action_calculate()
    check('zero_statement_not_receipt',zero.award_amount==0 and not zero._report_row()['is_final'])
    zero.version_id.wage=3100
    blocked('stale_draft_cannot_print',zero.action_print_clearance)
    R['passed']=True
except Exception:
    R['passed']=False;R['error']=traceback.format_exc()
finally:
    env.cr.rollback();R['rolled_back']=True
    Path('/mnt/qa-evidence/baseer_eos_workflow_checks.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(R,ensure_ascii=False,indent=2))
assert R['passed'],R.get('error')
