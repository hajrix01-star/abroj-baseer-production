"""Staging-only writer and independent source acceptance before one commit."""
import json
import traceback
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from odoo import api

assert env.cr.dbname == 'baseer_sim90_20260910'
root = Path('/tmp/sim90')
info = json.loads((root / 'context.json').read_text(encoding='utf8'))
local = api.Environment(env.cr, info['user_id'], {
    'allowed_company_ids': [info['company_id']], 'lang': 'en_US', 'tz': 'Asia/Riyadh',
    'tracking_disable': True, 'mail_create_nolog': True, 'mail_create_nosubscribe': True,
    'mail_notify_force_send': False}, su=False)
ctx = dict(info, simulation_authorized=True,
    company=local['res.company'].browse(info['company_id']),
    cash_journal=local['account.journal'].browse(info['cash_journal_id']),
    bank_journal=local['account.journal'].browse(info['bank_journal_id']),
    progress=lambda area, count, day: print('SIM90_PROGRESS', area, count, day, flush=True))
scope = {}
exec(compile((root / 'seed_sales.py').read_bytes(), 'seed_sales.py', 'exec'), scope)


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


try:
    result = scope['seed_sales'](local, ctx)
    local.flush_all()
    checks = []

    def check(label, expected, actual, model=None, ident=None):
        passed = expected == actual
        checks.append({'label': label, 'model': model, 'id': ident,
                       'expected': expected, 'actual': actual, 'passed': passed})

    for row in result['summaries']:
        source = local['baseer.pos.summary'].browse(row['id'])
        check('summary gross', row['gross'], money(source.amount_gross), source._name, source.id)
        check('summary active', row['active_expected'], source.state == 'approved', source._name, source.id)
        check('summary customers', row['customers'], source.customer_count, source._name, source.id)
        for method_id, expected in row['allocation_by_method'].items():
            actual = sum((money(a.amount) for a in source.allocation_ids if a.payment_method_id.id == method_id), Decimal(0))
            check('summary method %s' % method_id, expected, actual, source._name, source.id)
    for row in result['orders']:
        source = local['pos.order'].browse(row['id'])
        check('native order gross', row['gross'], money(source.amount_total), source._name, source.id)
        check('native order historical date', row['date'], str(source.date_order.date()), source._name, source.id)
    for row in result['invoices']:
        source = local['account.move'].browse(row['id'])
        check('invoice total', abs(row['gross']), money(source.amount_total), source._name, source.id)
        check('invoice tax', abs(row['tax']), money(source.amount_tax), source._name, source.id)
        check('invoice active', row['active_expected'], source.state == 'posted', source._name, source.id)
        if row['active_expected']:
            check('invoice residual', abs(row['expected_residual']), money(source.amount_residual), source._name, source.id)
    for row in result['claims']:
        source = local[row['model']].browse(row['id'])
        moves = source._native_moves() if source._name == 'baseer.pos.summary' else source._get_related_account_moves()
        lines = moves.line_ids.filtered(lambda line: line.account_id.id == row['account_id'])
        check('platform residual', row['expected_residual'],
              sum((money(line.amount_residual) for line in lines), Decimal(0)), source._name, source.id)
    owned_ids = sorted({ident for row in result['events'] for ident in row['move_ids']})
    for move in local['account.move'].browse(owned_ids):
        check('owned move balanced', Decimal(0), sum((money(line.balance) for line in move.line_ids), Decimal(0)), move._name, move.id)
        check('owned move company', info['company_id'], move.company_id.id, move._name, move.id)
    for row in result['events']:
        moves = local['account.move'].browse(row['move_ids']).filtered(lambda move: move.state == 'posted')
        liquidity = moves.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_cash')
        check('event actual cash net: ' + row['key'], money(row['expected_cash_in'] + row['expected_cash_out']),
              money(sum((money(line.balance) for line in liquidity), Decimal(0))), row['model'], row['id'])
    result['seed_checks'] = checks
    result['failed_checks'] = [row for row in checks if not row['passed']]
    (root / 'sales-manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    assert not result['failed_checks'], result['failed_checks'][:25]
    env.cr.commit()
    summary = {'status': 'PASS', 'database': env.cr.dbname, 'company_id': info['company_id'],
               'counts': result['counts'], 'seed_checks': len(checks), 'failed_checks': 0,
               'manifest': '/tmp/sim90/sales-manifest.json', 'committed': True}
    (root / 'sales.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    print('SIM90_SALES_COMPLETE', json.dumps(summary), flush=True)
except Exception:
    env.cr.rollback()
    (root / 'sales-error.txt').write_text(traceback.format_exc(), encoding='utf8')
    raise
