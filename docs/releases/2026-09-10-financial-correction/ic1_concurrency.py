"""Two real database sessions confirm competing QA corrections of one invoice."""
import json
import threading
from unittest.mock import patch
from pathlib import Path
from odoo import api
from odoo.exceptions import UserError
from psycopg2.errors import SerializationFailure
assert env.cr.dbname == 'baseer_ic1_20260910' and env.su
meta = json.loads(Path('/mnt/qa-evidence/ic1-ui-fixtures.json').read_text())
context = {'allowed_company_ids':[meta['company_id']], 'lang':'en_US','tracking_disable':True}
actor = env(user=meta['user_ids']['accountant'], su=False, context=context)
source = actor['account.move'].browse(meta['move_id'])
invoice = source.copy({'ref':'IC1 QA competing corrections','invoice_date':source.invoice_date})
invoice.action_post()
wizard_ids = []
for amount in ('500.00','600.00'):
    action = invoice.action_baseer_correct_operation()
    wizard = actor['baseer.financial.correction'].browse(action['res_id'])
    wizard.write({'reason':'IC1 QA concurrent correction '+amount})
    wizard.line_ids.write({'price_unit_input':amount})
    wizard_ids.append(wizard.id)
env.cr.commit()
registry, dbname = env.registry, env.cr.dbname
barrier = threading.Barrier(2)
results = []

def confirm(wizard_id):
    for attempt in range(3):
        with registry.cursor() as cursor:
            local = api.Environment(cursor, meta['user_ids']['accountant'], context)
            try:
                wizard = local['baseer.financial.correction'].browse(wizard_id)
                wizard.read(['completed'])
                if attempt == 0:
                    barrier.wait(timeout=15)
                wizard.action_confirm()
                cursor.commit()
                results.append({'wizard':wizard_id,'status':'committed','attempts':attempt+1})
                return
            except SerializationFailure:
                cursor.rollback()
                if attempt == 2:
                    raise
            except UserError as error:
                cursor.rollback()
                assert 'source changed' in str(error).lower(), str(error)
                results.append({'wizard':wizard_id,'status':'stale_rejected','attempts':attempt+1})
                return

threads = [threading.Thread(target=confirm,args=(wizard_id,)) for wizard_id in wizard_ids]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(timeout=30)
assert not any(thread.is_alive() for thread in threads), 'Concurrent confirmation deadlocked'
env.cr.rollback()
env.invalidate_all()
invoice = actor['account.move'].browse(invoice.id)
audits = actor['baseer.financial.correction.audit'].search([('move_id','=',invoice.id)])
assert sorted(item['status'] for item in results) == ['committed','stale_rejected'], results
assert len(audits) == 1 and invoice.amount_total in (500,600) and invoice.state == 'posted'
assert sum(invoice.line_ids.mapped('balance')) == 0
report = {'status':'PASS','database':dbname,'results':results,'audit_count':len(audits),
          'final_total':invoice.amount_total,'balanced':True,'move_id':invoice.id,
          'qa_fixture_committed':True,'main_untouched':True}

# Hold the parent lock while a separate request attempts to edit its input line.
second_invoice = source.copy({'ref':'IC1 QA line edit race','invoice_date':source.invoice_date})
second_invoice.action_post()
dialog = actor['baseer.financial.correction'].browse(second_invoice.action_baseer_correct_operation()['res_id'])
dialog.write({'reason':'IC1 QA line edit versus confirmation'})
dialog.line_ids.write({'price_unit_input':'500.00'})
dialog_id, line_id = dialog.id, dialog.line_ids.id
env.cr.commit()
locked, writer_attempt = threading.Event(), threading.Event()
race_results = []
original_lock = type(dialog)._lock

def controlled_lock(record):
    original_lock(record)
    if record.id == dialog_id:
        locked.set()
        assert writer_attempt.wait(5), 'Line writer did not start'

def confirm_second():
    with registry.cursor() as cursor:
        local = api.Environment(cursor, meta['user_ids']['accountant'],context)
        local['baseer.financial.correction'].browse(dialog_id).action_confirm()
        cursor.commit()
        race_results.append('confirmed')

def edit_line():
    assert locked.wait(5), 'Confirmation did not acquire parent lock'
    for attempt in range(3):
        with registry.cursor() as cursor:
            local = api.Environment(cursor,meta['user_ids']['accountant'],context)
            try:
                local['baseer.financial.correction'].browse(dialog_id).read(['completed'])
                writer_attempt.set()
                local['baseer.financial.correction.line'].browse(line_id).write({'price_unit_input':'700.00'})
                cursor.commit()
                race_results.append('unexpected_edit')
                return
            except SerializationFailure:
                cursor.rollback()
            except (UserError,):
                cursor.rollback()
                race_results.append('completed_edit_rejected')
                return

with patch.object(type(dialog),'_lock',controlled_lock):
    pair = [threading.Thread(target=confirm_second),threading.Thread(target=edit_line)]
    for thread in pair:
        thread.start()
    for thread in pair:
        thread.join(timeout=20)
    assert not any(thread.is_alive() for thread in pair), 'Line edit race deadlocked'
env.cr.rollback()
env.invalidate_all()
assert sorted(race_results)==['completed_edit_rejected','confirmed'],race_results
assert dialog.completed and dialog.line_ids.price_unit_input=='500.00' and second_invoice.amount_total==500
report['line_edit_race']={'results':race_results,'line_preserved':True,'final_total':second_invoice.amount_total}
Path('/mnt/qa-evidence/ic1-concurrency.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
env.cr.rollback()
