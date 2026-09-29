"""QA native two-cursor replay/lock proof; explicit zero-day fixtures only.

Positive one-step posting and rollback are covered by pos_s3_checks. These
committed concurrency fixtures avoid adding any native financial documents.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import perf_counter
from odoo import api
from odoo.service.model import retrying

assert env.cr.dbname == 'baseer_reports_qa_20260907'
registry, uid = env.registry, env.ref('base.user_admin').id
context = {'allowed_company_ids': [6], 'lang': 'en_US'}
dates = ['2038-04-25', '2038-04-26']
entry_ids, original_ids, results = [], [], []

def pair(label, functions):
    barrier = Barrier(2)
    def worker(fn):
        with registry.cursor() as cr:
            local = api.Environment(cr, uid, context)
            attempts = []
            barrier.wait(timeout=20)
            started = perf_counter()
            def attempt():
                attempts.append(1)
                return fn(local)
            value = retrying(attempt, local)
            return {'result': value, 'attempts': len(attempts), 'seconds': perf_counter()-started}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, fn) for fn in functions]
        rows = [future.result(timeout=120) for future in futures]
    results.append({'case': label, 'requests': rows})

try:
    with registry.cursor() as cr:
        qa = api.Environment(cr, uid, context)
        assert not qa['baseer.pos.summary'].search_count([('company_id', '=', 6), ('business_date', 'in', dates)])
        assert not qa['baseer.pos.closure'].search_count([('company_id', '=', 6), ('date_from', '<=', dates[-1]), ('date_to', '>=', dates[0])])
        for date in dates:
            entry = qa['baseer.pos.day.entry'].create({'business_date': date, 'day_schedule': 'split', 'first_zero_sales': True, 'second_zero_sales': True})
            entry_ids.append(entry.id)
        saved = qa['baseer.pos.day.entry'].browse(entry_ids[1])
        saved.action_save()
        independent_id = saved.saved_summary_ids.sorted('id')[0].id
        cr.commit()
    pair('same fresh entry one-step Save twice', [
        lambda local: local['baseer.pos.day.entry'].browse(entry_ids[0]).action_save_and_approve(),
        lambda local: local['baseer.pos.day.entry'].browse(entry_ids[0]).action_save_and_approve()])
    pair('saved entry Save versus independent original approval', [
        lambda local: local['baseer.pos.day.entry'].browse(entry_ids[1]).action_save_and_approve(),
        lambda local: local['baseer.pos.summary'].browse(independent_id).action_approve()])
    with registry.cursor() as cr:
        qa = api.Environment(cr, uid, context)
        for entry_id, date in zip(entry_ids, dates):
            entry = qa['baseer.pos.day.entry'].browse(entry_id)
            summaries = qa['baseer.pos.summary'].search([('company_id', '=', 6), ('business_date', '=', date)])
            assert entry.state == 'approved' and len(summaries) == 2
            assert set(summaries.ids) == set(entry.saved_summary_ids.ids)
            assert set(summaries.mapped('period_scope')) == {'morning', 'evening'}
            assert all(row.state == 'approved' and row.zero_sales and not row.order_id and not row.session_id for row in summaries)
            original_ids.extend(summaries.ids)
finally:
    if entry_ids:
        with registry.cursor() as cr:
            qa = api.Environment(cr, uid, context)
            fixtures = qa['baseer.pos.summary'].search([('company_id', '=', 6), ('business_date', 'in', dates)])
            assert all(row.zero_sales and not row.order_id and not row.session_id for row in fixtures)
            cr.execute('DELETE FROM baseer_pos_day_entry WHERE id IN %s AND company_id=6', [tuple(entry_ids)])
            # Only exact explicit-zero acceptance fixtures; no production audit
            # mutation capability is introduced into application code.
            if fixtures:
                cr.execute('DELETE FROM baseer_pos_summary WHERE id IN %s AND company_id=6', [tuple(fixtures.ids)])
            cr.commit()
            assert not qa['baseer.pos.summary'].search_count([('company_id', '=', 6), ('business_date', 'in', dates)])

payload = {'passed': True, 'cases': results, 'original_summary_ids': original_ids,
           'scope': 'Explicit zero sales tests lock/replay paths without native financial documents. Positive posting/late rollback separately covered by pos_s3_checks.',
           'cleanup': 'Exact entries and zero-summary fixtures removed.'}
Path('/mnt/qa-evidence/pos_s3_concurrency.json').write_text(json.dumps(payload, indent=2))
print('POS_S3_CONCURRENCY_OK', json.dumps(payload))
