"""IC2 native cancellation/pair resolution, isolated and fully rolled back."""
import hashlib
import json
import traceback
from calendar import monthrange
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.baseer_financial_correction.models.lifecycle import lifecycle_scope

assert env.su and env.cr.dbname.startswith('baseer_ic')
out = Path('/mnt/qa-evidence/ic2-core-checks.json')
checks = []
result = {'status': 'FAIL', 'checks': checks, 'rollback': False, 'database': env.cr.dbname, 'timings_ms': []}
def check(label, condition):
    assert condition, label
    checks.append(label)
def deny(label, call):
    try:
        with env.cr.savepoint():
            call()
    except (AccessError, UserError, ValidationError):
        checks.append(label)
        return
    raise AssertionError(label + ': allowed')
def dec(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))
def counts():
    return {name: env[name].with_context(active_test=False).search_count([]) for name in (
        'res.users', 'res.partner', 'account.move', 'account.move.line', 'account.payment',
        'account.partial.reconcile', 'baseer.purchase.batch', 'baseer.financial.correction.audit')}
before = counts()
modules = env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('IC2 fixtures cannot commit'))
guard.start()
try:
    company = env['res.company'].search([('currency_id.name', '=', 'SAR')]).filtered(lambda c: c.baseer_salary_expense_id)[:1]
    ctx = {'allowed_company_ids': company.ids, 'lang': 'en_US', 'tz': 'Asia/Riyadh', 'tracking_disable': True, 'no_reset_password': True}
    admin = env(context=ctx)
    users, actors = {}, {}
    for role in ('accountant', 'cashier', 'owner'):
        users[role] = admin['res.users'].create({'name': 'IC2 rollback ' + role, 'login': 'ic2-rollback-' + role,
            'baseer_access_role': role, 'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        actors[role] = env(user=users[role].id, su=False, context=ctx)
    actor = actors['accountant']
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_deduction_account_id | company.baseer_loan_account_id
    def account(kind):
        return admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', kind), ('id', 'not in', private.ids)], limit=1)
    expense, income, payable, receivable = (account(kind) for kind in ('expense', 'income', 'liability_payable', 'asset_receivable'))
    purchase = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'purchase')], limit=1)
    sale = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'sale')], limit=1)
    treasury = admin['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank'])]).filtered(lambda j: j.default_account_id.account_type == 'asset_cash')[:1]
    for method in treasury.inbound_payment_method_line_ids | treasury.outbound_payment_method_line_ids:
        if method.code == 'manual':
            method.payment_account_id = treasury.default_account_id
    vendor = admin['res.partner'].create({'name': 'IC2 synthetic counterparty', 'company_id': company.id,
        'property_account_payable_id': payable.id, 'property_account_receivable_id': receivable.id})
    today = fields.Date.context_today(admin['account.move'])
    def invoice(amount, kind='in_invoice'):
        move = admin['account.move'].create({'move_type': kind, 'company_id': company.id,
            'journal_id': (purchase if kind == 'in_invoice' else sale).id, 'partner_id': vendor.id,
            'invoice_date': today, 'date': today, 'invoice_line_ids': [Command.create({'name': 'IC2 fixture',
                'quantity': 1, 'price_unit': amount, 'account_id': (expense if kind == 'in_invoice' else income).id,
                'tax_ids': [Command.clear()]})]})
        move.action_post()
        return move
    def pay(move, amount):
        method = (treasury.outbound_payment_method_line_ids if move.move_type == 'in_invoice' else treasury.inbound_payment_method_line_ids).filtered(lambda p: p.code == 'manual')[:1]
        return admin['account.payment.register'].with_context(active_model='account.move', active_ids=move.ids).create({
            'journal_id': treasury.id, 'payment_method_line_id': method.id, 'amount': amount, 'payment_date': today,
            'installments_mode': 'full', 'payment_difference_handling': 'open'})._create_payments()
    def wizard(move, operation='cancel', user=actor):
        source = user['account.move'].browse(move.id)
        action = source.action_baseer_cancel_operation() if operation == 'cancel' else source.action_baseer_correct_operation()
        result_wizard = user['baseer.financial.correction'].browse(action['res_id'])
        result_wizard.reason = 'Cancel erroneous bookkeeping fixture' if operation == 'cancel' else 'Correct fixture'
        return result_wizard
    def confirm(wizard):
        start = perf_counter()
        result_action = wizard.action_confirm()
        result['timings_ms'].append(round((perf_counter()-start)*1000, 2))
        return result_action
    def cash_reference():
        handler = actor['eh.account.dynamic.report.handler.baseer_cash_categories']
        options = handler.normalize_options({'company_ids': company.ids, 'posted_only': True, 'baseer_include_tax': True,
            'date': {'mode': 'range', 'date_from': str(today.replace(day=1)),
                     'date_to': str(today.replace(day=monthrange(today.year,today.month)[1]))}})
        return handler._authorized_report_handler(options)._compute_report(options)['meta']['exact_totals']

    bill = invoice(500)
    payment = pay(bill, 500)
    original_ids, original_lines = (bill | payment.move_id).ids, (bill | payment.move_id).line_ids.ids
    cash_before = cash_reference()
    w = wizard(bill)
    check('cancel operation server-selected with original payment preview', w.operation == 'cancel' and w.payment_id.id == payment.id and not w.line_ids)
    deny('payment cancellation requires explicit acknowledgement', w.action_confirm)
    check('missing acknowledgement leaves invoice and payment posted', bill.state == 'posted' and payment.move_id.state == 'posted')
    w.payment_cancel_ack = True
    move_count = admin['account.move'].search_count([])
    confirm(w)
    check('paid invoice and payment canceled together', bill.state == 'cancel' and payment.state == 'canceled' and payment.move_id.state == 'cancel')
    check('cancel preserves original documents and lines', set((bill | payment.move_id).exists().ids) == set(original_ids) and set((bill | payment.move_id).line_ids.ids) == set(original_lines))
    check('cancel creates no reversal or replacement move', admin['account.move'].search_count([]) == move_count and not bill.reversal_move_ids and not payment.move_id.reversal_move_ids)
    check('cancel clears owned reconciliation only', not (bill | payment.move_id).line_ids.matched_debit_ids and not (bill | payment.move_id).line_ids.matched_credit_ids)
    cash_after = cash_reference()
    check('cancel removes500 outgoing without fictitious receipt', Decimal(cash_after['payments'])-Decimal(cash_before['payments']) == 500 and cash_after['receipts'] == cash_before['receipts'])
    register = actor['account.move'].with_context(baseer_register_cash_month=today.strftime('%Y-%m'))
    data = register.baseer_financial_register_cash_kpis([('id','in',original_ids)])
    check('cancelled operation absent from posted cash register', all(Decimal(c['display'].replace(',','')) == 0 for c in data['currency_groups'][0]['sections'][0]['cards']))
    check('immutable audit classifies cancellation and captures native beforeafter', w.audit_id.operation == 'cancel' and json.loads(w.audit_id.before_json)['moves'][0]['state'] == 'posted' and all(m['state'] == 'cancel' for m in json.loads(w.audit_id.after_json)['moves']))
    audit_count = admin['baseer.financial.correction.audit'].search_count([])
    confirm(w)
    check('same confirmation is idempotent', audit_count == admin['baseer.financial.correction.audit'].search_count([]))
    deny('new request rejects already canceled operation', lambda: wizard(bill))
    deny('canceled invoice cannot be edited or restored', lambda: wizard(bill, 'edit'))

    partial = invoice(600)
    partial_payment = pay(partial, 400)
    wp = wizard(partial)
    check('partial cancellation preview uses real400 payment not600 total', wp.payment_amount_input == '400.00')
    wp.payment_cancel_ack = True
    confirm(wp)
    check('partial cancellation closes invoice and actual payment', partial.state == 'cancel' and partial_payment.move_id.state == 'cancel' and dec(partial_payment.amount) == 400 and dec(partial.amount_total) == 600)
    unpaid = invoice(250)
    wu = wizard(unpaid)
    confirm(wu)
    check('unpaid invoice cancellation creates no payment', unpaid.state == 'cancel' and not wu.payment_id)
    customer = invoice(300, 'out_invoice')
    incoming = pay(customer, 300)
    wc = wizard(customer)
    wc.payment_cancel_ack = True
    confirm(wc)
    check('customer invoice and receipt cancel through same native path', customer.state == 'cancel' and incoming.move_id.state == 'cancel')

    manual_bill = invoice(350)
    manual_method = treasury.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')[:1]
    manual_payment = admin['account.payment'].create({'company_id': company.id, 'journal_id': treasury.id,
        'payment_method_line_id': manual_method.id, 'payment_type': 'outbound', 'partner_type': 'supplier',
        'partner_id': vendor.id, 'amount': 350, 'date': today, 'currency_id': company.currency_id.id})
    manual_payment.action_post()
    (manual_bill.line_ids | manual_payment.move_id.line_ids).filtered(lambda line: line.account_id == payable).reconcile()
    check('manual pair fixture uses reconciliation without static invoice link', not manual_payment.invoice_ids and dec(manual_bill.amount_residual) == 0)
    manual_source = actor['account.move'].browse(manual_bill.id)
    manual_actor_payment = actor['account.payment'].browse(manual_payment.id)
    deny('partial-only invoice direct cancel denied', manual_source.button_cancel)
    deny('partial-only invoice direct reset denied', manual_source.button_draft)
    deny('partial-only payment direct cancel denied', manual_actor_payment.action_cancel)
    deny('partial-only payment direct reset denied', manual_actor_payment.action_draft)
    wm = wizard(manual_bill)
    check('partial graph resolves dedicated manually reconciled payment', wm.payment_id.id == manual_payment.id)
    wm.payment_cancel_ack = True
    confirm(wm)
    check('manual reconciliation pair cancels both native documents', manual_bill.state == 'cancel' and manual_payment.move_id.state == 'cancel')
    standalone = admin['account.payment'].create({'company_id': company.id, 'journal_id': treasury.id,
        'payment_method_line_id': manual_method.id, 'payment_type': 'outbound', 'partner_type': 'supplier',
        'partner_id': vendor.id, 'amount': 175, 'date': today, 'currency_id': company.currency_id.id})
    standalone.action_post()
    standalone_action = actor['account.payment'].browse(standalone.id).action_baseer_cancel_operation()
    ws = actor['baseer.financial.correction'].browse(standalone_action['res_id'])
    ws.write({'reason': 'Cancel erroneous standalone payment', 'payment_cancel_ack': True})
    confirm(ws)
    check('standalone payment cancels without inventing invoice source', not ws.move_id and standalone.state == 'canceled' and standalone.move_id.state == 'cancel')

    legacy = invoice(500)
    legacy_payment = pay(legacy, 500)
    # Reproduce the prior native cancel behavior before IC2 source guards existed;
    # use the private exact-record scope only to construct this legacy fixture.
    lifecycle_scope(legacy, legacy, legacy_payment).button_cancel()
    check('legacy fixture has canceled invoice but posted linked payment', legacy.state == 'cancel' and legacy_payment.move_id.state == 'posted' and legacy_payment.invoice_ids == legacy and not legacy.line_ids.matched_debit_ids and not legacy.line_ids.matched_credit_ids)
    wl = wizard(legacy)
    check('legacy pair resolved from persistent native associations', wl.payment_id.id == legacy_payment.id and wl.move_id.id == legacy.id)
    wl.payment_cancel_ack = True
    confirm(wl)
    check('legacy cleanup cancels remaining payment without restoring invoice', legacy.state == 'cancel' and legacy_payment.move_id.state == 'cancel' and legacy_payment.state == 'canceled')

    edit = invoice(400)
    edit_payment = pay(edit,400)
    we = wizard(edit,'edit')
    we.line_ids.price_unit_input='500'
    we.write({'correct_payment': True,'payment_amount_input':'500'})
    confirm(we)
    check('existing edit path remains native and synchronized', edit.state == 'posted' and dec(edit.amount_total)==500 and dec(edit_payment.amount)==500 and dec(edit.amount_residual)==0 and we.audit_id.operation=='edit')
    deny('operation type cannot be changed through RPC write', lambda: we.write({'operation':'cancel'}))
    deny('cashier cancellation denied', lambda: wizard(edit,user=actors['cashier']))
    opened=wizard(edit)
    opened.payment_cancel_ack=True
    users['accountant'].baseer_allow_financial_correction=False
    deny('permission revocation blocks alreadyopened cancellation',opened.action_confirm)
    users['accountant'].baseer_allow_financial_correction=True
    deny('public direct invoice cancellation cannot orphan payment',lambda: actor['account.move'].browse(edit.id).button_cancel())
    deny('public direct payment cancellation cannot orphan invoice',lambda: actor['account.payment'].browse(edit_payment.id).action_cancel())
    native_payment_move = actor['account.move'].browse(edit_payment.move_id.id)
    deny('underlying paid payment entry direct reset denied', native_payment_move.button_draft)
    deny('underlying paid payment entry direct cancel denied', native_payment_move.button_cancel)
    deny('underlying paid payment entry draft state write denied', lambda: native_payment_move.write({'state': 'draft'}))
    deny('underlying paid payment entry cancel state write denied', lambda: native_payment_move.write({'state': 'cancel'}))
    deny('underlying paid payment origin detachment denied', lambda: native_payment_move.write({'origin_payment_id': False}))
    deny('public invoice association detachment denied', lambda: actor['account.move'].browse(edit.id).write({'matched_payment_ids': [Command.clear()]}))
    deny('public payment association detachment denied', lambda: actor['account.payment'].browse(edit_payment.id).write({'invoice_ids': [Command.clear()]}))
    deny('public linked payment move reassignment denied', lambda: actor['account.payment'].browse(edit_payment.id).write({'move_id': False}))

    failed=invoice(500)
    failed_payment=pay(failed,500)
    wf=wizard(failed)
    wf.payment_cancel_ack=True
    audit_before=admin['baseer.financial.correction.audit'].search_count([])
    with patch.object(type(wf),'_verify_cancellation',side_effect=ValidationError('IC2 injected failure')):
        deny('failure after native cancellations is atomic',wf.action_confirm)
    check('rollback restores states reconciliation and no audit',failed.state=='posted' and failed_payment.move_id.state=='posted' and dec(failed.amount_residual)==0 and admin['baseer.financial.correction.audit'].search_count([])==audit_before)

    other=invoice(200)
    association=wizard(failed)
    association.payment_cancel_ack=True
    # An association change is a distinct source graph, even if amounts match.
    lifecycle_scope(failed_payment,failed,failed_payment).write({'invoice_ids':[Command.set((failed|other).ids)]})
    deny('shared or changed native invoice associations rejected',association.action_confirm)

    mapping=admin['baseer.purchase.category.map'].search([('company_id','=',company.id)],limit=1)
    method=treasury.outbound_payment_method_line_ids.filtered(lambda m:m.code=='manual')[:1]
    batch=actor['baseer.purchase.batch'].create({'company_id':company.id,'line_ids':[Command.create({
        'invoice_date':today,'partner_id':vendor.id,'supplier_ref':'IC2-BATCH-'+str(i),'category_map_id':mapping.id,
        'description':'IC2 batch fixture','gross_amount':500,'tax_id':False,'payment_method_line_id':method.id,'is_credit':False}) for i in range(2)]})
    batch.action_approve()
    row,neighbor=batch.line_ids
    batch_source = actor['account.move'].browse(row.move_id.id)
    deny('approved batch supplier reference direct edit denied', lambda: batch_source.write({'ref': 'Detached supplier reference'}))
    deny('approved batch payment reference direct edit denied', lambda: batch_source.write({'payment_reference': 'Detached payment reference'}))
    batch_native_line = batch_source.invoice_line_ids.filtered(lambda line: line.display_type == 'product')[:1]
    deny('approved batch line label direct edit denied', lambda: batch_native_line.write({'name': 'Detached line label'}))
    deny('approved batch line tax tags direct edit denied', lambda: batch_native_line.write({'tax_tag_ids': [Command.clear()]}))
    deny('approved batch line analytic allocation direct edit denied', lambda: batch_native_line.write({'analytic_distribution': {}}))
    payment_vals = {'company_id': company.id, 'journal_id': treasury.id, 'payment_method_line_id': method.id,
        'payment_type': 'outbound', 'partner_type': 'supplier', 'partner_id': vendor.id,
        'amount': 500, 'date': today, 'currency_id': company.currency_id.id}
    deny('new payment cannot claim source-owned move', lambda: actor['account.payment'].create(dict(payment_vals, move_id=row.payment_id.move_id.id)))
    deny('default new payment cannot claim source-owned move', lambda: actor['account.payment'].with_context(default_move_id=row.payment_id.move_id.id).create(payment_vals))
    deny('public batch reversal target creation denied', lambda: actor['account.move'].create({'move_type': 'in_refund', 'journal_id': purchase.id, 'partner_id': vendor.id, 'reversed_entry_id': row.move_id.id}))
    deny('context default batch reversal target denied', lambda: actor['account.move'].with_context(default_reversed_entry_id=row.move_id.id).create({'move_type': 'in_refund', 'journal_id': purchase.id, 'partner_id': vendor.id}))
    wb=actor['baseer.financial.correction'].browse(row.action_baseer_cancel_operation()['res_id'])
    wb.write({'reason':'Cancel erroneous purchase input','payment_cancel_ack':True})
    confirm(wb)
    check('batch canceled row retains original values and links',row.baseer_cancelled and dec(row.gross_amount)==500 and row.move_id.state=='cancel' and row.payment_id.move_id.state=='cancel')
    check('active batch totals exclude canceled row and preserve neighbor',dec(batch.amount_gross)==500 and not neighbor.baseer_cancelled and neighbor.move_id.state=='posted' and neighbor.payment_id.move_id.state=='posted')
    check('batch cancel stores actual actor and reason',row.baseer_cancelled_by_id.id==actor.uid and row.baseer_cancel_reason=='Cancel erroneous purchase input')
    print_data = batch._get_print_data()
    print_row = print_data['rows'][0]
    check('batch print marks cancelled row with zero active amount and historical500', print_row['gross'] == '0.00' and print_row['payment'] == 'Cancelled' and '500' in print_row['description'])
    deny('already canceled batch row cannot be edited',row.action_baseer_correct_operation)
    deny('already canceled batch row cannot cancel twice',row.action_baseer_cancel_operation)
    result['status']='PASS'
except Exception:
    result['error']=traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    guard.stop()
    result['rollback']=before==counts()
    result['modules_preserved']=modules==env['ir.module.module'].search([('state','=','installed')]).mapped('name')
    result['hard_commit_guard']=True
    result['passed']=len(checks)
    result['source_sha256']=hashlib.sha256(Path('/mnt/ic1-addons/baseer_financial_correction/models/correction.py').read_bytes()).hexdigest()
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
assert result['status']=='PASS' and result['rollback'] and result['modules_preserved']
