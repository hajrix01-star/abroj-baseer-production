"""IC1 native accounting fixtures. Isolated clone only; all fixtures roll back."""
import json
import hashlib
import traceback
from calendar import monthrange
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.su and env.cr.dbname.startswith('baseer_ic1_')
checks = []
out = Path('/mnt/qa-evidence/ic1-checks.json')
source_paths = [Path('/mnt/ic1-addons/baseer_financial_correction') / name for name in (
    'models/correction.py', 'models/dispatcher.py', 'models/batch_adapter.py', 'security/correction_rules.xml')]
def hashes():
    return {str(path.relative_to('/mnt/ic1-addons/baseer_financial_correction')):
            hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
result = {'status': 'FAIL', 'database': env.cr.dbname, 'checks': checks, 'rollback': False, 'timings_ms': [],
          'source_hashes': hashes()}
def check(label, value):
    assert value, label
    checks.append(label)
def deny(label, call, errors=(AccessError, UserError, ValidationError)):
    try:
        with env.cr.savepoint():
            call()
    except errors:
        checks.append(label)
        return
    raise AssertionError(label + ': unexpectedly allowed')
def dec(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))
def stamp():
    return {model: env[model].with_context(active_test=False).search_count([]) for model in (
        'res.users', 'res.partner', 'res.company', 'account.move', 'account.move.line', 'account.payment',
        'account.partial.reconcile', 'baseer.purchase.batch', 'baseer.financial.correction.audit')}
before = stamp()
modules = env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('IC1 fixtures must never commit'))
guard.start()
try:
    company = env['res.company'].search([('currency_id.name', '=', 'SAR')]).filtered(lambda c: c.baseer_salary_expense_id)[:1]
    assert company
    ctx = {'allowed_company_ids': company.ids, 'lang': 'en_US', 'tz': 'Asia/Riyadh', 'tracking_disable': True, 'no_reset_password': True}
    admin = env(context=ctx)
    actors = {}
    for role in ('accountant', 'owner', 'cashier'):
        user = admin['res.users'].create({'name': 'IC1 rollback ' + role, 'login': 'ic1-rollback-' + role,
            'baseer_access_role': role, 'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        actors[role] = env(user=user.id, su=False, context=ctx)
    actor = actors['accountant']
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_deduction_account_id | company.baseer_loan_account_id
    def account(kind):
        return admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', kind), ('id', 'not in', private.ids)], limit=1)
    expense, income, payable, receivable = (account(kind) for kind in ('expense', 'income', 'liability_payable', 'asset_receivable'))
    purchase = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'purchase')], limit=1)
    sale = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'sale')], limit=1)
    treasuries = admin['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank'])]).filtered(lambda j: j.default_account_id.account_type == 'asset_cash')
    treasury = treasuries[:1]
    assert all((expense, income, payable, receivable, purchase, sale, treasury))
    today = fields.Date.context_today(admin['account.move'])
    def cash_reference():
        handler = actor['eh.account.dynamic.report.handler.baseer_cash_categories']
        options = handler.normalize_options({'company_ids': company.ids, 'posted_only': True,
            'baseer_include_tax': True, 'date': {'mode': 'range', 'date_from': str(today.replace(day=1)),
            'date_to': str(today.replace(day=monthrange(today.year, today.month)[1]))}})
        return handler._authorized_report_handler(options)._compute_report(options)['meta']['exact_totals']
    def partner(name):
        return admin['res.partner'].create({'name': 'IC1 ' + name, 'company_id': company.id,
            'property_account_payable_id': payable.id, 'property_account_receivable_id': receivable.id})
    vendor, other_vendor = partner('vendor'), partner('replacement vendor')
    for journal in treasuries:
        for method in journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids:
            if method.code == 'manual':
                method.payment_account_id = journal.default_account_id
    def invoice(amount, kind='in_invoice', lines=False):
        move = admin['account.move'].create({'move_type': kind, 'company_id': company.id,
            'journal_id': (purchase if kind == 'in_invoice' else sale).id, 'partner_id': vendor.id,
            'invoice_date': today, 'date': today, 'ref': 'IC1 ROLLBACK',
            'invoice_line_ids': lines or [Command.create({'name': 'IC1 synthetic invoice', 'quantity': 1,
                'price_unit': amount, 'account_id': (expense if kind == 'in_invoice' else income).id, 'tax_ids': [Command.clear()]})]})
        move.action_post()
        return move
    def pay(move, amount):
        method = (treasury.outbound_payment_method_line_ids if move.move_type == 'in_invoice' else treasury.inbound_payment_method_line_ids).filtered(lambda p: p.code == 'manual')[:1]
        return admin['account.payment.register'].with_context(active_model='account.move', active_ids=move.ids).create({
            'journal_id': treasury.id, 'payment_method_line_id': method.id, 'amount': amount,
            'payment_date': today, 'installments_mode': 'full', 'payment_difference_handling': 'open'})._create_payments()
    def wizard(move, user=actor):
        action = user['account.move'].browse(move.id).action_baseer_correct_operation()
        assert action['context'].get('edit') is True and action['context'].get('form_view_initial_mode') == 'edit'
        return user['baseer.financial.correction'].browse(action['res_id'])
    def price(wiz, amount):
        wiz.line_ids.write({'price_unit_input': str(amount)})
        wiz.reason = 'Correct synthetic input'
    def confirm(wiz):
        start = perf_counter()
        response = wiz.action_confirm()
        result['timings_ms'].append(round((perf_counter() - start) * 1000, 2))
        return response
    def balanced(move):
        return move.state == 'posted' and sum((dec(line.balance) for line in move.line_ids), Decimal(0)) == 0

    bill = invoice(400)
    payment = pay(bill, 400)
    w = wizard(bill)
    check('payment correction defaults off', not w.correct_payment)
    price(w, 500)
    confirm(w)
    check('invoice only 400 to 500 preserves actual payment400', dec(bill.amount_total) == 500 and dec(payment.amount) == 400 and dec(bill.amount_residual) == 100)
    check('partial invoice native state', bill.payment_state == 'partial')
    check('invoice and payment entries remain balanced', balanced(bill) and balanced(payment.move_id))
    check('one immutable audit created', w.completed and bool(w.audit_id) and w.audit_id.user_id.id == actor.uid)
    before_ids = payment.move_id.ids, admin['baseer.financial.correction.audit'].search_count([])
    confirm(w)
    check('repeated confirmation idempotent', before_ids == (payment.move_id.ids, admin['baseer.financial.correction.audit'].search_count([])))

    bill2 = invoice(600)
    payment2 = pay(bill2, 600)
    original_payment2_move_id = payment2.move_id.id
    cash_before = cash_reference()
    w2 = wizard(bill2)
    price(w2, 500)
    deny('preserved overpayment rejected rather than inventing refund', w2.action_confirm)
    check('rejected overpayment rolls back invoice and settlement', dec(bill2.amount_total) == 600 and dec(bill2.amount_residual) == 0)
    w2.write({'correct_payment': True, 'payment_amount_input': '500'})
    confirm(w2)
    check('explicit invoice600 payment600 to actual500 paid', dec(bill2.amount_total) == 500 and dec(payment2.amount) == 500 and dec(bill2.amount_residual) == 0)
    check('same payment and source move retained no reversal', payment2.move_id.id == original_payment2_move_id and not payment2.move_id.reversed_entry_id)
    check('actual liquidity is exactly500 out', dec(payment2._seek_for_lines()[0].balance) == -500)
    cash_after = cash_reference()
    check('native cash report correction changes outgoing by100 without false receipt', Decimal(cash_after['payments']) - Decimal(cash_before['payments']) == 100 and cash_after['receipts'] == cash_before['receipts'])
    cash_reader = actor['account.move'].with_context(baseer_register_cash_month=today.strftime('%Y-%m'))
    payload = cash_reader.baseer_financial_register_cash_kpis([('id', '=', payment2.move_id.id)])
    cards = {card['key']: Decimal(card['display'].replace(',', '')) for card in payload['currency_groups'][0]['sections'][0]['cards']}
    check('native financial register corrected payment cards exact500', cards == {'receipts': Decimal(0), 'payments': Decimal(-500), 'net': Decimal(-500)})
    cash_row = cash_reader.browse(payment2.move_id.id)
    check('native register row exact500 agrees with cash card', dec(cash_row.baseer_register_cash_payments) == -500 and dec(cash_row.baseer_register_cash_receipts) == 0)

    bill3 = invoice(400)
    payment3 = pay(bill3, 400)
    w3 = wizard(bill3)
    price(w3, 500)
    w3.partner_id = other_vendor.id
    deny('preserved payment wrong supplier rejected', w3.action_confirm)
    w3.write({'correct_payment': True, 'payment_amount_input': '500'})
    confirm(w3)
    check('explicit supplier change updates native invoice and payment', bill3.partner_id == other_vendor and payment3.partner_id == other_vendor and dec(bill3.amount_residual) == 0)

    customer = invoice(400, 'out_invoice')
    incoming = pay(customer, 400)
    wc = wizard(customer)
    price(wc, 500)
    wc.write({'correct_payment': True, 'payment_amount_input': '500'})
    confirm(wc)
    check('customer incoming corrected without outgoing reversal', dec(incoming._seek_for_lines()[0].balance) == 500 and dec(customer.amount_residual) == 0)

    unpaid = invoice(400)
    wu = wizard(unpaid)
    price(wu, 500)
    confirm(wu)
    check('unpaid invoice remains unpaid', dec(unpaid.amount_total) == 500 and dec(unpaid.amount_residual) == 500 and not wu.payment_id)

    if len(treasuries) < 2:
        second = admin['account.journal'].create({'name': 'IC1 Synthetic Bank', 'code': 'IC1BK', 'type': 'bank', 'company_id': company.id})
        for method in second.outbound_payment_method_line_ids | second.inbound_payment_method_line_ids:
            if method.code == 'manual':
                method.payment_account_id = second.default_account_id
    else:
        second = treasuries[1]
    wj = wizard(bill2)
    wj.write({'reason': 'Correct actual bank', 'correct_payment': True, 'payment_journal_id': second.id,
        'payment_method_line_id': second.outbound_payment_method_line_ids.filtered(lambda method: method.code == 'manual')[:1].id})
    confirm(wj)
    check('journal correction moves actual500 to selected treasury', payment2.journal_id == second and payment2._seek_for_lines()[0].account_id == second.default_account_id and dec(payment2._seek_for_lines()[0].balance) == -500)
    proposed = actor['baseer.financial.correction'].new({'payment_id': payment2.id, 'payment_journal_id': treasury.id})
    proposed._onchange_payment_journal_id()
    check('journal onchange selects sole matching manual method', proposed.payment_method_line_id == treasury.outbound_payment_method_line_ids.filtered(lambda method: method.code == 'manual')[:1])

    invalid = invoice(400)
    wi = wizard(invalid)
    price(wi, '500.001')
    deny('raw subcent price rejected', wi.action_confirm)
    check('invalid raw input has no financial effect', dec(invalid.amount_total) == 400)
    price(wi, 'NaN')
    deny('nonfinite input rejected', wi.action_confirm)
    price(wi, 500)
    wi.reason = ''
    deny('missing reason rejected', wi.action_confirm)
    wi.reason = 'Correct actual amount'
    invalid.ref = 'Concurrent source change'
    deny('stale source rejected', wi.action_confirm)

    deny('cashier source action denied', lambda: actors['cashier']['account.move'].browse(bill.id).action_baseer_correct_operation())
    deny('cashier direct confirm denied', lambda: actors['cashier']['baseer.financial.correction'].browse(wi.id).action_confirm())
    deny('other owner cannot confirm somebody elses wizard', lambda: actors['owner']['baseer.financial.correction'].browse(wi.id).action_confirm())
    deny('public wizard create source spoof denied', lambda: actor['baseer.financial.correction'].create({'move_id': bill.id, 'company_id': company.id}))
    deny('protected baseline write denied', lambda: wi.write({'baseline_json': '{}'}))
    deny('protected source write denied', lambda: wi.write({'move_id': bill.id}))
    deny('source line reassignment denied', lambda: wi.line_ids.write({'original_line_id': bill.invoice_line_ids[:1].id}))
    deny('public audit injection denied', lambda: actor['baseer.financial.correction.audit'].create({'reason': 'fake'}))
    deny('immutable audit write denied', lambda: w.audit_id.write({'reason': 'fake'}))
    deny('immutable audit unlink denied', w.audit_id.unlink)
    deny('completed wizard write denied', lambda: w.write({'reason': 'fake'}))

    rollback_bill = invoice(400)
    rollback_payment = pay(rollback_bill, 400)
    wr = wizard(rollback_bill)
    price(wr, 500)
    wr.write({'correct_payment': True, 'payment_amount_input': '500'})
    prior_audits = admin['baseer.financial.correction.audit'].search_count([])
    with patch.object(type(wr), '_verify_result', side_effect=ValidationError('IC1 induced verification failure')):
        deny('induced post verification failure is atomic', wr.action_confirm)
    check('failure restores original native invoice payment and audit', dec(rollback_bill.amount_total) == 400 and dec(rollback_payment.amount) == 400 and dec(rollback_bill.amount_residual) == 0 and admin['baseer.financial.correction.audit'].search_count([]) == prior_audits)

    shared1, shared2 = invoice(400), invoice(400)
    sharedpayment = pay(shared1, 200)
    # One payment reused with an additional invoice is a rejected ownership graph.
    sharedpayment.invoice_ids = [Command.set((shared1 | shared2).ids)]
    deny('shared invoice associations rejected', lambda: wizard(shared1))

    leaf = admin['account.tax'].create({'name': 'IC1 ordinary child', 'amount': 10, 'amount_type': 'percent',
        'type_tax_use': 'none', 'company_id': company.id, 'tax_exigibility': 'on_invoice'})
    group = admin['account.tax'].create({'name': 'IC1 grouped tax', 'amount_type': 'group',
        'type_tax_use': 'purchase', 'company_id': company.id, 'children_tax_ids': [Command.set(leaf.ids)]})
    multi = invoice(0, lines=[Command.create({'name': 'IC1 grouped tax line', 'quantity': 1, 'price_unit': 100,
        'account_id': expense.id, 'tax_ids': [Command.set(group.ids)]}), Command.create({'name': 'IC1 plain line',
        'quantity': 2, 'price_unit': 25, 'account_id': expense.id, 'tax_ids': [Command.clear()]})])
    wm = wizard(multi)
    wm.reason = 'Correct native multiline amount'
    wm.line_ids[:1].price_unit_input = '200'
    confirm(wm)
    check('native multiline grouped on-invoice taxes supported', dec(multi.amount_total) == 270 and dec(multi.amount_tax) == 20 and len(multi.invoice_line_ids) == 2)
    stale_tax = wizard(multi)
    stale_tax.reason = 'Stale child tax test'
    with env.cr.savepoint():
        leaf.amount = 11
        deny('child tax configuration change invalidates baseline', stale_tax.action_confirm)
        leaf.amount = 10
    transition = admin['account.account'].create({'name': 'IC1 CABA transition', 'code': 'IC1CABA',
        'account_type': 'asset_current', 'reconcile': True, 'company_ids': [Command.set(company.ids)]})
    caba_child = leaf.copy({'name': 'IC1 cash basis child', 'tax_exigibility': 'on_payment', 'cash_basis_transition_account_id': transition.id})
    caba_group = group.copy({'name': 'IC1 cash basis group', 'children_tax_ids': [Command.set(caba_child.ids)]})
    wcaba = wizard(unpaid)
    wcaba.reason = 'Reject cash basis child'
    wcaba.line_ids.tax_ids = [Command.set(caba_group.ids)]
    deny('submitted grouped cash-basis child rejected before mutation', wcaba.action_confirm)
    check('cash-basis rejection preserves invoice total', dec(unpaid.amount_total) == 500)
    caba_invoice = invoice(0, lines=[Command.create({'name': 'IC1 CABA existing', 'quantity': 1, 'price_unit': 100,
        'account_id': expense.id, 'tax_ids': [Command.set(caba_group.ids)]})])
    deny('existing grouped cash-basis invoice rejected', lambda: wizard(caba_invoice))

    locked = invoice(100)
    with env.cr.savepoint():
        company.fiscalyear_lock_date = today
        deny('locked accounting period rejected before reset', lambda: wizard(locked))
        company.fiscalyear_lock_date = False
    check('locked failure preserves posted entry', locked.state == 'posted' and dec(locked.amount_total) == 100)
    writeoff_bill = invoice(600)
    writeoff_method = treasury.outbound_payment_method_line_ids.filtered(lambda method: method.code == 'manual')[:1]
    admin['account.payment.register'].with_context(active_model='account.move', active_ids=writeoff_bill.ids).create({
        'journal_id': treasury.id, 'payment_method_line_id': writeoff_method.id, 'amount': 500,
        'payment_date': today, 'installments_mode': 'full', 'payment_difference_handling': 'reconcile',
        'writeoff_account_id': expense.id, 'writeoff_label': 'IC1 synthetic writeoff'})._create_payments()
    deny('native payment with writeoff excluded', lambda: wizard(writeoff_bill))

    private_vendor = partner('private destination')
    private_vendor.property_account_payable_id = company.baseer_salary_payable_id
    private_payment = admin['account.payment'].create({'partner_id': private_vendor.id, 'partner_type': 'supplier',
        'payment_type': 'outbound', 'amount': 100, 'date': today, 'company_id': company.id,
        'journal_id': treasury.id, 'payment_method_line_id': treasury.outbound_payment_method_line_ids.filtered(lambda method: method.code == 'manual')[:1].id})
    private_payment.action_post()
    deny('owner cannot generically correct private HR payment', lambda: actors['owner']['account.payment'].browse(private_payment.id).action_baseer_correct_operation())
    wp = wizard(unpaid)
    wp.reason = 'Reject private counterparty destination'
    wp.partner_id = private_vendor.id
    deny('candidate private HR destination rejected', wp.action_confirm)
    check('private candidate rejection leaves source partner', unpaid.partner_id == vendor)
    original_audit_id = w.audit_id.id
    original_wizard_line_ids = w.line_ids.ids
    old_salary_expense = company.baseer_salary_expense_id
    company.baseer_salary_expense_id = expense
    result['audit_privacy_probe'] = {
        'native_move_visible': bool(actor['account.move'].search([('id', '=', bill.id)])),
        'audit_visible': bool(actor['baseer.financial.correction.audit'].search([('id', '=', original_audit_id)])),
        'company_id': company.id, 'configured_private_expense': company.baseer_salary_expense_id.id,
        'source_expense': expense.id}
    check('native source is actually private under current configuration', not result['audit_privacy_probe']['native_move_visible'])
    check('audit search follows current native source privacy', not actor['baseer.financial.correction.audit'].search([('id', '=', original_audit_id)]))
    deny('audit detail cannot reveal newly private source', lambda: actor['baseer.financial.correction.audit'].browse(original_audit_id).read(['before_json']))
    check('wizard baseline follows current native source privacy', not actor['baseer.financial.correction'].search([('id', '=', w.id)]))
    check('wizard lines follow current native source privacy', not actor['baseer.financial.correction.line'].search([('id', 'in', original_wizard_line_ids)]))
    company.baseer_salary_expense_id = old_salary_expense
    check('ordinary audit becomes readable under restored native policy', actor['baseer.financial.correction.audit'].search([('id', '=', original_audit_id)]).id == original_audit_id)
    extra_rule = admin['ir.rule'].create({'name': 'IC1 synthetic independent source rule',
        'model_id': admin['ir.model']._get_id('account.move'), 'domain_force': repr([('id', '!=', bill.id)])})
    check('audit honors additional independent native source rule', not actor['baseer.financial.correction.audit'].search([('id', '=', original_audit_id)]))
    extra_rule.unlink()

    wrong_company = admin['res.company'].search([('id', '!=', company.id)], limit=1)
    if wrong_company:
        deny('forged active company cannot broaden original correction', lambda: actor['account.move'].with_context(allowed_company_ids=wrong_company.ids).browse(unpaid.id).action_baseer_correct_operation())

    standalone = admin['account.payment'].create({'partner_id': vendor.id, 'partner_type': 'supplier',
        'payment_type': 'outbound', 'amount': 400, 'date': today, 'company_id': company.id,
        'journal_id': treasury.id, 'payment_method_line_id': treasury.outbound_payment_method_line_ids.filtered(lambda method: method.code == 'manual')[:1].id})
    standalone.action_post()
    ws = actor['baseer.financial.correction'].browse(actor['account.payment'].browse(standalone.id).action_baseer_correct_operation()['res_id'])
    ws.write({'reason': 'Correct standalone actual amount', 'payment_amount_input': '500'})
    confirm(ws)
    check('standalone payment actual amount corrected natively', dec(standalone.amount) == 500 and dec(standalone._seek_for_lines()[0].balance) == -500 and not ws.move_id)

    # Batch native approval and correction preserve neighboring source rows.
    mapping = admin['baseer.purchase.category.map'].search([('company_id', '=', company.id)], limit=1)
    if mapping:
        method = treasury.outbound_payment_method_line_ids.filtered(lambda p: p.code == 'manual')[:1]
        batch = actor['baseer.purchase.batch'].create({'company_id': company.id, 'line_ids': [Command.create({
            'invoice_date': today, 'partner_id': vendor.id, 'supplier_ref': 'IC1-BATCH-' + str(index),
            'category_map_id': mapping.id, 'description': 'IC1 batch', 'gross_amount': 400,
            'tax_id': False, 'payment_method_line_id': method.id, 'is_credit': False}) for index in range(2)]})
        batch.action_approve()
        row, neighbor = batch.line_ids
        neighbor_before = neighbor.read(['gross_amount', 'move_id', 'payment_id', 'partner_id'])
        wb = actor['baseer.financial.correction'].browse(row.action_baseer_correct_operation()['res_id'])
        wb.write({'reason': 'Correct batch actual payment', 'gross_amount_input': '500', 'correct_payment': True, 'payment_amount_input': '500'})
        confirm(wb)
        check('batch correction synchronizes current source gross and bill', dec(row.gross_amount) == 500 and dec(row.move_id.amount_total) == 500 and dec(row.payment_id.amount) == 500)
        check('batch remains approved and neighbor untouched', batch.state == 'approved' and neighbor_before == neighbor.read(['gross_amount', 'move_id', 'payment_id', 'partner_id']))
        original = json.loads(wb.audit_id.before_json)['batch']
        check('immutable audit retains original batch input', dec(original['gross']) == 400 and original['partner_id'] == vendor.id)
        wbpartial = actor['baseer.financial.correction'].browse(neighbor.action_baseer_correct_operation()['res_id'])
        wbpartial.write({'reason': 'Correct batch invoice preserve payment', 'gross_amount_input': '500'})
        confirm(wbpartial)
        check('batch partial correction keeps actual payment400', dec(neighbor.gross_amount) == 500 and dec(neighbor.payment_id.amount) == 400 and dec(neighbor.move_id.amount_residual) == 100)
    else:
        raise AssertionError('A batch category mapping fixture is required')
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    guard.stop()
    result['rollback'] = before == stamp()
    result['modules_preserved'] = modules == env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
    result['hard_commit_guard'] = True
    result['source_unchanged_during_checks'] = result['source_hashes'] == hashes()
    result['pass_count'] = len(checks)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, default=str))
assert result['status'] == 'PASS' and result['rollback'] and result['modules_preserved'] and result['source_unchanged_during_checks']
