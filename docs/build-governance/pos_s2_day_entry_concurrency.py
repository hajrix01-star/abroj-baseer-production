"""Independent QA proof: two saves of one entry create two drafts only once."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import perf_counter
from odoo import api, Command
from odoo.service.model import retrying

assert env.cr.dbname == 'baseer_reports_qa_20260907'
registry, uid = env.registry, env.ref('base.user_admin').id
context = {'allowed_company_ids': [6], 'lang': 'en_US'}
date, entry_id = '2038-04-24', None
results = []
try:
    with registry.cursor() as cr:
        qa = api.Environment(cr, uid, context)
        assert not qa['baseer.pos.summary'].search_count([('company_id', '=', 6), ('business_date', '=', date)])
        assert not qa['baseer.pos.closure'].search_count([('company_id', '=', 6), ('date_from', '<=', date), ('date_to', '>=', date)])
        config = qa['baseer.pos.summary']._default_config()
        method = config.payment_method_ids[:1]
        assert method
        entry = qa['baseer.pos.day.entry'].create({'business_date': date, 'day_schedule': 'split',
            'first_customers': 10, 'second_customers': 20,
            'first_allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': 115})],
            'second_allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': 230})]})
        entry_id = entry.id
        cr.commit()
    barrier = Barrier(2)
    def worker():
        with registry.cursor() as cr:
            qa = api.Environment(cr, uid, context)
            attempts = []
            barrier.wait(timeout=20)
            started = perf_counter()
            def attempt():
                attempts.append(1)
                return qa['baseer.pos.day.entry'].browse(entry_id).action_save()
            result = retrying(attempt, qa)
            return {'result': result, 'attempts': len(attempts), 'seconds': perf_counter()-started}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker), pool.submit(worker)]
        results = [future.result(timeout=120) for future in futures]
    assert all(row['result']['res_id'] == entry_id for row in results)
    with registry.cursor() as cr:
        qa = api.Environment(cr, uid, context)
        entry = qa['baseer.pos.day.entry'].browse(entry_id)
        records = qa['baseer.pos.summary'].search([('company_id', '=', 6), ('business_date', '=', date)])
        assert entry.state == 'saved' and len(records) == 2 and set(records.ids) == set(entry.saved_summary_ids.ids)
        assert set(records.mapped('period_scope')) == {'morning', 'evening'}
        assert sum(records.mapped('amount_gross')) == 345 and sum(records.mapped('customer_count')) == 30
        assert all(row.state == 'draft' and not row.order_id and not row.session_id for row in records)
        saved_ids = records.ids
finally:
    if entry_id:
        with registry.cursor() as cr:
            qa = api.Environment(cr, uid, context)
            entry = qa['baseer.pos.day.entry'].browse(entry_id).exists()
            records = qa['baseer.pos.summary'].search([('company_id', '=', 6), ('business_date', '=', date)])
            assert all(row.state == 'draft' and not row.order_id and not row.session_id for row in records)
            # Exact test-only transient; ordinary saved entries remain immutable.
            cr.execute('DELETE FROM baseer_pos_day_entry WHERE id=%s AND company_id=6', [entry_id])
            records.unlink()
            cr.commit()
            assert not qa['baseer.pos.summary'].search_count([('company_id', '=', 6), ('business_date', '=', date)])

payload = {'passed': True, 'requests': results, 'created_summary_ids': saved_ids,
           'assertions': 'Both requests return same entry; exactly two original drafts, gross345/customers30; no native financial documents; fixtures cleaned.'}
Path('/mnt/qa-evidence/pos_s2_day_entry_concurrency.json').write_text(json.dumps(payload, indent=2))
print('POS_S2_DAY_ENTRY_CONCURRENCY_OK', json.dumps(payload))
