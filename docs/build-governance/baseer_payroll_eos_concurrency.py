"""Real ORM approval races; run through Odoo shell on the disposable clone only.

This script commits synthetic fixtures and approvals. It deliberately refuses QA,
production, and repeat execution: recreate baseer_payroll_profile_race to rerun.
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
from odoo.exceptions import UserError, ValidationError
from odoo.addons.baseer_payroll.models.common import money


TARGET = 'baseer_payroll_profile_race'
if env.cr.dbname != TARGET:
    raise RuntimeError('Refusing committed concurrency fixtures outside ' + TARGET)

REGISTRY = env.registry
ADMIN_ID = env.ref('base.user_admin').id
COMPANY_ID = 10
PREFIX = 'BP-S4 EOS RACE '
CONTEXT = {
    'allowed_company_ids': [COMPANY_ID], 'lang': 'en_US', 'active_test': False,
    'tracking_disable': True, 'mail_notrack': True,
    'mail_create_nosubscribe': True, 'mail_notify_force_send': False,
}
RESULT = {'database': TARGET, 'status': 'started', 'checks': [], 'races': {}}
OUTPUT = Path('/mnt/qa-evidence/baseer_payroll_eos_concurrency.json')


def check(name, condition):
    RESULT['checks'].append({'name': name, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(name)


def environment(cursor):
    if cursor.dbname != TARGET:
        raise RuntimeError('Unexpected concurrency cursor database')
    return api.Environment(cursor, ADMIN_ID, dict(CONTEXT), su=False)


def seed():
    with REGISTRY.cursor() as cursor:
        E = environment(cursor)
        check('ordinary_admin_has_required_roles', not E.su
              and E.user.has_group('om_hr_payroll.group_hr_payroll_manager')
              and E.user.has_group('hr.group_hr_manager')
              and E.user.has_group('account.group_account_user'))
        check('fresh_disposable_fixture', not E['hr.employee'].search_count([
            ('name', '=like', PREFIX + '%')]))
        company = E.company
        purchase = E['account.journal'].search([
            ('company_id', '=', COMPANY_ID), ('type', '=', 'purchase')], limit=1)
        check('clone_accounting_fixture_available', bool(purchase
              and company.baseer_salary_expense_id and company.baseer_salary_payable_id))
        company.write({
            'baseer_eos_journal_id': purchase.id,
            'baseer_eos_expense_id': company.baseer_salary_expense_id.id,
        })
        departure_reason = E['hr.departure.reason'].search([], limit=1)
        check('native_departure_reason_available', bool(departure_reason))
        bill_ids_before = E['account.move'].search([]).ids
        requests = []
        for suffix, count in [('SAME REQUEST', 1), ('COMPETING REQUESTS', 2)]:
            person = E['hr.employee'].create({
                'name': PREFIX + suffix, 'company_id': COMPANY_ID,
                'baseer_payroll_enabled': False,
            })
            version = person.version_id
            version.write({
                'date_version': '2018-01-01', 'contract_date_start': '2018-01-01',
                'wage': 3000, 'baseer_salary_mode': 'fixed',
                'baseer_allowance_total': 300,
            })
            if not person.work_contact_id:
                person.work_contact_id = E['res.partner'].create({
                    'name': person.name, 'company_id': COMPANY_ID,
                })
            person.work_contact_id.with_company(company).property_account_payable_id = company.baseer_salary_payable_id
            E['hr.departure.wizard'].with_context(employee_termination=True).create({
                'employee_ids': [(6, 0, person.ids)],
                'departure_reason_id': departure_reason.id,
                'departure_date': '2026-08-31', 'set_date_end': True,
                'remove_related_user': False,
            }).action_register_departure()
            check('native_departure_' + suffix, version.departure_date == date(2026, 8, 31))
            for index in range(count):
                request = E['baseer.hr.eos'].create({
                    'employee_id': person.id, 'version_id': version.id,
                    'service_start': '2018-01-01', 'service_end': '2026-08-31',
                    'reason': 'termination',
                })
                request.action_calculate()
                request.write({
                    'evidence_reference': PREFIX + suffix + ' / ' + str(index + 1),
                    'approval_confirmed': True,
                })
                requests.append(request.id)
        E.flush_all()
        cursor.commit()
        RESULT['fixture_request_ids'] = requests
        RESULT['fixtures_committed'] = True
        return requests, set(bill_ids_before)


def approve(request_id, barrier):
    retries = []
    for attempt in range(1, 6):
        try:
            with REGISTRY.cursor() as cursor:
                E = environment(cursor)
                # Establish both real transaction snapshots before either approves.
                # The barrier is never used on retry, which would deadlock a winner.
                request = E['baseer.hr.eos'].browse(request_id)
                if attempt == 1:
                    if request.state != 'draft':
                        raise AssertionError('Race must start with a draft request')
                    cursor.execute('SELECT pg_backend_pid(), txid_current_snapshot()::text')
                    backend_pid, snapshot = cursor.fetchone()
                    barrier.wait(timeout=30)
                action = request.action_approve()
                E.flush_all()
                bill_id = request.bill_id.id
                if request.state != 'approved' or action.get('res_id') != bill_id:
                    raise AssertionError('Native approval did not return its posted award bill')
                cursor.commit()
                return {'request_id': request_id, 'outcome': 'approved',
                        'bill_id': bill_id, 'attempts': attempt, 'retries': retries,
                        'backend_pid': backend_pid, 'initial_snapshot': snapshot}
        except psycopg2.Error as error:
            code = error.pgcode
            if code in ('40001', '40P01'):
                retries.append({'attempt': attempt, 'sqlstate': code})
                if attempt == 5:
                    raise
                time.sleep(0.05 * attempt)
                continue
            constraint = error.diag.constraint_name or ''
            if code == '23505' and constraint in (
                    'baseer_hr_eos_approved_period_unique',
                    'baseer_hr_eos_approved_departure_unique'):
                # Native RPC also maps IntegrityError to a model business error.
                # Limit this mapping to the two known award uniqueness constraints.
                with REGISTRY.cursor() as cursor:
                    message = environment(cursor)['baseer.hr.eos']._sql_error_to_message(error)
                return {'request_id': request_id, 'outcome': 'business_rejected',
                        'message': str(message), 'sqlstate': code, 'constraint': constraint,
                        'attempts': attempt, 'retries': retries,
                        'backend_pid': backend_pid, 'initial_snapshot': snapshot}
            raise
        except (UserError, ValidationError) as error:
            if 'already' not in str(error).lower() or 'award' not in str(error).lower():
                raise
            return {'request_id': request_id, 'outcome': 'business_rejected',
                    'message': str(error), 'attempts': attempt, 'retries': retries,
                    'backend_pid': backend_pid, 'initial_snapshot': snapshot}


def race(name, request_ids):
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='eos-native-race') as pool:
        futures = [pool.submit(approve, request_id, barrier) for request_id in request_ids]
        outcomes = [future.result(timeout=120) for future in futures]
    RESULT['races'][name] = outcomes
    check(name + '_two_database_connections', len({r['backend_pid'] for r in outcomes}) == 2)
    return outcomes


try:
    request_ids, bill_ids_before = seed()
    shared = race('same_request', [request_ids[0], request_ids[0]])
    check('same_request_both_calls_succeed', all(r['outcome'] == 'approved' for r in shared))
    check('same_request_idempotent_bill', len({r['bill_id'] for r in shared}) == 1)
    competing = race('competing_requests', request_ids[1:])
    check('competing_one_approval_one_business_rejection',
          sorted(r['outcome'] for r in competing) == ['approved', 'business_rejected'])
    with REGISTRY.cursor() as cursor:
        E = environment(cursor)
        requests = E['baseer.hr.eos'].browse(request_ids)
        bills = E['account.move'].search([('baseer_eos_id', 'in', request_ids)])
        check('exactly_two_bills_for_three_requests', len(bills) == 2)
        check('exactly_two_new_accounting_moves',
              set(E['account.move'].search([]).ids) - bill_ids_before == set(bills.ids))
        check('exactly_two_approved_requests', len(requests.filtered(lambda r: r.state == 'approved')) == 2)
        loser = requests.filtered(lambda r: r.state == 'draft')
        check('loser_has_no_bill', len(loser) == 1 and not loser.bill_id)
        for request in requests.filtered(lambda r: r.state == 'approved'):
            bill = request.bill_id
            check('bill_' + str(bill.id) + '_posted_exact_native_award',
                  bill.state == 'posted' and bill.move_type == 'in_invoice'
                  and bill.baseer_eos_id == request
                  and bill.company_id == request.company_id
                  and bill.partner_id == request.employee_id.work_contact_id
                  and bill.date == date(2026, 8, 31)
                  and money(bill.amount_total) == money(request.award_amount)
                  and money(bill.amount_tax) == 0 and not bill.invoice_line_ids.tax_ids
                  and money(sum(bill.line_ids.mapped('balance'))) == 0)
        RESULT['bill_ids'] = bills.ids
    RESULT['status'] = 'passed'
except Exception:
    RESULT['status'] = 'failed'
    RESULT['traceback'] = traceback.format_exc()
    raise
finally:
    OUTPUT.write_text(json.dumps(RESULT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(RESULT, ensure_ascii=False, indent=2))
