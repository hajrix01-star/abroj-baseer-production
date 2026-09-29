"""Validate native source actions in the existing cash report QA showcase.

No synthetic ledger, company or configuration writes. The current transaction
rolls back; vendor failure audit may persist through independent QA transactions.
"""
import json
from decimal import Decimal
from pathlib import Path

from odoo.exceptions import AccessError, UserError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
c = env['res.company'].browse(9).exists()
assert c and c.name == 'QA الفئات النقدية'
ctx = dict(env.context, allowed_company_ids=c.ids)
scoped = env(context=ctx)
report = scoped['eh.account.dynamic.report'].search([('code', '=', 'baseer_cash_categories')], limit=1)
assert report
options = {'date': {'mode': 'range', 'date_from': '2026-09-01', 'date_to': '2026-09-30'},
    'company_ids': c.ids, 'posted_only': True, 'baseer_include_tax': True,
    'lazy_expand': True, 'unfold_all': True}
checks = []


def passed(condition, label, **evidence):
    assert condition, (label, evidence)
    checks.append({'check': label, 'passed': True, **evidence})


def money(actual, expected, label):
    passed(Decimal(str(actual)).quantize(Decimal('.01')) == Decimal(str(expected)).quantize(Decimal('.01')),
        label, actual=str(actual), expected=str(expected))


def original_moves(action):
    """Evaluate only the native returned action against normal ORM record rules."""
    assert isinstance(action, dict) and action.get('type') == 'ir.actions.act_window', action
    model = action.get('res_model')
    assert model in ('account.move', 'account.move.line'), model
    records = scoped[model].browse(action['res_id']).exists() if action.get('res_id') else scoped[model].search(action.get('domain') or [])
    assert all(record.company_id == c for record in records), 'Action leaks another company'
    operations = records if model == 'account.move' else records.move_id
    assert all(move.state == 'posted' for move in operations), 'Action includes a draft operation'
    return records, operations


def action_for(line_id, opts=None, target=None):
    return (target or report).get_drilldown_for_line(opts or options, line_id)


def operation_ids(line_id, opts=None):
    return set(original_moves(action_for(line_id, opts))[1].ids)


try:
    gross = report.render(options, use_cache=False)
    net_opts = dict(options, baseer_include_tax=False)
    net = report.render(net_opts, use_cache=False)
    money(gross['totals']['displayed_net_movement'], -271, 'gross report amount unchanged')
    money(net['totals']['displayed_net_movement'], -277, 'tax-excluded report amount unchanged')
    action_evidence = []
    for payload, opts, mode in [(gross, options, 'gross'), (net, net_opts, 'tax-excluded')]:
        for line in payload['lines']:
            value = line['columns'][0]['value']
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            action = action_for(line['id'], opts)
            records, originals = original_moves(action)
            passed(True, mode + ' amount opens a safe native source action: ' + line['id'],
                model=action['res_model'], source_count=len(records), operation_count=len(originals), value=value)
            action_evidence.append({'mode': mode, 'line_id': line['id'], 'model': action['res_model'],
                'source_ids': sorted(records.ids), 'operation_ids': sorted(originals.ids), 'value': value})

    invoices = scoped['account.move'].search([('company_id', '=', c.id),
        ('state', '=', 'posted'), ('move_type', 'in', ['in_invoice', 'out_invoice', 'out_refund'])])
    mixed = invoices.filtered(lambda move: move.move_type == 'in_invoice' and Decimal(str(move.amount_total)) == Decimal('445'))
    passed(len(mixed) == 1, 'mixed partial-payment original invoice located')
    water = scoped['product.category'].search([('name', '=', 'مياه')], limit=1)
    soft = scoped['product.category'].search([('name', '=', 'مشروبات غازية')], limit=1)
    food = scoped['product.category'].search([('name', '=', 'مواد غذائية')], limit=1)
    category_lines = []
    for category in (water, soft, food):
        line = next(line for line in gross['lines'] if line['id'].startswith('payments/category-') and line['id'].endswith('category-%s' % category.id))
        category_lines.append(line)
        passed(operation_ids(line['id']) == set(mixed.ids), 'category opens exact mixed-bill original: ' + category.name)
        passed(operation_ids(line['id'], net_opts) == operation_ids(line['id']), 'tax toggle preserves category original documents: ' + category.name)
    mother_id = category_lines[0]['parent_id']
    children = [line for line in gross['lines'] if line.get('parent_id') == mother_id]
    union = set().union(*(operation_ids(line['id']) for line in children))
    passed(operation_ids(mother_id) == union, 'parent category original sources equal union of children')
    single = action_for(category_lines[0]['id'])
    passed(bool(single.get('res_id')) and 'form' in single.get('view_mode', ''), 'one original opens native form directly')
    multiple = action_for('payments')
    passed(not multiple.get('res_id') and 'list' in multiple.get('view_mode', ''), 'multiple originals open native list')

    source_domain = [('company_id', '=', c.id), ('parent_state', '=', 'posted'), ('account_id.account_type', '=', 'asset_cash')]
    for key, date_operator in [('opening_cash_balance', '<'), ('closing_cash_balance', '<=')]:
        cutoff = '2026-09-01' if key == 'opening_cash_balance' else '2026-09-30'
        expected = scoped['account.move.line'].search(source_domain + [('date', date_operator, cutoff)])
        records, originals = original_moves(action_for('baseer-total-' + key))
        passed(set(originals.ids) == set(expected.move_id.ids), key + ' opens exact cash ledger operations')
        if records._name == 'account.move.line':
            passed(set(records.ids) == set(expected.ids), key + ' contains exact posted cash lines and cutoff')

    for line in gross['lines']:
        if line['id'].startswith('receipts/journal-') and line['id'].count('/') == 1:
            journal_id = int(line['id'].split('journal-')[1])
            cash_receipts = scoped['account.move.line'].search(source_domain + [
                ('journal_id', '=', journal_id), ('date', '>=', '2026-09-01'),
                ('date', '<=', '2026-09-30'), ('balance', '>', 0)])
            # Exclude the incoming bank leg of a same-move cash transfer + fee.
            cash_receipts = cash_receipts.filtered(lambda row: sum(
                move_line.balance for move_line in row.move_id.line_ids
                if move_line.account_id.account_type == 'asset_cash') > 0)
            records, originals = original_moves(action_for(line['id']))
            passed(records._name == 'account.move.line' and set(records.ids) == set(cash_receipts.ids),
                'receipt channel opens exact cash source lines: ' + line['name'])

    taxes = invoices.filtered(lambda move: move.amount_tax and move.amount_residual < move.amount_total)
    tax_records, tax_originals = original_moves(action_for('baseer-total-excluded_tax_bridge', net_opts))
    passed(set(tax_originals.ids) == set(taxes.ids), 'VAT bridge opens only settled tax-bearing source invoices')
    passed(all(move.amount_tax for move in tax_originals), 'VAT bridge excludes salary/electricity/direct entries')
    period_cash = scoped['account.move.line'].search(source_domain + [('date', '>=', '2026-09-01'), ('date', '<=', '2026-09-30')])
    external_cash = period_cash.filtered(lambda row: row.balance * sum(
        peer.balance for peer in row.move_id.line_ids if peer.account_id.account_type == 'asset_cash') > 0)
    for key, expected in [('receipts', external_cash.filtered(lambda row: row.balance > 0)),
                          ('payments', external_cash.filtered(lambda row: row.balance < 0)),
                          ('displayed_net_movement', external_cash),
                          ('actual_net_movement', period_cash), ('balance_check', period_cash)]:
        records, originals = original_moves(action_for('baseer-total-' + key))
        passed(records._name == 'account.move.line' and set(records.ids) == set(expected.ids),
            key + ' total uses its exact cash source scope')

    unknown = next(line for line in gross['lines'] if line['id'] == 'payments/unclassified')
    records, originals = original_moves(action_for(unknown['id']))
    expected_advance = scoped['account.move.line'].search([('company_id', '=', c.id),
        ('account_id.name', '=', 'سلف ودفعات مقدمة'), ('balance', '=', 40)])
    passed(set(originals.ids) == set(expected_advance.move_id.ids), 'unclassified advance opens exact original entry')
    zero_action = action_for('baseer-total-balance_check')
    passed(isinstance(zero_action, dict), 'zero reconciliation amount remains actionable')

    for bad_id in ['payments/category-999999999', '../../account.move/1', '', None]:
        try:
            with env.cr.savepoint():
                action_for(bad_id)
        except (UserError, AccessError):
            checks.append({'check': 'invalid/tampered source row rejected', 'row_id': bad_id, 'passed': True})
        else:
            raise AssertionError(('Invalid row accepted', bad_id))
    forged_options = dict(options, source_ids=[1], move_ids=[1], domain=[('company_id', '!=', c.id)])
    try:
        with env.cr.savepoint():
            forged = action_for(category_lines[0]['id'], forged_options)
            passed(set(original_moves(forged)[1].ids) == set(mixed.ids), 'caller-supplied source IDs/domain cannot redirect action')
    except (UserError, AccessError):
        checks.append({'check': 'forged source options rejected', 'passed': True})

    restricted = env['res.users'].search([('login', '=', 'qa_cash_categories_restricted')], limit=1)
    assert restricted
    for label, actor, bad_options in [
        ('missing report role', env.ref('base.public_user'), options),
        ('unauthorized company', restricted, dict(options, company_ids=[6])),
    ]:
        try:
            with env.cr.savepoint():
                report.with_user(actor).with_context(allowed_company_ids=c.ids).get_drilldown_for_line(bad_options, 'payments')
        except AccessError:
            checks.append({'check': label + ' source access denied', 'passed': True})
        else:
            raise AssertionError(label + ' action access was allowed')

    money(report.render(options, use_cache=False)['totals']['displayed_net_movement'], -271, 'drilldown does not alter financial result')
    env.cr.rollback()
    result = {'company_id': 9, 'checks': checks, 'action_evidence': action_evidence,
        'synthetic_ledger_company_config_changes': False,
        'audit_retention_note': 'Vendor durable failure audit may remain in QA through independent transactions.'}
    Path('/mnt/qa-evidence/cash_drilldown_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('CASH_DRILLDOWN_QA_SUCCESS', len(checks), 'checks; no ledger/configuration mutation')
except Exception:
    env.cr.rollback()
    raise
