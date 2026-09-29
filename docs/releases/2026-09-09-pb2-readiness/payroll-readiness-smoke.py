import json, traceback
from pathlib import Path
from odoo.service.model import call_kw as native_call_kw
def call_kw(model, method, args, kwargs):
    return native_call_kw(model, method, args, {'context':dict(model.env.context), **kwargs})
from odoo.exceptions import AccessError, UserError, ValidationError
R={'checks': [], 'database':env.cr.dbname}
def check(name, expected, actual):
    R['checks'].append({'name':name,'expected':str(expected),'actual':str(actual),'pass':expected==actual})
def denied(name, action):
    try:
        with env.cr.savepoint(): action()
    except (AccessError, UserError, ValidationError): check(name,True,True)
    else: check(name,True,False)
try:
    C=env['res.company'].browse(10)
    E=env(user=env.ref('base.user_admin').id, context={'allowed_company_ids':[C.id], 'tracking_disable':True,'mail_create_nolog':True,'mail_create_nosubscribe':True,'mail_notify_force_send':False,'lang':'en_US'},su=False)
    E['hr.employee'].search([('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    hr=env['res.users'].with_context(no_reset_password=True).create({'name':'PB2 HR only','login':'pb2-hr-smoke','company_id':C.id,'company_ids':[(6,0,[C.id])], 'group_ids':[(6,0,[env.ref('base.group_user').id,env.ref('hr.group_hr_manager').id])]})
    H=E(user=hr.id)
    check('HR has no payroll manager',False,hr.has_group('om_hr_payroll.group_hr_payroll_manager'))
    emp=H['hr.employee'].browse(call_kw(H['hr.employee'],'create',[{'name':'PB2 minimal HR employee','company_id':C.id}],{}))
    employee=E['hr.employee'].browse(emp.id)
    check('HR native creation default stored',True,employee.baseer_payroll_enabled)
    check('native real version',True,bool(employee.version_id))
    check('no invented start',False,employee.version_id.contract_date_start)
    check('no invented salary',0,employee.version_id.wage)
    denied('HR protected flag read',lambda:call_kw(emp,'read',[[emp.id],['baseer_payroll_enabled']],{}))
    denied('HR protected flag write',lambda:call_kw(emp,'write',[[emp.id],{'baseer_payroll_enabled':False}],{}))
    employee.version_id.write({'date_version':'2048-01-01','wage':3000})
    run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':'2048-01-01'})
    slip=run.slip_ids
    check('pending row loaded',1,len(slip))
    check('pending state','pending',slip.baseer_readiness)
    R['warning_ar']=slip.with_context(lang='ar_001').baseer_readiness_warning
    R['problem_ar']=slip.with_context(lang='ar_001')._baseer_setup_problem()
    check('pending gross',0,slip.baseer_gross)
    officer=E['res.users'].with_context(no_reset_password=True).create({'name':'PB2 officer','login':'pb2-officer-smoke','company_id':C.id,'company_ids':[(6,0,[C.id])],'group_ids':[(6,0,[E.ref('base.group_user').id,E.ref('om_hr_payroll.group_hr_payroll_user').id])]})
    O=E(user=officer.id)
    check('Officer native readiness read', 'pending',call_kw(O['hr.payslip'],'read',[[slip.id],['baseer_readiness']],{})[0]['baseer_readiness'])
    denied('Officer foreign parent read',lambda:call_kw(O['hr.payslip'].with_context(allowed_company_ids=[6]),'read',[[slip.id],['baseer_readiness']],{}))
    slip.write({'baseer_deduction':100,'baseer_deduction_reason':'Retain pending input'})
    check('pending net',0,slip.baseer_net)
    check('pending residual',0,slip.baseer_residual)
    check('pending deduction retained',100,slip.baseer_deduction)
    check('pending deduction effective total',0,run.baseer_deduction)
    denied('pending compute',slip.compute_sheet)
    denied('pending approve',run.action_approve)
    denied('pending native approval',slip.action_payslip_done)
    denied('pending report',lambda:E['ir.actions.report']._render_qweb_html('baseer_payroll.report_payslips',slip.ids))
    call_kw(H['hr.version'],'write',[[employee.version_id.id],{'contract_date_start':'2048-01-16'}],{})
    denied('completed data still needs refresh',slip.action_payslip_done)
    run.action_load_employees()
    check('refresh same slip',slip.ids,run.slip_ids.ids)
    check('ready state','ready',slip.baseer_readiness)
    check('half month days',16,slip.baseer_days)
    check('ready positive net',True,slip.baseer_net>0)
    html=O['ir.actions.report']._render_qweb_html('baseer_payroll.report_payslips',slip.ids)[0]
    check('Officer allowed ready draft report',True,len(html)>100)
    call_kw(H['hr.version'],'write',[[employee.version_id.id],{'contract_date_start':False}],{})
    check('HR invalidates gross',0,slip.baseer_gross)
    check('HR invalidates net',0,slip.baseer_net)
    check('HR retains manual input',100,slip.baseer_deduction)
    check('HR removes native calculated lines',0,len(slip.line_ids))
    denied('invalidated native approval',slip.action_payslip_done)
    R['status']='passed' if all(c['pass'] for c in R['checks']) else 'failed'
except Exception:
    R['status']='error';R['traceback']=traceback.format_exc()
finally:
    env.cr.rollback()
    Path('/mnt/qa-evidence/payroll-readiness-smoke.json').write_text(json.dumps(R,ensure_ascii=False,indent=2))
    print(json.dumps(R,ensure_ascii=False,indent=2))
