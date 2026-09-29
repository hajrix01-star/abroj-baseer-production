"""HR2 scoped salary/job data import. Driver injects PAYLOAD and COMMIT."""
import json
from decimal import Decimal
from odoo import Command

assert env.cr.dbname=='baseer_dev'
assert PAYLOAD['scope']=='salary_and_jobs'
MODULE='baseer_legacy_hr_import'
env.cr.execute('SELECT pg_advisory_xact_lock(19420909, 2)')
env.cr.execute('SELECT id FROM resource_calendar WHERE id=ANY(%s) ORDER BY id FOR UPDATE',
               [sorted({r['baseline']['calendar_id'] for r in PAYLOAD['employees']})])
calendar_before=env['resource.calendar'].with_context(active_test=False).search([]).ids
version_before=env['hr.version'].with_context(active_test=False).search([]).ids
employee_before=env['hr.employee'].with_context(active_test=False).search([]).ids
job_before=env['hr.job'].with_context(active_test=False).search([]).ids

def protected():
    env.flush_all()
    env.cr.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'account_%' OR tablename LIKE 'baseer_%' OR tablename LIKE 'hr_payslip%' OR tablename LIKE 'hr_leave%' OR tablename LIKE 'hr_attendance%' OR tablename LIKE 'hr_work_entry%' OR tablename LIKE 'resource_calendar%' OR tablename IN ('res_company','res_users','hr_job')) ORDER BY tablename")
    out={}
    for (table,) in env.cr.fetchall():
        assert table.replace('_','').isalnum()
        suffix='';params=[]
        if table in ('resource_calendar','hr_job'):
            suffix=' WHERE id=ANY(%s)';params=[calendar_before if table=='resource_calendar' else job_before]
        env.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_data,\'\' ORDER BY row_data),\'\')) FROM (SELECT row_to_json(t)::text row_data FROM "'+table+'" t'+suffix+')s',params)
        out[table]=env.cr.fetchone()
    return out

def source_employee(row):
    links=[env.ref(xmlid) for xmlid in row['employee_xmlids']]
    assert links and len({e.id for e in links})==1
    e=links[0].with_context(active_test=False)
    assert e._name=='hr.employee' and e.company_id.id==row['company_id']
    assert e.name==row['name'] and e.active==row['active']
    assert not e.user_id
    return e.with_company(e.company_id).with_context(allowed_company_ids=[e.company_id.id],
        tracking_disable=True,mail_create_nosubscribe=True,mail_create_nolog=True,salary_simulation=True)

def identity(name,model,record):
    D=env['ir.model.data']; link=D.search([('module','=',MODULE),('name','=',name)])
    if link:
        assert len(link)==1 and link.model==model and link.res_id==record.id
    else:
        D.create({'module':MODULE,'name':name,'model':model,'res_id':record.id,'noupdate':True})

def salary_calendar(company,hours):
    key='salary_basis_'+str(company.id)+'_'+str(hours)
    cal=env.ref(MODULE+'.'+key,raise_if_not_found=False)
    if not cal:
        cal=env['resource.calendar'].with_company(company).create({
            'name':f'حساب الراتب فقط — {hours} ساعة يومياً — الشفتات غير محددة',
            'company_id':company.id,'schedule_type':'flexible','hours_per_day':hours,
            'hours_per_week':0,'attendance_ids':[Command.clear()],
            'global_leave_ids':[Command.clear()],'tz':'Asia/Riyadh'})
        identity(key,'resource.calendar',cal)
    assert cal.company_id==company and cal.flexible_hours
    assert cal.hours_per_day==hours and not cal.hours_per_week
    assert not cal.attendance_ids and not cal.global_leave_ids
    return cal

def job_record(company,title):
    # Exact source titles, no invented translations or occupational categories.
    jobs=env['hr.job'].with_context(active_test=False).search([('company_id','=',company.id),('name','=',title)])
    assert len(jobs)<=1, 'Duplicate existing job definition'
    if jobs:
        assert jobs.active, 'Existing job is archived'
        return jobs
    return env['hr.job'].with_company(company).with_context(tracking_disable=True,mail_create_nolog=True).create({'name':title,'company_id':company.id,'no_of_recruitment':0})

def run_pass():
    changed=[];mapping=[];calids=set();jobids=set()
    # Define the company's missing job titles first, then assign employees.
    job_map={}
    for company_id,title in sorted({(r['company_id'],r['job_title']) for r in PAYLOAD['employees'] if r.get('job_title')}):
        job=job_record(env['res.company'].browse(company_id),title)
        job_map[(company_id,title)]=job
        jobids.add(job.id)
    for row in PAYLOAD['employees']:
        e=source_employee(row)
        assert len(e.version_ids)==1, 'Employee history changed since names import'
        v=e.version_id
        assert not v.contract_date_start and not v.contract_date_end, 'Contract was edited; do not overwrite'
        vals={};salary=row.get('salary')
        if salary:
            assert Decimal(salary['gross'])==Decimal(salary['basic'])+Decimal(salary['allowances'])+Decimal(salary['overtime'])
            assert salary['mode'] in ('fixed','inclusive')
            assert salary['effective_date']<='2026-09-09'
            # Write only untouched HR1 defaults, or verify an exact HR2 replay.
            key='salary_profile_'+salary['identity'].replace('-','_')
            marker=env.ref(MODULE+'.'+key,raise_if_not_found=False)
            desired={'wage':float(salary['gross']),'baseer_allowance_total':float(salary['allowances']),
                     'baseer_salary_mode':salary['mode'],'baseer_work_days':salary['work_days'],
                     'date_version':salary['effective_date']}
            if salary.get('keep_target_calendar'):
                desired['resource_calendar_id']=row['baseline']['calendar_id']
            elif salary['daily_hours']:
                cal=salary_calendar(e.company_id,salary['daily_hours']);calids.add(cal.id)
                desired['resource_calendar_id']=cal.id
            if marker:
                assert marker==v
            else:
                assert not v.wage and not v.baseer_allowance_total and v.baseer_salary_mode=='fixed', 'Salary was manually edited'
                assert v.resource_calendar_id.id==row['baseline']['calendar_id'], 'Schedule changed after planning'
                vals.update(desired)
            if vals:
                v.write(vals)
                identity(key,'hr.version',v)
            for field,value in desired.items():
                actual=v[field]
                if field=='resource_calendar_id':actual=actual.id
                elif field=='date_version':actual=str(actual)
                assert actual==value,(field,'Target differs from reviewed salary')
            assert Decimal(str(e.baseer_basic_salary))==Decimal(salary['basic'])
            assert Decimal(str(e.baseer_overtime_salary))==Decimal(salary['overtime'])
            assert Decimal(str(e.baseer_salary_total))==Decimal(salary['gross'])
            assert Decimal(str(e.baseer_allowance_total))==Decimal(salary['allowances'])
            old='الرواتب والبدلات والعقد وجدول الدوام لم تُنقل؛ مؤجلة حسب طلب المالك.'
            new='نُقلت إعدادات الراتب والبدلات والإضافي من المصدر؛ العقد يحتاج الاستكمال. لم تُنقل شفتات حضور من المصدر.'
            note=e.additional_note or ''
            if old in note:
                note=note.replace(old,new)
                note=note.replace('جدول بانتظار تحديد الدوام مؤقت بلا ساعات عمل؛ ليس جدول الدوام الفعلي.',
                    'حُفظ جدول الدوام الذي عيّنه المستخدم.' if salary.get('keep_target_calendar') else 'ساعات الجدول أساس حساب الراتب فقط؛ أوقات الشفتات غير محددة.')
                e.write({'additional_note':note});vals['note']=True
            assert new in (e.additional_note or '')
        title=row.get('job_title')
        if title:
            job=job_map[(e.company_id.id,title)]
            if e.job_id!=job or e.job_title!=title:
                assert not e.job_id and not e.job_title, 'Job was manually edited'
                e.write({'job_id':job.id,'job_title':title})
                vals['job_id']=job.id
            assert e.job_id==job and e.job_title==title
        if vals:changed.append(e.id)
        assert e.active==row['active'] and e.company_id.id==row['company_id']
        assert not e.contract_date_start and not e.contract_date_end
        mapping.append({'employee_id':e.id,'company_id':e.company_id.id,'active':e.active,
                        'salary':bool(salary),'job':bool(title)})
    return changed,mapping,calids,jobids

before=protected()
admin=env['hr.employee'].browse(1).read(['name','version_id','resource_calendar_id','baseer_salary_total','job_id','job_title'])
try:
    # Pin the actual target after the owner edited schedules during planning.
    # Run once before any mutation; the second import pass tests idempotence.
    for row in PAYLOAD['employees']:
        e=source_employee(row);v=e.version_id;c=v.resource_calendar_id;b=row['baseline']
        assert v.id==b['version_id'] and str(v.date_version)==b['date_version']
        assert str(v.write_date)==b['version_write_date'] and str(e.write_date)==b['employee_write_date'], 'Employee changed after planning'
        assert c.id==b['calendar_id'] and str(c.write_date)==b['calendar_write_date'] and c.hours_per_day==b['hours'], 'Calendar changed after planning'
        assert e.job_id.id==b['job_id'] and (e.job_title or False)==b['job_title']
        assert (e.additional_note or '')==b['note']
    changed,mapping,cals,jobs=run_pass()
    second,mapping2,cals2,jobs2=run_pass()
    assert not second and mapping2==mapping and cals2==cals and jobs2==jobs
    assert set(env['resource.calendar'].with_context(active_test=False).search([]).ids)-set(calendar_before)==cals-set(calendar_before)
    assert set(env['hr.job'].with_context(active_test=False).search([]).ids)-set(job_before)==jobs-set(job_before)
    assert env['hr.employee'].with_context(active_test=False).search([]).ids==employee_before
    assert set(env['hr.version'].with_context(active_test=False).search([]).ids)==set(version_before)
    assert before==protected(), 'Protected financial/operational data changed'
    assert admin==env['hr.employee'].browse(1).read(['name','version_id','resource_calendar_id','baseer_salary_total','job_id','job_title'])
    result={'scope':PAYLOAD['scope'],'mode':'committed' if COMMIT else 'rollback','employees_changed':len(changed),
        'salaries':sum(m['salary'] for m in mapping),'jobs':sum(m['job'] for m in mapping),
        'salary_basis_calendars':len(cals),'job_definitions':len(jobs),
        'protected_tables':len(before),'idempotent_second_pass':True,'administrator_unchanged':True,
        'totals':PAYLOAD['totals'],'missing':PAYLOAD['missing'],'mapping':mapping}
    if COMMIT:env.cr.commit()
    else:env.cr.rollback()
    print('HR2_RESULT='+json.dumps(result,ensure_ascii=False))
except Exception:
    env.cr.rollback()
    raise
