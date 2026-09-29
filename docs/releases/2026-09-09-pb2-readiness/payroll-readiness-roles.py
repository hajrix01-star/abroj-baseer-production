import json,uuid,traceback
from pathlib import Path
from odoo.service.model import call_kw as native_call_kw
def call_kw(model, method, args, kwargs):
    return native_call_kw(model, method, args, {'context':dict(model.env.context), **kwargs})
from odoo.exceptions import AccessError,UserError,ValidationError
R={'checks':[]}
def check(n,e,a):R['checks'].append({'name':n,'expected':str(e),'actual':str(a),'pass':e==a})
def deny(n,fn):
    try:
        with env.cr.savepoint():fn()
    except (AccessError,UserError,ValidationError):check(n,True,True)
    else:check(n,True,False)
try:
    E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'tracking_disable':True,'mail_create_nolog':True,'mail_create_nosubscribe':True,'mail_notify_force_send':False},su=False)
    def user(group):
        u=E['res.users'].with_context(no_reset_password=True).create({'name':'PB2 roles','login':'pb2-role-'+uuid.uuid4().hex,'company_id':10,'company_ids':[(6,0,[10])],'group_ids':[(6,0,[E.ref('base.group_user').id]+([E.ref(group).id] if group else []))]})
        return E(user=u.id)
    H=user('hr.group_hr_user');N=user(False)
    ident=call_kw(H['hr.employee'],'create',[{'name':'PB2 HR officer minimal','company_id':10}],{})
    emp=E['hr.employee'].browse(ident)
    check('HR officer create enabled',True,emp.baseer_payroll_enabled)
    check('HR officer no payroll manager',False,H.user.has_group('om_hr_payroll.group_hr_payroll_manager'))
    check('HR officer no HR manager',False,H.user.has_group('hr.group_hr_manager'))
    deny('non HR cannot create employee',lambda:call_kw(N['hr.employee'],'create',[{'name':'Unauthorized PB2','company_id':10}],{}))
    deny('HR cannot create explicit payroll flag',lambda:call_kw(H['hr.employee'],'create',[{'name':'PB2 explicit','company_id':10,'baseer_payroll_enabled':False}],{}))
    deny('HR cannot default payroll flag',lambda:call_kw(H['hr.employee'].with_context(default_baseer_payroll_enabled=False,baseer_payroll_internal=True),'create',[{'name':'PB2 injected','company_id':10}],{}))
    deny('HR cannot read salary related',lambda:call_kw(H['hr.employee'],'read',[[ident],['baseer_salary_total']],{}))
    deny('HR cannot write salary related',lambda:call_kw(H['hr.employee'],'write',[[ident],{'baseer_salary_total':1}],{}))
    disabled=call_kw(E['hr.employee'],'create',[{'name':'PB2 disabled','company_id':10,'baseer_payroll_enabled':False}],{})
    check('authorized explicit false remains false',False,E['hr.employee'].browse(disabled).baseer_payroll_enabled)
    disabled_default=call_kw(E['hr.employee'].with_context(default_baseer_payroll_enabled=False),'create',[{'name':'PB2 authorized default false','company_id':10}],{})
    check('authorized context false remains false',False,E['hr.employee'].browse(disabled_default).baseer_payroll_enabled)
    R['status']='passed' if all(c['pass'] for c in R['checks']) else 'failed'
except Exception:R['status']='error';R['traceback']=traceback.format_exc()
finally:
    env.cr.rollback();Path('/mnt/qa-evidence/payroll-readiness-roles.json').write_text(json.dumps(R,ensure_ascii=False,indent=2));print(json.dumps(R,ensure_ascii=False,indent=2))
