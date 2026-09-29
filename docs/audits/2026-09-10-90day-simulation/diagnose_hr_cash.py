"""Read-only, bounded cash-category payroll diagnosis on the published QA dataset."""
import calendar
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch
from odoo import api

assert env.cr.dbname == 'baseer_ic1_20260910'
env.cr.execute('SET TRANSACTION READ ONLY')
OUT = Path('/tmp/sim90')
HR = json.loads((OUT / 'hr-manifest.json').read_text(encoding='utf8'))
E = api.Environment(env.cr, 5, {'allowed_company_ids': [2], 'lang': 'en_US'}, su=False)
company = E['res.company'].browse(2)
handler = E['eh.account.dynamic.report.handler.baseer_cash_categories']
result = {'database': env.cr.dbname, 'read_only': True, 'months': [], 'samples': [], 'checks': []}


def q(x):
    return Decimal(str(x or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def aml(row):
    return {'id': row.id, 'move_id': row.move_id.id, 'name': row.name, 'date': str(row.date),
        'account_id': row.account_id.id, 'account_code': row.account_id.code,
        'balance': str(q(row.balance)), 'residual': str(q(row.amount_residual)),
        'payslip_id': row.move_id.baseer_payslip_id.id,
        'loan_id': row.move_id.baseer_loan_id.id,
        'origin_payment_id': row.move_id.origin_payment_id.id,
        'matches': [{'id': m.id, 'amount': str(q(m.amount)), 'debit': m.debit_move_id.id,
                     'credit': m.credit_move_id.id} for m in row.matched_debit_ids | row.matched_credit_ids]}


cash_event = {mid: event for event in HR['events'] for mid in event.get('move_ids', [])
              if q(event.get('expected_cash_in')) or q(event.get('expected_cash_out'))}
salary_event = {mid: event for event in HR['events'] if event['kind'] == 'salary_payment'
                for mid in event['move_ids']}
salary_key = 'ledger-%s' % company.baseer_salary_expense_id.id
for month in (1, 2, 3):
    first, last = date(2026, month, 1), date(2026, month, calendar.monthrange(2026, month)[1])
    expected = defaultdict(lambda: q(0))
    for event in HR['events']:
        if str(first) <= event['date'] <= str(last):
            expected[event['kind']] += q(event.get('expected_cash_out')) + q(event.get('expected_cash_in'))
    captured = []
    original_payload = type(handler)._payload
    def capture(self, movements, *args, **kwargs):
        captured.extend(movements)
        return original_payload(self, movements, *args, **kwargs)
    with patch.object(type(handler), '_payload', capture):
        payload = handler._compute_report({'company_ids': [2], 'posted_only': True,
            'baseer_include_tax': True, 'date': {'mode': 'range', 'date_from': str(first), 'date_to': str(last)}})
    salary_rows = [r for r in payload['lines'] if r['id'].endswith('/' + salary_key)]
    unknown_rows = [r for r in payload['lines'] if r['id'].endswith('/unclassified')]
    by_cash = {}
    for frag in captured:
        if frag['direction'] != 'out':
            continue
        cid = frag['cash_source']
        row = by_cash.setdefault(cid, {'salary': q(0), 'unknown': q(0), 'total': q(0), 'fragments': []})
        row['total'] += q(frag['gross'])
        keys = [p[0] for p in frag['path']]
        if salary_key in keys:
            row['salary'] += q(frag['gross'])
        if 'unclassified' in keys:
            row['unknown'] += q(frag['gross'])
        row['fragments'].append({'gross': str(q(frag['gross'])), 'source': frag['source'],
            'path': frag['path'], 'unknown': frag['unknown'], 'transfer': frag.get('transfer')})
    grouped = defaultdict(lambda: {'salary': q(0), 'unknown': q(0), 'actual_cash': q(0), 'sources': 0})
    candidates = []
    for cash_id, row in by_cash.items():
        cash = E['account.move.line'].browse(cash_id)
        event = cash_event.get(cash.move_id.id)
        kind = event['kind'] if event else 'non_hr_cash'
        group = grouped[kind]
        group['salary'] += row['salary']
        group['unknown'] += row['unknown']
        group['actual_cash'] += q(cash.balance)
        group['sources'] += 1
        if row['salary'] and cash.move_id.id in salary_event:
            candidates.append((abs(row['salary']) - abs(q(cash.balance)), cash, row))
    native_salary = E['account.move.line'].search([('company_id', '=', 2),
        ('parent_state', '=', 'posted'), ('account_id.account_type', '=', 'asset_cash'),
        ('move_id', 'in', list(salary_event)), ('date', '>=', first), ('date', '<=', last)])
    actual_salary = sum((q(line.balance) for line in native_salary), q(0))
    result['checks'].append({'name': 'salary input cash agrees native ledger %s' % month,
        'expected': str(expected['salary_payment']), 'actual': str(actual_salary),
        'passed': expected['salary_payment'] == actual_salary})
    result['months'].append({'month': first.strftime('%Y-%m'), 'expected_hr_cash_by_kind': expected,
        'actual_salary_cash': actual_salary, 'salary_report_rows': salary_rows, 'unclassified_rows': unknown_rows,
        'allocation_by_cash_source_kind': grouped, 'balance_check': payload['totals']['balance_check'],
        'diagnostics': payload['meta']['diagnostics']})
    for inflation, cash, row in sorted(candidates, key=lambda item: item[0], reverse=True)[:1]:
        counterparts = cash.move_id.line_ids.filtered(lambda line: line.account_id.account_type != 'asset_cash')
        matched = (counterparts.matched_debit_ids | counterparts.matched_credit_ids)
        peers = (matched.debit_move_id | matched.credit_move_id) - counterparts
        result['samples'].append({'month': month, 'salary_overallocation_above_actual_cash': inflation,
            'cash_line': aml(cash), 'cash_counterparts': [aml(x) for x in counterparts],
            'matched_salary_moves': {str(m.id): [aml(line) for line in m.line_ids] for m in peers.move_id},
            'allocation': row})
env.cr.rollback()
result['all_input_cash_checks_passed'] = all(c['passed'] for c in result['checks'])
(OUT / 'hr-cash-diagnostic.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
print('SIM90_HR_CASH_DIAG', json.dumps({'checks': result['checks'], 'months': [
    {'month': m['month'], 'actual_salary_cash': m['actual_salary_cash'],
     'allocation_by_cash_source_kind': m['allocation_by_cash_source_kind'],
     'salary_report_rows': m['salary_report_rows'], 'unclassified_rows': m['unclassified_rows']}
    for m in result['months']]}, default=str, ensure_ascii=True), flush=True)
