"""QA-only WS1 concurrency acceptance using independent Odoo transactions.

Unlike ws1_checks.py, this script commits a small, uniquely named QA fixture so
independent connections can see it. It deletes that fixture through native ORM
in finally. Worker transactions have bounded lock/statement timeouts. Run only
after baseer_work_schedule is installed on baseer_reports_qa_20260907.
"""
import json
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dateutil.relativedelta import relativedelta
from psycopg2.errors import SerializationFailure
from odoo import api, fields
from odoo.exceptions import ValidationError


assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA database required'
registry = env.registry
admin = env.ref('base.user_admin').id
company_id = 10
context = {'allowed_company_ids': [company_id], 'tracking_disable': True, 'lang': 'en_US'}
tag = 'WS1-CONCURRENCY-' + uuid.uuid4().hex[:10]
R = {'checks': [], 'fixture_tag': tag, 'database': env.cr.dbname}
fixture = {'employee': [], 'calendar': [], 'wizard': [], 'leave_type': []}
workers = []


def check(name, condition):
    R['checks'].append({'name': name, 'passed': bool(condition)})
    assert condition, name


def actor(cr):
    # Odoo's real isolation level is intentionally retained. A READ COMMITTED
    # test would conceal stale snapshots behind a successful advisory wait.
    cr.execute("SET LOCAL lock_timeout = '12s'")
    cr.execute("SET LOCAL statement_timeout = '25s'")
    return api.Environment(cr, admin, context, su=False)


def new_wizard(E, employee_id, effective):
    return E['baseer.schedule.wizard'].create({
        'name': tag, 'company_id': company_id, 'employee_id': employee_id,
        'effective_date': effective,
        'day_ids': [(6, 0, [E.ref('baseer_work_schedule.day_%d' % d).id for d in range(5)])],
        'period_ids': [(0, 0, {'time_from': '08:00', 'time_to': '16:00'})],
    })


def worker(operation, *, retries=0):
    state = {'ready': threading.Event(), 'done': threading.Event(), 'attempts': []}

    def run():
        started = time.monotonic()
        try:
            for attempt in range(retries + 1):
                try:
                    with registry.cursor() as cr:
                        E = actor(cr)
                        cr.execute('SELECT pg_backend_pid()')
                        state['pid'] = cr.fetchone()[0]
                        state['ready'].set()
                        operation(E)
                        # A successful competing operation is only observed;
                        # rollback protects the fixture if the test finds a bug.
                        state['result'] = 'succeeded'
                        cr.rollback()
                    break
                except SerializationFailure as exc:
                    state['attempts'].append({'type': 'SerializationFailure', 'message': str(exc)})
                    if attempt == retries:
                        raise
                except ValidationError as exc:
                    state['result'] = 'rejected'
                    state['message'] = str(exc)
                    break
        except Exception:
            state['result'] = 'error'
            state['error'] = traceback.format_exc()
        finally:
            state['elapsed_seconds'] = round(time.monotonic() - started, 4)
            state['done'].set()

    thread = threading.Thread(target=run, name=tag + '-worker', daemon=True)
    workers.append((thread, state))
    thread.start()
    check('worker connection opened ' + str(len(workers)), state['ready'].wait(5))
    return state


def wait_for_advisory_block(state, label):
    deadline = time.monotonic() + 8
    seen = False
    with registry.cursor() as monitor:
        while time.monotonic() < deadline and not state['done'].is_set():
            monitor.execute('SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s AND locktype=%s AND NOT granted)',
                            [state['pid'], 'advisory'])
            if monitor.fetchone()[0]:
                seen = True
                break
            time.sleep(0.05)
    if not seen:
        R[label + '_before_lock_failure'] = {k: v for k, v in state.items() if k not in ('ready', 'done')}
    check(label + ' waits on actual PostgreSQL advisory lock', seen)
    check(label + ' cannot finish while schedule transaction owns lock', not state['done'].is_set())


def finish(state, label):
    check(label + ' finishes after lock release', state['done'].wait(20))
    R[label] = {k: v for k, v in state.items() if k not in ('ready', 'done')}
    if state.get('error'):
        raise AssertionError(state['error'])


def cleanup_exact_tag(cleanup_tag):
    """Delete only this test's native records, including orphan native versions."""
    assert cleanup_tag.startswith('WS1-CONCURRENCY-') and len(cleanup_tag) == 26
    with registry.cursor() as cleanup_cr:
        E = actor(cleanup_cr)
        employees = E['hr.employee'].with_context(active_test=False).search([('name', '=', cleanup_tag)])
        users = E['res.users'].with_context(active_test=False).search([('login', '=', cleanup_tag)])
        user_partners = users.partner_id
        calendars = E['resource.calendar'].with_context(active_test=False).search([('name', '=', cleanup_tag)])
        versions = E['hr.version'].with_context(active_test=False).search([
            '|', ('employee_id', 'in', employees.ids), ('resource_calendar_id', 'in', calendars.ids)])
        assert not (versions.employee_id - employees), 'Tagged calendar referenced by an unrelated employee'
        version_ids = versions.ids
        E['baseer.schedule.wizard'].search([('name', '=', cleanup_tag)]).unlink()
        E['hr.attendance'].search([('employee_id', 'in', employees.ids)]).unlink()
        leaves = E['hr.leave'].search([('employee_id', 'in', employees.ids)])
        if leaves:
            leaves.action_refuse()
            leaves.unlink()
        # Native employee deletion retains versions with employee_id=NULL.
        # Delete those captured versions through ORM before the calendar guard.
        employees.unlink()
        E['hr.version'].browse(version_ids).exists().unlink()
        calendars.unlink()
        E['hr.leave.type'].with_context(active_test=False).search([('name', '=', cleanup_tag)]).unlink()
        users.unlink()
        user_partners.exists().unlink()
        cleanup_cr.commit()
    with registry.cursor() as cr:
        E = actor(cr)
        remaining = any((
            E['hr.employee'].with_context(active_test=False).search_count([('name', '=', cleanup_tag)]),
            E['resource.calendar'].with_context(active_test=False).search_count([('name', '=', cleanup_tag)]),
            E['baseer.schedule.wizard'].search_count([('name', '=', cleanup_tag)]),
            E['hr.leave.type'].with_context(active_test=False).search_count([('name', '=', cleanup_tag)]),
            E['res.users'].with_context(active_test=False).search_count([('login', '=', cleanup_tag)]),
            bool(E['hr.version'].browse(version_ids).exists()),
        ))
    return not remaining


try:
    # Explicit recovery of the one fixture left by the initial cleanup defect;
    # no wildcard cleanup of other WS1 runs or business records is permitted.
    R['previous_fixture_cleaned_up'] = cleanup_exact_tag('WS1-CONCURRENCY-65e7a872aa')
    check('previous exact failed-run fixture cleaned up', R['previous_fixture_cleaned_up'])
    with registry.cursor() as cr:
        E = actor(cr)
        today = fields.Date.today()
        future = today.replace(day=1) + relativedelta(months=2)
        past = today.replace(day=1) - relativedelta(months=2)
        cal = E['resource.calendar'].create({'name': tag, 'company_id': company_id,
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {'name': tag, 'dayofweek': str(d),
                'day_period': 'morning', 'hour_from': 8, 'hour_to': 16}) for d in range(5)]})
        fixture['calendar'] = cal.ids
        emp = E['hr.employee'].create({'name': tag, 'company_id': company_id})
        fixture['employee'] = emp.ids
        emp.version_id.write({'date_version': past, 'contract_date_start': past,
            'resource_calendar_id': cal.id, 'wage': 3000, 'baseer_salary_mode': 'fixed',
            'baseer_work_days': 30, 'baseer_allowance_total': 0})
        default_user = E['res.users'].create({'name': tag, 'login': tag, 'company_id': company_id,
            'company_ids': [(6, 0, [company_id])], 'group_ids': [(6, 0, [E.ref('base.group_user').id,
                E.ref('hr_attendance.group_hr_attendance_user').id])]})
        emp.user_id = default_user
        default_user_id = default_user.id
        first = new_wizard(E, emp.id, future)
        second = new_wizard(E, emp.id, future)
        later = new_wizard(E, emp.id, future + relativedelta(months=1))
        fixture['wizard'] = first.ids + second.ids + later.ids
        leave_type = E['hr.leave.type'].create({'name': tag, 'company_id': company_id,
            'requires_allocation': False, 'leave_validation_type': 'no_validation', 'create_calendar_meeting': False})
        fixture['leave_type'] = leave_type.ids
        employee_id, first_id, second_id, later_id = emp.id, first.id, second.id, later.id
        check('two open forms share initial revision', first.expected_revision == second.expected_revision)
        cr.commit()
        R['fixture_committed'] = True

    # The first apply has finished but retains its transaction lock. The second
    # request really blocks, then either detects stale state or receives Odoo's
    # normal serialization retry before detecting the unchanged stale form.
    with registry.cursor() as cr_a:
        A = actor(cr_a)
        first = A['baseer.schedule.wizard'].browse(first_id)
        first.action_apply()
        generated_id = first.applied_calendar_id.id
        fixture['calendar'].append(generated_id)
        contender = worker(lambda B: B['baseer.schedule.wizard'].browse(second_id).action_apply(), retries=1)
        wait_for_advisory_block(contender, 'competing schedule')
        cr_a.commit()
    finish(contender, 'competing_schedule')
    check('second saved form rejects stale expected revision', contender.get('result') == 'rejected'
          and 'changed while this form was open' in contender.get('message', ''))
    with registry.cursor() as cr:
        E = actor(cr)
        check('only one future version committed', E['hr.version'].search_count([
            ('employee_id', '=', employee_id), ('date_version', '=', future)]) == 1)
        check('one generated calendar committed', E['resource.calendar'].search_count([
            ('name', '=', tag), ('baseer_simple', '=', True)]) == 1)
        check('rejected form remains unapplied', not E['baseer.schedule.wizard'].browse(second_id).applied_calendar_id)

    # Native attendance and leave writers must join the same employee lock.
    # The schedule is rolled back; native worker writes also roll back after
    # successfully proceeding, so only the one race winner stays for cleanup.
    for model, label in (('hr.attendance', 'native_attendance'), ('hr.leave', 'native_leave')):
        with registry.cursor() as cr_a:
            A = actor(cr_a)
            later = A['baseer.schedule.wizard'].browse(later_id)
            later._onchange_employee_date()
            later.action_apply()
            event_day = future + relativedelta(months=1, days=7)
            if model == 'hr.attendance':
                vals = {'check_in': datetime.combine(event_day, datetime.min.time()) + timedelta(hours=8),
                    'check_out': datetime.combine(event_day, datetime.min.time()) + timedelta(hours=16)}
            else:
                event_day += timedelta(days=(7 - event_day.weekday()) % 7)
                vals = {'name': tag,
                    'holiday_status_id': fixture['leave_type'][0],
                    'request_date_from': event_day, 'request_date_to': event_day}
            def create_with_native_default(B, model=model, vals=vals):
                records = B[model].with_user(default_user_id)
                if model == 'hr.attendance':
                    records = records.sudo()
                assert 'employee_id' not in vals and 'default_employee_id' not in records.env.context
                created = records.create(dict(vals))
                assert created.employee_id.id == employee_id, 'Native default selected the wrong employee'
            pending = worker(create_with_native_default)
            wait_for_advisory_block(pending, label)
            cr_a.rollback()
        finish(pending, label)
        check(label + ' succeeds after schedule rollback', pending.get('result') == 'succeeded')
    R['status'] = 'passed'
except Exception:
    R['status'] = 'failed'
    R['error'] = traceback.format_exc()
finally:
    # Exiting all holder cursor contexts releases advisory locks even on failure.
    for thread, state in workers:
        thread.join(30)
    try:
        R['cleaned_up'] = cleanup_exact_tag(tag)
        check('all committed QA fixture records cleaned up', R['cleaned_up'])
    except Exception:
        R['cleanup_error'] = traceback.format_exc()
        R['status'] = 'failed'
    env.cr.rollback()
    Path('/mnt/qa-evidence/ws1_concurrency.json').write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False, indent=2))

assert R['status'] == 'passed', R.get('error') or R.get('cleanup_error')
