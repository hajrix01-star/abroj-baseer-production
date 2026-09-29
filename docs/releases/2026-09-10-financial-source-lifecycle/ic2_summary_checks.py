"""Isolated native summary lifecycle fixtures; full rollback, no MAIN calls."""
import json
import time
import traceback
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
out = Path('/mnt/qa-evidence/ic2-summary-checks.json')
checks = []
result = {'status': 'FAIL', 'database': env.cr.dbname, 'checks': checks, 'rollback': False}
models = ('account.move', 'account.move.line', 'account.payment', 'pos.order', 'pos.session',
          'baseer.pos.summary', 'baseer.pos.summary.allocation', 'baseer.financial.correction.audit', 'res.users')

def counts():
    return {m: env[m].with_context(active_test=False).search_count([]) for m in models}

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

before = counts()
versions = {m.name: m.latest_version for m in env['ir.module.module'].search([('state', '=', 'installed')])}
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('Summary fixtures cannot commit'))
guard.start()
try:
    config = env['pos.config'].search([('baseer_summary_only', '=', True)]).filtered(
        lambda c: c.company_id.currency_id.name == 'SAR' and {'cash', 'bank', 'platform'}.issubset(
            set(c.payment_method_ids.filtered('active').mapped('baseer_category_id.kind'))))[:1]
    assert config, 'Configured cash/bank/application summary fixture required'
    company = config.company_id
    ctx = {'allowed_company_ids': company.ids, 'lang': 'en_US', 'tracking_disable': True, 'no_reset_password': True}
    admin = env(context=ctx)
    methods = [config.payment_method_ids.filtered(lambda m: m.active and m.baseer_category_id.kind == kind)[:1]
               for kind in ('cash', 'bank', 'platform')]
    users, actors = {}, {}
    for role in ('owner', 'accountant', 'cashier'):
        user = admin['res.users'].create({'name': 'IC2 summary ' + role, 'login': 'ic2-summary-' + role,
            'baseer_access_role': role, 'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        users[role] = user
        actors[role] = env(user=user.id, su=False, context=ctx)
    actor = actors['accountant']
    first_date = fields.Date.context_today(admin['baseer.pos.summary']) - timedelta(days=35)
    next_day = [first_date]

    def make(zero=False):
        while admin['baseer.pos.summary'].search_count([('company_id', '=', company.id), ('business_date', '=', next_day[0])]):
            next_day[0] += timedelta(days=1)
        day = next_day[0]
        next_day[0] += timedelta(days=1)
        source = actor['baseer.pos.summary'].create({'company_id': company.id, 'config_id': config.id,
            'business_date': day, 'day_schedule': 'all', 'period_scope': 'all', 'customer_count': 0 if zero else 12,
            'zero_sales': zero, 'allocation_ids': [Command.create({'payment_method_id': method.id,
                'amount': 0 if zero else amount}) for method, amount in zip(methods, (115, 230, 345))]})
        source.action_approve()
        return source

    def open_wizard(source, target=actor):
        action = source.with_env(target).action_open_correction()
        return target['baseer.pos.summary.correction'].browse(action['res_id'])

    def confirm_values(wizard, operation='edit'):
        wizard.write({'operation': operation, 'reason': 'IC2 reviewed bookkeeping correction', 'acknowledge_bookkeeping': True})

    source = make()
    check('accountant approves native cash bank application source', source.state == 'approved' and source.amount_gross == 690)
    original_moves = source._native_moves()
    original_ids = original_moves.ids
    wizard = open_wizard(source)
    stale = open_wizard(source)
    check('summary editor defaults to edit with original count and methods', wizard.operation == 'edit'
          and wizard.customer_count_input == '12' and len(wizard.line_ids) == 3)
    deny('cashier old source correction entry blocked', lambda: source.with_env(actors['cashier']).action_open_correction())
    deny('cashier cannot directly create old native wizard', lambda: actors['cashier']['baseer.pos.summary.correction'].create({'summary_id': source.id}))
    deny('creator cannot forge baseline', lambda: wizard.write({'baseline_json': '{}'}))
    deny('creator cannot replace original payment method', lambda: wizard.line_ids[:1].write({'original_allocation_id': source.allocation_ids[-1].id}))
    deny('fractional third decimal rejected before monetary coercion', lambda: wizard.line_ids[:1].write({'amount_input': '1.001'}))
    wizard.write({'reason': 'Needs acknowledgement'})
    deny('bookkeeping effect acknowledgement required', wizard.action_correct)
    users['accountant'].baseer_allow_financial_correction = False
    deny('revoked accountant cannot open summary correction', source.action_open_correction)
    deny('revoked accountant cannot confirm previously opened summary wizard', wizard.action_correct)
    users['accountant'].baseer_allow_financial_correction = True
    confirm_values(wizard)
    wizard.write({'customer_count_input': '18', 'line_ids': [Command.update(line.id, {'amount_input': str(amount)})
                 for line, amount in zip(wizard.line_ids, (230, 345, 460))]})
    started = time.monotonic()
    wizard.action_correct()
    result['edit_seconds'] = round(time.monotonic() - started, 3)
    replacement = source.replacement_id
    check('edit atomically cancels original and approves replacement', source.state == 'cancelled' and replacement.state == 'approved')
    check('replacement preserves business date and source lineage', replacement.business_date == source.business_date and replacement.replaces_id == source)
    check('edited sales and customers match native replacement', replacement.amount_gross == 1035 and replacement.customer_count == 18)
    check('original evidence IDs and amounts retained', source._native_moves().ids == original_ids and source.amount_gross == 690)
    check('all original native moves reversed exactly once', set(source.reversal_move_ids.reversed_entry_id.ids) == set(original_ids)
          and all(m.state == 'posted' and m.date == source.business_date for m in source.reversal_move_ids))
    for account in (original_moves | source.reversal_move_ids).line_ids.account_id:
        check('original and reversal net zero account ' + str(account.id),
              round(sum((original_moves | source.reversal_move_ids).line_ids.filtered(lambda l: l.account_id == account).mapped('balance')), 2) == 0)
    check('audit records actual accountant and edit classification', wizard.audit_id.user_id.id == actor.uid and wizard.audit_id.operation == 'edit')
    snapshot_counts = counts()
    wizard.action_correct()
    check('repeat edit confirmation is idempotent', counts() == snapshot_counts)
    confirm_values(stale, 'cancel')
    deny('stale competing cancel cannot reverse source twice', stale.action_correct)
    totals = actor['baseer.pos.daily.report']._aggregate_days(company, source.business_date, source.business_date)['totals']
    check('daily report excludes cancelled original and includes edited totals once', float(totals['recorded_sales']) == 1035 and totals['recorded_customers'] == 18)

    cancel = open_wizard(replacement)
    confirm_values(cancel, 'cancel')
    cancel.action_correct()
    check('cancel reverses entire replacement without making a new draft', replacement.state == 'cancelled' and not replacement.replacement_id)
    check('cancellation retains immutable audit classification', cancel.audit_id.operation == 'cancel' and cancel.completed)
    totals = actor['baseer.pos.daily.report']._aggregate_days(company, source.business_date, source.business_date)['totals']
    check('cancelled operation no longer contributes sales or customers', float(totals['recorded_sales']) == 0 and totals['recorded_customers'] == 0)
    snapshot_counts = counts()
    cancel.action_correct()
    check('repeat cancel creates no second reversals or audit', counts() == snapshot_counts)

    zero_source = make()
    zero = open_wizard(zero_source)
    confirm_values(zero)
    zero.write({'zero_sales': True, 'customer_count_input': '0',
                'line_ids': [Command.update(line.id, {'amount_input': '0'}) for line in zero.line_ids]})
    zero.action_correct()
    check('nonzero to zero-sales transition approves atomically', zero_source.replacement_id.zero_sales
          and zero_source.replacement_id.state == 'approved' and not zero_source.replacement_id.move_id)
    zero_cancel = open_wizard(zero_source.replacement_id)
    confirm_values(zero_cancel, 'cancel')
    zero_cancel.action_correct()
    check('zero-sales cancellation needs no artificial accounting entry', not zero_source.replacement_id.reversal_move_ids
          and zero_source.replacement_id.state == 'cancelled')

    failed_source = make()
    tax_stale = open_wizard(failed_source)
    confirm_values(tax_stale)
    tax = config.baseer_summary_tax_id
    original_rate = tax.amount
    tax.amount = original_rate + 1
    deny('same-transaction tax rate change invalidates source preview', tax_stale.action_correct)
    tax.amount = original_rate
    failed = open_wizard(failed_source)
    confirm_values(failed)
    saved_counts = counts()
    original_approve = type(failed_source).action_approve
    def fail_replacement(records):
        if records.replaces_id:
            raise ValidationError('Injected native replacement approval failure')
        return original_approve(records)
    with patch.object(type(failed_source), 'action_approve', fail_replacement):
        deny('replacement approval failure rolls back reversal and replacement', failed.action_correct)
    check('failed edit retains original approved source and all counts', failed_source.state == 'approved'
          and not failed_source.replacement_id and not failed_source.reversal_move_ids and counts() == saved_counts)
    with patch.object(type(failed_source), '_check_journal_dates', side_effect=ValidationError('Locked period')):
        deny('native locked-date rejection leaves original untouched', failed.action_correct)
    check('locked-date failure has no financial effects', counts() == saved_counts)

    platform_account = methods[2].outstanding_account_id
    original_platform_line = failed_source._native_moves().line_ids.filtered(lambda l: l.account_id == platform_account and l.balance > 0)
    assert platform_account.reconcile and original_platform_line
    settlement = admin['account.move'].create({'journal_id': methods[0].journal_id.id, 'company_id': company.id,
        'date': failed_source.business_date, 'line_ids': [Command.create({'account_id': platform_account.id, 'credit': 10}),
         Command.create({'account_id': methods[0].journal_id.default_account_id.id, 'debit': 10})]})
    settlement.action_post()
    (original_platform_line | settlement.line_ids.filtered(lambda l: l.account_id == platform_account)).reconcile()
    ext = open_wizard(failed_source)
    confirm_values(ext, 'cancel')
    deny('actual external settlement blocks whole-summary cancellation', ext.action_correct)
    check('external settlement stays linked after refused cancellation', bool(original_platform_line.matched_credit_ids)
          and failed_source.state == 'approved' and not failed_source.reversal_move_ids)
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    guard.stop()
    result.update(rollback=before == counts(), hard_commit_guard=True, passed=len(checks),
        modules_preserved=versions == {m.name: m.latest_version for m in env['ir.module.module'].search([('state', '=', 'installed')])})
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
assert result['status'] == 'PASS' and result['rollback'] and result['modules_preserved']
