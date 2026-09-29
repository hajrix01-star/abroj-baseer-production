"""SP1 two-company race against one absent shared identity, disposable DB only.

Reviewer authored. Commits synthetic master fixtures inside the disposable clone;
the release lead creates and deletes the clone. Never run against QA/main.
"""
import json
import time
import traceback
from pathlib import Path
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor

import psycopg2
from odoo import api


assert env.cr.dbname == 'baseer_shared_partners_race', 'Disposable SP1 clone only'
R = {'status': 'started', 'checks': [], 'fixture_key': 'sp1_race'}
registry = env.registry
uid = env.ref('base.user_admin').id
PROVIDER = ('sp1_race', 'جهة تجربة تزامن الشركات', 'SP1 Cross Company Race Provider',
            'government', None, None)
XML_NAME = 'provider_sp1_race'


def E(cr, company_id):
    return api.Environment(cr, uid, {
        'allowed_company_ids': [company_id], 'lang': 'en_US', 'tracking_disable': True})


def check(name, result):
    R['checks'].append({'name': name, 'passed': bool(result)})
    assert result, name


def financial_fingerprint(cr):
    result = {}
    for table in ('account_move', 'account_move_line', 'account_payment', 'account_partial_reconcile'):
        cr.execute("SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM " + table + ' t')
        result[table] = cr.fetchone()
    return result


try:
    with registry.cursor() as cr:
        C = E(cr, 6)
        check('initial_global_identity_absent', not C['ir.model.data'].search_count([
            ('module', '=', 'baseer_service_seed'), ('name', '=', XML_NAME)]))
        check('initial_fixture_contact_absent', not C['res.partner'].with_context(active_test=False).search_count([
            ('ref', '=', PROVIDER[2])]))
        before = financial_fingerprint(cr)

    barrier = Barrier(2)

    def prepare(company_id):
        retries = []
        start = time.monotonic()
        first_pid = None
        for attempt in range(5):
            try:
                with registry.cursor() as cr:
                    C = E(cr, company_id)
                    company = C['res.company'].browse(company_id)
                    if attempt == 0:
                        # The read establishes each transaction's original MVCC
                        # snapshot before either worker takes the global lock.
                        assert not C['ir.model.data'].search_count([
                            ('module', '=', 'baseer_service_seed'), ('name', '=', XML_NAME)])
                        cr.execute('SELECT pg_backend_pid()')
                        first_pid = cr.fetchone()[0]
                        barrier.wait(timeout=20)
                    partner = company._baseer_canonical_provider(PROVIDER)
                    C.flush_all()
                    result = {'company_id': company_id, 'pid': first_pid, 'partner_id': partner.id,
                              'shared': not partner.company_id, 'retries': retries,
                              'seconds': round(time.monotonic() - start, 4)}
                    cr.commit()
                    return result
            except psycopg2.Error as exc:
                if exc.pgcode not in ('40001', '40P01'):
                    raise
                retries.append(exc.pgcode)
                if attempt == 4:
                    raise

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(prepare, company_id) for company_id in (6, 10)]
        results = [future.result(timeout=50) for future in futures]
    R['workers'] = results
    check('different_company_contexts', {r['company_id'] for r in results} == {6, 10})
    check('independent_connections', results[0]['pid'] != results[1]['pid'])
    check('same_shared_provider_from_both_calls', results[0]['partner_id'] == results[1]['partner_id'] and all(r['shared'] for r in results))
    check('actual_serialization_retry_observed', any('40001' in r['retries'] for r in results))

    with registry.cursor() as cr:
        C = E(cr, 6)
        identities = C['ir.model.data'].search([
            ('module', '=', 'baseer_service_seed'), ('name', '=', XML_NAME)])
        check('exactly_one_global_xmlid', len(identities) == 1 and identities.model == 'res.partner')
        partners = C['res.partner'].with_context(active_test=False).search([('ref', '=', PROVIDER[2])])
        check('exactly_one_shared_contact', len(partners) == 1 and not partners.company_id and partners.id == identities.res_id)
        check('canonical_has_no_parent', not partners.parent_id and partners.commercial_partner_id == partners)
        check('canonical_bilingual_fields', partners.baseer_name_ar == PROVIDER[1] and partners.baseer_name_en == PROVIDER[2])
        check('canonical_bilingual_name', PROVIDER[1] in partners.name and PROVIDER[2] in partners.name)
        check('canonical_supplier_and_no_assumed_vat', partners.supplier_rank > 0 and not partners.vat)
        check('provider_visible_from_second_company', E(cr, 10)['res.partner'].browse(partners.id).read(['name'])[0]['name'] == partners.name)
        for company_id in (6, 10):
            repeated = E(cr, company_id)['res.company'].browse(company_id)._baseer_canonical_provider(PROVIDER)
            check('idempotent_repeat_company_' + str(company_id), repeated.id == partners.id)
        check('no_financial_history_changed', financial_fingerprint(cr) == before)
        # No new work from this verification needs persistence; the two worker
        # commits above are intentionally confined to this disposable clone.
        cr.rollback()
    R['status'] = 'passed'
except Exception:
    R['status'] = 'failed'
    R['traceback'] = traceback.format_exc()
finally:
    R['check_count'] = len(R['checks'])
    R['cleanup_required'] = 'Drop disposable database baseer_shared_partners_race after collecting evidence.'
    Path('/mnt/qa-evidence/shared_partners_concurrency.json').write_text(
        json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False))
