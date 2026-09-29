"""Committed native company-seed race, restricted to one disposable database.

Run through Odoo shell on baseer_company_seed_race. Recreate the clone to rerun.
The two workers seed an already-localized company; chart loading is not raced.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier
import time
import traceback

import psycopg2
from odoo import api


TARGET = 'baseer_company_seed_race'
if env.cr.dbname != TARGET:
    raise RuntimeError('Refusing committed company fixtures outside ' + TARGET)

REGISTRY = env.registry
ADMIN_ID = env.ref('base.user_admin').id
INITIAL_COMPANY_ID = env.company.id
FIXTURE_NAME = 'CAS1 RACE — isolated Saudi company'
MAPPINGS = (
    'baseer_salary_expense_id', 'baseer_salary_payable_id',
    'baseer_deduction_account_id', 'baseer_loan_account_id',
    'baseer_eos_expense_id', 'baseer_payroll_journal_id', 'baseer_eos_journal_id',
)
CREATED_KEYS = {
    'baseer_salary_payable_id': 'account.account',
    'baseer_loan_account_id': 'account.account',
    'payroll': 'account.journal',
}
CONTEXT = {
    'lang': 'en_US', 'active_test': False, 'tracking_disable': True,
    'mail_notrack': True, 'mail_create_nosubscribe': True,
    'mail_notify_force_send': False,
}
RESULT = {'database': TARGET, 'status': 'started', 'checks': []}
OUTPUT = Path('/mnt/qa-evidence/company_accounting_seed_concurrency.json')


def check(name, condition):
    RESULT['checks'].append({'name': name, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(name)


def environment(cursor, company_id=INITIAL_COMPANY_ID):
    if cursor.dbname != TARGET:
        raise RuntimeError('Unexpected company-seed cursor database')
    # The private initializer is privileged by the native create/chart callbacks.
    # This harness tests that initializer's transactional identity, not public ACLs.
    return api.Environment(cursor, ADMIN_ID, dict(CONTEXT, allowed_company_ids=[company_id]), su=True)


def mapping(company):
    return {name: company[name].id or False for name in MAPPINGS}


def identity_domain(company_id):
    return [('module', '=', 'baseer_company_setup'),
            ('name', '=like', '%_company_' + str(company_id))]


def snapshot(E, company):
    accounts = E['account.account'].search([('company_ids', 'in', company.ids)], order='id')
    journals = E['account.journal'].search([('company_id', '=', company.id)], order='id')
    data = E['ir.model.data'].search(identity_domain(company.id), order='name')
    return {
        'settings': mapping(company), 'chart_template': company.chart_template,
        'accounts': {a.id: [a.code, a.name, a.account_type, a.reconcile, a.active, a.company_ids.ids] for a in accounts},
        'journals': {j.id: [j.code, j.name, j.type, j.active, j.company_id.id,
                          j.default_account_id.id, [(m.id, m.payment_account_id.id) for m in j.outbound_payment_method_line_ids]] for j in journals},
        'identities': {d.name: [d.model, d.res_id, d.noupdate] for d in data},
        'move_ids': E['account.move'].search([]).ids,
    }


def fixture():
    # Phase one lets every native company/chart callback finish before the race.
    with REGISTRY.cursor() as cursor:
        E = environment(cursor)
        check('fresh_disposable_fixture', not E['res.company'].search_count([('name', '=', FIXTURE_NAME)]))
        company = E['res.company'].create({
            'name': FIXTURE_NAME, 'country_id': E.ref('base.sa').id,
            'currency_id': E.ref('base.SAR').id,
        })
        company_id = company.id
        company.env['account.chart.template']._load('sa', company, install_demo=False)
        E.flush_all()
        cursor.commit()
        RESULT['fixture_company_id'] = company_id
        RESULT['fixtures_committed'] = True

    # Remove only the three exact, unused seed records owned by this new fixture.
    # All native SA chart records, native XMLIDs and starter journals are retained.
    with REGISTRY.cursor() as cursor:
        E = environment(cursor, company_id)
        company = E['res.company'].browse(company_id)
        check('fixture_is_localized_independent_sa', company.name == FIXTURE_NAME
              and not company.parent_id and company.chart_template == 'sa'
              and company.country_id.code == 'SA' and company.currency_id.name == 'SAR')
        check('initial_native_seed_complete', all(mapping(company).values()))
        check('fixture_has_no_financial_documents',
              not E['account.move'].search_count([('company_id', '=', company_id)])
              and not E['account.payment'].search_count([('company_id', '=', company_id)]))
        targets = []
        for key, model in CREATED_KEYS.items():
            xmlid = E['ir.model.data'].search([
                ('module', '=', 'baseer_company_setup'),
                ('name', '=', key + '_company_' + str(company_id)),
            ])
            check('exact_fixture_identity_' + key, len(xmlid) == 1 and xmlid.model == model)
            record = E[model].browse(xmlid.res_id).exists()
            owned = (record.company_ids.ids == [company_id] if model == 'account.account'
                     else record.company_id.id == company_id)
            check('exclusive_unused_fixture_record_' + key, bool(record) and owned
                  and not E['account.move.line'].search_count([
                      ('account_id' if model == 'account.account' else 'journal_id', '=', record.id)]))
            targets.append((xmlid, record))
        company.write({name: False for name in MAPPINGS})
        for xmlid, record in targets:
            xmlid.unlink()
            record.unlink()
        E.flush_all()
        baseline = snapshot(E, company)
        check('all_seven_settings_empty_before_race', not any(baseline['settings'].values()))
        check('native_chart_preserved_before_race', baseline['chart_template'] == 'sa' and bool(baseline['accounts']))
        cursor.commit()
    return company_id, baseline


def prepare(company_id, barrier):
    retries = []
    for attempt in range(1, 6):
        try:
            with REGISTRY.cursor() as cursor:
                E = environment(cursor, company_id)
                company = E['res.company'].browse(company_id)
                if attempt == 1:
                    if any(mapping(company).values()):
                        raise AssertionError('Both workers must see blank settings initially')
                    cursor.execute('SELECT pg_backend_pid(), txid_current_snapshot()::text')
                    backend_pid, transaction_snapshot = cursor.fetchone()
                    barrier.wait(timeout=30)
                company._baseer_prepare_accounting()
                E.flush_all()
                values = mapping(company)
                if not all(values.values()):
                    raise AssertionError('Seed left required accounting mappings empty')
                cursor.commit()
                return {'backend_pid': backend_pid, 'initial_snapshot': transaction_snapshot,
                        'attempts': attempt, 'retries': retries, 'settings': values}
        except psycopg2.Error as error:
            collision = error.pgcode == '23505' and error.diag.table_name in (
                'account_account', 'account_journal', 'ir_model_data')
            if error.pgcode not in ('40001', '40P01') and not collision:
                raise
            retries.append({'attempt': attempt, 'sqlstate': error.pgcode,
                            'constraint': error.diag.constraint_name,
                            'table': error.diag.table_name})
            if attempt == 5:
                raise
            time.sleep(0.05 * attempt)


try:
    company_id, baseline = fixture()
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='company-seed-race') as pool:
        futures = [pool.submit(prepare, company_id, barrier) for _ in range(2)]
        outcomes = [future.result(timeout=120) for future in futures]
    RESULT['workers'] = outcomes
    check('two_independent_database_connections', len({row['backend_pid'] for row in outcomes}) == 2)
    check('both_workers_return_same_settings', outcomes[0]['settings'] == outcomes[1]['settings'])
    check('actual_collision_retry_observed', any(row['retries'] for row in outcomes))
    with REGISTRY.cursor() as cursor:
        E = environment(cursor, company_id)
        company = E['res.company'].browse(company_id)
        final = snapshot(E, company)
        check('persisted_settings_equal_both_workers', final['settings'] == outcomes[0]['settings'])
        check('all_seven_settings_ready', all(final['settings'].values()))
        check('same_native_sa_chart', final['chart_template'] == baseline['chart_template'] == 'sa')
        check('exactly_two_new_accounts', len(final['accounts']) == len(baseline['accounts']) + 2)
        check('exactly_one_new_payroll_journal', len(final['journals']) == len(baseline['journals']) + 1)
        check('native_chart_accounts_unchanged', all(final['accounts'].get(key) == value for key, value in baseline['accounts'].items()))
        check('native_starter_journals_unchanged', all(final['journals'].get(key) == value for key, value in baseline['journals'].items()))
        check('no_new_accounting_moves', final['move_ids'] == baseline['move_ids'])
        for key, model in CREATED_KEYS.items():
            name = key + '_company_' + str(company_id)
            records = E['ir.model.data'].search([('module', '=', 'baseer_company_setup'), ('name', '=', name)])
            target_field = 'baseer_payroll_journal_id' if key == 'payroll' else key
            check('one_canonical_identity_' + key, len(records) == 1
                  and records.model == model and records.res_id == company[target_field].id and records.noupdate)
        for name, value in baseline['identities'].items():
            check('prior_fixture_identity_preserved_' + name, final['identities'].get(name) == value)
        check('payroll_payable_reconcilable', company.baseer_salary_payable_id.account_type == 'liability_payable'
              and company.baseer_salary_payable_id.reconcile)
        check('employee_advances_reconcilable', company.baseer_loan_account_id.account_type == 'asset_receivable'
              and company.baseer_loan_account_id.reconcile)
        check('all_setting_records_company_owned', all(
            company.id in company[field].company_ids.ids for field in MAPPINGS if field.endswith('account_id') or field.endswith('expense_id') or field == 'baseer_salary_payable_id')
            and company.baseer_payroll_journal_id.company_id == company
            and company.baseer_eos_journal_id.company_id == company)
        company._baseer_prepare_accounting()
        E.flush_all()
        check('replay_exactly_stable', snapshot(E, company) == final)
        cursor.commit()
    RESULT['status'] = 'passed'
except Exception:
    RESULT['status'] = 'failed'
    RESULT['traceback'] = traceback.format_exc()
    raise
finally:
    OUTPUT.write_text(json.dumps(RESULT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(RESULT, ensure_ascii=False, indent=2))
