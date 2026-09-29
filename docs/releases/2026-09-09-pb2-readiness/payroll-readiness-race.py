"""Two real transactions on committed synthetic PB2-clone fixtures only."""
import json,threading,traceback,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from odoo import api,Command
from odoo.service.model import call_kw as native_call_kw
def call_kw(model, method, args, kwargs):
    return native_call_kw(model, method, args, {'context':dict(model.env.context), **kwargs})
from odoo.exceptions import AccessError,UserError,ValidationError
from psycopg2.errors import SerializationFailure,DeadlockDetected
R={'checks':[],'races':[],'database':env.cr.dbname}
def check(n,e,a):R['checks'].append({'name':n,'expected':str(e),'actual':str(a),'pass':e==a})
try:
    context={'allowed_company_ids':[10],'lang':'en_US','tracking_disable':True,'mail_create_nolog':True,'mail_create_nosubscribe':True,'mail_notify_force_send':False}
    E=api.Environment(env.cr,env.ref('base.user_admin').id,context);C=E.company
    E['hr.employee'].search([('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    users={}
    for role,groups in [('HR',['hr.group_hr_manager']),('Payroll',['hr.group_hr_manager','om_hr_payroll.group_hr_payroll_manager','account.group_account_user'])]:
        users[role]=E['res.users'].with_context(no_reset_password=True).create({'name':'PB2 race '+role,'login':'pb2-race-'+uuid.uuid4().hex,'company_id':10,'company_ids':[Command.set([10])],'group_ids':[Command.set([E.ref(g).id for g in ['base.group_user']+groups])]})
    def fixture(month):
        emp=E['hr.employee'].create({'name':'PB2 concurrency '+month,'company_id':10})
        emp.version_id.write({'date_version':month,'contract_date_start':month,'wage':3000,'baseer_allowance_total':0,'baseer_salary_mode':'fixed'})
        if not emp.work_contact_id:emp.work_contact_id=E['res.partner'].create({'name':emp.name,'company_id':10})
        emp.work_contact_id.with_company(C).property_account_payable_id=C.baseer_salary_payable_id
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':month})
        return emp,run,run.slip_ids
    emp,run,slip=fixture('2050-01-01')
    emp2,run2,slip2=fixture('2050-02-01')
    # Both rows in February are valid; disabling an employee would intentionally invalidate its draft.
    env.cr.commit()
    def race(name,jobs):
        barrier=threading.Barrier(2)
        def execute(job):
            role,model,ident,method,vals=job;errors=[]
            for attempt in range(3):
                with env.registry.cursor() as cr:
                    T=api.Environment(cr,users[role].id,context)
                    if not attempt:
                        cr.execute('SELECT count(*) FROM hr_payslip');cr.fetchone();barrier.wait(timeout=20)
                    try:
                        args=[[ident]]+([vals] if vals is not None else [])
                        call_kw(T[model],method,args,{})
                        cr.commit();return {'outcome':'success','attempts':attempt+1,'retries':errors}
                    except (SerializationFailure,DeadlockDetected) as e:cr.rollback();errors.append(type(e).__name__)
                    except (AccessError,UserError,ValidationError) as e:
                        cr.rollback();return {'outcome':'blocked','attempts':attempt+1,'retries':errors,'message':str(e)}
            return {'outcome':'exhausted','retries':errors}
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,jobs))
        R['races'].append({'name':name,'results':results})
        return results
    result=race('HR start removal versus approval',[
        ('HR','hr.version',emp.version_id.id,'write',{'contract_date_start':False}),
        ('Payroll','hr.payslip.run',run.id,'action_approve',None)])
    check('HR edit succeeds consistently', 'success',result[0]['outcome'])
    check('no exhausted transaction',False,any(o['outcome']=='exhausted' for o in result))
    env.cr.rollback();E.invalidate_all()
    if slip.state=='done':
        check('approval first preserved posted salary',3000,slip.baseer_net)
        check('approval first one posted journal','posted',slip.move_id.state)
    else:
        check('HR first approval blocked','blocked',result[1]['outcome'])
        check('HR first zero draft salary',0,slip.baseer_net)
        check('HR first zero accounting',False,bool(slip.move_id))
    result=race('two refresh requests same run',[
        ('Payroll','hr.payslip.run',run2.id,'action_load_employees',None),
        ('Payroll','hr.payslip.run',run2.id,'action_load_employees',None)])
    check('two refresh calls finish',2,sum(o['outcome']=='success' for o in result))
    check('two refresh serialized retry',True,any(o['retries'] for o in result))
    env.cr.rollback();E.invalidate_all()
    check('two refresh no duplicate employees',len(run2.slip_ids.employee_id),len(run2.slip_ids))
    check('pending employee contributes zero after race',3000,run2.baseer_net)
    check('no draft journals after refresh',False,bool(run2.slip_ids.move_id))
    R['fixtures']={'employee_ids':[emp.id,emp2.id],'run_ids':[run.id,run2.id],'users':{k:v.id for k,v in users.items()}}
    R['status']='passed' if all(c['pass'] for c in R['checks']) else 'failed'
except Exception:R['status']='error';R['traceback']=traceback.format_exc()
finally:
    env.cr.rollback();Path('/mnt/qa-evidence/payroll-readiness-race.json').write_text(json.dumps(R,ensure_ascii=False,indent=2));print(json.dumps(R,ensure_ascii=False,indent=2))
