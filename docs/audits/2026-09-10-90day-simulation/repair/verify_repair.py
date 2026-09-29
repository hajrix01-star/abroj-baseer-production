"""Independent, PostgreSQL read-only repair verification; no fixture mutation.

Run in Odoo shell on the exact repair clone. REPAIR_PHASE=targeted or coupling.
Old manifests and evidence remain immutable; new outputs stay in /tmp/sim90/repair.
"""
import calendar
import hashlib
import json
import os
import time
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch

from odoo import api

BASE = Path('/tmp/sim90')
OUT = BASE / 'repair'
assert env.cr.dbname in ('baseer_sim90_fix_20260911', 'baseer_ic1_20260910')
phase = os.environ.get('REPAIR_PHASE', 'targeted')
assert phase in ('targeted', 'coupling')
namespace = {'__name__': 'independent_simulation_library'}
exec(compile((OUT / 'verify_simulation.py').read_bytes(), str(OUT / 'verify_simulation.py'), 'exec'), namespace)
data = json.loads((BASE / 'context.json').read_text())
manifest_files = [BASE / 'context.json']
for part in ('sales', 'hr', 'purchases'):
    path = BASE / (part + '.json')
    loaded = json.loads(path.read_text())
    if isinstance(loaded.get('manifest'), str):
        path = Path(loaded['manifest'])
        loaded = json.loads(path.read_text())
    assert isinstance(loaded['events'], list)
    data[part] = loaded
    manifest_files.append(path)

if phase == 'targeted':
    sections = [f'2026-{m:02d}:{kind}' for m in (1, 2, 3) for kind in ('cash', 'ledger')]
    sections += ['cash-quarter', 'security']
else:
    sections = ['all-quarter'] + [f'2026-{m:02d}:inout' for m in (1, 2, 3)]
data['_verify_sections'] = sections
assert not os.environ.get('SIMULATION_VERIFY_SECTIONS'), 'Use phase selection only'
result = namespace['verify'](env, data)
result['phase'] = phase
result['manifest_files'] = [{'name': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in manifest_files]
result['script_files'] = [{'name': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in (OUT / 'verify_repair.py', OUT / 'verify_simulation.py')]

CENT = Decimal('.01')
ZERO = Decimal('0.00')
def q(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)

def check(key, actual, expected, tolerance=ZERO):
    passed = abs(q(actual) - q(expected)) <= tolerance
    result['checks'].append({'key': 'repair-independent|' + key, 'status': 'PASS' if passed else 'FAIL',
                             'actual': str(actual), 'expected': str(expected), 'rounding_tolerance': str(tolerance)})

if phase == 'targeted':
    env.cr.execute('SET TRANSACTION READ ONLY')
    actor = api.Environment(env.cr, int(data['user_id']), {
        'allowed_company_ids': [int(data['company_id'])], 'lang': 'en_US'}, su=False)
    assert not actor.su
    company = actor.company
    handler = actor['eh.account.dynamic.report.handler.baseer_cash_categories']
    hr = data['hr']
    slips = {int(row['id']): row['expected'] for row in hr['manifest'] if row['model'] == 'hr.payslip'}
    events = [row for row in hr['events'] if row['kind'] in (
        'salary_payment', 'advance_disbursement', 'advance_direct_repayment')]
    accounts = {'salary': company.baseer_salary_expense_id.id,
                'deduction': company.baseer_deduction_account_id.id,
                'loan': company.baseer_loan_account_id.id}
    samples = []
    for month in (1, 2, 3):
        first, last = f'2026-{month:02d}-01', f'2026-{month:02d}-{calendar.monthrange(2026, month)[1]}'
        captures = []
        original = type(handler)._payload
        def capture(self, movements, *args, **kwargs):
            captures.extend(movements)
            return original(self, movements, *args, **kwargs)
        started = time.perf_counter()
        with patch.object(type(handler), '_payload', capture):
            handler._compute_report({'company_ids': [company.id], 'posted_only': True,
                'baseer_include_tax': True,
                'date': {'mode': 'range', 'date_from': first, 'date_to': last}})
        result['endpoint_timings'].append({'endpoint': 'independent-hr-fragments', 'from': first, 'to': last,
            'milliseconds': round((time.perf_counter() - started) * 1000, 2)})
        cash_lines = actor['account.move.line'].browse(sorted({f['cash_source'] for f in captures}))
        cash_move = {line.id: line.move_id.id for line in cash_lines}
        per_move = defaultdict(list)
        for frag in captures:
            per_move[cash_move[frag['cash_source']]].append(frag)
        for event in events:
            if not first <= event['date'] <= last:
                continue
            fragments = [f for mid in event['move_ids'] for f in per_move.get(mid, [])]
            values = {kind: sum((q(f['gross']) for f in fragments
                       if 'ledger-' + str(account) in [p[0] for p in f['path']]), ZERO)
                      for kind, account in accounts.items()}
            unknown = sum((q(f['gross']) for f in fragments if 'unclassified' in [p[0] for p in f['path']]), ZERO)
            cash = q(event['expected_cash_in']) + q(event['expected_cash_out'])
            key = event['key']
            check(key + ':fragment-net-input', sum((q(f['gross']) for f in fragments), ZERO), cash)
            check(key + ':no-unclassified-offset', unknown, ZERO)
            expected = {'salary': ZERO, 'deduction': ZERO, 'loan': cash}
            tolerance = ZERO
            if event['kind'] == 'salary_payment':
                slip_id = int(key.rsplit('-', 1)[1])  # Explicit seed key embeds slip identity.
                plan = slips[slip_id]
                gross, net = q(plan['baseer_gross']), q(plan['baseer_net'])
                deduction, loan = q(plan['baseer_deduction']), q(plan['baseer_loan_amount'])
                check(key + ':input-components-balance', gross - deduction - loan, net)
                ratio = -cash / net
                expected = {'salary': -gross * ratio, 'deduction': deduction * ratio, 'loan': loan * ratio}
                # Aggregate components may differ by one cent after distributing a
                # partial payment; full payments and total cash remain exact.
                tolerance = ZERO if -cash == net else CENT
            for kind in accounts:
                check(key + ':' + kind + ':input-allocation', values[kind], expected[kind], tolerance)
            samples.append({'key': key, 'date': event['date'], 'move_ids': event['move_ids'],
                            'cash': str(cash), 'expected': {k: str(q(v)) for k, v in expected.items()},
                            'actual': {k: str(v) for k, v in values.items()}, 'unknown': str(unknown)})
    result['hr_source_samples'] = samples
    env.cr.execute('SHOW transaction_read_only')
    assert env.cr.fetchone()[0] == 'on'
    env.cr.rollback()

result['status'] = 'FAIL' if any(row['status'] == 'FAIL' for row in result['checks']) else 'PASS'
result['counts_final'] = {'checks': len(result['checks']),
                        'failed': sum(row['status'] == 'FAIL' for row in result['checks'])}
target = OUT / ('verification-' + phase + '.json')
attempt = 1
while target.exists():
    attempt += 1
    target = OUT / ('verification-' + phase + '-' + str(attempt) + '.json')
result['evidence_output'] = target.name
target.write_text(json.dumps(result, default=str, ensure_ascii=False, indent=2))
print('REPAIR_VERIFICATION', phase, result['status'], json.dumps(result['counts_final']), flush=True)
