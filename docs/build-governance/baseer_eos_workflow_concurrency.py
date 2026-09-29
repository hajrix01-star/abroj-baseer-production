"""Committed, synthetic EOS entry races on a disposable clone ONLY.

Run once through Odoo shell; recreate the clone to rerun. No external messages.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
from pathlib import Path
from threading import Barrier
import time
import traceback

import psycopg2
from odoo import api
from odoo.exceptions import ValidationError
from odoo.addons.baseer_payroll.models.common import money


TARGET = 'baseer_eos_workflow_race'
if env.cr.dbname != TARGET:
    raise RuntimeError('Refusing committed fixtures outside ' + TARGET)
REGISTRY = env.registry
ADMIN_ID = env.ref('base.user_admin').id
COMPANY_ID = 10
PREFIX = 'BP-S6 EOS ENTRY RACE '
CONTEXT = {'allowed_company_ids': [COMPANY_ID], 'lang': 'en_US', 'active_test': False,
           'tracking_disable': True, 'mail_notrack': True, 'mail_create_nosubscribe': True,
           'mail_notify_force_send': False}
OUTPUT = Path('/mnt/qa-evidence/baseer_eos_workflow_concurrency.json')
RESULT = {'database': TARGET, 'status': 'started', 'checks': [], 'races': {}}


def check(name, value):
    RESULT['checks'].append({'name': name, 'passed': bool(value)})
    if not value:
        raise AssertionError(name)


def environment(cursor):
    if cursor.dbname != TARGET:
        raise RuntimeError('Unexpected concurrency database')
    return api.Environment(cursor, ADMIN_ID, dict(CONTEXT), su=False)


def seed():
    with REGISTRY.cursor() as cursor:
        E = environment(cursor)
        check('ordinary_admin_has_required_roles', not E.su
              and E.user.has_group('om_hr_payroll.group_hr_payroll_manager')
              and E.user.has_group('hr.group_hr_manager')
              and E.user.has_group('account.group_account_user'))
        check('fresh_disposable_fixture', not E['hr.employee'].search_count([('name', '=like', PREFIX + '%')]))
        company = E.company
        purchase = E['account.journal'].search([('company_id', '=', COMPANY_ID), ('type', '=', 'purchase')], limit=1)
        check('native_accounting_configuration', purchase and company.baseer_salary_expense_id and company.baseer_salary_payable_id)
        company.write({'baseer_eos_journal_id': purchase.id, 'baseer_eos_expense_id': company.baseer_salary_expense_id.id})
        person = E['hr.employee'].create({'name': PREFIX + 'EMPLOYEE', 'company_id': COMPANY_ID, 'baseer_payroll_enabled': False})
        version = person.version_id
        version.write({'date_version': '2018-01-01', 'contract_date_start': '2018-01-01', 'wage': 3000,
                       'baseer_salary_mode': 'fixed', 'baseer_allowance_total': 300})
        if not person.work_contact_id:
            person.work_contact_id = E['res.partner'].create({'name': person.name, 'company_id': COMPANY_ID})
        person.work_contact_id.with_company(company).property_account_payable_id = company.baseer_salary_payable_id
        reason = E.ref('hr.departure_fired')
        E['hr.departure.wizard'].with_context(employee_termination=True).create({
            'employee_ids': [(6, 0, person.ids)], 'departure_reason_id': reason.id,
            'departure_date': '2026-08-31', 'set_date_end': True, 'remove_related_user': False,
        }).action_register_departure()
        check('native_employee_departure_recorded', not person.active and version.departure_date == date(2026, 8, 31)
              and version.departure_reason_id == reason)
        check('new_employee_has_no_award', not E['baseer.hr.eos'].search_count([('employee_id', '=', person.id)]))
        before_ids = set(E['account.move'].search([]).ids)
        E.flush_all()
        cursor.commit()
        RESULT['employee_id'] = person.id
        RESULT['fixtures_committed'] = True
        return person.id, before_ids


def worker(employee_id, barrier, mode, award_id=None):
    retries = []
    started = time.monotonic()
    backend_pid = snapshot = None
    for attempt in range(1, 7):
        try:
            with REGISTRY.cursor() as cursor:
                E = environment(cursor)
                person = E['hr.employee'].browse(employee_id)
                if attempt == 1:
                    # Read before the barrier to establish both transaction snapshots.
                    rows = E['baseer.hr.eos'].search([('employee_id', '=', employee_id)])
                    if mode == 'open' and rows:
                        raise AssertionError('Entry race must begin without an award')
                    if mode == 'approve' and (rows.ids != [award_id] or rows.state != 'draft'):
                        raise AssertionError('Approval race must begin with exactly one draft')
                    cursor.execute('SELECT pg_backend_pid(), txid_current_snapshot()::text')
                    backend_pid, snapshot = cursor.fetchone()
                    barrier.wait(timeout=30)
                call_started = time.monotonic()
                if mode == 'open':
                    action = person.action_open_departure_award()
                else:
                    action = E['baseer.hr.eos'].browse(award_id).action_approve_workflow()
                if action.get('res_model') != 'baseer.hr.eos' or not action.get('res_id'):
                    raise AssertionError('Workflow must return the award form')
                award = E['baseer.hr.eos'].browse(action['res_id'])
                E.flush_all()
                outcome = {'award_id': award.id, 'bill_id': award.bill_id.id, 'state': award.state,
                           'attempts': attempt, 'retries': retries, 'backend_pid': backend_pid,
                           'initial_snapshot': snapshot, 'action_seconds': round(time.monotonic() - call_started, 6)}
                cursor.commit()
                outcome['elapsed_seconds'] = round(time.monotonic() - started, 6)
                return outcome
        except psycopg2.Error as error:
            constraint = error.diag.constraint_name or ''
            known_entry_collision = (mode == 'open' and error.pgcode == '23505'
                                     and constraint == 'baseer_hr_eos_departure_entry_unique')
            if error.pgcode not in ('40001', '40P01') and not known_entry_collision:
                raise
            retries.append({'attempt': attempt, 'sqlstate': error.pgcode, 'constraint': constraint})
            if attempt == 6:
                raise
            time.sleep(0.05 * attempt)
        except ValidationError as error:
            # Some ORM paths translate only this known SQL uniqueness error.
            if mode != 'open' or 'This departure is already being processed.' not in str(error) or attempt == 6:
                raise
            retries.append({'attempt': attempt, 'business_error': 'departure_entry_unique'})
            time.sleep(0.05 * attempt)


def race(employee_id, mode, award_id=None):
    barrier = Barrier(2)
    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='eos-entry-' + mode) as pool:
        futures = [pool.submit(worker, employee_id, barrier, mode, award_id) for _ in range(2)]
        outcomes = [future.result(timeout=150) for future in futures]
    RESULT['races'][mode] = {'workers': outcomes, 'elapsed_seconds': round(time.monotonic() - began, 6)}
    check(mode + '_two_distinct_database_connections', len({row['backend_pid'] for row in outcomes}) == 2)
    check(mode + '_both_resolve_one_award', len({row['award_id'] for row in outcomes}) == 1)
    return outcomes


try:
    employee_id, before_ids = seed()
    opened = race(employee_id, 'open')
    award_id = opened[0]['award_id']
    check('entry_button_does_not_issue_bill', all(row['state'] == 'draft' and not row['bill_id'] for row in opened))
    with REGISTRY.cursor() as cursor:
        E = environment(cursor)
        awards = E['baseer.hr.eos'].search([('employee_id', '=', employee_id)])
        check('exactly_one_calculated_departure_entry', awards.ids == [award_id] and awards.departure_entry
              and awards.source_snapshot and money(awards.award_amount) > 0)
        check('opening_creates_no_accounting_moves', set(E['account.move'].search([]).ids) == before_ids)
        check('draft_employee_button_replay', E['hr.employee'].browse(employee_id).action_open_departure_award()['res_id'] == award_id)
        awards.write({'approval_confirmed': True, 'evidence_reference': 'BP-S6 reviewed native departure race'})
        E.flush_all()
        cursor.commit()
    approved = race(employee_id, 'approve', award_id)
    check('wrapper_both_approved_same_bill', all(row['state'] == 'approved' and row['bill_id'] for row in approved)
          and len({row['bill_id'] for row in approved}) == 1)
    with REGISTRY.cursor() as cursor:
        E = environment(cursor)
        person = E['hr.employee'].browse(employee_id)
        award = E['baseer.hr.eos'].browse(award_id)
        bill = award.bill_id
        check('native_bill_matches_reviewed_award', bill.state == 'posted' and bill.move_type == 'in_invoice'
              and bill.baseer_eos_id == award and bill.company_id == E.company
              and bill.partner_id == person.work_contact_id and bill.date == date(2026, 8, 31)
              and money(bill.amount_total) == money(award.award_amount) and money(bill.amount_tax) == 0
              and money(sum(bill.line_ids.mapped('balance'))) == 0)
        check('wrapper_replay_returns_same_award', award.action_approve_workflow()['res_id'] == award_id)
        check('original_approval_replay_returns_same_bill', award.action_approve()['res_id'] == bill.id)
        check('approved_employee_button_replay', person.action_open_departure_award()['res_id'] == award_id)
        check('one_award_after_all_replays', E['baseer.hr.eos'].search([('employee_id', '=', employee_id)]).ids == [award_id])
        check('exactly_one_new_native_bill', set(E['account.move'].search([]).ids) - before_ids == {bill.id}
              and E['account.move'].search([('baseer_eos_id', '=', award_id)]).ids == [bill.id])
        check('document_identity_captured', bool(award.document_snapshot))
        RESULT.update({'award_id': award_id, 'bill_id': bill.id, 'award_amount': str(money(award.award_amount))})
        E.flush_all()
        cursor.commit()
    RESULT['status'] = 'passed'
except Exception:
    RESULT['status'] = 'failed'
    RESULT['traceback'] = traceback.format_exc()
    raise
finally:
    OUTPUT.write_text(json.dumps(RESULT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(RESULT, ensure_ascii=False, indent=2))
