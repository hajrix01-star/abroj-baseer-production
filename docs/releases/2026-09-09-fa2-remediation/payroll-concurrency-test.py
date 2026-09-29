"""Exclusive FA2 clone: committed synthetic fixtures required for two MVCC cursors."""
import json, threading, traceback, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from odoo import api, Command
from odoo.exceptions import UserError, ValidationError, AccessError
from psycopg2.errors import SerializationFailure

assert env.cr.dbname == 'baseer_fix_payroll_20260909'
R={'checks':[], 'races':[], 'database':env.cr.dbname}
def check(name,e,a):R['checks'].append({'name':name,'expected':str(e),'actual':str(a),'pass':e==a})
try:
    C=env['res.company'].browse(10)
    context={'allowed_company_ids':[10],'tracking_disable':True,'mail_create_nolog':True,
             'mail_create_nosubscribe':True,'mail_notify_force_send':False,'lang':'en_US'}
    E=env(user=env.ref('base.user_admin').id,context=context,su=False)
    E['hr.employee'].search([('company_id','=',10),('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    C=E.company
    cash=E['account.journal'].search([('company_id','=',10),('type','=','cash')],limit=1)
    cash.default_account_id.reconcile=False
    cash.outbound_payment_method_line_ids.write({'payment_account_id':cash.default_account_id.id})
    users=[]
    for role,groups in [('accounting',['account.group_account_user']),('payroll',[])]:
        users.append(E['res.users'].create({'name':'FA2 race '+role,'login':'fa2.race.'+role+'.'+uuid.uuid4().hex,
            'company_id':10,'company_ids':[Command.set([10])],
            'group_ids':[Command.set([E.ref(g).id for g in ['base.group_user','om_hr_payroll.group_hr_payroll_manager']+groups])]}))
    manager,payroll=users
    def fixture(month):
        emp=E['hr.employee'].create({'name':'FA2 concurrency '+month,'company_id':10})
        emp.version_id.write({'date_version':month,'contract_date_start':month,'wage':3000,'baseer_salary_mode':'fixed','baseer_allowance_total':0})
        if not emp.work_contact_id:emp.work_contact_id=E['res.partner'].create({'name':emp.name,'company_id':10})
        emp.work_contact_id.with_company(C).property_account_payable_id=C.baseer_salary_payable_id
        emp.baseer_payroll_enabled=True
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':month});run.action_approve()
        emp.baseer_payroll_enabled=False
        return run,run.slip_ids
    def wizard(slip,amount,user=manager):
        return E['baseer.payroll.correction'].with_user(user).create({'slip_id':slip.id,'kind':'wage','amount':amount,
            'date':slip.date_to,'reason':'FA2 documented race correction','reviewed':True})
    run,s=fixture('2041-01-01');one=wizard(s,10);two=wizard(s,20)
    run2,s2=fixture('2041-02-01');same=wizard(s2,11)
    run3,s3=fixture('2041-03-01');corr=wizard(s3,-1500)
    pay=E['baseer.payroll.settlement'].with_user(manager).create({'run_id':run3.id,'journal_id':cash.id,
        'payment_method_line_id':cash.outbound_payment_method_line_ids[:1].id,'payment_date':s3.date_to})
    pay.line_ids.amount=2000
    try:
        with env.cr.savepoint():wizard(s3,1,user=payroll).action_confirm()
    except AccessError:check('nonadmin payroll without accounting denied',True,True)
    else:check('nonadmin payroll without accounting denied',True,False)
    env.cr.commit()
    def race(label,jobs):
        barrier=threading.Barrier(2)
        def execute(job):
            model,ident=job
            errors=[]
            for attempt in range(3):
                with env.registry.cursor() as cr:
                    T=api.Environment(cr,manager.id,context)
                    record=T[model].browse(ident)
                    if attempt==0:
                        cr.execute('SELECT count(*) FROM account_move')
                        cr.fetchone();barrier.wait(timeout=30)
                    try:
                        record.action_confirm();cr.commit()
                        return {'result':'success','attempts':attempt+1,'errors':errors}
                    except SerializationFailure as error:
                        cr.rollback();errors.append(type(error).__name__)
                    except (ValidationError,UserError,AccessError) as error:
                        cr.rollback();return {'result':'blocked','attempts':attempt+1,'errors':errors,'message':str(error)}
            return {'result':'retry_exhausted','errors':errors}
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,jobs))
        R['races'].append({'name':label,'results':results})
        return results
    out=race('different correction wizards', [('baseer.payroll.correction',one.id),('baseer.payroll.correction',two.id)])
    check('different wizards one success',1,sum(o['result']=='success' for o in out))
    check('different wizards one stale block',1,sum(o['result']=='blocked' for o in out))
    out=race('same correction replay',[('baseer.payroll.correction',same.id)]*2)
    check('same wizard both calls succeed',2,sum(o['result']=='success' for o in out))
    out=race('payment versus salary reduction',[('baseer.payroll.correction',corr.id),('baseer.payroll.settlement',pay.id)])
    check('payment correction one success',1,sum(o['result']=='success' for o in out))
    check('payment correction one stale block',1,sum(o['result']=='blocked' for o in out))
    env.cr.rollback();E.invalidate_all()
    check('different correction one journal',1,len(s.baseer_correction_ids))
    check('same correction one journal',1,len(s2.baseer_correction_ids))
    check('same correction net exactly3011',3011,s2.baseer_net)
    check('race salary debt nonnegative',True,s3.baseer_residual>=0)
    R['fixtures']={'slips':(s|s2|s3).ids,'users':[u.id for u in users]}
    R['status']='completed'
    assert all(x['pass'] for x in R['checks'])
except Exception:
    env.cr.rollback();R['status']='execution_error';R['error']=traceback.format_exc()
finally:
    Path('/mnt/qa-evidence/payroll-concurrency-result.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(R,ensure_ascii=False))
