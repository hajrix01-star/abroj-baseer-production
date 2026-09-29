"""WS4 native acceptance. QA database only; every fixture write rolls back."""
import json
import time
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError

R = {'checks': [], 'database': env.cr.dbname}


def check(name, condition):
    R['checks'].append({'name': name, 'passed': bool(condition)})
    assert condition, name


def blocked(name, fn):
    try:
        with env.cr.savepoint():
            fn()
            env.flush_all()
    except (AccessError, UserError, ValidationError) as exc:
        check(name, True)
        R.setdefault('rejection_messages', {})[name] = str(exc)
    else:
        check(name, False)


def template(label='template'):
    w = E['baseer.schedule.wizard'].create({
        'name': 'WS4 ' + label + ' ' + token, 'company_id': company.id,
        'day_ids': [(6, 0, E['baseer.schedule.day'].search([('weekday', 'in', list(range(5)))]).ids)],
        'period_ids': [(0, 0, {'time_from': '08:00', 'time_to': '16:00'})],
    })
    w.action_apply()
    return w.applied_calendar_id


def edit(source, effective=None, actor=None, end=None):
    actor = actor or E
    action = source.with_env(actor).action_baseer_edit_schedule()
    w = actor['baseer.schedule.wizard'].with_context(action['context']).create({
        'effective_date': effective or future})
    if end:
        w.write({'period_ids': [(5, 0, 0), (0, 0, {'time_from': '08:00', 'time_to': end})]})
    return w


def employee(label, calendar, mode='fixed', active=True):
    emp = E['hr.employee'].create({'name': 'WS4 ' + label + ' ' + token, 'company_id': company.id})
    emp.version_id.write({'date_version': past, 'contract_date_start': past,
        'resource_calendar_id': calendar.id, 'wage': 3000, 'baseer_salary_mode': mode,
        'baseer_work_days': 30, 'baseer_allowance_total': 0})
    emp.baseer_payroll_enabled = True
    if not active:
        emp.active = False
    return emp


def snapshot(table, ids):
    assert table in ('resource_calendar_attendance', 'hr_attendance', 'hr_leave', 'resource_calendar_leaves')
    env.flush_all()
    env.cr.execute('SELECT row_to_json(t) FROM ' + table + ' t WHERE id=ANY(%s) ORDER BY id', [ids])
    return env.cr.fetchall()


def counts():
    return (E['resource.calendar'].with_context(active_test=False).search_count([]),
            E['hr.version'].with_context(active_test=False).search_count([]))


try:
    assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA database required'
    token = uuid.uuid4().hex[:8]
    company = env['res.company'].browse(10).exists()
    assert company, 'QA company 10 required'
    E = env(user=env.ref('base.user_admin').id,
            context={'allowed_company_ids': company.ids, 'tracking_disable': True, 'lang': 'en_US'}, su=False)
    today = fields.Date.today()
    future = today.replace(day=1) + relativedelta(months=2)
    past = today.replace(day=1) - relativedelta(months=3)
    source = template()
    other = template('same-name independent')
    other.name = source.name
    a, b = employee('linked A', source), employee('linked B', source)
    archived = employee('archived', source, active=False)
    unrelated = employee('same name independent', other)
    private = employee('private copy', source)
    copy_wizard = E['baseer.schedule.wizard'].create({'employee_id': private.id, 'company_id': company.id,
        'source_calendar_id': source.id, 'effective_date': today})
    copy_wizard._onchange_source_calendar()
    copy_wizard.action_apply()
    private_calendar = copy_wizard.applied_calendar_id
    private_version_ids = private.version_ids.ids
    check('private fixture is a native employee copy', private_calendar != source and not private_calendar.baseer_is_template)
    old_versions = a.version_id | b.version_id
    old_values = old_versions.read(['date_version', 'resource_calendar_id', 'wage',
        'baseer_salary_mode', 'baseer_allowance_total', 'baseer_work_days'])
    old_rows = snapshot('resource_calendar_attendance', source.attendance_ids.ids)
    old_day = past + timedelta(days=(7 - past.weekday()) % 7)
    hist_att = E['hr.attendance'].create({'employee_id': a.id,
        'check_in': datetime.combine(old_day, datetime.min.time()) + timedelta(hours=8),
        'check_out': datetime.combine(old_day, datetime.min.time()) + timedelta(hours=16)})
    hist_att_before = snapshot('hr_attendance', hist_att.ids)
    leave_type = E['hr.leave.type'].create({'name': 'WS4 leave ' + token, 'requires_allocation': False,
        'leave_validation_type': 'no_validation', 'company_id': company.id, 'create_calendar_meeting': False})
    leave = E['hr.leave'].create({'name': 'WS4 historical', 'employee_id': b.id,
        'holiday_status_id': leave_type.id, 'request_date_from': old_day, 'request_date_to': old_day})
    leave_rows = E['resource.calendar.leaves'].search([('holiday_id', '=', leave.id)])
    check('native historical leave approved with resource intervals', leave.state == 'validate' and bool(leave_rows))
    leave_before = snapshot('hr_leave', leave.ids)
    leave_rows_before = snapshot('resource_calendar_leaves', leave_rows.ids)
    holiday = E['resource.calendar.leaves'].create({'name': 'WS4 holiday ' + token,
        'calendar_id': source.id, 'date_from': datetime(2030, 1, 7), 'date_to': datetime(2030, 1, 8), 'time_type': 'leave'})
    w = edit(source, end='18:00')
    check('edit action populates locked source and revision', w.edit_template and w.source_calendar_id == source and bool(w.template_revision))
    check('edit preserves visible source name', w.name == source.name)
    check('edit preloads five weekdays', set(w.day_ids.mapped('weekday')) == set(range(5)))
    check('affected scope contains exact active direct assignments', w.affected_count == 2 and set(w.affected_employee_ids.ids) == {a.id, b.id})
    stale = edit(source)
    w.action_apply()
    replacement = w.applied_calendar_id
    check('same-name replacement is a distinct native template', replacement != source and replacement.name == source.name and replacement.baseer_is_template)
    check('source retained active but hidden from templates', source.active and not source.baseer_is_template and source.baseer_superseded_by_id == replacement)
    check('replacement effective date recorded', replacement.baseer_effective_date == future)
    check('all direct employees receive native effective versions', all(e._get_version(future).resource_calendar_id == replacement for e in (a, b)))
    check('future revision does not change present assignments', a.resource_calendar_id == source and b.resource_calendar_id == source)
    check('historical native employee versions unchanged', old_versions.read(['date_version', 'resource_calendar_id', 'wage', 'baseer_salary_mode', 'baseer_allowance_total', 'baseer_work_days']) == old_values)
    check('source attendance rows byte-identical', snapshot('resource_calendar_attendance', source.attendance_ids.ids) == old_rows)
    check('historical actual attendance byte-identical', snapshot('hr_attendance', hist_att.ids) == hist_att_before)
    check('historical approved leave byte-identical', snapshot('hr_leave', leave.ids) == leave_before)
    check('historical resource leave byte-identical', snapshot('resource_calendar_leaves', leave_rows.ids) == leave_rows_before)
    check('archived employee remains on source with one version', len(archived.version_ids) == 1 and archived.version_id.resource_calendar_id == source)
    check('same-name independent template remains unchanged', other.baseer_is_template and len(unrelated.version_ids) == 1 and unrelated.resource_calendar_id == other)
    check('actual private employee copy remains independent', private.version_ids.ids == private_version_ids and private.resource_calendar_id == private_calendar)
    copied_holidays = replacement.global_leave_ids.filtered(lambda r: not r.resource_id)
    check('only global holidays copied with original dates', len(copied_holidays) == 1 and copied_holidays.date_from == holiday.date_from and copied_holidays.date_to == holiday.date_to and not copied_holidays.holiday_id)
    lines = E['hr.payslip'].get_worked_day_lines(old_versions.filtered(lambda v: v.employee_id == a), old_day, old_day + timedelta(days=6))
    work = [line for line in lines if line['code'] == 'WORK100']
    check('native historical payroll still consumes 40-hour week', len(work) == 1 and abs(work[0]['number_of_hours'] - 40) < 1e-6)
    before = counts()
    w.action_apply()
    check('same wizard apply is idempotent', counts() == before and w.applied_calendar_id == replacement)
    blocked('second open template edit rejected', stale.action_apply)
    blocked('superseded source cannot be edited again', lambda: edit(source).action_apply())
    blocked('future replacement cannot be applied prematurely', lambda: private.create_version({'date_version': future - timedelta(days=1), 'resource_calendar_id': replacement.id}))
    blocked('superseded source cannot gain assignments on effective date', lambda: private.create_version({'date_version': future, 'resource_calendar_id': source.id}))
    blocked('replacement cannot be edited before its effective date', lambda: edit(replacement, future - timedelta(days=1)).action_apply())

    for field, value in (('baseer_superseded_by_id', other.id), ('baseer_effective_date', future)):
        blocked('RPC cannot write revision field ' + field, lambda field=field, value=value: other.write({field: value}))
        blocked('RPC cannot create revision field ' + field, lambda field=field, value=value: E['resource.calendar'].create({'name': 'WS4 forged', 'company_id': company.id, field: value}))
        blocked('RPC context cannot default revision field ' + field, lambda field=field, value=value: E['resource.calendar'].with_context(**{'default_' + field: value}).create({'name': 'WS4 forged', 'company_id': company.id}))
    blocked('source attendance mutation rejected', lambda: source.attendance_ids[:1].write({'hour_to': 20}))
    blocked('referenced historical source cannot be deleted', source.unlink)
    fresh = template('tamper')
    untouched = template('other source')
    for vals, label in (({'source_calendar_id': untouched.id}, 'source'), ({'employee_id': private.id}, 'employee'), ({'name': 'tampered'}, 'name')):
        blocked('edit cannot tamper with ' + label, lambda vals=vals: edit(fresh).write(vals))
    blocked('forged stale revision rejected', lambda: E['baseer.schedule.wizard'].create({'name': fresh.name, 'company_id': company.id,
        'edit_template': True, 'source_calendar_id': fresh.id, 'template_revision': 'forged', 'effective_date': future}).action_apply())
    blocked('direct create cannot rename edited source', lambda: E['baseer.schedule.wizard'].create({'name': 'tampered', 'company_id': company.id,
        'edit_template': True, 'source_calendar_id': fresh.id, 'effective_date': future}).action_apply())
    blocked('past template effective date rejected', lambda: edit(fresh, today - timedelta(days=1)).action_apply())

    future_source = template('future conflict')
    future_emp = employee('future conflict', future_source)
    future_emp.create_version({'date_version': future + timedelta(days=1), 'resource_calendar_id': untouched.id})
    before = counts()
    blocked('existing future employee choice rejects full fanout', lambda: edit(future_source).action_apply())
    check('future conflict creates no calendar or version', counts() == before and not future_source.baseer_superseded_by_id)
    for model, label in (('hr.attendance', 'attendance'), ('hr.leave', 'leave')):
        conflict_source = template(label + ' conflict')
        clean_emp = employee(label + ' first clean employee', conflict_source)
        conflict_emp = employee(label + ' conflicting employee', conflict_source)
        event_day = future + timedelta(days=(7 - future.weekday()) % 7)
        if model == 'hr.attendance':
            E[model].create({'employee_id': conflict_emp.id, 'check_in': datetime.combine(event_day, datetime.min.time()) + timedelta(hours=8),
                'check_out': datetime.combine(event_day, datetime.min.time()) + timedelta(hours=16)})
        else:
            E[model].create({'name': 'WS4 conflict', 'employee_id': conflict_emp.id, 'holiday_status_id': leave_type.id,
                'request_date_from': event_day, 'request_date_to': event_day})
        before = counts()
        blocked('one employee ' + label + ' conflict rejects entire edit', lambda: edit(conflict_source).action_apply())
        check(label + ' rejection leaves no partial fanout', counts() == before and len(clean_emp.version_ids) == 1 and not conflict_source.baseer_superseded_by_id)
    inclusive_source = template('inclusive')
    inclusive = employee('inclusive', inclusive_source, mode='inclusive')
    before = counts()
    blocked('inclusive salary split change midmonth rejected', lambda: edit(inclusive_source, future.replace(day=15), end='18:00').action_apply())
    check('salary guard rolls back whole edit', counts() == before and not inclusive_source.baseer_superseded_by_id)
    edit(inclusive_source, future, end='18:00').action_apply()
    check('inclusive salary split change accepted first of month', inclusive._get_version(future).resource_calendar_id.hours_per_day == 10)
    tomorrow_source = template('tomorrow')
    tomorrow_emp = employee('tomorrow fixed', tomorrow_source)
    edit(tomorrow_source, today + timedelta(days=1), end='18:00').action_apply()
    check('fixed payroll tomorrow edit preserves prior day', tomorrow_emp._get_version(today).resource_calendar_id == tomorrow_source and tomorrow_emp._get_version(today + timedelta(days=1)).resource_calendar_id.hours_per_day == 10)

    hr_user = E['res.users'].create({'name': 'WS4 HR ' + token, 'login': 'ws4-hr-' + token,
        'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [E.ref('hr.group_hr_manager').id])]})
    H = env(user=hr_user.id, context={'allowed_company_ids': company.ids}, su=False)
    check('HR manager fixture has no payroll manager role', not hr_user.has_group('om_hr_payroll.group_hr_payroll_manager'))
    hr_source = template('HR access')
    hr_employee = employee('HR access', hr_source)
    edit(hr_source, actor=H).action_apply()
    check('HR manager can fan out without payroll manager role', hr_employee._get_version(future).resource_calendar_id != hr_source)
    basic = E['res.users'].create({'name': 'WS4 basic ' + token, 'login': 'ws4-basic-' + token,
        'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [E.ref('base.group_user').id])]})
    U = env(user=basic.id, context={'allowed_company_ids': company.ids}, su=False)
    blocked('ordinary user cannot open template edit', lambda: fresh.with_env(U).action_baseer_edit_schedule())
    blocked('ordinary user cannot forge direct edit wizard', lambda: U['baseer.schedule.wizard'].create({'name': fresh.name, 'edit_template': True, 'source_calendar_id': fresh.id}).action_apply())
    foreign_company = env['res.company'].search([('id', '!=', company.id)], limit=1)
    assert foreign_company
    foreign = env['resource.calendar'].sudo().with_company(foreign_company).create({'name': 'WS4 foreign ' + token,
        'company_id': foreign_company.id, 'baseer_is_template': True})
    blocked('foreign company edit rejected server-side', lambda: edit(foreign, actor=H).action_apply())

    load_source = template('load50')
    load_employees = E['hr.employee']
    for i in range(50):
        load_employees |= employee('load50 %03d' % i, load_source)
    load_w = edit(load_source, end='18:00')
    check('load preview lists all 50 employees', load_w.affected_count == 50)
    started = time.monotonic()
    load_w.action_apply()
    R['load_50_apply_seconds'] = round(time.monotonic() - started, 4)
    check('50 employee atomic edit below ten seconds on QA', R['load_50_apply_seconds'] < 10)
    check('all 50 receive exactly one dated revision', all(len(e.version_ids) == 2 and e._get_version(future).resource_calendar_id == load_w.applied_calendar_id for e in load_employees))
    cap_source = template('cap201')
    # Inactive and historical references count toward the limit, even with no active fanout.
    for i in range(201):
        employee('cap %03d' % i, cap_source, active=False)
    before = counts()
    blocked('201 inactive candidates exceed total membership cap', lambda: edit(cap_source).action_apply())
    check('candidate cap rejection has no partial fanout', counts() == before and not cap_source.baseer_superseded_by_id)
    R['status'] = 'passed'
except Exception:
    R['status'] = 'failed'
    R['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    R['rolled_back'] = True
    Path('/mnt/qa-evidence/ws4_checks.json').write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False, indent=2))

assert R['status'] == 'passed', R.get('error')
