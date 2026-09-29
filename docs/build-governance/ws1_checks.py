"""WS1 acceptance in Odoo shell on QA only. All database writes roll back.

Exercise the public wizard and native consumers; no production fixture changes.
Run after installing baseer_work_schedule. Result persists outside the database.
"""
import json
import time
import traceback
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytz
from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError

R = {'checks': [], 'apply_seconds': []}


def check(name, condition):
    R['checks'].append({'name': name, 'passed': bool(condition)})
    assert condition, name


def blocked(name, fn):
    """Only expected access/business errors count as a correct rejection."""
    try:
        with env.cr.savepoint():
            fn()
            env.flush_all()
    except (AccessError, UserError, ValidationError) as exc:
        check(name, True)
        R.setdefault('rejection_messages', {})[name] = str(exc)
    else:
        check(name, False)


def days(numbers):
    return [E.ref('baseer_work_schedule.day_%s' % d).id for d in numbers]


def wizard(day_numbers=(0, 1, 2, 3, 4), periods=(('08:00', '16:00'),),
           employee=None, effective=None, source=None, environment=None):
    actor = environment or E
    vals = {'name': 'WS1 ' + token, 'company_id': company.id}
    if employee:
        vals.update(employee_id=employee.id, effective_date=effective or future)
    if source:
        vals['source_calendar_id'] = source.id
    w = actor['baseer.schedule.wizard'].create(vals)
    if employee:
        w._onchange_employee_date()
    if source:
        w._onchange_source_calendar()
        return w
    lines = []
    for period in periods:
        line = {'time_from': period[0], 'time_to': period[1]}
        if len(period) == 3:
            line.update(custom_days=True, day_ids=[(6, 0, days(period[2]))])
        lines.append((0, 0, line))
    w.write({'day_ids': [(6, 0, days(day_numbers))],
             'period_ids': [(5, 0, 0)] + lines})
    return w


def apply(w):
    started = time.monotonic()
    w.action_apply()
    R['apply_seconds'].append(round(time.monotonic() - started, 4))
    check('wizard returns a native calendar ' + str(w.id), bool(w.applied_calendar_id))
    return w.applied_calendar_id


def employee(name, calendar, mode='fixed'):
    emp = E['hr.employee'].create({'name': 'WS1 ' + name + ' ' + token,
                                  'company_id': company.id})
    emp.version_id.write({'date_version': past, 'contract_date_start': past,
                          'resource_calendar_id': calendar.id, 'wage': 3000,
                          'baseer_salary_mode': mode, 'baseer_work_days': 30,
                          'baseer_allowance_total': 0})
    emp.baseer_payroll_enabled = True
    return emp


def snapshot(table, ids):
    env.flush_all()
    assert table in ('hr_leave', 'resource_calendar_leaves')
    env.cr.execute('SELECT row_to_json(t) FROM ' + table + ' t WHERE id=ANY(%s) ORDER BY id', [ids])
    return env.cr.fetchall()


def week_duration(calendar, monday):
    tz = pytz.timezone(calendar.tz)
    start = tz.localize(datetime.combine(monday, datetime.min.time()))
    end = tz.localize(datetime.combine(monday + timedelta(days=7), datetime.min.time()))
    return calendar.get_work_duration_data(start, end, compute_leaves=False)


try:
    assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA database required'
    token = uuid.uuid4().hex[:8]
    company = env['res.company'].browse(10).exists()
    assert company, 'QA company 10 required'
    E = env(user=env.ref('base.user_admin').id,
            context={'allowed_company_ids': company.ids, 'tracking_disable': True}, su=False)
    today = fields.Date.today()
    future = today.replace(day=1) + relativedelta(months=2)
    midmonth = future.replace(day=15)
    past = today.replace(day=1) - relativedelta(months=3)
    monday = date(2030, 1, 7)

    # Exact minutes, gaps, three periods, native duration/day consumption.
    minute_cal = apply(wizard((0, 1, 2), (('08:10', '12:25'), ('13:05', '16:50'))))
    check('split periods preserve 480 minutes daily', abs(minute_cal.hours_per_day - 8) < 1e-9)
    check('split periods preserve 1440 minutes weekly', abs(minute_cal.hours_per_week - 24) < 1e-9)
    check('six native intervals represent three selected days', len(minute_cal.attendance_ids) == 6)
    data = week_duration(minute_cal, monday)
    check('native duration agrees with three days and 24 hours', abs(data['hours'] - 24) < 1e-9 and abs(data['days'] - 3) < 1e-9)
    three = apply(wizard((0,), (('08:00', '10:00'), ('10:30', '12:30'), ('13:00', '17:00'))))
    check('three daily periods preserve eight hours', len(three.attendance_ids) == 3 and three.hours_per_day == 8)
    all_day = wizard((0,), (('00:00', '24:00'),))
    check('24 hour period preview displays 24:00', all_day.period_ids.duration_label == '24:00' and all_day.total_label == '24:00')
    all_day_cal = apply(all_day)
    check('24 hour period native duration remains 24 hours', all_day_cal.hours_per_day == 24 and all_day_cal.hours_per_week == 24)
    custom = apply(wizard((0, 1), (('08:00', '16:00'), ('09:15', '13:45', (5,)))))
    check('custom day group contributes 270 minutes', abs(custom.hours_per_week - 20.5) < 1e-9)
    check('custom day group uses selected weekdays', set(custom.attendance_ids.mapped('dayofweek')) == {'0', '1', '5'})

    for title, ds, ps in [
        ('overlap on same day', (0,), (('08:00', '12:00'), ('11:00', '16:00'))),
        ('duplicate interval', (0,), (('08:00', '12:00'), ('08:00', '12:00'))),
        ('week wrap overlap', (6,), (('22:00', '06:00'), ('05:00', '07:00', (0,)))),
        ('zero length', (0,), (('08:00', '08:00'),)),
        ('invalid minute', (0,), (('08:60', '16:00'),)),
        ('invalid hour', (0,), (('25:00', '16:00'),)),
        ('decimal input', (0,), (('8.5', '16:00'),)),
        ('missing days', (), (('08:00', '16:00'),)),
        ('missing custom days', (0,), (('08:00', '16:00', ()),)),
        ('missing periods', (0,), ()),
    ]:
        blocked(title, lambda ds=ds, ps=ps: wizard(ds, ps).action_apply())
    touching = apply(wizard((0,), (('08:00', '12:00'), ('12:00', '16:00'))))
    check('adjacent periods are valid', touching.hours_per_day == 8)

    for day, title in ((0, 'Monday'), (6, 'Sunday wrap')):
        night = apply(wizard((day,), (('22:00', '06:00'),)))
        rows = night.attendance_ids
        check(title + ' splits at midnight', len(rows) == 2 and set(rows.mapped('dayofweek')) == {str(day), str((day + 1) % 7)})
        check(title + ' maintains eight hour average', night.hours_per_day == 8 and night.hours_per_week == 8)
        check(title + ' native row day weights sum to one', abs(sum(rows.mapped('duration_days')) - 1) < 1e-9)
        data = week_duration(night, monday)
        check(title + ' native weekly duration eight hours one day', abs(data['hours'] - 8) < 1e-9 and abs(data['days'] - 1) < 1e-9)

    template_w = wizard()
    template = apply(template_w)
    original_rows = template.attendance_ids.read(['dayofweek', 'hour_from', 'hour_to', 'duration_days'])
    copied = apply(wizard(source=template))
    check('editing template creates an independent native template', copied != template and copied.attendance_ids != template.attendance_ids)
    check('source template untouched by copy', original_rows == template.attendance_ids.read(['dayofweek', 'hour_from', 'hour_to', 'duration_days']))
    before_count = E['resource.calendar'].search_count([])
    template_w.action_apply()
    check('repeated apply is idempotent', template_w.applied_calendar_id == template and before_count == E['resource.calendar'].search_count([]))
    blocked('generated calendar hours mutation denied', lambda: template.write({'hours_per_day': 12}))
    blocked('generated attendance write denied', lambda: template.attendance_ids[:1].write({'hour_to': 18}))
    blocked('generated attendance deletion denied', lambda: template.attendance_ids[:1].unlink())
    blocked('generated attendance insertion denied', lambda: E['resource.calendar.attendance'].create({
        'name': 'Injected', 'calendar_id': template.id, 'dayofweek': '5',
        'day_period': 'morning', 'hour_from': 8, 'hour_to': 16}))
    blocked('RPC cannot forge generated calendar marker', lambda: E['resource.calendar'].create({
        'name': 'WS1 forged ' + token, 'company_id': company.id, 'baseer_simple': True}))
    blocked('RPC context cannot default generated calendar marker', lambda: E['resource.calendar'].with_context(
        default_baseer_simple=True).create({'name': 'WS1 forged default ' + token, 'company_id': company.id}))
    blocked('RPC boolean cannot impersonate internal schedule token', lambda: E['resource.calendar'].with_context(
        default_baseer_simple=True, _baseer_schedule_change=True).create({'name': 'WS1 forged token ' + token, 'company_id': company.id}))

    a = employee('A', template)
    b = employee('B', template)
    old = a.version_id
    b_version = b.version_id
    forged_version = {'employee_id': b.id, 'date_version': future + relativedelta(months=3),
        'contract_date_start': past, 'resource_calendar_id': template.id, 'wage': 3000,
        'baseer_salary_mode': 'fixed', 'baseer_work_days': 30}
    blocked('RPC cannot create payroll schedule version marker', lambda: E['hr.version'].create(
        dict(forged_version, baseer_schedule_version=True)))
    blocked('RPC context cannot default payroll schedule version marker', lambda: E['hr.version'].with_context(
        default_baseer_schedule_version=True).create(dict(forged_version)))
    blocked('RPC cannot mark existing version as schedule-only', lambda: b_version.write({'baseer_schedule_version': True}))
    private_w = wizard(employee=a, source=template, effective=future)
    private = apply(private_w)
    new = a._get_version(future)
    check('employee receives independent calendar', private != template and new.resource_calendar_id == private)
    check('history remains original native calendar', a._get_version(future - timedelta(days=1)) == old and old.resource_calendar_id == template)
    check('another employee remains unchanged', b.version_id == b_version and b.resource_calendar_id == template)
    check('future schedule does not become current early', a.resource_calendar_id == template)
    check('effective dated native employee context reads future schedule', a.with_context(version_id=new.id).resource_calendar_id == private)
    blocked('generated calendar deletion cannot remove employee history', private.unlink)
    check('employee history remains after rejected calendar deletion', new.exists() and new.resource_calendar_id == private and private.exists())
    blocked('existing effective date rejected', lambda: wizard(employee=a, effective=future).action_apply())
    blocked('past effective date rejected', lambda: wizard(employee=a, effective=today - timedelta(days=1)).action_apply())

    initial_emp = E['hr.employee'].create({'name': 'WS1 initial ' + token, 'company_id': company.id})
    initial_version = initial_emp.version_id
    initial_version.write({'resource_calendar_id': template.id, 'wage': 3000,
        'baseer_salary_mode': 'inclusive', 'baseer_work_days': 30, 'baseer_allowance_total': 0})
    initial_split = initial_version._baseer_split()
    check('initial employee has one version dated today', len(initial_emp.version_ids) == 1 and initial_version.date_version == today)
    initial_calendar = apply(wizard(employee=initial_emp, effective=today, periods=(('08:00', '18:00'),)))
    check('initial schedule updates sole native version', initial_emp.version_ids == initial_version and initial_version.resource_calendar_id == initial_calendar)
    check('initial employee allows inclusive split change midmonth without history', initial_version._baseer_split() != initial_split and initial_calendar.hours_per_day == 10)

    # A stale wizard must not override a schedule saved after it was opened.
    stale_emp = employee('stale', template)
    stale = wizard(employee=stale_emp, effective=future)
    apply(wizard(employee=stale_emp, effective=future + timedelta(days=1)))
    blocked('stale employee form rejected after intervening save', stale.action_apply)

    fixed = employee('fixed midmonth', template)
    apply(wizard(employee=fixed, effective=midmonth, periods=(('08:00', '18:00'),)))
    selected = fixed._baseer_version_for_period(future, future + relativedelta(months=1, days=-1))
    check('fixed salary schedule-only midmonth remains payroll compatible', bool(selected) and selected._baseer_split() == fixed._get_version(future)._baseer_split())
    inclusive = employee('inclusive midmonth', template, mode='inclusive')
    count_cal = E['resource.calendar'].search_count([])
    count_version = E['hr.version'].search_count([('employee_id', '=', inclusive.id)])
    blocked('inclusive split-changing midmonth rejected', lambda: wizard(employee=inclusive, effective=midmonth, periods=(('08:00', '18:00'),)).action_apply())
    check('rejection leaves no orphan calendar or version', count_cal == E['resource.calendar'].search_count([]) and count_version == E['hr.version'].search_count([('employee_id', '=', inclusive.id)]))
    apply(wizard(employee=inclusive, effective=future, periods=(('08:00', '18:00'),)))
    check('inclusive changed split accepted at month boundary', inclusive._get_version(future).resource_calendar_id.hours_per_day == 10)

    # Traditional payroll must consume the selected historical calendar even
    # when the employee's currently active calendar has different hours.
    worked_emp = employee('historical worked days', template)
    worked_old = worked_emp.version_id
    apply(wizard(employee=worked_emp, effective=today, periods=(('08:00', '18:00'),)))
    check('worked days fixture currently ten hours historically eight', worked_emp.resource_calendar_id.hours_per_day == 10 and worked_old.resource_calendar_id.hours_per_day == 8)
    historical_monday = past + timedelta(days=(7 - past.weekday()) % 7)
    historical_end = historical_monday + timedelta(days=6)
    lines = E['hr.payslip'].get_worked_day_lines(worked_old, historical_monday, historical_end)
    work = [line for line in lines if line['code'] == 'WORK100']
    check('traditional payroll historical worked hours', len(work) == 1 and abs(work[0]['number_of_hours'] - 40) < 1e-6)

    # Native approved historical leave and its resource leave must stay byte-identical.
    leave_type = E['hr.leave.type'].create({'name': 'WS1 leave ' + token, 'requires_allocation': False,
        'leave_validation_type': 'no_validation', 'company_id': company.id, 'create_calendar_meeting': False})
    le = employee('historical leave', template)
    leave_day = historical_monday
    leave = E['hr.leave'].create({'name': 'WS1 historical', 'employee_id': le.id,
        'holiday_status_id': leave_type.id, 'request_date_from': leave_day, 'request_date_to': leave_day})
    check('historical leave fixture approved', leave.state == 'validate')
    resource_leaves = E['resource.calendar.leaves'].search([('holiday_id', '=', leave.id)])
    check('historical resource leave exists', bool(resource_leaves))
    leave_before = snapshot('hr_leave', leave.ids)
    resource_before = snapshot('resource_calendar_leaves', resource_leaves.ids)
    apply(wizard(employee=le, effective=future, periods=(('09:00', '19:00'),)))
    check('historical approved leave unchanged', snapshot('hr_leave', leave.ids) == leave_before)
    check('historical resource intervals unchanged', snapshot('resource_calendar_leaves', resource_leaves.ids) == resource_before)

    holiday_start = datetime.combine(monday, datetime.min.time())
    holiday_stop = holiday_start + timedelta(days=1)
    public_holiday = E['resource.calendar.leaves'].create({'name': 'WS1 public holiday ' + token,
        'calendar_id': template.id, 'date_from': holiday_start, 'date_to': holiday_stop,
        'time_type': 'leave'})
    holiday_source_leave_count = E['resource.calendar.leaves'].search_count([('holiday_id', '=', leave.id)])
    holiday_employee = employee('public holiday copy', template)
    for holiday_wizard, label in ((wizard(source=template), 'source template'),
                                 (wizard(employee=holiday_employee, effective=future), 'current employee calendar')):
        holiday_calendar = apply(holiday_wizard)
        copied_holidays = E['resource.calendar.leaves'].search([('calendar_id', '=', holiday_calendar.id)])
        check(label + ' preserves public holiday dates and exclusion', len(copied_holidays) == 1
              and copied_holidays.name == public_holiday.name
              and copied_holidays.date_from == public_holiday.date_from
              and copied_holidays.date_to == public_holiday.date_to
              and copied_holidays.time_type == 'leave'
              and holiday_calendar.get_work_hours_count(holiday_start, holiday_stop) == 0)
        check(label + ' does not clone employee time off', not copied_holidays.resource_id
              and not copied_holidays.holiday_id
              and E['resource.calendar.leaves'].search_count([('holiday_id', '=', leave.id)]) == holiday_source_leave_count)

    conflict_day = future + timedelta(days=(7 - future.weekday()) % 7)
    conflict_emp = employee('future leave', template)
    E['hr.leave'].create({'name': 'WS1 future', 'employee_id': conflict_emp.id,
        'holiday_status_id': leave_type.id, 'request_date_from': conflict_day, 'request_date_to': conflict_day})
    blocked('future approved leave rejects affected schedule', lambda: wizard(employee=conflict_emp, effective=future).action_apply())
    bounded_emp = employee('next version boundary', template)
    next_date = future + relativedelta(months=1)
    later_cal = apply(wizard(employee=bounded_emp, effective=next_date))
    later_day = next_date + timedelta(days=(7 - next_date.weekday()) % 7)
    later_leave = E['hr.leave'].create({'name': 'WS1 outside affected range', 'employee_id': bounded_emp.id,
        'holiday_status_id': leave_type.id, 'request_date_from': later_day, 'request_date_to': later_day})
    later_before = snapshot('hr_leave', later_leave.ids)
    apply(wizard(employee=bounded_emp, effective=future, periods=(('09:00', '17:00'),)))
    check('leave after next version boundary does not block earlier interval', bounded_emp._get_version(next_date).resource_calendar_id == later_cal)
    check('leave beyond next version boundary remains unchanged', snapshot('hr_leave', later_leave.ids) == later_before)
    attendance_emp = employee('attendance', template)
    E['hr.attendance'].create({'employee_id': attendance_emp.id,
        'check_in': datetime.combine(conflict_day, datetime.min.time()) + timedelta(hours=8),
        'check_out': datetime.combine(conflict_day, datetime.min.time()) + timedelta(hours=16)})
    blocked('existing attendance rejects affected schedule', lambda: wizard(employee=attendance_emp, effective=future).action_apply())
    open_emp = employee('open attendance', template)
    E['hr.attendance'].create({'employee_id': open_emp.id, 'check_in': datetime.combine(today, datetime.min.time())})
    blocked('open attendance crossing effective date rejected', lambda: wizard(employee=open_emp, effective=future).action_apply())

    # Real role checks use non-superuser environments.
    hr_user = E['res.users'].create({'name': 'WS1 HR ' + token, 'login': 'ws1-hr-' + token,
        'company_id': company.id, 'company_ids': [(6, 0, company.ids)],
        'group_ids': [(6, 0, [E.ref('hr.group_hr_manager').id])]})
    H = env(user=hr_user.id, context={'allowed_company_ids': company.ids}, su=False)
    check('HR actor has no payroll manager role', not hr_user.has_group('om_hr_payroll.group_hr_payroll_manager'))
    hr_emp = employee('HR access', template)
    apply(wizard(employee=hr_emp, effective=future, environment=H))
    user = E['res.users'].create({'name': 'WS1 basic ' + token, 'login': 'ws1-basic-' + token,
        'company_id': company.id, 'company_ids': [(6, 0, company.ids)],
        'group_ids': [(6, 0, [E.ref('base.group_user').id])]})
    U = env(user=user.id, context={'allowed_company_ids': company.ids}, su=False)
    blocked('basic user cannot create schedule wizard', lambda: wizard(environment=U).action_apply())
    own_employee = employee('ordinary check in', template)
    own_employee.user_id = user
    check('ordinary check in actor has no HR or payroll manager role', not user.has_group('hr.group_hr_manager') and not user.has_group('om_hr_payroll.group_hr_payroll_manager'))
    # Match native /hr_attendance/systray_check_in_out employee resolution.
    # Do not add direct create/write ACLs or sudo that the controller lacks.
    own_web = U.user.with_company(U.company).employee_id
    check('native systray resolves only the signed in employee', own_web.id == own_employee.id)
    clock_in = own_web._attendance_action_change({'mode': 'systray'})
    check('ordinary user native web check in succeeds', clock_in.employee_id.id == own_employee.id and not clock_in.check_out and clock_in.in_mode == 'systray')
    clock_out = own_web._attendance_action_change({'mode': 'systray'})
    check('ordinary user native web check out updates same record', clock_out == clock_in and bool(clock_out.check_out) and clock_out.out_mode == 'systray')
    # Public kiosk controllers already authorize company/token/PIN, then use
    # native sudo on the selected employee. This checks that existing ORM path.
    kiosk_employee = employee('kiosk check in', template)
    kiosk = kiosk_employee.with_user(user).sudo()
    kiosk_in = kiosk._attendance_action_change({'mode': 'kiosk'})
    kiosk_out = kiosk._attendance_action_change({'mode': 'kiosk'})
    check('native kiosk check in and out remains compatible', kiosk_in == kiosk_out and bool(kiosk_out.check_out) and kiosk_out.in_mode == 'kiosk' and kiosk_out.out_mode == 'kiosk')
    default_user = E['res.users'].create({'name': 'WS1 defaults ' + token, 'login': 'ws1-defaults-' + token,
        'company_id': company.id, 'company_ids': [(6, 0, company.ids)],
        'group_ids': [(6, 0, [E.ref('base.group_user').id, E.ref('hr_attendance.group_hr_attendance_user').id])]})
    default_employee = employee('native employee defaults', template)
    default_employee.user_id = default_user
    D = env(user=default_user.id, context={'allowed_company_ids': company.ids}, su=False)
    check('native create fixtures omit context employee override', 'default_employee_id' not in D.context)
    default_attendance = D['hr.attendance'].sudo().create({
        'check_in': datetime.combine(today - timedelta(days=1), datetime.min.time()) + timedelta(hours=8),
        'check_out': datetime.combine(today - timedelta(days=1), datetime.min.time()) + timedelta(hours=16)})
    check('attendance native default supplies linked employee before locking', default_attendance.employee_id.id == default_employee.id)
    default_leave_day = future + timedelta(days=(7 - future.weekday()) % 7)
    default_leave = D['hr.leave'].create({'name': 'WS1 self leave default', 'holiday_status_id': leave_type.id,
        'request_date_from': default_leave_day, 'request_date_to': default_leave_day})
    check('ordinary self leave native default supplies linked employee before locking', default_leave.employee_id.id == default_employee.id)
    other_company = env['res.company'].search([('id', '!=', company.id)], limit=1)
    assert other_company, 'Second QA company required for company isolation test'
    foreign = env['hr.employee'].sudo().with_company(other_company).create({'name': 'WS1 foreign ' + token, 'company_id': other_company.id})
    blocked('foreign company employee rejected', lambda: wizard(employee=foreign, effective=future, environment=H).action_apply())
    foreign_cal = env['resource.calendar'].sudo().with_company(other_company).create({'name': 'WS1 foreign calendar ' + token, 'company_id': other_company.id})
    blocked('foreign company template rejected', lambda: wizard(source=foreign_cal, environment=H).action_apply())
    R['maximum_apply_seconds'] = max(R['apply_seconds'])
    check('small QA apply below two seconds excluding registry', R['maximum_apply_seconds'] < 2)
    R['status'] = 'passed'
except Exception:
    R['status'] = 'failed'
    R['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    R['rolled_back'] = True
    Path('/mnt/qa-evidence/ws1_checks.json').write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False, indent=2))

assert R['status'] == 'passed', R.get('error')
