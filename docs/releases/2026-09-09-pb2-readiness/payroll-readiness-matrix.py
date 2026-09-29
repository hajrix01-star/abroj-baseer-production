import io,json,time,traceback
from pathlib import Path
from lxml import etree
from odoo.service.model import call_kw as native_call_kw,get_public_method
def call_kw(model, method, args, kwargs):
    return native_call_kw(model, method, args, {'context':dict(model.env.context), **kwargs})
from odoo.exceptions import AccessError,UserError,ValidationError
from odoo.tools.translate import trans_export
R={'checks':[],'database':env.cr.dbname}
def check(name,e,a):R['checks'].append({'name':name,'expected':str(e),'actual':str(a),'pass':e==a})
def denied(name,fn):
    try:
        with env.cr.savepoint():fn()
    except (AccessError,UserError,ValidationError):check(name,True,True)
    else:check(name,True,False)
try:
    E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'lang':'en_US','tracking_disable':True,'mail_create_nolog':True,'mail_create_nosubscribe':True,'mail_notify_force_send':False},su=False)
    C=E.company;C.baseer_proration='fixed30'
    E['hr.employee'].search([('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    def employee(name,start='2049-02-01',wage=3000,**extra):
        emp=E['hr.employee'].create({'name':'PB2 '+name,'company_id':C.id,**extra})
        emp.version_id.write({'date_version':'2049-02-01','contract_date_start':start,'wage':wage,'baseer_salary_mode':'fixed','baseer_allowance_total':0})
        if not emp.work_contact_id:emp.work_contact_id=E['res.partner'].create({'name':emp.name,'company_id':C.id})
        emp.work_contact_id.with_company(C).property_account_payable_id=C.baseer_salary_payable_id
        return emp
    ready=E['hr.employee'];missing_start=E['hr.employee'];missing_salary=E['hr.employee'];excluded=E['hr.employee']
    for i in range(50):
        if i<20:ready|=employee('ready '+str(i))
        elif i<30:missing_start|=employee('no start '+str(i),False)
        elif i<40:missing_salary|=employee('no salary '+str(i),wage=0)
        elif i<44:excluded|=employee('future '+str(i),'2049-03-01')
        elif i<47:
            emp=employee('ended '+str(i),'2049-01-01');emp.version_id.contract_date_end='2049-01-31';excluded|=emp
        elif i<49:excluded|=employee('archived '+str(i),active=False)
        else:excluded|=employee('disabled '+str(i),baseer_payroll_enabled=False)
    began=time.monotonic();run=E['hr.payslip.run'].with_context(active_test=False).create({'baseer_managed':True,'baseer_month':'2049-02-01'});R['load_seconds']=round(time.monotonic()-began,3)
    check('50 mixed load below15seconds',True,R['load_seconds']<15)
    check('eligible + incomplete rows',40,len(run.slip_ids))
    check('twenty pending',20,run.baseer_pending_setup_count)
    check('future ended archived disabled excluded',set(),set(excluded.ids)&set(run.slip_ids.employee_id.ids))
    check('full February monthly salary',60000,run.baseer_gross)
    check('full February net',60000,run.baseer_net)
    p=run.slip_ids.filtered(lambda s:s.employee_id==missing_start[:1]);p.write({'baseer_deduction':120,'baseer_deduction_reason':'Future reviewed deduction','baseer_defer_loan':True})
    check('pending computed rules empty',0,len(p.line_ids))
    check('pending manual input retained',120,p.baseer_deduction)
    check('pending run manual effective zero',0,run.baseer_deduction)
    moves=E['account.move'].search_count([])
    # Deliberately catch without savepoint: readiness preflight must not post any row.
    try:run.action_approve()
    except (AccessError,UserError,ValidationError):check('mixed approval blocked',True,True)
    else:check('mixed approval blocked',True,False)
    check('mixed atomic zero moves before exception',moves,E['account.move'].search_count([]))
    check('mixed atomic all draft',{'draft'},set(run.slip_ids.mapped('state')))
    ids=run.slip_ids.ids;run.action_load_employees();run.action_load_employees()
    check('two refreshes reuse rows',ids,run.slip_ids.ids)
    check('two refreshes pending totals stable',60000,run.baseer_net)
    for field,value in [('baseer_needs_refresh',False),('baseer_readiness','ready'),('baseer_readiness_warning',False)]:
        denied('protected '+field,lambda field=field,value=value:call_kw(p.with_context(baseer_payroll_internal=True),'write',[[p.id],{field:value}],{}))
    denied('RPC private invalidate',lambda:get_public_method(E['hr.employee'],'_baseer_invalidate_draft_payroll'))
    denied('forged defaults',lambda:E['hr.payslip'].with_context(baseer_payroll_internal=True,default_baseer_readiness='ready').create({'employee_id':p.employee_id.id,'version_id':p.version_id.id,'date_from':p.date_from,'date_to':p.date_to}))
    denied('foreign company approval',lambda:run.with_context(allowed_company_ids=[1]).action_approve())
    ar=p.with_context(lang='ar_001')
    check('Arabic missing start warning',True,'تاريخ بداية' in ar.baseer_readiness_warning)
    labels=dict(ar._fields['baseer_readiness']._description_selection(ar.env))
    check('Arabic pending label','بيانات ناقصة',labels['pending'])
    view=E['hr.payslip.run'].with_context(lang='ar_001').get_view(E.ref('baseer_payroll.view_baseer_payroll_run_form').id,'form')
    check('Arabic run banner',True,'أكمل بيانات الموظف' in view['arch'])
    hrview=E['hr.employee'].with_context(lang='ar_001').get_view(E.ref('hr.view_employee_form').id,'form')
    check('Arabic open ended hint',True,'للعقد غير محدد المدة' in hrview['arch'])
    out=io.BytesIO();trans_export('ar_001',['baseer_payroll'],out,'po',ar.env);Path('/mnt/qa-evidence/pb2-native-export-ar.po').write_bytes(out.getvalue())
    missing_start.version_id.write({'contract_date_start':'2049-02-15'})
    missing_salary.version_id.write({'wage':3000})
    denied('complete but stale mixed run',run.action_approve)
    run.action_load_employees()
    check('all forty now ready',0,run.baseer_pending_setup_count)
    check('half February14days',14,p.baseer_days)
    check('half February fixed30 salary',1400,p.baseer_gross)
    check('saved manual deduction applied once',1280,p.baseer_net)
    check('saved defer preserved',True,p.baseer_defer_loan)
    check('mixed correct total gross',104000,run.baseer_gross)
    check('mixed correct total net',103880,run.baseer_net)
    ready_slip=run.slip_ids.filtered(lambda s:s.employee_id==ready[:1]);oldlineids=ready_slip.line_ids.ids
    ready[:1].version_id.write({'wage':3300})
    check('ready to changed ready flagged',True,ready_slip.baseer_needs_refresh)
    check('ready to changed ready zero',0,ready_slip.baseer_net)
    check('other row unchanged',1280,p.baseer_net)
    denied('stale positive salary direct done',ready_slip.action_payslip_done)
    run.action_load_employees();check('new wage refreshed',3300,ready_slip.baseer_gross)
    ready[:1].version_id.write({'wage':0,'baseer_allowance_total':300})
    check('zero salary can retain allowance setup',300,ready[:1].baseer_allowance_total)
    check('salary removed no residual',0,ready_slip.baseer_residual)
    check('salary removed warning',True,'monthly salary' in ready_slip.baseer_readiness_warning)
    ready[:1].version_id.write({'wage':3300});run.action_load_employees()
    check('salary restored cleanly',3300,ready_slip.baseer_net)
    bank=E['account.journal'].search([('company_id','=',C.id),('type','=','bank')],limit=1)
    loan=E['baseer.hr.loan'].create({'employee_id':ready[:1].id,'amount':600,'installment_count':2,'date':'2049-02-01','first_due_date':'2049-02-28','journal_id':bank.id});loan.action_disburse()
    run.action_load_employees();check('loan after refresh',300,ready_slip.baseer_loan_amount)
    run.action_load_employees();check('loan repeat refresh same',300,ready_slip.baseer_loan_amount)
    run.action_approve();run.action_approve()
    check('forty approved moves',40,len(run.slip_ids.move_id))
    check('loan recovered once',300,loan.balance)
    check('one loan allocation',1,len(loan.allocation_ids))
    original=(ready_slip.baseer_gross,ready_slip.baseer_net,ready_slip.line_ids.ids,ready_slip.move_id.id)
    ready[:1].version_id.wage=3400
    check('posted historical snapshot unchanged',original,(ready_slip.baseer_gross,ready_slip.baseer_net,ready_slip.line_ids.ids,ready_slip.move_id.id))
    # Future version must not replace valid historical period version.
    everyone=ready|missing_start|missing_salary|excluded;everyone.baseer_payroll_enabled=False
    historical=employee('historical version');old=historical.version_id
    future=old.copy({'date_version':'2049-04-01','wage':7000})
    March=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2049-03-01'})
    check('future salary version not selected',old.id,March.slip_ids.version_id.id)
    check('historical wage used',3000,March.slip_ids.baseer_gross)
    March.slip_ids.write({'baseer_deduction':20,'baseer_deduction_reason':'Preserve on archive'})
    historical.active=False;March.action_load_employees()
    check('archive existing manual row retained pending',1,len(March.slip_ids))
    check('archive existing row zero',0,March.baseer_net)
    denied('archive existing row not approved',March.action_approve)
    R['status']='passed' if all(c['pass'] for c in R['checks']) else 'failed'
except Exception:R['status']='error';R['traceback']=traceback.format_exc()
finally:
    env.cr.rollback();Path('/mnt/qa-evidence/payroll-readiness-matrix.json').write_text(json.dumps(R,ensure_ascii=False,indent=2));print(json.dumps(R,ensure_ascii=False,indent=2))
