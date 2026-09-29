"""WS4 real REPEATABLE READ races, isolated tagged QA fixtures only.

Holders commit solely to exercise visibility across independent connections.
Contenders always roll back. Exact-tag ORM cleanup runs even after failures.
"""
import json
import threading
import time
import traceback
import uuid
from datetime import timedelta
from pathlib import Path

from dateutil.relativedelta import relativedelta
from psycopg2.errors import SerializationFailure
from odoo import api, fields
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA database required'
registry = env.registry
admin = env.ref('base.user_admin').id
context = {'allowed_company_ids': [10], 'tracking_disable': True, 'lang': 'en_US'}
tag = 'WS4-CONCURRENCY-' + uuid.uuid4().hex[:10]
R = {'checks': [], 'fixture_tag': tag, 'database': env.cr.dbname}
workers = []


def check(name, condition):
    R['checks'].append({'name': name, 'passed': bool(condition)})
    assert condition, name


def actor(cr):
    cr.execute("SET LOCAL lock_timeout = '12s'")
    cr.execute("SET LOCAL statement_timeout = '25s'")
    return api.Environment(cr, admin, context, su=False)


def new_template(E):
    w = E['baseer.schedule.wizard'].create({'name': tag, 'company_id': 10,
        'day_ids': [(6, 0, E['baseer.schedule.day'].search([('weekday', 'in', list(range(5)))]).ids)],
        'period_ids': [(0, 0, {'time_from': '08:00', 'time_to': '16:00'})]})
    w.action_apply()
    return w.applied_calendar_id


def new_employee(E, calendar):
    emp = E['hr.employee'].create({'name': tag, 'company_id': 10})
    emp.version_id.write({'date_version': past, 'contract_date_start': past,
        'resource_calendar_id': calendar.id, 'wage': 3000, 'baseer_salary_mode': 'fixed',
        'baseer_work_days': 30, 'baseer_allowance_total': 0})
    return emp


def new_edit(E, source):
    action = source.action_baseer_edit_schedule()
    w = E['baseer.schedule.wizard'].with_context(action['context']).create({'effective_date': future})
    w.period_ids.write({'time_to': '18:00'})
    return w


def worker(operation, retries=1):
    state = {'ready': threading.Event(), 'done': threading.Event(), 'attempts': []}

    def run():
        started = time.monotonic()
        try:
            for attempt in range(retries + 1):
                try:
                    with registry.cursor() as cr:
                        E = actor(cr)
                        cr.execute('SHOW transaction_isolation')
                        state['isolation'] = cr.fetchone()[0]
                        cr.execute('SELECT pg_backend_pid()')
                        state['pid'] = cr.fetchone()[0]
                        state['ready'].set()
                        operation(E)
                        E.flush_all()
                        state['result'] = 'succeeded'
                        cr.rollback()
                    break
                except SerializationFailure as exc:
                    state['attempts'].append({'type': 'SerializationFailure', 'message': str(exc)})
                    if attempt == retries:
                        raise
                except (AccessError, UserError, ValidationError) as exc:
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


def wait_for_block(state, label):
    deadline = time.monotonic() + 8
    kinds = []
    with registry.cursor() as monitor:
        while time.monotonic() < deadline and not state['done'].is_set():
            monitor.execute('SELECT locktype FROM pg_locks WHERE pid=%s AND NOT granted', [state['pid']])
            kinds = [r[0] for r in monitor.fetchall()]
            if kinds:
                break
            time.sleep(0.05)
    state['observed_wait_locks'] = kinds
    if not kinds:
        R[label + '_early_result'] = {k: v for k, v in state.items() if k not in ('ready', 'done')}
    check(label + ' blocks on actual PostgreSQL lock', bool(kinds))
    check(label + ' remains pending until holder releases', not state['done'].is_set())


def finish(state, label, expected='rejected'):
    check(label + ' completes after lock release', state['done'].wait(30))
    R[label] = {k: v for k, v in state.items() if k not in ('ready', 'done')}
    if state.get('error'):
        raise AssertionError(state['error'])
    check(label + ' uses native repeatable read', state.get('isolation') == 'repeatable read')
    check(label + ' ends with ' + expected, state.get('result') == expected)


def cleanup_exact_tag(cleanup_tag):
    assert cleanup_tag.startswith('WS4-CONCURRENCY-') and len(cleanup_tag) == 26
    with registry.cursor() as cr:
        E = actor(cr)
        employees = E['hr.employee'].with_context(active_test=False).search([('name', '=', cleanup_tag)])
        calendars = E['resource.calendar'].with_context(active_test=False).search([('name', '=', cleanup_tag)])
        versions = E['hr.version'].with_context(active_test=False).search([
            '|', ('employee_id', 'in', employees.ids), ('resource_calendar_id', 'in', calendars.ids)])
        assert not (versions.employee_id - employees), 'Tagged calendar has an unrelated employee'
        version_ids = versions.ids
        E['baseer.schedule.wizard'].search([('name', '=', cleanup_tag)]).unlink()
        employees.unlink()
        E['hr.version'].browse(version_ids).exists().unlink()
        # Parent links point to successors; delete oldest first after history removal.
        for cal in calendars.sorted('id'):
            cal.unlink()
        cr.commit()
    with registry.cursor() as cr:
        E = actor(cr)
        return not any((
            E['hr.employee'].with_context(active_test=False).search_count([('name', '=', cleanup_tag)]),
            E['resource.calendar'].with_context(active_test=False).search_count([('name', '=', cleanup_tag)]),
            E['baseer.schedule.wizard'].search_count([('name', '=', cleanup_tag)]),
            bool(E['hr.version'].browse(version_ids).exists()),
        ))


try:
    today = fields.Date.today()
    future = today.replace(day=1) + relativedelta(months=2)
    past = today.replace(day=1) - relativedelta(months=3)
    with registry.cursor() as cr:
        E = actor(cr)
        source = new_template(E)
        emp = new_employee(E, source)
        first, second = new_edit(E, source), new_edit(E, source)
        source_id, emp_id, first_id, second_id = source.id, emp.id, first.id, second.id
        check('two template forms share initial revision', first.template_revision == second.template_revision)
        cr.commit()
        R['fixture_committed'] = True
    with registry.cursor() as holder:
        A = actor(holder)
        first = A['baseer.schedule.wizard'].browse(first_id)
        first.action_apply()
        pending = worker(lambda B: B['baseer.schedule.wizard'].browse(second_id).action_apply())
        wait_for_block(pending, 'competing_template_edit')
        holder.commit()
    finish(pending, 'competing_template_edit')
    with registry.cursor() as cr:
        E = actor(cr)
        check('only one revision won template race', E['hr.version'].search_count([('employee_id', '=', emp_id), ('date_version', '=', future)]) == 1)
        check('losing template form unapplied', not E['baseer.schedule.wizard'].browse(second_id).applied_calendar_id)

    # Incoming employees are absent from the fanout's initial candidate query.
    # Source tuple touches must close this phantom-membership race.
    for mutation in ('create', 'write', 'unlink', 'date', 'active', 'wage'):
        with registry.cursor() as cr:
            E = actor(cr)
            source, outside = new_template(E), new_template(E)
            linked = new_employee(E, source)
            mover = new_employee(E, outside)
            if mutation in ('unlink', 'date', 'active'):
                mover.version_id.write({'resource_calendar_id': source.id})
                old_id = mover.version_id.id
                mover.create_version({'date_version': past + timedelta(days=1), 'resource_calendar_id': outside.id})
            elif mutation == 'wage':
                mover.version_id.write({'resource_calendar_id': source.id})
                old_id = mover.version_id.id
            else:
                old_id = mover.version_id.id
            form = new_edit(E, source)
            form_id, mover_id, source_id = form.id, mover.id, source.id
            cr.commit()
        with registry.cursor() as holder:
            A = actor(holder)
            mover = A['hr.employee'].browse(mover_id)
            if mutation == 'create':
                mover.create_version({'date_version': today, 'resource_calendar_id': source_id})
            elif mutation == 'write':
                mover.version_id.write({'resource_calendar_id': source_id})
            elif mutation == 'unlink':
                A['hr.version'].browse(old_id).unlink()
            elif mutation == 'active':
                A['hr.version'].browse(old_id).write({'active': False})
            elif mutation == 'wage':
                A['hr.version'].browse(old_id).write({'wage': 3456})
            else:
                A['hr.version'].browse(old_id).write({'date_version': past - timedelta(days=1)})
            A.flush_all()
            pending = worker(lambda B, form_id=form_id: B['baseer.schedule.wizard'].browse(form_id).action_apply())
            label = 'membership_' + mutation + '_wins'
            wait_for_block(pending, label)
            holder.commit()
        finish(pending, label)
        with registry.cursor() as cr:
            E = actor(cr)
            check(label + ' stale edit creates no replacement', not E['resource.calendar'].browse(source_id).baseer_superseded_by_id)
            # Fresh read includes the committed membership and can safely fan out.
            current_form = new_edit(E, E['resource.calendar'].browse(source_id))
            expected = 2 if mutation in ('create', 'write', 'wage') else 1
            check(label + ' fresh preview has exact membership', current_form.affected_count == expected)
            current_form.action_apply()
            check(label + ' fresh edit succeeds', bool(current_form.applied_calendar_id))
            if mutation == 'wage':
                check('fresh fanout copies committed wage', E['hr.employee'].browse(mover_id)._get_version(future).wage == 3456)
            cr.rollback()

    # Reverse order: a stale incoming native assignment waits for a winning edit,
    # then retries under the successor's effective-date protection.
    with registry.cursor() as cr:
        E = actor(cr)
        source, outside = new_template(E), new_template(E)
        linked, mover = new_employee(E, source), new_employee(E, outside)
        form = new_edit(E, source)
        source_id, mover_id, form_id = source.id, mover.id, form.id
        cr.commit()
    with registry.cursor() as holder:
        A = actor(holder)
        A['baseer.schedule.wizard'].browse(form_id).action_apply()
        pending = worker(lambda B: B['hr.employee'].browse(mover_id).create_version({'date_version': future, 'resource_calendar_id': source_id}))
        wait_for_block(pending, 'template_edit_wins_incoming_assignment')
        holder.commit()
    finish(pending, 'template_edit_wins_incoming_assignment')
    with registry.cursor() as cr:
        E = actor(cr)
        check('incoming rejected assignment leaves no future version', not E['hr.version'].search_count([('employee_id', '=', mover_id), ('date_version', '=', future)]))
    R['status'] = 'passed'
except Exception:
    R['status'] = 'failed'
    R['error'] = traceback.format_exc()
finally:
    for thread, state in workers:
        thread.join(30)
    try:
        R['cleaned_up'] = cleanup_exact_tag(tag)
        check('all committed QA fixture records cleaned up', R['cleaned_up'])
    except Exception:
        R['cleanup_error'] = traceback.format_exc()
        R['status'] = 'failed'
    env.cr.rollback()
    Path('/mnt/qa-evidence/ws4_concurrency.json').write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False, indent=2))

assert R['status'] == 'passed', R.get('error') or R.get('cleanup_error')
