"""BP-S4 salary source, precision, preview and history tests, rolled back."""
import json, traceback
from pathlib import Path
from decimal import Decimal
from odoo.tests import Form
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.addons.baseer_payroll.models.common import split_salary
R={'checks':[]}
def check(name, condition):
    R['checks'].append({'name':name,'passed':bool(condition)})
    assert condition,name
def blocked(name, fn):
    try:
        with env.cr.savepoint(): fn();env.flush_all()
    except (UserError,ValidationError,AccessError,ValueError): check(name,True)
    else: check(name,False)
def cal(E,h):
    return E['resource.calendar'].create({'name':'BP4 schedule '+str(h),'company_id':10,
        'attendance_ids':[(0,0,{'name':'Work','dayofweek':str(d),'day_period':'morning','hour_from':8,'hour_to':8+h}) for d in range(5)]})
try:
    assert env.cr.dbname=='baseer_reports_qa_20260907'
    E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'tracking_disable':True},su=False)
    check('old_formula_2000_12h_30d',split_salary(2000,0,'inclusive',12,30)==(Decimal('954.13'),Decimal('1045.87'),Decimal('0.00')))
    check('fixed_allowances',split_salary(2000,300,'fixed',8,26)==(Decimal('1700'),Decimal('0'),Decimal('300')))
    check('native_eight_hours_supported',split_salary(2000,0,'inclusive',8,26)[0]==2000)
    blocked('invalid_allowance_equal_total',lambda:split_salary(2000,2000,'inclusive',12,30))
    blocked('invalid_precision',lambda:split_salary('2000.001',0,'fixed',8,26))
    c12=cal(E,12); c105=cal(E,10.5)
    emp=E['hr.employee'].create({'name':'BP4 Salary QA','company_id':10})
    v=emp.version_id
    v.write({'date_version':'2020-01-01','contract_date_start':'2020-01-01','resource_calendar_id':c12.id,'wage':2000,'baseer_salary_mode':'inclusive','baseer_work_days':30,'baseer_allowance_total':0})
    emp.baseer_payroll_enabled=True
    check('calendar_is_source',emp.baseer_daily_hours==12 and emp.baseer_work_calendar_id==c12)
    check('native_version_preview',emp.baseer_basic_salary==954.13 and emp.baseer_overtime_salary==1045.87)
    # Pseudo-record models the same onchange cache as an unsaved native form.
    draft=E['hr.employee'].new({'version_id':v.id,'baseer_salary_total':4000,
        'baseer_salary_mode':'inclusive','baseer_work_days':30,'baseer_allowance_total':0})
    check('unsaved_gross_preview',draft.baseer_basic_salary==float(split_salary(4000,0,'inclusive',12,30)[0]))
    draft.baseer_allowance_total=4000
    check('invalid_preview_clear_warning',bool(draft.baseer_salary_warning) and draft.baseer_basic_salary==0 and draft.baseer_overtime_salary==0)
    check('preview_does_not_write_contract',v.wage==2000 and v.baseer_allowance_total==0)
    blocked('invalid_profile_save',lambda:emp.write({'baseer_allowance_total':2000}))
    blocked('no_manual_employee_hours',lambda:emp.write({'baseer_daily_hours':11}))
    blocked('no_manual_version_hours',lambda:v.write({'baseer_daily_hours':11}))
    v.resource_calendar_id=c105
    check('fractional_calendar_preserved',emp.baseer_daily_hours==10.5)
    check('fractional_salary_matches',v._baseer_split()==split_salary(2000,0,'inclusive',10.5,30))
    newer=v.copy({'date_version':'2025-01-01','wage':3000,'resource_calendar_id':c12.id})
    historical=emp.with_context(version_id=v.id)
    current=emp.with_context(version_id=newer.id)
    check('historical_selected_version',historical.version_id==v and historical.baseer_salary_total==2000 and historical.baseer_daily_hours==10.5)
    historical.write({'baseer_salary_total':2100})
    check('historical_edit_isolated',v.wage==2100 and newer.wage==3000 and current.baseer_salary_total==3000)
    # A native form must calculate with unsaved input, rather than old related values.
    with Form(current) as f:
        f.baseer_salary_total=4000
        check('native_form_live_preview',f.baseer_basic_salary==float(split_salary(4000,0,'inclusive',12,30)[0]))
    check('native_form_save_single_wage',newer.wage==4000 and current.wage==4000)
    with Form(current) as f:
        f.resource_calendar_id=c105
        check('native_calendar_unsaved_preview',f.baseer_daily_hours==10.5 and f.baseer_basic_salary==float(split_salary(4000,0,'inclusive',10.5,30)[0]))
    users={}
    for name,groups in [('hr',['hr.group_hr_manager']),('payroll',['om_hr_payroll.group_hr_payroll_manager']),('basic',['hr.group_hr_user'])]:
        users[name]=E['res.users'].create({'name':'BP4 '+name,'login':'bp4-'+name+'@example.invalid','company_id':10,'company_ids':[(6,0,[10])],'group_ids':[(6,0,[E.ref(g).id for g in groups])]})
    hr=current.with_user(users['hr'])
    check('hr_role_separate',not users['hr'].has_group('om_hr_payroll.group_hr_payroll_manager'))
    env.invalidate_all()
    hr.write({'wage':4100})
    check('hr_native_wage_edit',newer.wage==4100)
    manager=current.with_user(users['payroll'])
    check('payroll_role_separate',not users['payroll'].has_group('hr.group_hr_manager'))
    env.invalidate_all()
    manager.write({'baseer_salary_total':4200})
    check('payroll_salary_edit',newer.wage==4200)
    blocked('basic_cannot_read_salary',lambda:current.with_user(users['basic']).read(['baseer_salary_total']))
    blocked('basic_cannot_read_split',lambda:current.with_user(users['basic']).read(['baseer_basic_salary']))
    blocked('basic_cannot_read_version_wage',lambda:newer.with_user(users['basic']).read(['wage']))
    blocked('basic_cannot_read_version_split',lambda:newer.with_user(users['basic']).read(['baseer_basic_salary']))
    other=env['res.company'].search([('id','!=',10)],limit=1)
    foreign=env['hr.employee'].sudo().with_company(other).create({'name':'BP4 foreign QA','company_id':other.id})
    blocked('foreign_company_salary_read',lambda:foreign.version_id.with_user(users['payroll']).with_context(allowed_company_ids=[10]).read(['wage']))
    # Validate the new merged view inside this rollback before the module upgrade.
    from lxml import etree
    xml=etree.parse('/mnt/baseer-addons/baseer_payroll/views/settings_views.xml')
    node=xml.xpath("//record[@id='view_baseer_employee_payroll']/field[@name='arch']")[0]
    E.ref('baseer_payroll.view_baseer_employee_payroll').write({'arch_db':'<data>'+''.join(etree.tostring(n,encoding='unicode') for n in node)+'</data>','priority':30})
    for role in ('hr','payroll'):
        view=E['hr.employee'].with_user(users[role]).get_view(E.ref('hr.view_employee_form').id,'form')
        arch=etree.fromstring(view['arch'])
        check('one_payroll_page_'+role,len(arch.xpath("//page[@name='payroll_information']"))==1 and not arch.xpath("//page[@name='baseer_payroll']"))
        fields={n.get('name') for n in arch.xpath('//field')}
        check('salary_view_'+role,('baseer_salary_total' in fields) == (role=='payroll'))
    E['hr.employee'].search([('company_id','=',10),('id','!=',emp.id),('baseer_payroll_enabled','=',True)]).write({'baseer_payroll_enabled':False})
    expected=newer._baseer_split()
    for month in range(1,7):
        run=E['hr.payslip.run'].create({'baseer_managed':True,'baseer_month':f'2025-{month:02d}-01'})
        run.action_approve()
        slip=run.slip_ids.filtered(lambda s:s.employee_id==emp)
        check('six_month_split_'+str(month),len(slip)==1 and tuple(Decimal(str(x)) for x in (slip.baseer_basic,slip.baseer_overtime,slip.baseer_allowance))==expected)
        check('six_month_balanced_'+str(month),slip.move_id.state=='posted' and sum(Decimal(str(l.balance)) for l in slip.move_id.line_ids)==0)
    R['status']='passed'
except Exception:
    R['status']='failed';R['error']=traceback.format_exc()
finally:
    env.cr.rollback();R['rolled_back']=True
    Path('/mnt/qa-evidence/baseer_payroll_profile_checks.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(R,ensure_ascii=False,indent=2))
