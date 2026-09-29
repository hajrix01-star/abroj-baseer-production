"""Two real QA sessions: payment amount edit versus summary confirmation."""
import json
import threading
from pathlib import Path
from odoo import api
from odoo.exceptions import UserError
from psycopg2.errors import SerializationFailure

assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
meta = json.loads(Path('/mnt/qa-evidence/ic2-ui-fixtures-summary.json').read_text())
uid = meta['owner_id']
ctx = {'allowed_company_ids': [meta['company_id']], 'lang': 'en_US', 'tracking_disable': True}
actor = env(user=uid, su=False, context=ctx)
summary = actor['baseer.pos.summary'].browse(meta['summary_race']['id'])
wizard = actor['baseer.pos.summary.correction'].browse(summary.action_open_correction()['res_id'])
wizard.write({'reason': 'IC2 isolated concurrent amount edit', 'acknowledge_bookkeeping': True})
line = wizard.line_ids.sorted('id')[0]
original = float(line.amount_input)
changed = original + 100
line_id, wizard_id, summary_id = line.id, wizard.id, summary.id
env.cr.commit()  # Explicitly authorized isolated QA fixture only.
barrier = threading.Barrier(2)
results = []

def run(kind):
    try:
        for attempt in range(3):
            with env.registry.cursor() as cr:
                local = api.Environment(cr, uid, ctx)
                try:
                    request = local['baseer.pos.summary.correction'].browse(wizard_id)
                    request.read(['completed'])
                    if attempt == 0:
                        barrier.wait(timeout=15)
                    if kind == 'edit':
                        local['baseer.pos.summary.correction.line'].browse(line_id).write({'amount_input': str(changed)})
                    else:
                        request.action_correct()
                    cr.commit()
                    results.append({'kind': kind, 'status': 'committed', 'attempt': attempt + 1})
                    return
                except SerializationFailure:
                    cr.rollback()
                except UserError as error:
                    cr.rollback()
                    results.append({'kind': kind, 'status': 'rejected', 'message': str(error)})
                    return
        raise AssertionError('Serialization retry exhausted')
    except Exception as error:
        results.append({'kind': kind, 'status': 'error', 'message': repr(error)})

threads = [threading.Thread(target=run, args=(kind,)) for kind in ('edit', 'confirm')]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(timeout=40)
assert not any(thread.is_alive() for thread in threads), 'Deadlock'
env.cr.rollback()
env.invalidate_all()
assert next(row for row in results if row['kind'] == 'confirm')['status'] == 'committed', results
edit_status = next(row for row in results if row['kind'] == 'edit')['status']
assert edit_status in ('committed', 'rejected'), results
assert summary.state == 'cancelled' and summary.replacement_id.state == 'approved', summary.state
expected = changed if edit_status == 'committed' else original
allocation = summary.replacement_id.allocation_ids.filtered(lambda item: item.payment_method_id == line.payment_method_id)
assert allocation.amount == expected and float(line.amount_input) == expected
assert wizard.completed and wizard.audit_id
report = {'status': 'PASS', 'results': results, 'database': env.cr.dbname,
          'expected_amount': expected, 'replacement_amount': allocation.amount,
          'request_matches_posting': True, 'qa_fixture_committed': True, 'main_untouched': True}
Path('/mnt/qa-evidence/ic2-summary-concurrency.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
env.cr.rollback()
