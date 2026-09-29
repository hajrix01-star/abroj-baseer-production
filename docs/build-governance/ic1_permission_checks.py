"""Targeted user correction-toggle checks; no broad accounting regression."""
import json
import traceback
from pathlib import Path
from unittest.mock import patch
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.su and env.cr.dbname.startswith('baseer_ic1_')
out = Path('/mnt/qa-evidence/ic1-permission-checks.json')
checks = []
result = {'status': 'FAIL', 'database': env.cr.dbname, 'checks': checks, 'rollback': False}
def check(label, condition):
    assert condition, label
    checks.append(label)
def deny(label, callback):
    try:
        with env.cr.savepoint():
            callback()
    except (AccessError, UserError, ValidationError):
        checks.append(label)
        return
    raise AssertionError(label + ': unexpectedly allowed')
def counts():
    return {model: env[model].with_context(active_test=False).search_count([]) for model in (
        'res.users', 'res.partner', 'account.move', 'account.move.line', 'account.payment',
        'baseer.financial.correction.audit', 'baseer.pos.summary')}
before = counts()
modules = env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('Permission fixtures must never commit'))
guard.start()
try:
    company = env['res.company'].search([('currency_id.name', '=', 'SAR')]).filtered(lambda c: c.baseer_salary_expense_id)[:1]
    assert company
    ctx = {'allowed_company_ids': company.ids, 'lang': 'en_US', 'tracking_disable': True, 'no_reset_password': True}
    admin = env(context=ctx)
    users, actors = {}, {}
    for role in ('accountant', 'cashier', 'owner'):
        users[role] = admin['res.users'].create({'name': 'IC1 permission ' + role,
            'login': 'ic1-permission-' + role, 'baseer_access_role': role,
            'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        actors[role] = env(user=users[role].id, su=False, context=ctx)
    check('new accountant retains enabled default', users['accountant'].baseer_allow_financial_correction is True)
    actor = actors['accountant']
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_deduction_account_id | company.baseer_loan_account_id
    expense = admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', 'expense'), ('id', 'not in', private.ids)], limit=1)
    payable = admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', 'liability_payable'), ('id', 'not in', private.ids)], limit=1)
    purchase = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'purchase')], limit=1)
    treasury = admin['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank'])]).filtered(lambda j: j.default_account_id.account_type == 'asset_cash')[:1]
    method = treasury.outbound_payment_method_line_ids.filtered(lambda p: p.code == 'manual')[:1]
    method.payment_account_id = treasury.default_account_id
    vendor = admin['res.partner'].create({'name': 'IC1 permission supplier', 'company_id': company.id, 'property_account_payable_id': payable.id})
    today = fields.Date.context_today(admin['account.move'])
    bill = admin['account.move'].create({'move_type': 'in_invoice', 'company_id': company.id,
        'journal_id': purchase.id, 'partner_id': vendor.id, 'invoice_date': today, 'date': today,
        'invoice_line_ids': [Command.create({'name': 'Permission fixture', 'quantity': 1, 'price_unit': 400,
            'account_id': expense.id, 'tax_ids': [Command.clear()]})]})
    bill.action_post()
    action = actor['account.move'].browse(bill.id).action_baseer_correct_operation()
    check('enabled accountant opens standard correction', action['res_model'] == 'baseer.financial.correction')
    check('enabled accountant sees correction entry flag', actor['account.move'].browse(bill.id).baseer_can_correct_operation)
    wizard = actor['baseer.financial.correction'].browse(action['res_id'])
    wizard.reason = 'Permission revocation test'
    wizard.line_ids.price_unit_input = '500'
    payment = admin['account.payment'].create({'company_id': company.id, 'partner_id': vendor.id,
        'partner_type': 'supplier', 'payment_type': 'outbound', 'amount': 400, 'date': today,
        'journal_id': treasury.id, 'payment_method_line_id': method.id})
    payment.action_post()
    users['accountant'].baseer_allow_financial_correction = False
    check('disabled accountant entry flags update for invoice payment and batch',
        not actor['account.move'].browse(bill.id).baseer_can_correct_operation
        and not actor['account.payment'].browse(payment.id).baseer_can_correct_operation
        and not actor['baseer.purchase.batch.line'].new({}).baseer_can_correct_operation)
    deny('disabled accountant cannot open invoice correction', lambda: actor['account.move'].browse(bill.id).action_baseer_correct_operation())
    deny('disabled accountant cannot open payment correction', lambda: actor['account.payment'].browse(payment.id).action_baseer_correct_operation())
    deny('revocation blocks confirmation of an already opened wizard', wizard.action_confirm)
    deny('disabled accountant cannot bypass dispatcher through factory', lambda: actor['baseer.financial.correction']._open_for_source(move=actor['account.move'].browse(bill.id)))
    check('revoked confirmation changes no accounting or audit', bill.amount_total == 400 and payment.amount == 400
        and admin['baseer.financial.correction.audit'].search_count([]) == before['baseer.financial.correction.audit'])
    with patch.object(type(actor['account.move']), '_baseer_correction_owner', side_effect=AssertionError('A disabled user reached source routing')):
        deny('disabled permission checked before source-owned dispatcher', lambda: actor['account.move'].browse(bill.id).action_baseer_correct_operation())
    config = admin['pos.config'].search([('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
    assert config
    summary = admin['baseer.pos.summary'].create({'company_id': company.id, 'config_id': config.id,
        'business_date': today, 'period_scope': 'morning', 'day_schedule': 'morning', 'zero_sales': True})
    # Routing classification only. The owning POS posting engine is not invoked.
    tagged = bill.copy({'ref': 'IC1 permission POS route'})
    env.cr.execute('UPDATE account_move SET baseer_pos_summary_id=%s WHERE id=%s', [summary.id, tagged.id])
    tagged.invalidate_recordset()
    deny('disabled accountant cannot route POS correction', lambda: actor['account.move'].browse(tagged.id).action_baseer_correct_operation())
    me = actor['res.users'].browse(actor.uid)  # env.user itself is a sudo recordset in Odoo.
    deny('accountant cannot enable own flag directly', lambda: me.write({'baseer_allow_financial_correction': True}))
    deny('accountant cannot change own flag together with preferences', lambda: me.write({'baseer_allow_financial_correction': True, 'notification_type': 'email'}))
    check('self-enable failure leaves flag disabled', users['accountant'].baseer_allow_financial_correction is False)
    deny('accountant cannot inject enabled flag on user creation', lambda: actor['res.users'].create({
        'name': 'Forbidden permission user', 'login': 'ic1-permission-forbidden', 'baseer_allow_financial_correction': True}))
    deny('accountant cannot enable flag through forged default context', lambda: actor['res.users'].with_context(default_baseer_allow_financial_correction=True).create({
        'name': 'Forbidden default user', 'login': 'ic1-permission-default-forbidden'}))
    users['cashier'].baseer_allow_financial_correction = True
    check('cashier correction entry flag remains hidden', not actors['cashier']['account.move'].browse(bill.id).baseer_can_correct_operation)
    deny('cashier enabled flag never grants correction', lambda: actors['cashier']['account.move'].browse(bill.id).action_baseer_correct_operation())
    deny('cashier direct confirmation remains forbidden', lambda: actors['cashier']['baseer.financial.correction'].browse(wizard.id).action_confirm())
    users['owner'].baseer_allow_financial_correction = False
    owner_action = actors['owner']['account.move'].browse(bill.id).action_baseer_correct_operation()
    check('owner retains correction rights despite disabled flag', owner_action['res_model'] == 'baseer.financial.correction')
    check('owner correction entry remains visible despite flag', actors['owner']['account.move'].browse(bill.id).baseer_can_correct_operation)
    actors['owner']['res.users'].browse(users['accountant'].id).write({'baseer_allow_financial_correction': True})
    check('owner can explicitly enable accountant permission', users['accountant'].baseer_allow_financial_correction is True)
    reopened = actor['account.move'].browse(bill.id).action_baseer_correct_operation()
    check('reenabled accountant can open correction again', reopened['res_model'] == 'baseer.financial.correction')
    check('reenabling refreshes the accountant entry flag', actor['account.move'].browse(bill.id).baseer_can_correct_operation)
    # Exercise real native confirmation once after re-enabling; financial logic
    # is unchanged and covered by the independent 63-case accounting suite.
    valid = actor['baseer.financial.correction'].browse(reopened['res_id'])
    valid.reason = 'Authorized permission toggle correction'
    valid.line_ids.price_unit_input = '500'
    valid.action_confirm()
    check('reenabled accountant confirms ordinary correction', bill.amount_total == 500 and bill.state == 'posted' and valid.completed)
    check('exactly one authorized audit records real caller', valid.audit_id.user_id.id == actor.uid
        and admin['baseer.financial.correction.audit'].search_count([]) == before['baseer.financial.correction.audit'] + 1)
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    guard.stop()
    result['rollback'] = before == counts()
    result['modules_preserved'] = modules == env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
    result['hard_commit_guard'] = True
    result['passed'] = len(checks)
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
assert result['status'] == 'PASS' and result['rollback'] and result['modules_preserved']
