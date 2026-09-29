"""Bounded POS-S1 backend contract tests. QA only; every fixture rolls back."""
import json
from pathlib import Path
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
qa = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids': [6], 'lang': 'en_US', 'tz': 'Asia/Riyadh'})
Summary = qa['baseer.pos.summary']
config = qa['pos.config'].browse(1)
checks = []
serial = 0


def check(condition, name):
    assert condition, name
    checks.append(name)


def denied(call, name):
    try:
        with env.cr.savepoint():
            call()
    except (AccessError, UserError, ValidationError):
        check(True, name)
    else:
        raise AssertionError(name + ' was allowed')


def counts():
    return {model: qa[model].search_count([]) for model in ('pos.order', 'pos.session', 'pos.payment', 'account.move', 'account.payment', 'account.move.line')}


def values(date='2026-04-04', period='all'):
    global serial
    serial += 1
    return {'business_date': date, 'period_scope': period, 'external_reference': 'BACKEND ROLLBACK %s' % serial,
            'customer_count': 60, 'allocation_ids': [Command.create({'payment_method_id': method, 'amount': amount})
                                                   for method, amount in [(1, 500), (2, 700), (3, 600)]]}


before_all = counts()
summary = Summary.create(values())
denied(lambda: Summary.create(values(period='morning')), 'All Day excludes Morning')
morning = Summary.create(values('2026-04-05', 'morning'))
evening = Summary.create(values('2026-04-05', 'evening'))
denied(lambda: Summary.create(values('2026-04-05')), 'Morning and Evening exclude All Day')
check(morning.id != evening.id, 'Distinct nonoverlapping shifts are accepted')
denied(lambda: summary.with_context(allowed_company_ids=[9, 6]).write({'notes': 'wrong company'}), 'Stale active-company summary write rejected')
denied(lambda: summary.allocation_ids[:1].with_context(allowed_company_ids=[9, 6]).write({'amount': 600}), 'Stale active-company allocation write rejected')
denied(lambda: summary.write({'company_id': 9}), 'Summary company immutable')
denied(lambda: Summary.create(dict(values('2026-04-06'), customer_count=True)), 'Boolean customer count rejected')
denied(lambda: Summary.create(dict(values('2026-04-06'), customer_count=-1)), 'Negative customer count rejected')
denied(lambda: summary.allocation_ids[:1].write({'amount': 0.001}), 'Subcent amount rejected')
denied(lambda: qa['pos.session'].with_context(_baseer_pos_summary_token=True).create({'config_id': config.id}), 'RPC boolean token cannot open dedicated summary session')
denied(lambda: config.open_ui(), 'Dedicated POS cannot open ordinary cashier UI')

result = summary.action_approve()
check(result['res_model'] == 'baseer.pos.summary' and result['res_id'] == summary.id, 'Approval returns persisted summary')
counts_approved = counts()
summary.action_approve()
check(counts() == counts_approved, 'Repeated approval does not create more native documents')
denied(lambda: summary.write({'notes': 'change'}), 'Approved summary immutable')
denied(lambda: summary.allocation_ids[:1].write({'amount': 1}), 'Approved allocation immutable')
denied(lambda: summary.order_id.write({'amount_total': 1}), 'Native summary order cannot be edited directly')
denied(lambda: summary.order_id.lines.write({'price_unit': 1}), 'Native summary line cannot be edited directly')
denied(lambda: summary.order_id.payment_ids[:1].write({'amount': 1}), 'Native summary payment cannot be edited directly')
denied(lambda: summary.session_id.write({'stop_at': False}), 'Native summary session dates protected')
invoice_source_counts = counts()
denied(summary.order_id.action_pos_order_invoice, 'Native Invoice RPC cannot create a duplicate summary invoice')
denied(summary.order_id.refund, 'Native Return Products RPC cannot create a summary refund session or order')
denied(summary.order_id.unlink, 'Original summary order cannot be deleted')
denied(summary.order_id.lines.unlink, 'Original summary lines cannot be deleted')
denied(lambda: summary.order_id.with_context(_force_unlink=True).unlink(), 'Uninstall context cannot bypass summary order deletion guard')
denied(lambda: summary.order_id.lines.with_context(_force_unlink=True).unlink(), 'Uninstall context cannot bypass summary line deletion guard')
check(counts() == invoice_source_counts and len(summary.order_id.lines) == 1 and not summary.order_id.account_move,
      'Invoice, refund and unlink RPC attempts leave native source and all financial counts unchanged')
denied(lambda: config.payment_method_ids[:1].write({'baseer_category_id': config.payment_method_ids[1].baseer_category_id.id}), 'Approved method category cannot change')
denied(lambda: config.payment_method_ids[:1].baseer_category_id.write({'kind': 'bank'}), 'Approved category kind cannot change')

context_draft = Summary.with_context(default_state='approved', default_order_id=summary.order_id.id,
                                    default_session_id=summary.session_id.id).create(values('2026-04-06'))
check(context_draft.state == 'draft' and not context_draft.order_id and not context_draft.session_id,
      'Context defaults cannot forge summary state or original links')
denied(lambda: Summary.create(dict(values('2026-04-07'), order_id=summary.order_id.id)), 'Explicit original source forgery rejected')

# A genuine normal POS remains available, with only a shared bank method so
# no cash method is assigned to two configurations.
ordinary = config.copy({'name': 'Backend rollback normal POS', 'baseer_summary_only': False,
                        'payment_method_ids': [Command.set([2])]})
normal_session = qa['pos.session'].create({'config_id': ordinary.id})
normal_session.set_opening_control(0, 'Rollback native POS control')
normal_order = qa['pos.order'].create({'session_id': normal_session.id, 'date_order': fields.Datetime.now(),
                                     'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0})
check(normal_order.source == 'pos' and not normal_order.baseer_summary_id, 'Ordinary native POS creates a normal order')
denied(lambda: normal_session.write({'config_id': config.id}), 'Normal session cannot target dedicated summary configuration')
denied(lambda: normal_order.write({'session_id': summary.session_id.id}), 'Normal order cannot target dedicated summary session')
denied(lambda: qa['pos.order'].with_context(default_session_id=summary.session_id.id).create({'amount_total': 0}),
       'Context-default dedicated session is guarded before native creation')

partial = Summary.create(values('2026-04-07'))
before_partial = counts()
session_class = type(qa['pos.session'])
original_bank = session_class._create_combine_account_payment
calls = [0]


def fail_second_bank(record, *args, **kwargs):
    calls[0] += 1
    if calls[0] == 2:
        raise UserError('Injected late native platform posting failure')
    return original_bank(record, *args, **kwargs)


with patch.object(session_class, '_create_combine_account_payment', fail_second_bank):
    denied(partial.action_approve, 'Late native payment failure raises')
check(calls[0] == 2 and counts() == before_partial, 'Late native payment failure rolls back all generated documents')
check(partial.exists() and partial.state == 'draft' and not partial.order_id and not partial.session_id,
      'Caught approval failure preserves the saved draft and its inputs')


class Restore(Exception):
    pass


try:
    with env.cr.savepoint():
        qa['res.company'].browse(6).write({'sale_lock_date': '2026-04-07'})
        denied(partial.action_approve, 'Locked historical business date rejected without shifting')
        raise Restore()
except Restore:
    pass

pos_only = qa['res.users'].with_context(no_reset_password=True).create({
    'name': 'POS summary backend rollback POS only', 'login': 'pos-summary-backend-rollback-pos-only',
    'company_id': 6, 'company_ids': [Command.set([6])],
    'group_ids': [Command.set([qa.ref('base.group_user').id, qa.ref('point_of_sale.group_pos_user').id])],
})
check(bool(partial.with_user(pos_only).read(['name'])), 'POS-only internal operator can read its company summary')
check(not pos_only.has_group('account.group_account_invoice'), 'Operator fixture has no invoicing permission')
denied(lambda: partial.with_user(pos_only).action_approve(), 'POS-only operator cannot bypass invoicing approval permission')

env.cr.rollback()
check(counts() == before_all, 'All test financial and POS fixtures rolled back')
Path('/mnt/qa-evidence/pos_summary_backend_checks.json').write_text(
    json.dumps({'database': env.cr.dbname, 'checks': checks, 'passed': len(checks), 'rollback': True}, indent=2), encoding='utf-8')
print('POS_SUMMARY_BACKEND_OK', len(checks))
