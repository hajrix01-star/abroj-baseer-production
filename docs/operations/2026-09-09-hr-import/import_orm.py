"""HR1 names-only native ORM writer. PAYLOAD/COMMIT injected by local driver.

No application source, salary, accounting, contract or schedule migration.
All identity data stays in private local evidence, never in seeded addons.
"""
import hashlib
import json
from collections import Counter
from odoo import fields, Command

assert env.cr.dbname == 'baseer_dev'
assert PAYLOAD['scope'] == 'names_only'
assert PAYLOAD['source_sha256'] == 'a8eda338b31b9947ab69ff275c75f39cd7c5cb3d9922e46309564a8017e8ce13'
MODULE = 'baseer_legacy_hr_import'
company_map = PAYLOAD['companies']
employees = PAYLOAD['employees']
assert len({e['id'] for e in employees}) == len(employees)
assert len(employees) <= 51
assert all(e['status'] in ('ACTIVE','ON_LEAVE','TERMINATED','ARCHIVED') for e in employees)
env.cr.execute("SELECT pg_advisory_xact_lock(19420909, 1)")

calendar_before_ids = env['resource.calendar'].with_context(active_test=False).search([]).ids

def signatures():
    # Exact row hashes for operational/financial objects and existing employee.
    env.flush_all()
    env.cr.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'account_%' OR tablename LIKE 'baseer_%' OR tablename LIKE 'hr_payslip%' OR tablename LIKE 'hr_leave%' OR tablename LIKE 'hr_attendance%' OR tablename LIKE 'hr_work_entry%' OR tablename LIKE 'resource_calendar%' OR tablename IN ('res_company','res_users')) ORDER BY tablename")
    result = {}
    for (table,) in env.cr.fetchall():
        assert table.replace('_','').isalnum()
        if table == 'resource_calendar':
            env.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_data,\'\' ORDER BY row_data),\'\')) FROM (SELECT row_to_json(t)::text row_data FROM resource_calendar t WHERE id = ANY(%s))s', [calendar_before_ids])
        else:
            env.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_data,\'\' ORDER BY row_data),\'\')) FROM (SELECT row_to_json(t)::text row_data FROM "'+table+'" t)s')
        result[table] = env.cr.fetchone()
    return result

def administrative_note(row):
    states={'ACTIVE':'نشط','ON_LEAVE':'في إجازة بالمصدر؛ لم تُنقل فترة إجازة','TERMINATED':'منتهي الخدمة في المصدر','ARCHIVED':'مؤرشف في المصدر'}
    return '\n'.join([
        'ترحيل أسماء الموظفين من بصير القديم — HR1',
        'أرقام الموظف في المصدر: '+', '.join(r['employeeNumber'] for r in row['source_records']),
        'الاسم الإنجليزي: '+(row['nameEn'] or 'غير متوفر'),
        'حالات المصدر: '+'؛ '.join(states[r['status']] for r in row['source_records']),
        'معرفات المصدر: '+', '.join(r['id'] for r in row['source_records']),
        'الرواتب والبدلات والعقد وجدول الدوام لم تُنقل؛ مؤجلة حسب طلب المالك.',
        'جدول بانتظار تحديد الدوام مؤقت بلا ساعات عمل؛ ليس جدول الدوام الفعلي.',
    ])

def pending_calendar(company):
    D=env['ir.model.data']
    key='pending_schedule_company_'+str(company.id)
    link=D.search([('module','=',MODULE),('name','=',key)])
    if link:
        assert len(link)==1 and link.model=='resource.calendar'
        cal=env['resource.calendar'].browse(link.res_id).exists()
        assert cal and cal.company_id==company
    else:
        cal=env['resource.calendar'].with_company(company).create({
            'name':'بانتظار تحديد الدوام', 'company_id':company.id,
            'schedule_type':'flexible', 'hours_per_day':0, 'hours_per_week':0,
            'attendance_ids':[Command.clear()], 'global_leave_ids':[Command.clear()],
            'tz':'Asia/Riyadh'})
        D.create({'module':MODULE,'name':key,'model':'resource.calendar','res_id':cal.id,'noupdate':True})
    assert cal.flexible_hours and not cal.hours_per_day and not cal.hours_per_week
    assert not cal.attendance_ids and not cal.global_leave_ids
    return cal

def import_pass():
    created=[]
    mapping=[]
    for row in employees:
        target=company_map[row['companyId']]
        company=env['res.company'].browse(target['id']).exists()
        assert company and company.name == target['target_name']
        assert company.currency_id.name == 'SAR'
        context=dict(allowed_company_ids=[company.id], active_test=False,
                     tracking_disable=True, mail_create_nosubscribe=True,
                     mail_create_nolog=True, salary_simulation=True)
        # Native import context skips generated avatars/onboarding and unrelated
        # simulation hooks (leave manager/work entries). These new bare profiles
        # have no manager, contract or wages. Model validation still applies.
        E=env['hr.employee'].with_company(company).with_context(**context)
        D=env['ir.model.data']
        key='employee_'+row['companyId'].replace('-','')+'_'+row['id'].replace('-','')
        identity=D.search([('module','=',MODULE),('name','=',key)])
        active=row['status'] in ('ACTIVE','ON_LEAVE')
        note=administrative_note(row)
        cal=pending_calendar(company)
        if identity:
            assert len(identity)==1 and identity.model=='hr.employee'
            employee=E.browse(identity.res_id).exists()
            assert employee and employee.company_id==company
        else:
            matches=E.search([('company_id','=',company.id),('name','=',row['nameAr'])])
            assert not matches, 'Unmapped existing employee has the same company/name'
            employee=E.create({'name':row['nameAr'],'company_id':company.id,
                'active':active, 'resource_calendar_id':cal.id,
                'baseer_payroll_enabled':active,
                'contract_date_start':False,'contract_date_end':False,
                'additional_note':note, 'tz':'Asia/Riyadh'})
            for source_row in row['source_records']:
                alias='employee_'+row['companyId'].replace('-','')+'_'+source_row['id'].replace('-','')
                assert not D.search_count([('module','=',MODULE),('name','=',alias)])
                D.create({'module':MODULE,'name':alias,'model':'hr.employee',
                          'res_id':employee.id,'noupdate':True})
            created.append(employee.id)
        assert employee.name==row['nameAr'] and employee.active==active
        assert employee.additional_note==note
        assert not employee.user_id
        assert employee.baseer_payroll_enabled==active
        assert employee.resource_calendar_id==cal and employee.resource_id.calendar_id==cal
        assert not employee.contract_date_start and not employee.contract_date_end
        assert employee.baseer_salary_total==0 and employee.baseer_allowance_total==0
        assert employee.resource_id.company_id==company
        assert employee.version_id.company_id==company
        assert employee.work_contact_id
        for source_row in row['source_records']:
            alias='employee_'+row['companyId'].replace('-','')+'_'+source_row['id'].replace('-','')
            link=D.search([('module','=',MODULE),('name','=',alias)])
            assert len(link)==1 and link.model=='hr.employee' and link.res_id==employee.id
            mapping.append({'source_id':source_row['id'],'source_company':row['companyId'],
                'employee_number':source_row['employeeNumber'],'target_id':employee.id,
                'target_company_id':company.id,'active':active,'xmlid':MODULE+'.'+alias})
    return created,mapping

before=signatures()
original=env['hr.employee'].browse(1).read(['name','company_id','active','version_id','resource_calendar_id','baseer_salary_total','baseer_allowance_total'])
try:
    created,mapping=import_pass()
    repeated,repeated_mapping=import_pass()
    assert not repeated and repeated_mapping==mapping
    placeholder_ids={env.ref(MODULE+'.pending_schedule_company_'+str(c)).id for c in (1,2,3)}
    assert len(placeholder_ids)==3
    new_calendar_ids=set(env['resource.calendar'].with_context(active_test=False).search([]).ids)-set(calendar_before_ids)
    assert new_calendar_ids==placeholder_ids-set(calendar_before_ids)
    after=signatures()
    assert before==after, 'Protected operational/financial data changed'
    assert original==env['hr.employee'].browse(1).read(['name','company_id','active','version_id','resource_calendar_id','baseer_salary_total','baseer_allowance_total'])
    assert env['hr.employee'].with_context(active_test=False).search_count([])==1+len(employees)
    result={'mode':'committed' if COMMIT else 'rollback','scope':'names_only',
        'source_sha256':PAYLOAD['source_sha256'],'created_count':len(created),
        'matched_count':len(mapping),'idempotent_second_pass':True,
        'protected_tables_unchanged':len(before),'administrator_unchanged':True,
        'by_company':{str(c):{'active':len({m['target_id'] for m in mapping if m['target_company_id']==c and m['active']}),
                             'archived':len({m['target_id'] for m in mapping if m['target_company_id']==c and not m['active']})} for c in (1,2,3)},
        'salary_contract_schedule_deferred':True,'placeholder_calendars':len(placeholder_ids),
        'new_calendars':len(new_calendar_ids),'mapping':mapping}
    if COMMIT:
        env.cr.commit()
    else:
        env.cr.rollback()
    print('HR1_RESULT='+json.dumps(result,ensure_ascii=False,default=str))
except Exception:
    env.cr.rollback()
    raise
