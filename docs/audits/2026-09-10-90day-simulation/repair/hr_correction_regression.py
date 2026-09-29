"""Two native payroll-correction cash boundaries, isolated clone, full rollback."""
import hashlib
import json
import traceback
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch
from odoo import api

assert env.cr.dbname == 'baseer_sim90_fix_20260911'
BASE = Path('/tmp/sim90')
OUT = BASE / 'repair'
OUT.mkdir(exist_ok=True)
HR = json.loads((BASE / 'hr-manifest.json').read_text(encoding='utf8'))
E = api.Environment(env.cr, 5, {'allowed_company_ids': [2], 'lang': 'en_US', 'tz': 'Asia/Riyadh',
    'tracking_disable': True, 'mail_create_nolog': True, 'mail_create_nosubscribe': True}, su=False)
company = E['res.company'].browse(2)
H = E['eh.account.dynamic.report.handler.baseer_cash_categories']
DAY = date(2026, 3, 31)
result = {'status': 'FAIL', 'database': env.cr.dbname, 'checks': [], 'sources': [],
          'hard_commit_guard': True, 'rolled_back': False}


def q(x):
    return Decimal(str(x or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def check(name, actual, expected):
    result['checks'].append({'name': name, 'actual': str(actual), 'expected': str(expected), 'passed': actual == expected})
    assert actual == expected, result['checks'][-1]


def fingerprint():
    tables = {'account.move': ['write_date', 'state', 'date', 'amount_total', 'amount_residual', 'line_ids'],
        'account.move.line': ['write_date', 'account_id', 'debit', 'credit', 'balance', 'amount_residual',
                             'matched_debit_ids', 'matched_credit_ids'],
        'account.payment': ['write_date', 'state', 'amount', 'move_id'],
        'account.partial.reconcile': ['write_date', 'amount', 'debit_move_id', 'credit_move_id'],
        'baseer.hr.loan': ['write_date', 'state', 'balance'],
        'baseer.hr.loan.allocation': ['write_date', 'amount', 'reversal_move_id'],
        'hr.payslip': ['write_date', 'state', 'baseer_net', 'baseer_paid', 'baseer_residual', 'baseer_correction_ids'],
        'res.users': ['write_date', 'group_ids', 'company_ids', 'baseer_allow_financial_correction']}
    answer = {}
    for model, fields in tables.items():
        rows = env[model].with_context(active_test=False).search([], order='id').read(fields)
        answer[model] = {'count': len(rows), 'sha256': hashlib.sha256(
            json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()}
    return answer


def trace(move, cutoff):
    cash = E['account.move.line'].search([('company_id', '=', 2), ('parent_state', '=', 'posted'),
        ('account_id.account_type', '=', 'asset_cash'), ('date', '>=', cutoff.replace(day=1)), ('date', '<=', cutoff)])
    state = {'company_id': 2, 'date_to': cutoff, 'cash_ids': set(cash.ids), 'opening_cash_ids': set(),
             'visits': 0, 'diagnostics': set(), 'budget': None}
    fragments = []
    for line in move.line_ids.filtered(lambda row: row.account_id.account_type != 'asset_cash' and row.balance):
        fragments.extend(H._trace(line, -q(line.balance), state))
    return fragments


before = fingerprint()
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('Correction regression must never commit'))
guard.start()
try:
    candidate_ids = [row['id'] for row in HR['manifest'] if row['model'] == 'hr.payslip'
                     and q(row['expected']['baseer_paid']) == 0]
    slip = E['hr.payslip'].browse(candidate_ids).filtered(lambda row: row.date_to == DAY).sorted('id')[:1]
    assert slip and q(slip.baseer_residual) > 0
    treasury = E['account.journal'].browse(json.loads((BASE / 'context.json').read_text())['bank_journal_id'])
    original_net = q(slip.baseer_net)
    original_paid = q(slip.baseer_paid)
    for kind, signed_adjustment, paid, expense_account in (
            ('wage', q('100.01'), q('100.01'), company.baseer_salary_expense_id),
            ('deduction', q('-25.01'), q('25.01'), company.baseer_deduction_account_id)):
        wizard = E['baseer.payroll.correction'].create({'slip_id': slip.id, 'company_id': 2,
            'kind': kind, 'amount': float(signed_adjustment), 'date': DAY,
            'reason': 'SIM90 rollback-only cash boundary regression ' + kind, 'reviewed': True})
        wizard.action_confirm()
        source = wizard.move_id
        check(kind + ' correction posted through native workflow', source.state, 'posted')
        check(kind + ' immutable source points to original payslip', source.baseer_correction_payslip_id.id, slip.id)
        check(kind + ' immutable original accounting link', source.baseer_correction_source_id.id, slip.move_id.id)
        check(kind + ' posting date remains actual source date', source.date, DAY)
        expense = source.line_ids.filtered(lambda row: row.account_id == expense_account)
        check(kind + ' input funded expense exact', q(sum(expense.mapped('balance'))), paid)
        register = E['account.payment.register'].with_context(active_model='account.move', active_ids=source.ids).create({
            'journal_id': treasury.id,
            'payment_method_line_id': treasury.outbound_payment_method_line_ids.filtered(lambda row: row.code == 'manual')[:1].id,
            'payment_date': DAY, 'amount': float(paid), 'group_payment': True, 'payment_difference_handling': 'open'})
        payment = register._create_payments()
        check(kind + ' one native cash payment', len(payment), 1)
        check(kind + ' actual payment posted', payment.state, 'paid')
        check(kind + ' actual liquidity exact', q(sum(payment.move_id.line_ids.filtered(
            lambda row: row.account_id.account_type == 'asset_cash').mapped('balance'))), -paid)
        fragments = trace(payment.move_id, DAY)
        check(kind + ' source boundary conserves actual cash', sum((q(row['gross']) for row in fragments), q(0)), -paid)
        check(kind + ' no invented tax', sum((q(row['net']) for row in fragments), q(0)), -paid)
        check(kind + ' no unresolved source', any(row['unknown'] for row in fragments), False)
        check(kind + ' all allocated evidence stays in correction source',
              {E['account.move.line'].browse(row['source']).move_id.id for row in fragments}, {source.id})
        check(kind + ' correction account category only',
              {E['account.move.line'].browse(row['source']).account_id.id for row in fragments}, {expense_account.id})
        prior = trace(payment.move_id, date(2026, 3, 30))
        check(kind + ' future correction payment not classified before cutoff', all(row['unknown'] for row in prior), True)
        check(kind + ' cutoff fallback still conserves amount', sum((q(row['gross']) for row in prior), q(0)), -paid)
        result['sources'].append({'kind': kind, 'payslip_id': slip.id, 'correction_id': wizard.id,
            'correction_move_id': source.id, 'payment_id': payment.id, 'payment_move_id': payment.move_id.id,
            'expected_account_id': expense_account.id, 'expected_cash': str(-paid),
            'fragment_source_ids': [row['source'] for row in fragments]})
    slip.invalidate_recordset()
    check('two native adjustments increase net by declared 125.02', q(slip.baseer_net), original_net + q('125.02'))
    check('two correction-only payments increase paid by 125.02', q(slip.baseer_paid), original_paid + q('125.02'))
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    guard.stop()
    after = fingerprint()
    result.update(before=before, after=after, rolled_back=before == after,
                  checks_passed=sum(row['passed'] for row in result['checks']))
    (OUT / 'hr-correction-regression.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    print('SIM90_HR_CORRECTION_REGRESSION', result['status'], result['checks_passed'], 'ROLLBACK', result['rolled_back'], flush=True)
assert result['status'] == 'PASS' and result['rolled_back'], result.get('error', 'Rollback fingerprint mismatch')
