"""Real two-cursor concurrency on dedicated committed QA fixtures, native retry corridor."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
from pathlib import Path
from time import perf_counter
from odoo import api
from odoo.service.model import retrying
from odoo.exceptions import UserError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
out = Path('/mnt/qa-evidence')
ids = json.loads((out / 'purchase_batch_preview_ids.json').read_text())
uid = env.ref('base.user_admin').id
registry = env.registry
env.cr.rollback()
results = []

def run_pair(batch_ids, case):
    barrier = Barrier(2)
    def approve(ident):
        with registry.cursor() as cr:
            local = api.Environment(cr, uid, {'allowed_company_ids': [ids['company_id']], 'tracking_disable': True, 'lang': 'en_US'})
            barrier.wait(timeout=15)
            start = perf_counter()
            try:
                retrying(lambda: local['baseer.purchase.batch'].browse(ident).action_approve(), local)
                return {'id': ident, 'approved': True, 'seconds': perf_counter() - start}
            except UserError as exc:
                cr.rollback()
                return {'id': ident, 'approved': False, 'error': str(exc), 'seconds': perf_counter() - start}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(approve, ident) for ident in batch_ids]
        pair = [future.result(timeout=90) for future in futures]
    results.append({'case': case, 'requests': pair})
    return pair

same = run_pair([ids['same_batch_id']] * 2, 'same persisted batch double click')
assert all(r['approved'] for r in same), same
duplicate = run_pair(ids['duplicate_batch_ids'], 'two batches same normalized supplier reference')
assert sum(r['approved'] for r in duplicate) == 1, duplicate
separate = run_pair(ids['separate_batch_ids'], 'two different bills in same company')
assert all(r['approved'] for r in separate), separate
with registry.cursor() as cr:
    local = api.Environment(cr, uid, {'allowed_company_ids': [ids['company_id']]})
    batch = local['baseer.purchase.batch'].browse(ids['same_batch_id'])
    assert batch.state == 'approved' and len(batch.line_ids.move_id) == 1 and len(batch.line_ids.payment_id) == 1
    duplicate_batches = local['baseer.purchase.batch'].browse(ids['duplicate_batch_ids'])
    assert len(duplicate_batches.line_ids.move_id) == 1 and len(duplicate_batches.line_ids.payment_id) == 1
    assert len(local['baseer.purchase.batch'].browse(ids['separate_batch_ids']).line_ids.move_id) == 2
(out / 'purchase_batch_concurrency.json').write_text(json.dumps({'passed': True, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
print('PB1_CONCURRENCY_OK', results)
