"""Native public method boundary and company/role checks; rollback only."""
import json,traceback,uuid
from pathlib import Path
from odoo import api,Command
from odoo.exceptions import AccessError,UserError,ValidationError
from odoo.service.model import call_kw,get_public_method
assert env.cr.dbname=='baseer_fix_payroll_20260909'
R={'checks':[]}
def check(n,v,e=None):R['checks'].append({'name':n,'pass':bool(v),'evidence':e})
def denied(n,fn):
    try:
        with env.cr.savepoint():result=fn()
    except (AccessError,UserError,ValidationError) as error:check(n,True,str(error))
    else:check(n,False,str(result))
try:
    A=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[10],'lang':'en_US','tracking_disable':True})
    s=A['hr.payslip'].search([('employee_id.name','=','FA2 concurrency 2041-01-01')],limit=1)
    assert s
    def user(role,groups,companies):
        u=A['res.users'].create({'name':'FA2 RPC '+role,'login':'fa2.rpc.'+role+'.'+uuid.uuid4().hex,
            'company_id':companies[0],'company_ids':[Command.set(companies)],
            'group_ids':[Command.set([A.ref(g).id for g in ['base.group_user']+groups])]})
        return api.Environment(env.cr,u.id,{'allowed_company_ids':companies,'lang':'en_US','tracking_disable':True})
    O=user('officer',['om_hr_payroll.group_hr_payroll_user'],[10])
    M=user('manager',['om_hr_payroll.group_hr_payroll_manager','account.group_account_user'],[10,6])
    F=api.Environment(env.cr,M.uid,{'allowed_company_ids':[6,10],'lang':'en_US'})
    values={'slip_id':s.id,'kind':'wage','amount':1,'date':'2041-01-31','reason':'RPC approved review','reviewed':True}
    denied('Officer public create denied',lambda:call_kw(O['baseer.payroll.correction'],'create',[values],{}))
    ident=call_kw(M['baseer.payroll.correction'],'create',[values],{})
    check('nonadmin accounting manager RPC create allowed',bool(ident))
    denied('Officer public action_confirm denied',lambda:call_kw(O['baseer.payroll.correction'],'action_confirm',[[ident]],{}))
    denied('wrong active company public create denied',lambda:call_kw(F['baseer.payroll.correction'],'create',[values],{}))
    denied('wrong active company public confirm denied',lambda:call_kw(F['baseer.payroll.correction'],'action_confirm',[[ident]],{}))
    for name in ['_sources','_new_move','_salary_adjustment','_reverse_recovery']:
        denied('native dispatcher denies '+name,lambda name=name:get_public_method(M['baseer.payroll.correction'],name))
    denied('Officer public payslip action_correct denied',lambda:call_kw(O['hr.payslip'],'action_correct',[[s.id]],{}))
    result=call_kw(M['baseer.payroll.correction'],'action_confirm',[[ident]],{})
    check('nonadmin accounting manager RPC confirmation allowed',bool(result.get('res_id')))
    R['status']='completed';assert all(c['pass'] for c in R['checks'])
except Exception:R['status']='execution_error';R['error']=traceback.format_exc()
finally:
    env.cr.rollback();R['rolled_back']=True
    Path('/mnt/qa-evidence/payroll-rpc-result.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(R,ensure_ascii=False))
