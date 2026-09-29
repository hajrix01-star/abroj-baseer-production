"""Real independent QA sessions: edit versus cancellation of one paid operation."""
import json
import threading
from pathlib import Path
from odoo import api
from odoo.exceptions import UserError
from psycopg2.errors import SerializationFailure

assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
meta=json.loads(Path('/mnt/qa-evidence/ic1-ui-fixtures.json').read_text())
uid=meta['user_ids']['owner']
ctx={'allowed_company_ids':[meta['company_id']], 'lang':'en_US','tracking_disable':True}
actor=env(user=uid,su=False,context=ctx)
source=actor['account.move'].browse(meta['move_id'])
invoice=source.copy({'ref':'IC2 QA concurrent edit versus cancellation','invoice_date':source.invoice_date})
invoice.action_post()
journal=actor['account.journal'].search([('company_id','=',invoice.company_id.id),('type','in',['cash','bank'])]).filtered(
    lambda item:item.default_account_id.account_type=='asset_cash')[:1]
method=journal.outbound_payment_method_line_ids.filtered(lambda item:item.code=='manual' and item.payment_account_id==journal.default_account_id)[:1]
assert method
payment=actor['account.payment.register'].with_context(active_model='account.move',active_ids=invoice.ids).create({
    'journal_id':journal.id,'payment_method_line_id':method.id,'amount':invoice.amount_total,'payment_date':invoice.date,
    'installments_mode':'full','payment_difference_handling':'open'})._create_payments()
edit=actor['baseer.financial.correction'].browse(invoice.action_baseer_correct_operation()['res_id'])
edit.write({'reason':'IC2 QA concurrent edit'})
edit.line_ids.write({'price_unit_input':'600.00'})
cancel=actor['baseer.financial.correction'].browse(invoice.action_baseer_cancel_operation()['res_id'])
cancel.write({'reason':'IC2 QA concurrent cancel','payment_cancel_ack':True})
ids=[edit.id,cancel.id]
env.cr.commit()  # Explicit isolated QA fixtures only, required for separate transactions.
barrier=threading.Barrier(2)
results=[]

def confirm(wizard_id):
    try:
        for attempt in range(3):
            with env.registry.cursor() as cr:
                local=api.Environment(cr,uid,ctx)
                try:
                    wizard=local['baseer.financial.correction'].browse(wizard_id)
                    wizard.read(['completed'])
                    if attempt==0:
                        barrier.wait(timeout=15)
                    wizard.action_confirm()
                    cr.commit()
                    results.append({'id':wizard_id,'status':'committed','attempt':attempt+1})
                    return
                except SerializationFailure:
                    cr.rollback()
                except UserError as error:
                    cr.rollback()
                    results.append({'id':wizard_id,'status':'rejected','message':str(error)})
                    return
        raise AssertionError('Serialization retry exhausted')
    except Exception as error:
        results.append({'id':wizard_id,'status':'error','message':repr(error)})

threads=[threading.Thread(target=confirm,args=(item,)) for item in ids]
for thread in threads: thread.start()
for thread in threads: thread.join(timeout=30)
assert not any(thread.is_alive() for thread in threads), 'Deadlock'
env.cr.rollback()
env.invalidate_all()
assert sorted(row['status'] for row in results)==['committed','rejected'],results
audits=actor['baseer.financial.correction.audit'].search([('move_id','=',invoice.id)])
assert len(audits)==1
if invoice.state=='cancel':
    assert payment.state=='canceled' and payment.move_id.state=='cancel'
else:
    assert invoice.state=='posted' and invoice.amount_total==600 and payment.move_id.state=='posted'
    assert invoice.amount_residual==600-payment.amount
assert all(sum(move.line_ids.mapped('balance'))==0 for move in invoice|payment.move_id)
report={'status':'PASS','database':env.cr.dbname,'results':results,'audit_count':1,
        'invoice_state':invoice.state,'payment_state':payment.state,'invoice_id':invoice.id,
        'qa_fixture_committed':True,'main_untouched':True,'scope':'Paid invoice edit versus cancel; one winner and source parity'}
Path('/mnt/qa-evidence/ic2-concurrency.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
env.cr.rollback()
