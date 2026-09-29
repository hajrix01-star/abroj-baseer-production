"""Read-only coverage diagnostics; no product edits and no fixture mutations."""
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from odoo import api
from odoo.addons.baseer_financial_register.models.cash_register import CashReportCapture, _PLATFORM_CAPTURE

assert env.cr.dbname == 'baseer_ic1_20260910'
env.cr.rollback()
env.cr.execute('SET TRANSACTION READ ONLY')
local = api.Environment(env.cr, 5, {'allowed_company_ids': [2], 'lang': 'en_US', 'tz': 'Asia/Riyadh'}, su=False)
company = local['res.company'].browse(2)
result = {'database': env.cr.dbname, 'read_only': True, 'months': {}}


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'))


def line_info(line):
    return {'id': line.id, 'move_id': line.move_id.id, 'move_name': line.move_id.name,
            'move_ref': line.move_id.ref, 'date': str(line.date), 'account_id': line.account_id.id,
            'account_type': line.account_id.account_type, 'balance': str(money(line.balance)),
            'residual': str(money(line.amount_residual))}


payments = local['account.payment'].search([('company_id', '=', 2), ('pos_session_id', '!=', False)]).filtered(
    lambda payment: payment.pos_payment_method_id.baseer_category_id.kind == 'platform')
invalid = []
for payment in payments:
    receipt, sale, account = payment.move_id, payment.pos_session_id.move_id, payment.pos_payment_method_id.outstanding_account_id
    if receipt.state != 'posted' or sale.state != 'posted':
        continue
    receipt_lines, sale_lines = receipt.line_ids, sale.line_ids
    reason = None
    clearing = receipt_lines.filtered(lambda line: line.account_id == account and line.account_id.account_type == 'asset_current')
    other = receipt_lines.filtered(lambda line: line.account_id != account and money(line.balance))
    gross = sum((money(line.balance) for line in clearing), Decimal(0))
    if not receipt_lines or not sale_lines or sum((money(line.balance) for line in receipt_lines), Decimal(0)) or sum((money(line.balance) for line in sale_lines), Decimal(0)):
        reason = 'missing_lines_or_unbalanced'
    elif not gross or not clearing or not other or any(line.account_id.account_type != 'asset_receivable' for line in other) or sum((money(line.balance) for line in other), Decimal(0)) != -gross:
        reason = 'zero_or_invalid_clearing_structure'
    if reason:
        invalid.append({'payment_id': payment.id, 'payment_amount': str(money(payment.amount)),
            'session_id': payment.pos_session_id.id, 'session_date': str(sale.date),
            'receipt_id': receipt.id, 'receipt_date': str(receipt.date), 'sale_id': sale.id,
            'method_id': payment.pos_payment_method_id.id, 'gross': str(gross), 'reason': reason,
            'receipt_lines': [line_info(line) for line in receipt_lines],
            'orders': [{'id': order.id, 'gross': str(money(order.amount_total)),
                'payments': [{'method_id': pos_payment.payment_method_id.id, 'amount': str(money(pos_payment.amount))}
                             for pos_payment in order.payment_ids]} for order in payment.pos_session_id.order_ids]})
result['invalid_origins'] = invalid

original_trace = CashReportCapture._trace
observed_calls = []


def observe_trace(self, line, amount, state, visited=frozenset(), depth=0):
    fragments = original_trace(self, line, amount, state, visited, depth)
    capture = _PLATFORM_CAPTURE.get()
    if capture and amount and line.id not in capture['trace_points'] and line.account_id.id in capture['platform_accounts']:
        unknown = [fragment for fragment in fragments if not fragment.get('baseer_platform_origin')]
        if unknown:
            observed_calls.append(dict(line_info(line), traced_amount=str(amount), depth=depth,
                visited=sorted(visited), fragments=fragments))
    return fragments


for month in ('2026-01', '2026-09'):
    year, number = map(int, month.split('-'))
    start, end = date(year, number, 1), date(year, number, monthrange(year, number)[1])
    model = local['account.move']
    origins = model._register_platform_origins(company, start, end)
    observed_calls.clear()
    options = {'company_ids': [company.id], 'posted_only': True, 'baseer_include_tax': True,
               'date': {'mode': 'range', 'date_from': str(start), 'date_to': str(end)}}
    capture = {'baseer_register_capture': True}
    token = _PLATFORM_CAPTURE.set(origins)
    try:
        with patch.object(CashReportCapture, '_trace', observe_trace):
            payload = local['eh.account.dynamic.report.handler.baseer_cash_categories']._compute_report(options, internal=capture)
    finally:
        _PLATFORM_CAPTURE.reset(token)
    final_fragments = capture['baseer_register_fragments']
    result['months'][month] = {'warnings': sorted(origins['warnings']),
        'trace_point_count': len(origins['trace_points']), 'recognized_row_count': len(origins['rows']),
        'warning_calls': list(observed_calls), 'warning_calls_count': len(observed_calls),
        'exact_native_totals': payload['meta']['exact_totals'],
        'final_fragments_count': len(final_fragments),
        'proven_platform_fragments': [fragment for fragment in final_fragments if fragment.get('baseer_platform_origin')],
        'final_unproven_fragments_touching_warning_moves': [fragment for fragment in final_fragments
            if not fragment.get('baseer_platform_origin') and fragment.get('source') in {call['id'] for call in observed_calls}]}

Path('/tmp/sim90/sales-coverage-diagnostic.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
env.cr.rollback()
print('SALES_COVERAGE_DIAGNOSTIC', json.dumps({'invalid_origins': len(invalid),
    'months': {month: {'warnings': value['warnings'], 'warning_calls': value['warning_calls_count']}
               for month, value in result['months'].items()}}, ensure_ascii=False), flush=True)
