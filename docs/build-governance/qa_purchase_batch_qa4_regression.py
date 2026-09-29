"""PB1 QA integration and bounded capacity checks. All writes roll back."""
import json
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
checks, timings = [], []
out = Path('/mnt/qa-evidence')
admin = env.ref('base.user_admin')
company = env['res.company'].browse(9)
ctx = dict(env.context, allowed_company_ids=company.ids, tracking_disable=True, mail_create_nolog=True, lang='en_US')
local = env(user=admin.id, context=ctx)
assert not local.su
Batch, Line, Map = [local[m] for m in ('baseer.purchase.batch', 'baseer.purchase.batch.line', 'baseer.purchase.category.map')]
prefix = 'PB1 TEST'

def check(condition, label, **data):
    assert condition, (label, data)
    checks.append(dict(check=label, passed=True, **data))

def cents(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))

def denied(fn, label):
    try:
        with env.cr.savepoint():
            fn()
    except (UserError, ValidationError, AccessError):
        check(True, label)
    else:
        raise AssertionError(label + ' was allowed')

def count():
    return {m: env[m].search_count([]) for m in ('account.move', 'account.payment', 'account.move.line')}

before_all = count()
account = lambda kind: local['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', kind)], limit=1)
partner = local['res.partner'].create({'name': prefix + ' supplier', 'company_id': company.id,
    'property_account_payable_id': account('liability_payable').id,
    'property_account_receivable_id': account('asset_receivable').id})
parent_cat = local['product.category'].create({'name': prefix + ' beverages'})
category = local['product.category'].create({'name': prefix + ' water', 'parent_id': parent_cat.id})
tax = local['account.tax'].search([('company_id', '=', company.id), ('type_tax_use', '=', 'purchase'), ('amount_type', '=', 'percent'), ('amount', '=', 15), ('active', '=', True)], limit=1)
check(bool(tax), 'configured native purchase VAT exists')
product = local['product.product'].create({'name': prefix + ' summary service', 'type': 'service', 'company_id': company.id,
    'categ_id': category.id, 'property_account_expense_id': account('expense').id, 'supplier_taxes_id': [Command.set(tax.ids)]})
mapping = Map.create({'company_id': company.id, 'category_id': category.id, 'product_id': product.id})
methods = []
for kind, code in [('cash', 'PBC'), ('bank', 'PBB')]:
    journal = local['account.journal'].create({'name': prefix + ' ' + kind, 'code': code, 'type': kind, 'company_id': company.id})
    method = journal.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')[:1]
    method.payment_account_id = journal.default_account_id
    methods.append(method)

serial = 0
def row(gross=115, paid=True, taxable=True, **overrides):
    global serial
    serial += 1
    vals = {'invoice_date': '2026-09-06', 'partner_id': partner.id, 'supplier_ref': prefix + '/' + str(serial),
        'entry_type': 'purchase', 'category_map_id': mapping.id, 'description': '', 'gross_amount': gross,
        'is_credit': not paid, 'tax_id': tax.id if taxable else False, 'payment_method_line_id': methods[0].id if paid else False}
    vals.update(overrides)
    return vals

def batch(rows, **overrides):
    return Batch.create(dict({'company_id': company.id, 'entry_date': '2026-09-07', 'line_ids': [Command.create(r) for r in rows]}, **overrides))

def cash_report():
    return local.ref('baseer_cash_categories.report_cash_categories').render({'company_ids': company.ids, 'posted_only': True,
        'date': {'mode': 'range', 'date_from': '2026-09-01', 'date_to': '2026-09-30'},
        'baseer_months': ['2026-09'], 'baseer_include_tax': True}, use_cache=False)

baseline = cash_report()
b = batch([row(), row(230, payment_method_line_id=methods[1].id, entry_type='expense', invoice_date='2026-09-05'), row(57.5, paid=False)])
check(cents(b.amount_gross) == Decimal('402.50'), 'draft gross aggregate')
check(cents(b.amount_net) == Decimal('350.00') and cents(b.amount_tax) == Decimal('52.50'), 'draft native tax preview')
draft_counts = count()
started = perf_counter()
b.action_approve()
timings.append({'rows': 3, 'seconds': perf_counter() - started})
check(b.state == 'approved' and len(b.line_ids.mapped('move_id')) == 3, 'three original vendor bills created')
check(len(b.line_ids.mapped('payment_id')) == 2, 'only paid rows create payments')
for line in b.line_ids:
    bill = line.move_id
    check(bill.state == 'posted' and bill.move_type == 'in_invoice', 'native posted bill ' + line.supplier_ref)
    check(cents(bill.amount_total) == cents(line.gross_amount), 'gross retained ' + line.supplier_ref)
    check(cents(bill.amount_untaxed) == cents(line.net_amount) and cents(bill.amount_tax) == cents(line.tax_amount), 'preview matches native tax ' + line.supplier_ref)
    check(bill.date == line.invoice_date == bill.invoice_date, 'administrative entry date never shifts accounting ' + line.supplier_ref)
    check(bill.invoice_line_ids.product_id == product, 'native service product category lineage ' + line.supplier_ref)
    if line.payment_method_line_id:
        check(bill.payment_state == 'paid' and cents(bill.amount_residual) == 0, 'actually paid ' + line.supplier_ref)
        check(line.payment_id.date == line.invoice_date, 'payment date matches invoice ' + line.supplier_ref)
        check(all(bill.line_ids.filtered(lambda l: l.account_id.account_type == 'liability_payable').mapped('reconciled')), 'payable reconciled ' + line.supplier_ref)
    else:
        check(bill.payment_state == 'not_paid' and cents(bill.amount_residual) == Decimal('57.50'), 'credit remains unpaid')
for move in b.line_ids.mapped('move_id') | b.line_ids.mapped('payment_id.move_id'):
    check(sum((cents(l.balance) for l in move.line_ids), Decimal(0)) == 0, 'balanced move ' + str(move.id))
after = cash_report()
check(cents(after['totals']['payments']) - cents(baseline['totals']['payments']) == -Decimal('345'), 'cash report counts only actual payments')
check(any('category-%s' % category.id in r['id'] for r in after['lines']), 'cash report shows chosen child category')
counts_approved = count()
b.action_approve()
check(count() == counts_approved, 'repeat approval creates nothing')
for field, value in [('state', 'draft'), ('company_id', 6), ('name', 'forged'), ('approved_by_id', admin.id)]:
    denied(lambda field=field, value=value: b.write({field: value}), 'approved batch immutable ' + field)
denied(lambda: b.unlink(), 'approved batch cannot be deleted')
for vals in [{'gross_amount': 1}, {'move_id': False}, {'payment_id': False}, {'batch_id': batch([row()]).id}]:
    denied(lambda vals=vals: b.line_ids[:1].write(vals), 'approved line mutation denied ' + str(list(vals)))
denied(lambda: b.line_ids[:1].unlink(), 'approved line cannot be deleted')
denied(lambda: Line.create(dict(row(), batch_id=b.id)), 'cannot append approved batch')
denied(lambda: batch([row()], state='approved'), 'forged batch state rejected')
draft = batch([row()])
denied(lambda: draft.line_ids.write({'move_id': b.line_ids[0].move_id.id}), 'forged bill link rejected in draft')
denied(lambda: batch([row(gross=1.234)]), 'more than two raw decimals rejected')
for value in (-1, 0, 'NaN', 'Infinity'):
    denied(lambda value=value: batch([row(gross=value)]).action_approve(), 'invalid gross rejected ' + str(value))
denied(lambda: batch([row(supplier_ref='   ')]).action_approve(), 'blank invoice reference rejected')
denied(lambda: batch([row(supplier_ref='SAME'), row(supplier_ref=' same ')]).action_approve(), 'duplicate reference within batch rejected')
denied(lambda: batch([row(supplier_ref=b.line_ids[0].supplier_ref.lower())]).action_approve(), 'existing supplier bill duplicate rejected')
for gross, taxable in [(0.01, True), (0.04, True), (115, False)]:
    tiny = batch([row(gross, taxable=taxable)])
    tiny.action_approve()
    check(cents(tiny.line_ids.move_id.amount_total) == cents(gross), 'exact gross roundtrip ' + str(gross) + '/' + str(taxable))
bad_journal = local['account.journal'].create({'name': prefix + ' outstanding only', 'code': 'PBO', 'type': 'bank', 'company_id': company.id})
bad = bad_journal.outbound_payment_method_line_ids[:1]
bad.payment_account_id = bad_journal.default_account_id
atomic = batch([row(), row(payment_method_line_id=bad.id)])
bad.payment_account_id = account('asset_current')
atomic_before = count()
denied(atomic.action_approve, 'unsettled payment setup rejected')
check(count() == atomic_before and atomic.state == 'draft' and not atomic.line_ids.move_id, 'failed batch has no financial side effects')
late_failure = batch([row(), row()])
late_before = count()
payment_class = type(local['account.payment.register'])
original_create_payments = payment_class._create_payments
payment_calls = [0]
def fail_second_payment(wizard, *args, **kwargs):
    payment_calls[0] += 1
    if payment_calls[0] == 2:
        raise UserError('PB1 injected late payment failure')
    return original_create_payments(wizard, *args, **kwargs)
with patch.object(payment_class, '_create_payments', fail_second_payment):
    try:
        late_failure.action_approve()
    except UserError:
        pass
    else:
        raise AssertionError('Late payment failure not reached')
check(payment_calls[0] == 2 and count() == late_before, 'internal atomic rollback after first completed payment, even when caller catches error')
check(late_failure.state == 'draft' and not late_failure.line_ids.move_id, 'late failure leaves editable draft and no links')
foreign_tax = local['account.tax'].with_context(allowed_company_ids=[6]).search([('company_id', '=', 6), ('type_tax_use', '=', 'purchase')], limit=1)
denied(lambda: batch([row(tax_id=foreign_tax.id)]).action_approve(), 'foreign company tax rejected')
denied(lambda: batch([row()] * 51).action_approve(), 'batch row ceiling enforced')
outsider = local['res.users'].with_context(no_reset_password=True).create({'name': prefix + ' outsider', 'login': 'pb1-test-outsider',
    'company_id': company.id, 'company_ids': [Command.set(company.ids)], 'group_ids': [Command.set([local.ref('base.group_user').id])]})
denied(lambda: b.with_user(outsider).read(['name']), 'non accounting user cannot read batches')
denied(lambda: Batch.with_user(outsider).create({'company_id': company.id}), 'non accounting user cannot create batches')
operator = local['res.users'].with_context(no_reset_password=True).create({'name': prefix + ' operator', 'login': 'pb1-test-operator',
    'company_id': company.id, 'company_ids': [Command.set(company.ids)],
    'group_ids': [Command.set([local.ref('account.group_account_invoice').id])]})
check(bool(mapping.with_user(operator).read(['product_id'])), 'operator can read category mapping')
denied(lambda: mapping.with_user(operator).write({'product_id': product.id}), 'operator cannot alter category accounting mapping')
operator_batch = batch([row(paid=False)]).with_user(operator)
operator_batch.action_approve()
check(operator_batch.state == 'approved', 'native invoicing operator can approve within rights')
operator_paid = batch([row()]).with_user(operator)
operator_paid.action_approve()
check(operator_paid.line_ids.move_id.payment_state == 'paid', 'native invoicing operator can fully settle paid batch')
context_batch = Batch.with_context(default_state='approved', default_approved_by_id=operator.id,
    default_name='FORGED', default_move_id=b.line_ids[0].move_id.id,
    default_payment_id=b.line_ids[0].payment_id.id, check_move_validity=False,
    skip_invoice_sync=True).create({'company_id': company.id, 'entry_date': '2026-09-07', 'line_ids': [Command.create(row())]})
check(context_batch.state == 'draft' and context_batch.name != 'FORGED' and not context_batch.line_ids.move_id,
      'context defaults cannot forge approval or accounting links')
context_batch.action_approve()
check(context_batch.line_ids.move_id.payment_state == 'paid', 'native approval safely resets injected financial bypass context')
denied(lambda: Batch.with_user(operator).with_context(allowed_company_ids=[6]).search([]), 'forged allowed company context denied')
denied(lambda: Batch.with_user(operator).create({'company_id': 6}), 'foreign company batch create denied')
class RevertProbe(Exception):
    pass
try:
    with env.cr.savepoint():
        local['res.company'].browse(company.id).write({'purchase_lock_date': '2026-09-06'})
        locked = batch([row()])
        denied(locked.action_approve, 'locked invoice date rejected without silent shift')
        raise RevertProbe()
except RevertProbe:
    pass
for size in (1, 10, 50):
    perf_batch = batch([row(gross=1, paid=False, taxable=False) for _ in range(size)])
    started = perf_counter()
    perf_batch.action_approve()
    elapsed = perf_counter() - started
    timings.append({'rows': size, 'seconds': elapsed})
    check(len(perf_batch.line_ids.move_id) == size, 'bounded capacity ' + str(size), seconds=elapsed)

env.cr.rollback()
check(count() == before_all, 'all QA integration financial fixtures rolled back')
(out / 'purchase_batch_qa4_regression_checks.json').write_text(json.dumps({'database': env.cr.dbname, 'passed': len(checks), 'checks': checks, 'timings': timings, 'rollback': True}, indent=2), encoding='utf-8')
print('PURCHASE_BATCH_OK', len(checks), timings)

