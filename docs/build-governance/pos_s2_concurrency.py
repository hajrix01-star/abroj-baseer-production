"""QA-only real transactions: closure/summary race; exact fixture cleanup."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import perf_counter

from odoo import api, Command
from odoo.exceptions import UserError
from odoo.service.model import retrying

assert env.cr.dbname == 'baseer_reports_qa_20260907'
registry = env.registry
uid = env.ref('base.user_admin').id
context = {'allowed_company_ids': [6], 'lang': 'en_US'}
summary_ids, closure_ids, results = [], [], []
dates = ['2038-04-21', '2038-04-22', '2038-04-23']

def pair(label, functions):
    barrier = Barrier(2)
    def worker(fn):
        with registry.cursor() as cr:
            local = api.Environment(cr, uid, context)
            barrier.wait(timeout=20)
            started = perf_counter()
            attempts = []
            def attempt():
                attempts.append(1)
                return fn(local)
            try:
                value = retrying(attempt, local)
                return {'ok': True, 'value': value, 'attempts': len(attempts), 'seconds': perf_counter() - started}
            except UserError as exc:
                cr.rollback()
                return {'ok': False, 'error': str(exc), 'attempts': len(attempts), 'seconds': perf_counter() - started}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, fn) for fn in functions]
        rows = [future.result(timeout=120) for future in futures]
    results.append({'case': label, 'requests': rows})
    assert sum(row['ok'] for row in rows) == 1, rows
    return rows

try:
    with registry.cursor() as cr:
        qa = api.Environment(cr, uid, context)
        assert not qa['baseer.pos.summary'].search_count([('company_id', '=', 6), ('business_date', 'in', dates)])
        assert not qa['baseer.pos.closure'].search_count([('company_id', '=', 6), ('date_from', '<=', dates[-1]), ('date_to', '>=', dates[0])])
        config = qa['pos.config'].search([('company_id', '=', 6), ('baseer_summary_only', '=', True)], limit=1)
        method_id = config.payment_method_ids[:1].id
        assert config and method_id
        for date in dates:
            closure = qa['baseer.pos.closure'].create({'date_from': date, 'date_to': date, 'period_scope': 'all', 'reason': 'other', 'notes': 'S2 isolated concurrency acceptance fixture'})
            closure_ids.append(closure.id)
        cr.commit()
    for date, closure_id in zip(dates[:2], closure_ids[:2]):
        def create_summary(local):
            record = local['baseer.pos.summary'].create({'business_date': date, 'period_scope': 'all', 'day_schedule': 'all', 'customer_count': 1,
                'allocation_ids': [Command.create({'payment_method_id': method_id, 'amount': 115})]})
            return record.id
        pair('closure confirm versus summary create ' + date, [
            lambda local: local['baseer.pos.closure'].browse(closure_id).action_confirm(), create_summary])
        with registry.cursor() as cr:
            qa = api.Environment(cr, uid, context)
            found = qa['baseer.pos.summary'].search([('company_id', '=', 6), ('business_date', '=', date)])
            summary_ids.extend(found.ids)
            closure = qa['baseer.pos.closure'].browse(closure_id)
            assert (closure.state == 'confirmed') != bool(found)
            assert all(row.state == 'draft' and not row.order_id and not row.session_id for row in found)
    # Separate drafts can coexist; confirmation is the exclusive transition.
    with registry.cursor() as cr:
        qa = api.Environment(cr, uid, context)
        duplicate = qa['baseer.pos.closure'].create({'date_from': dates[2], 'date_to': dates[2], 'period_scope': 'morning', 'reason': 'other', 'notes': 'S2 isolated competing confirm fixture'})
        duplicate_id = duplicate.id
        closure_ids.append(duplicate_id)
        cr.commit()
    pair('two overlapping closure confirmations', [
        lambda local: local['baseer.pos.closure'].browse(closure_ids[2]).action_confirm(),
        lambda local: local['baseer.pos.closure'].browse(duplicate_id).action_confirm()])
finally:
    with registry.cursor() as cr:
        qa = api.Environment(cr, uid, context)
        # Only fixture dates confirmed empty above; capture a successful request
        # even if a later assertion prevented collection of its returned ID.
        fixture_summaries = qa['baseer.pos.summary'].search([('company_id', '=', 6), ('business_date', 'in', dates)]) if closure_ids else qa['baseer.pos.summary']
        assert all(row.state == 'draft' and not row.order_id and not row.session_id for row in fixture_summaries)
        fixture_summaries.unlink()
        for closure in qa['baseer.pos.closure'].browse(closure_ids).exists():
            if closure.state == 'confirmed':
                closure.write({'cancellation_reason': 'Acceptance fixture cleanup'})
                closure.action_cancel()
            if closure.state == 'draft':
                closure.unlink()
            else:
                # Production audit rows remain immutable. This removes only
                # exact IDs generated by this isolated acceptance script.
                cr.execute('DELETE FROM baseer_pos_closure WHERE id=%s AND company_id=6', [closure.id])
        cr.commit()
        assert not qa['baseer.pos.summary'].search_count([('company_id', '=', 6), ('business_date', 'in', dates)])
        assert not qa['baseer.pos.closure'].search_count([('id', 'in', closure_ids)])

payload = {'passed': True, 'cases': results, 'cleanup': 'All exact fixture summaries/closures removed; no native financial documents created.'}
Path('/mnt/qa-evidence/pos_s2_concurrency.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
print('POS_S2_CONCURRENCY_OK', json.dumps(payload))
