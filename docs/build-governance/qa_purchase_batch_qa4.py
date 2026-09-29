"""QA4 company, explicit settlement and supplier defaults; rollback only."""
import json
from pathlib import Path
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
out = Path('/mnt/qa-evidence')
checks = []
local = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids': [6, 7], 'lang': 'en_US', 'tracking_disable': True})
B, L, P = (local[m] for m in ('baseer.purchase.batch', 'baseer.purchase.batch.line', 'res.partner'))
def check(value, name):
    assert value, name
    checks.append({'check': name, 'passed': True})
def denied(fn, name):
    try:
        with env.cr.savepoint(): fn()
    except (AccessError, UserError, ValidationError): check(True, name)
    else: raise AssertionError(name + ' allowed')
def row(**kw):
    values = dict(partner_id=33, invoice_date='2026-09-06', supplier_ref='QA4/intent', category_map_id=3, gross_amount=115, tax_id=100, payment_method_line_id=34)
    values.update(kw)
    return values
def batch(**kw):
    return B.create({'line_ids': [Command.create(row(**kw))]})
counts_before = {m: local[m].search_count([]) for m in ('account.move', 'account.move.line', 'account.payment')}
legacy = json.loads((out / 'qa4_legacy_before.json').read_text(encoding='utf-8-sig'))
# Snapshot formats retained by the pre-upgrade collector.
if isinstance(legacy, dict): legacy = legacy.get('rows', legacy.get('lines', legacy))
for old in legacy:
    line = L.browse(old['id'])
    check(line.is_credit == (not old['method']), 'migration preserves settlement intent %s' % line.id)
    check(line.payment_method_line_id.id == (old['method'] or False), 'migration preserves method %s' % line.id)
    check(line.write_date.isoformat() == old['write_date'], 'migration preserves audit date %s' % line.id)
denied(lambda: batch(payment_method_line_id=False), 'missing payment is not credit')
denied(lambda: batch(is_credit=True), 'explicit credit plus method rejected')
credit = batch(is_credit=True, payment_method_line_id=False)
check(credit.line_ids.is_credit and not credit.line_ids.payment_method_line_id, 'explicit credit stored')
denied(lambda: credit.line_ids.write({'is_credit': False}), 'credit off requires method')
credit.line_ids.write({'is_credit': False, 'payment_method_line_id': 34})
check(not credit.line_ids.is_credit, 'paid intent with method accepted')
credit.line_ids.write({'is_credit': True})
check(not credit.line_ids.payment_method_line_id, 'credit toggle clears draft method')
paid = batch()
check(not paid.line_ids.is_credit and paid.line_ids.partner_id.supplier_rank == 0, 'new rank-zero company supplier accepted')
empty = B.create({})
denied(lambda: empty.write({'company_id': 7}), 'even empty batch company immutable')
denied(lambda: B.create({'company_id': 7}), 'authorized inactive company create blocked')
foreign = paid.with_context(allowed_company_ids=[7, 6])
check(bool(foreign.read(['name'])), 'authorized historical read remains possible')
check(paid.is_current_company and paid.line_ids.is_current_company, 'active flags true')
check(not foreign.is_current_company and not foreign.line_ids.is_current_company, 'active flags context sensitive')
for name, fn in [('batch edit', lambda: foreign.write({'entry_date': '2026-09-05'})), ('batch delete', foreign.unlink), ('approve', foreign.action_approve), ('line edit', lambda: foreign.line_ids.write({'description': 'wrong company'})), ('line delete', foreign.line_ids.unlink), ('line create', lambda: L.with_context(allowed_company_ids=[7, 6]).create(dict(row(), batch_id=paid.id)))]:
    denied(fn, 'inactive company blocks ' + name)
shared = P.create({'name': 'QA4 shared fixture', 'company_id': False})
foreign_supplier = P.create({'name': 'QA4 foreign fixture', 'company_id': 7})
denied(lambda: batch(partner_id=shared.id), 'shared supplier rejected')
denied(lambda: batch(partner_id=foreign_supplier.id), 'foreign supplier rejected')
denied(lambda: paid.line_ids.write({'partner_id': shared.id}), 'changing supplier to shared rejected')
supplier = P.browse(33)
supplier.write({'baseer_purchase_category_map_id': 3})
values = row(); values.pop('category_map_id')
suggested = L.create(dict(values, batch_id=empty.id))
check(suggested.category_map_id.id == 3, 'omitted category uses supplier default')
explicit = batch(category_map_id=2)
check(explicit.line_ids.category_map_id.id == 2, 'explicit category overrides supplier default')
explicit.line_ids.write({'description': 'keep explicit'})
check(explicit.line_ids.category_map_id.id == 2, 'unrelated write preserves category')
proto = L.new({'batch_id': empty.id, 'partner_id': supplier.id})
proto._onchange_partner_default_category()
check(proto.category_map_id.id == 3, 'native supplier onchange suggests category')
operator = local['res.users'].with_context(no_reset_password=True).create({'name': 'QA4 operator', 'login': 'qa4-rollback-operator', 'company_id': 6, 'company_ids': [Command.set([6])], 'group_ids': [Command.set([local.ref('account.group_account_invoice').id])]})
check(supplier.with_user(operator).with_context(allowed_company_ids=[6]).baseer_purchase_category_map_id.id == 3, 'operator can read default')
denied(lambda: supplier.with_user(operator).with_context(allowed_company_ids=[6]).write({'baseer_purchase_category_map_id': False}), 'operator cannot configure default')
denied(lambda: P.with_user(operator).with_context(allowed_company_ids=[6]).create({'name': 'QA4 denied', 'company_id': 6, 'baseer_purchase_category_map_id': 3}), 'operator create cannot configure default')
denied(lambda: P.with_user(operator).with_context(allowed_company_ids=[6]).with_context(default_baseer_purchase_category_map_id=3).create({'name': 'QA4 denied context', 'company_id': 6}), 'context default cannot bypass manager rights')
denied(lambda: P.with_user(operator).with_context(allowed_company_ids=[6], default_baseer_purchase_category_map_id=False).create({'name': 'QA4 denied false context', 'company_id': 6}), 'explicit false context default requires manager rights')
denied(lambda: supplier.with_context(allowed_company_ids=[7, 6]).write({'baseer_purchase_category_map_id': 3}), 'default from another company rejected')
op_values = row(); op_values.pop('category_map_id')
op_batch = B.with_user(operator).with_context(allowed_company_ids=[6]).create({'line_ids': [Command.create(op_values)]})
check(op_batch.line_ids.category_map_id.id == 3, 'operator can use supplier default')
mapping = local['baseer.purchase.category.map'].browse(3)
mapping.active = False
denied(lambda: supplier.write({'baseer_purchase_category_map_id': 3}), 'inactive default category rejected')
mapping.active = True
check(not supplier.with_context(allowed_company_ids=[7, 6]).baseer_purchase_category_map_id, 'supplier property isolated by active company')
env.cr.rollback()
check({m: local[m].search_count([]) for m in counts_before} == counts_before, 'all focused fixtures rolled back')
(out / 'purchase_batch_qa4_checks.json').write_text(json.dumps({'passed': len(checks), 'checks': checks, 'rollback': True}, indent=2))
print('QA4_FOCUSED_OK', len(checks))
