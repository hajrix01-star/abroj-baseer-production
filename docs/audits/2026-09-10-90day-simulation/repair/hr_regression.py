"""Focused, read-only HR cash regressions on the authorized SIM90 repair clone.

Invoke in Odoo shell after loading the candidate addon source. No fixtures,
mutations, commit, independent source formulas imported from product code.
"""
import calendar
import json
import traceback
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from odoo import api
from odoo.exceptions import AccessError, UserError

assert env.cr.dbname == 'baseer_sim90_fix_20260911'
env.cr.execute('SET TRANSACTION READ ONLY')
BASE = Path('/tmp/sim90')
OUT = BASE / 'repair'
OUT.mkdir(exist_ok=True)
hr = json.loads((BASE / 'hr-manifest.json').read_text(encoding='utf8'))
E = api.Environment(env.cr, 5, {'allowed_company_ids': [2], 'lang': 'en_US'}, su=False)
H = E['eh.account.dynamic.report.handler.baseer_cash_categories']
company = E['res.company'].browse(2)
result = {'status': 'FAIL', 'database': env.cr.dbname, 'read_only': True, 'checks': [],
          'samples': [], 'monthly': {}, 'scenarios': {'salary_payments': 0, 'advance_cash_legs': 0}}


def q(x):
    return Decimal(str(x or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def check(name, actual, expected, tolerance=Decimal(0)):
    numeric = isinstance(actual, Decimal) and isinstance(expected, Decimal)
    passed = abs(actual - expected) <= tolerance if numeric else actual == expected
    result['checks'].append({'name': name, 'actual': str(actual), 'expected': str(expected),
                            'tolerance': str(tolerance), 'passed': passed})
    assert passed, result['checks'][-1]


def state(cutoff):
    start = cutoff.replace(day=1)
    cash = E['account.move.line'].search([('company_id', '=', 2), ('parent_state', '=', 'posted'),
        ('account_id.account_type', '=', 'asset_cash'), ('date', '>=', start), ('date', '<=', cutoff)])
    return {'company_id': 2, 'date_to': cutoff, 'cash_ids': set(cash.ids), 'opening_cash_ids': set(),
            'visits': 0, 'diagnostics': set(), 'budget': None}


def trace_cash(move, cutoff):
    s = state(cutoff)
    fragments = []
    for line in move.line_ids.filtered(lambda row: row.account_id.account_type != 'asset_cash' and row.balance):
        fragments.extend(H._trace(line, -q(line.balance), s))
    return fragments, s


def by_account(fragments):
    values = defaultdict(lambda: q(0))
    for fragment in fragments:
        source = E['account.move.line'].browse(fragment['source'])
        values[source.account_id.id] += q(fragment['gross'])
    return values


slips = {row['id']: row['expected'] for row in hr['manifest'] if row['model'] == 'hr.payslip'}
salary_account = company.baseer_salary_expense_id.id
deduction_account = company.baseer_deduction_account_id.id
advance_account = company.baseer_loan_account_id.id
month_totals = defaultdict(lambda: defaultdict(lambda: q(0)))
try:
    for event in hr['events']:
        if event['kind'] not in ('salary_payment', 'advance_disbursement', 'advance_direct_repayment'):
            continue
        move = E['account.move'].browse(event['move_ids'])
        assert len(move) == 1
        day = date.fromisoformat(event['date'])
        cutoff = day.replace(day=calendar.monthrange(day.year, day.month)[1])
        fragments, trace_state = trace_cash(move, cutoff)
        amount = q(event.get('expected_cash_out')) + q(event.get('expected_cash_in'))
        label = event['key']
        check(label + ' exact cash conservation', sum((q(x['gross']) for x in fragments), q(0)), amount)
        check(label + ' no invented tax', sum((q(x['net']) for x in fragments), q(0)), amount)
        check(label + ' no unresolved category fragments', any(x['unknown'] for x in fragments), False)
        check(label + ' original evidence lines not repeatedly consumed', len([x['source'] for x in fragments]),
              len({x['source'] for x in fragments}))
        actual = by_account(fragments)
        if event['kind'] == 'salary_payment':
            result['scenarios']['salary_payments'] += 1
            expected = slips[int(label.rsplit('-', 1)[1])]
            paid, net = -amount, q(expected['baseer_net'])
            # Independent input arithmetic. A largest-remainder category split
            # may allocate the final cent to a different nonzero category.
            desired = {salary_account: q(-q(expected['baseer_gross']) * paid / net),
                       deduction_account: q(q(expected['baseer_deduction']) * paid / net),
                       advance_account: q(q(expected['baseer_loan_amount']) * paid / net)}
            for account_id, value in desired.items():
                check(label + ' signed input category ' + str(account_id), actual[account_id], value, q('.01'))
            check(label + ' no category beyond source inputs', set(actual) - set(desired), set())
            for account_id, value in actual.items():
                month_totals[day.strftime('%Y-%m')][account_id] += value
            if move.id == 110:
                check('P1 payment32 cash', amount, q('-3706.19'))
                check('P1 payment32 salary gross once', actual[salary_account], q('-3774.19'))
                check('P1 payment32 deductions once', actual[deduction_account], q('68.00'))
                check('P1 payment32 no loan recovery', actual[advance_account], q(0))
                result['samples'].append({'move_id': move.id, 'payment_id': move.origin_payment_id.id,
                    'cash': str(amount), 'account_allocations': {str(k): str(v) for k, v in actual.items()},
                    'sources': [x['source'] for x in fragments]})
        else:
            result['scenarios']['advance_cash_legs'] += 1
            check(label + ' advance source only', dict(actual), {advance_account: amount})
            later, _ = trace_cash(move, date(2026, 3, 31))
            check(label + ' future recovery does not change cash classification', by_account(later), actual)
    check('full dense payroll payments covered', result['scenarios']['salary_payments'], 77)
    check('P1 payment32 sample was executed', bool(result['samples']), True)
    example = E['account.move'].browse(110).line_ids.filtered(lambda row: row.account_id.account_type == 'liability_payable')
    before_posting = state(date(2026, 1, 30))
    future = H._trace(example, -q(example.balance), before_posting)
    check('future payment retained unclassified before reporting cutoff', all(x['unknown'] for x in future), True)
    check('future payment cutoff preserves amount', sum((q(x['gross']) for x in future), q(0)), q('-3706.19'))
    for uid in (6, 7):
        actor = api.Environment(env.cr, uid, {'allowed_company_ids': [2], 'lang': 'en_US'}, su=False)
        try:
            actor['eh.account.dynamic.report.handler.baseer_cash_categories']._trace(
                actor['account.move.line'].browse(example.id), q('-3706.19'), state(date(2026, 1, 31)))
        except AccessError:
            check('private payroll cash source denied to role ' + str(uid), True, True)
        else:
            check('private payroll cash source denied to role ' + str(uid), False, True)
    sample_loan = E['baseer.hr.loan'].browse(next(row['id'] for row in hr['manifest'] if row['model'] == 'baseer.hr.loan'))
    principal = sample_loan.move_id.line_ids.filtered(lambda row: row.account_id.account_type == 'asset_receivable')
    exhausted = state(date(2026, 3, 31))
    exhausted['visits'] = H._BASEER_LIMIT
    try:
        H._trace(principal, -q(principal.balance), exhausted)
    except UserError:
        check('HR source respects the existing trace budget', True, True)
    else:
        check('HR source respects the existing trace budget', False, True)
    foreign = state(date(2026, 3, 31))
    foreign['company_id'] = 3
    try:
        H._baseer_cash_source_boundary(principal, -q(principal.balance), foreign)
    except AccessError:
        check('HR source boundary enforces company isolation', True, True)
    else:
        check('HR source boundary enforces company isolation', False, True)
    result['monthly'] = {month: {str(k): str(v) for k, v in amounts.items()} for month, amounts in month_totals.items()}
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    result['checks_passed'] = sum(c['passed'] for c in result['checks'])
    (OUT / 'hr-cash-regression.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    print('SIM90_HR_CASH_REGRESSION', result['status'], result['checks_passed'], flush=True)
assert result['status'] == 'PASS', result.get('error')
