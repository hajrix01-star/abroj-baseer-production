"""Same 90-day ledger, independent sales inputs, database-enforced read only."""
import json
import traceback
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch

from odoo import api
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.baseer_financial_register.models.cash_register import CashReportCapture

assert env.cr.dbname in ('baseer_sim90_fix_20260911', 'baseer_ic1_20260910')
env.cr.rollback()
env.cr.execute('SET TRANSACTION READ ONLY')
root = Path('/tmp/sim90')
info = json.loads((root / 'context.json').read_text(encoding='utf8'))
manifest = json.loads((root / 'sales-manifest.json').read_text(encoding='utf8'))
local = api.Environment(env.cr, info['user_id'], {'allowed_company_ids': [info['company_id']],
    'lang': 'en_US', 'tz': 'Asia/Riyadh'}, su=False)
checks, snapshots = [], {}
result = {'status': 'FAIL', 'database': env.cr.dbname, 'read_only': True, 'checks': checks,
          'monthly': snapshots, 'oracle': 'Persisted pre-repair scenario input events, not report output'}


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def check(label, expected, actual):
    checks.append({'label': label, 'expected': str(expected), 'actual': str(actual), 'passed': expected == actual})


try:
    owned_ids = {ident for event in manifest['events'] for ident in event['move_ids']}
    original_payload = CashReportCapture._payload
    observed = {}

    def capture_payload(self, *args, **kwargs):
        payload = original_payload(self, *args, **kwargs)
        internal = kwargs.get('internal')
        if internal and internal.get('baseer_register_capture'):
            observed['fragments'] = internal['baseer_register_fragments']
        return payload

    for month in ('2026-01', '2026-02', '2026-03', '2026-09'):
        observed.clear()
        with patch.object(CashReportCapture, '_payload', capture_payload):
            _, company, payload, rows = local['account.move']._register_cash_snapshot(month)
        fragments = observed['fragments']
        lines = local['account.move.line'].browse(sorted({fragment['cash_source'] for fragment in fragments}))
        line_moves = {line.id: line.move_id.id for line in lines}
        owned = [fragment for fragment in fragments if line_moves[fragment['cash_source']] in owned_ids]
        actual_in = sum((money(fragment['gross']) for fragment in owned if fragment['direction'] == 'in'), Decimal(0))
        actual_out = sum((money(fragment['gross']) for fragment in owned if fragment['direction'] == 'out'), Decimal(0))
        actual_collections = sum((money(fragment['gross']) for fragment in owned if fragment.get('sale_collection')), Decimal(0))
        expected_events = [event for event in manifest['events'] if event['date'].startswith(month)]
        expected_in = sum((money(event['expected_cash_in']) for event in expected_events), Decimal(0))
        expected_out = sum((money(event['expected_cash_out']) for event in expected_events), Decimal(0))
        expected_collections = sum((money(event['expected_sales_collections']) for event in expected_events), Decimal(0))
        expected_operational = sum((money(event['expected_operational_in']) for event in expected_events), Decimal(0))
        operational = sum((money(row['receipts']) for ident, row in rows.items() if ident in owned_ids), Decimal(0))
        check(month + ' actual cash in unchanged', expected_in, actual_in)
        check(month + ' actual cash out unchanged', expected_out, actual_out)
        check(month + ' positive evidenced sales collections', expected_collections, actual_collections)
        check(month + ' operational incoming unchanged', expected_operational, operational)
        check(month + ' complete application coverage', '', payload['meta']['baseer_platform_warning'])
        native = [fragment for fragment in owned if fragment.get('baseer_native_pos_session_id')]
        for fragment in native:
            check(month + ' native POS evidenced VAT line ' + str(fragment['cash_source']),
                money(money(fragment['gross']) / Decimal('1.15')), money(fragment['net']))
        snapshots[month] = {'cash_in': str(actual_in), 'cash_out': str(actual_out),
            'sales_collections': str(actual_collections), 'operational_in': str(operational),
            'native_fragments': len(native), 'warning': payload['meta']['baseer_platform_warning']}
        event_differences = []
        for event in expected_events:
            wanted = money(event['expected_sales_collections'])
            actual = sum((money(fragment['gross']) for fragment in owned
                          if fragment.get('sale_collection') and line_moves[fragment['cash_source']] in event['move_ids']), Decimal(0))
            if wanted != actual:
                event_differences.append({'event': event['key'], 'kind': event['kind'],
                    'move_ids': event['move_ids'], 'expected': str(wanted), 'actual': str(actual),
                    'fragments': [fragment for fragment in owned if line_moves[fragment['cash_source']] in event['move_ids']]})
        snapshots[month]['collection_event_differences'] = event_differences
        if month != '2026-09':
            year, number = map(int, month.split('-'))
            tax_capture = {'baseer_register_capture': True}
            tax_payload = local['eh.account.dynamic.report.handler.baseer_cash_categories']._compute_report({
                'company_ids': company.ids, 'posted_only': True, 'baseer_include_tax': False,
                'date': {'mode': 'range', 'date_from': month + '-01',
                         'date_to': str(date(year, number, monthrange(year, number)[1]))}}, internal=tax_capture)
            tax_fragments = tax_capture['baseer_register_fragments']
            sales_net_in = sum((money(fragment['net']) for fragment in tax_fragments
                if line_moves[fragment['cash_source']] in owned_ids and fragment['direction'] == 'in'), Decimal(0))
            sales_net_out = sum((money(fragment['net']) for fragment in tax_fragments
                if line_moves[fragment['cash_source']] in owned_ids and fragment['direction'] == 'out'), Decimal(0))
            expected_net_in = expected_net_out = Decimal(0)
            for event in expected_events:
                if event['kind'] == 'platform_settlement':
                    expected_net_in += money(money(event['gross']) / Decimal('1.15')) - money(event.get('fee'))
                else:
                    expected_net_in += money(money(event['expected_cash_in']) / Decimal('1.15'))
                    expected_net_out += money(money(event['expected_cash_out']) / Decimal('1.15'))
            check(month + ' tax excluded sales receipts from input VAT15', expected_net_in, sales_net_in)
            check(month + ' tax excluded refunds/reversals from input VAT15', expected_net_out, sales_net_out)
            check(month + ' tax excluded rendered receipts use net fragments',
                sum((money(fragment['net']) for fragment in tax_fragments if fragment['direction'] == 'in'), Decimal(0)),
                money(tax_payload['meta']['exact_totals']['receipts']))

    zero = local['account.payment'].browse(711)
    check('native equal sale/refund creates preserved zero payment', Decimal(0), money(zero.amount))
    check('zero payment keeps posted original receipt', 'posted', zero.move_id.state)
    check('zero receipt retains both zero journal lines', True,
          len(zero.move_id.line_ids) == 2 and all(money(line.balance) == 0 for line in zero.move_id.line_ids))
    handler = local['eh.account.dynamic.report.handler.baseer_cash_categories']
    session = local['pos.session'].browse(6)
    past = {'company_id': company.id, 'date_to': date(2025, 12, 31), 'visits': 0}
    check('source beyond cutoff never becomes proven sales', True,
          bool(handler._baseer_native_pos_evidence(session, past).get('error')))
    try:
        handler._baseer_native_pos_evidence(session, {'company_id': company.id,
            'date_to': date(2026, 3, 31), 'visits': 10000})
    except UserError:
        check('native evidence consumes report budget', True, True)
    else:
        check('native evidence consumes report budget', True, False)
    cashier = api.Environment(env.cr, info['roles']['cashier'], {'allowed_company_ids': [company.id]}, su=False)
    try:
        cashier['account.move']._register_cash_snapshot('2026-01')
    except (AccessError, UserError, ValidationError):
        check('cashier financial report access remains denied', True, True)
    else:
        check('cashier financial report access remains denied', True, False)
    result['failed'] = [item for item in checks if not item['passed']]
    result['status'] = 'PASS' if not result['failed'] else 'FAIL'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    (root / 'repair' / 'sales-regression.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    print('SALES_REGRESSION', result['status'], len(checks), 'failed', len(result.get('failed', [])), flush=True)
assert result['status'] == 'PASS', result.get('error') or result.get('failed')
