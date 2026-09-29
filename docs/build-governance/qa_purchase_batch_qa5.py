"""QA5 final-shape empty-save policy, native transaction rollback."""
import json
from pathlib import Path
from odoo import Command
from odoo.exceptions import UserError
assert env.cr.dbname == 'baseer_reports_qa_20260907'
local = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids': [6], 'lang': 'en_US', 'tracking_disable': True})
B = local['baseer.purchase.batch']
checks=[]
def check(ok, name):
    assert ok, name
    checks.append(name)
def denied(fn, name):
    try:
        with env.cr.savepoint(): fn()
    except UserError: check(True, name)
    else: raise AssertionError(name)
def counts():
    return [local[m].search_count([]) for m in ('baseer.purchase.batch','baseer.purchase.batch.line','account.move','account.move.line','account.payment')]
def row(ref):
    return {'partner_id': 33, 'invoice_date': '2026-09-06', 'supplier_ref': ref, 'category_map_id': 3, 'gross_amount': 115, 'tax_id': 100, 'payment_method_line_id':34}
before = counts()
denied(lambda:B.create({}), 'empty create rejected')
check(counts()==before, 'failed empty create leaves no row')
b=B.create({'line_ids':[Command.create(row('QA5/valid'))]})
check(len(b.line_ids)==1, 'nonempty parent create accepted')
old=b.line_ids.id
denied(lambda:b.write({'line_ids':[Command.clear()]}), 'last row removal through parent rejected')
check(b.line_ids.id==old, 'last row restored by transaction')
b.write({'line_ids':[Command.clear(),Command.create(row('QA5/replacement'))]})
check(len(b.line_ids)==1 and b.line_ids.id!=old, 'replace all rows accepted after final-shape validation')
denied(lambda:b.with_context(allowed_company_ids=[7,6]).write({'entry_date':'2026-09-05'}), 'active company guard retained')
b.action_approve()
check(b.line_ids.move_id.state=='posted' and b.line_ids.move_id.payment_state=='paid', 'nonempty native approval still posts and pays')
check(b.line_ids.move_id.amount_total==115 and b.line_ids.move_id.amount_tax==15, 'native totals retained')
denied(lambda:b.write({'line_ids':[Command.clear()]}), 'approved batch remains immutable')
env.cr.rollback()
check(counts()==before, 'all QA5 fixtures rolled back')
Path('/mnt/qa-evidence/purchase_batch_qa5_checks.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'rollback':True},indent=2))
print('QA5_OK',len(checks))
