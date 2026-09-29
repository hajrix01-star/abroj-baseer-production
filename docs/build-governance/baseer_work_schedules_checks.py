"""Native schedule seed acceptance; all temporary companies/edits rolled back."""
import json, time, traceback
from pathlib import Path
from odoo.exceptions import AccessError, ValidationError, UserError
from odoo.addons.baseer_payroll.models.common import split_salary

R={'checks':[]}
def check(name, condition):
    R['checks'].append({'name':name, 'passed':bool(condition)})
    assert condition, name
def pair(company):
    return [env.ref(f'baseer_payroll.work_schedule_{hours}_company_{company.id}') for hours in (84,60)]
def totals(company):
    for cal, hours, days, daily in zip(pair(company),(84,60),(7,6),(12,10)):
        check(f'{company.id}_{hours}_native_totals', cal.company_id==company and cal.hours_per_week==hours and cal.hours_per_day==daily and cal._get_days_per_week()==days)
        check(f'{company.id}_{hours}_full_days',len(cal.attendance_ids)==days and all(a.duration_days==1 and a.duration_hours==daily and a.day_period=='full_day' for a in cal.attendance_ids))
        check(f'{company.id}_{hours}_duration_mode',cal.duration_based and not cal.two_weeks_calendar and not cal.flexible_hours)
    check(f'{company.id}_friday_off', '4' not in pair(company)[1].attendance_ids.mapped('dayofweek'))

try:
    assert env.cr.dbname=='baseer_reports_qa_20260907'
    existing=env['res.company'].with_context(active_test=False).search([])
    check('existing_companies_seeded',all(all(pair(c)) for c in existing))
    totals(existing[0])
    E=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[10],'tracking_disable':True},su=False)
    started=time.monotonic()
    companies=E['res.company'].create([{'name':'WS QA A'},{'name':'WS QA B'}]).sudo()
    R['two_company_create_seconds']=round(time.monotonic()-started,3)
    for company in companies: totals(company)
    check('company_pairs_distinct',set(pair(companies[0])[0].ids+pair(companies[0])[1].ids).isdisjoint(pair(companies[1])[0].ids+pair(companies[1])[1].ids))
    check('native_default_unchanged',all(c.resource_calendar_id.hours_per_week==40 and c.resource_calendar_id not in pair(c) for c in companies))
    count=env['resource.calendar'].with_context(active_test=False).search_count([])
    companies._baseer_seed_work_schedules()
    check('repeat_no_duplicates',count==env['resource.calendar'].with_context(active_test=False).search_count([]))
    c84,c60=pair(companies[0])
    c84.write({'name':'Custom schedule','active':False})
    c84.attendance_ids[0].duration_hours=11
    companies._baseer_seed_work_schedules()
    check('custom_and_archive_preserved',c84.name=='Custom schedule' and not c84.active and c84.attendance_ids[0].duration_hours==11)
    env['res.company']._baseer_init_work_schedules()
    check('module_init_repeat_preserves_custom',c84.name=='Custom schedule' and not c84.active and count==env['resource.calendar'].with_context(active_test=False).search_count([]))
    custom=env['resource.calendar'].create({'name':'Custom default','company_id':companies[0].id})
    context={'default_name':'LEAK','default_duration_hours':1,'default_day_period':'lunch','default_hour_to':23,'default_week_type':'1','default_duration_based':False,'default_company_id':companies[0].id,'default_two_weeks_calendar':True}
    third=env['res.company'].with_context(**context).create({'name':'WS context QA','resource_calendar_id':custom.id})
    totals(third)
    check('explicit_company_default_preserved',third.resource_calendar_id==custom)
    check('context_not_leaked',all(a.name!='LEAK' and not a.week_type for cal in pair(third) for a in cal.attendance_ids))
    restricted=env['res.users'].create({'name':'WS restricted','login':'ws-seed-qa','company_id':companies[0].id,'company_ids':[(6,0,companies[0].ids)],'group_ids':[(6,0,env.ref('base.group_user').ids)]})
    U=env(user=restricted.id,context={'allowed_company_ids':companies[0].ids},su=False)
    check('native_calendar_read_access_preserved',bool(U['resource.calendar'].search([('id','in',[c.id for c in pair(companies[1])])])))
    check('own_company_calendar_visible',bool(U['resource.calendar'].search([('id','=',c60.id)])))
    try:
        with env.cr.savepoint(): U['res.company'].create({'name':'Unauthorized'})
    except AccessError: check('native_company_create_permission',True)
    else: check('native_company_create_permission',False)
    identity=env['ir.model.data'].search([('module','=','baseer_payroll'),('name','=',f'work_schedule_84_company_{companies[1].id}')])
    try:
        with env.cr.savepoint():
            identity.res_id=c84.id
            companies[1]._baseer_seed_work_schedules()
    except ValidationError: check('foreign_seed_reference_rejected',True)
    else: check('foreign_seed_reference_rejected',False)
    target=existing.filtered(lambda c:c.id==10)
    employee=E['hr.employee'].create({'name':'WS calculator QA','company_id':10})
    try:
        with env.cr.savepoint():
            employee.version_id.resource_calendar_id=pair(companies[1])[0]
            employee.version_id._check_company(['resource_calendar_id'])
            env.flush_all()
    except (UserError,ValidationError): check('native_explicit_company_checker_rejects_mismatch',True)
    else: check('native_explicit_company_checker_rejects_mismatch',False)
    employee.version_id.write({'wage':2000,'baseer_salary_mode':'inclusive','baseer_allowance_total':0,'baseer_work_days':30})
    for cal,daily in zip(pair(target),(12,10)):
        employee.version_id.resource_calendar_id=cal
        check(f'payroll_consumes_{daily}_native_hours',employee.baseer_daily_hours==daily and employee.version_id._baseer_split()==split_salary(2000,0,'inclusive',daily,30))
    R['passed']=True
except Exception:
    R['passed']=False
    R['error']=traceback.format_exc()
finally:
    env.cr.rollback()
    R['rolled_back']=True
    Path('/mnt/qa-evidence/baseer_work_schedules_checks.json').write_text(json.dumps(R,indent=2),encoding='utf-8')
    print(json.dumps(R,indent=2))
assert R['passed'],R.get('error')
