"""CSS1 real concurrent initial seeding, disposable clone database only.

This harness commits fixtures solely in baseer_service_seed_race. Root creates
and drops that clone. It must never be pointed at QA or the main database.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier
import time
import traceback

import psycopg2
from odoo import api

TARGET = 'baseer_service_seed_race'
if env.cr.dbname != TARGET:
    raise RuntimeError('Refusing committed fixtures outside ' + TARGET)
OUTPUT = Path('/mnt/qa-evidence/common_services_seed_concurrency.json')
R = {'database': TARGET, 'status': 'started', 'checks': []}
REGISTRY = env.registry
ADMIN_ID = env.ref('base.user_admin').id
ORIGINAL_COMPANY_ID = env.company.id
FIXTURE = 'CSS1 RACE isolated company'
CTX = {'lang': 'en_US', 'active_test': False, 'tracking_disable': True,
       'mail_notrack': True, 'mail_create_nosubscribe': True, 'mail_notify_force_send': False}


def check(name, condition):
    R['checks'].append({'name': name, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(name)


def environment(cr, company_id=ORIGINAL_COMPANY_ID):
    if cr.dbname != TARGET:
        raise RuntimeError('Unexpected cursor database')
    return api.Environment(cr, ADMIN_ID, dict(CTX, allowed_company_ids=[company_id]), su=True)


def data(E, company_id):
    return E['ir.model.data'].search([('module', '=', 'baseer_service_seed'),
        ('name', '=like', '%_company_' + str(company_id))], order='name')


def records(E, company_id, model):
    return E[model].browse(data(E, company_id).filtered(lambda d: d.model == model).mapped('res_id')).exists()


def snapshot(E, company):
    return {
        'chart': company.chart_template,
        'identities': {d.name: [d.model, d.res_id, d.noupdate] for d in data(E, company.id)},
        'providers': records(E, company.id, 'res.partner').ids,
        'products': records(E, company.id, 'product.product').ids,
        'mappings': records(E, company.id, 'baseer.purchase.category.map').ids,
        'accounts': {a.id: [a.code, a.name, a.account_type, a.active, a.company_ids.ids]
                     for a in E['account.account'].search([('company_ids', 'in', company.id)], order='id')},
        'journals': E['account.journal'].search([('company_id', '=', company.id)], order='id').ids,
        'financial_moves': E['account.move'].search([]).ids,
    }


def fixture():
    with REGISTRY.cursor() as cr:
        E = environment(cr)
        check('fresh_disposable_fixture', not E['res.company'].search_count([('name', '=', FIXTURE)]))
        company = E['res.company'].create({'name': FIXTURE, 'country_id': E.ref('base.sa').id,
                                           'currency_id': E.ref('base.SAR').id})
        cr.precommit.run()
        E.flush_all()
        company_id = company.id
        check('native_company_initially_seeded', len(records(E, company_id, 'res.partner')) == 20)
        cr.commit()
        R['fixture_company_id'] = company_id
        R['fixtures_committed'] = True
    with REGISTRY.cursor() as cr:
        E = environment(cr, company_id)
        company = E['res.company'].browse(company_id)
        check('fixture_name_and_sa_ownership', company.name == FIXTURE and not company.parent_id
              and company.chart_template == 'sa')
        check('fixture_no_financial_usage', not E['account.move'].search_count([('company_id', '=', company_id)]))
        identities = data(E, company_id)
        seeded_accounts = records(E, company_id, 'account.account')
        # Preserve every native account; only a purpose account with no native
        # localization identity, no history and this sole owner can be removed.
        removable_accounts = E['account.account']
        for account in seeded_accounts:
            native = E['ir.model.data'].search_count([('module', '=', 'account'), ('model', '=', 'account.account'),
                ('res_id', '=', account.id), ('name', '=like', str(company_id) + '_sa_account_%')])
            if not native:
                check('unused_private_seed_account_' + str(account.id), account.company_ids.ids == [company_id]
                      and not E['account.move.line'].search_count([('account_id', '=', account.id)]))
                removable_accounts |= account
        for model in ('res.partner', 'baseer.purchase.category.map', 'product.product'):
            owned = records(E, company_id, model)
            check('exact_private_cleanup_' + model, bool(owned) and all(r.company_id == company for r in owned))
            owned.unlink()
        identities.unlink()
        removable_accounts.unlink()
        E.flush_all()
        baseline = snapshot(E, company)
        check('empty_service_seed_before_race', not baseline['identities'] and not baseline['providers']
              and not baseline['products'] and not baseline['mappings'])
        cr.commit()
    return company_id, baseline


def prepare(company_id, barrier):
    retries = []
    began = time.monotonic()
    for attempt in range(1, 6):
        try:
            with REGISTRY.cursor() as cr:
                E = environment(cr, company_id)
                company = E['res.company'].browse(company_id)
                if attempt == 1:
                    if data(E, company_id):
                        raise AssertionError('Workers must both observe the initially empty seed')
                    cr.execute('SELECT pg_backend_pid(), txid_current_snapshot()::text')
                    backend_pid, initial_snapshot = cr.fetchone()
                    barrier.wait(timeout=30)
                company._baseer_prepare_accounting()
                E.flush_all()
                final = snapshot(E, company)
                if len(final['providers']) != 20 or len(final['products']) != 26 or len(final['mappings']) != 26:
                    raise AssertionError('Incomplete concurrent service seed')
                cr.commit()
                return {'backend_pid': backend_pid, 'initial_snapshot': initial_snapshot,
                        'attempts': attempt, 'retries': retries, 'snapshot': final,
                        'seconds': round(time.monotonic() - began, 6)}
        except psycopg2.Error as error:
            if error.pgcode not in ('40001', '40P01'):
                raise
            retries.append({'attempt': attempt, 'sqlstate': error.pgcode})
            if attempt == 5:
                raise
            time.sleep(0.05 * attempt)


try:
    company_id, baseline = fixture()
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='service-seed-race') as pool:
        futures = [pool.submit(prepare, company_id, barrier) for _ in range(2)]
        outcomes = [future.result(timeout=120) for future in futures]
    R['workers'] = outcomes
    check('two_independent_connections', len({o['backend_pid'] for o in outcomes}) == 2)
    check('observed_real_mvcc_retry', any(o['retries'] for o in outcomes))
    check('both_workers_same_canonical_records', outcomes[0]['snapshot'] == outcomes[1]['snapshot'])
    check('initial_localized_seed_under_15_seconds', min(o['seconds'] for o in outcomes) < 15)
    with REGISTRY.cursor() as cr:
        E = environment(cr, company_id)
        company = E['res.company'].browse(company_id)
        final = snapshot(E, company)
        check('persisted_result_matches_workers', final == outcomes[0]['snapshot'])
        check('exactly_20_private_providers', len(final['providers']) == 20)
        check('exactly_26_products_and_mappings', len(final['products']) == len(final['mappings']) == 26)
        check('native_chart_accounts_preserved', final['chart'] == baseline['chart'] == 'sa'
              and all(final['accounts'].get(k) == v for k, v in baseline['accounts'].items()))
        check('native_journals_preserved', final['journals'] == baseline['journals'])
        check('no_new_financial_documents', final['financial_moves'] == baseline['financial_moves'])
        check('all_identities_unique_and_noupdate', all(value[2] for value in final['identities'].values())
              and len(data(E, company_id)) == len(final['identities']))
        company._baseer_prepare_accounting()
        E.flush_all()
        check('full_replay_stable', snapshot(E, company) == final)
        cr.commit()
    R['status'] = 'passed'
except Exception:
    R['status'] = 'failed'
    R['traceback'] = traceback.format_exc()
    raise
finally:
    R['check_count'] = len(R['checks'])
    OUTPUT.write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False, indent=2))
