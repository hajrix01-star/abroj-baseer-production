"""QA-only cash preview parity; native report is the independent numeric oracle."""
import calendar
import json
import traceback
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from odoo import Command, fields
from odoo.fields import Domain
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.cr.dbname.startswith('baseer_ar1_') and env.su
OUT = Path('/mnt/qa-evidence/fl2-cash-checks.json')
checks = []
result = {'status': 'FAIL', 'checks': checks, 'rollback': False, 'database': env.cr.dbname}
HANDLER = 'eh.account.dynamic.report.handler.baseer_cash_categories'

def check(name, condition):
    assert condition, name
    checks.append(name)

def deny(name, call, errors=(AccessError,)):
    try:
        with env.cr.savepoint():
            call()
    except errors:
        checks.append(name)
        return
    raise AssertionError(name + ': unexpectedly allowed')

def dec(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))

def counts():
    return {model: env[model].with_context(active_test=False).search_count([]) for model in (
        'res.users', 'res.partner', 'res.company', 'account.account', 'account.journal',
        'account.move', 'account.move.line', 'account.payment', 'account.partial.reconcile')}

before = counts()
modules = sorted(env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name'))
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('FL2 fixtures must never commit'))
guard.start()
try:
    company = env['res.company'].search([('currency_id.name', '=', 'SAR')]).filtered(
        lambda company: company.baseer_salary_expense_id and company.baseer_salary_payable_id)[:1]
    assert company
    today = fields.Date.context_today(env['account.move'])
    start, end = today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])
    month = start.strftime('%Y-%m')
    context = {'allowed_company_ids': company.ids, 'lang': 'en_US', 'tz': 'Asia/Riyadh',
               'tracking_disable': True, 'mail_create_nolog': True, 'no_reset_password': True}
    admin = env(context=context)
    actors = {}
    for role in ('owner', 'accountant', 'cashier'):
        user = admin['res.users'].create({'name': 'FL2 synthetic ' + role, 'login': 'fl2-synthetic-' + role,
            'company_id': company.id, 'company_ids': [Command.set(company.ids)], 'baseer_access_role': role})
        actors[role] = env(user=user.id, su=False, context=context)
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_loan_account_id | company.baseer_deduction_account_id
    def account(kind):
        return admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', kind),
            ('id', 'not in', private.ids)], limit=1)
    income, expense = account('income'), account('expense')
    payable, receivable = account('liability_payable'), account('asset_receivable')
    treasury = admin['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank'])]).filtered(
        lambda journal: journal.default_account_id.account_type == 'asset_cash')[:1]
    assert income and expense and payable and receivable and treasury
    cash = treasury.default_account_id
    cash2 = admin['account.account'].create({'name': 'FL2 second cash', 'code': 'FL2CASH',
        'account_type': 'asset_cash', 'company_ids': [Command.set(company.ids)]})
    clearing = admin['account.account'].create({'name': 'FL2 transfer clearing', 'code': 'FL2CLR',
        'account_type': 'asset_current', 'reconcile': True, 'company_ids': [Command.set(company.ids)]})
    journal = admin['account.journal'].create({'name': 'FL2 native test entries', 'code': 'FL2QA',
        'type': 'general', 'company_id': company.id})
    partner = admin['res.partner'].create({'name': 'FL2 synthetic partner', 'company_id': company.id,
        'property_account_payable_id': payable.id, 'property_account_receivable_id': receivable.id})
    def entry(label, legs, day=today, post=True):
        move = admin['account.move'].create({'move_type': 'entry', 'journal_id': journal.id,
            'company_id': company.id, 'date': day, 'ref': 'FL2 ' + label,
            'line_ids': [Command.create({'name': 'FL2 ' + label, 'account_id': account.id,
                'debit': float(max(Decimal('0'), Decimal(str(balance)))),
                'credit': float(max(Decimal('0'), -Decimal(str(balance))))}) for account, balance in legs]})
        if post:
            move.action_post()
        return move
    options = {'company_ids': company.ids, 'posted_only': True, 'baseer_include_tax': True,
               'date': {'mode': 'range', 'date_from': str(start), 'date_to': str(end)}}
    def reference(actor):
        handler = actor[HANDLER]
        normalized = handler.normalize_options(options)
        return handler._authorized_report_handler(normalized)._compute_report(normalized)['meta']['exact_totals']

    baseline = reference(actors['accountant'])
    check('clean fixture month has no initial cash movements', Decimal(baseline['receipts']) == 0 and Decimal(baseline['payments']) == 0)
    receipt = entry('receipt', [(cash, 8000), (income, -8000)])
    payment = entry('payment', [(expense, 5000), (cash, -5000)])
    oracle = reference(actors['accountant'])
    check('native reference sample receipts8000 payments5000 net3000',
          oracle['receipts'] == '8000.00' and oracle['payments'] == '-5000.00' and oracle['actual_net_movement'] == '3000.00')
    reader = actors['accountant']['account.move'].with_context(baseer_register_cash_month=month)
    owner = actors['owner']['account.move'].with_context(baseer_register_cash_month=month)
    cashier = actors['cashier']['account.move'].with_context(baseer_register_cash_month=month)
    action = reader.action_open_register_cash(month)
    cash_domain = Domain(action['domain'])
    cash_fields = ['baseer_register_cash_receipts', 'baseer_register_cash_payments', 'baseer_register_cash_net']
    def values(payload):
        return {card['key']: Decimal(card['display'].replace(',', ''))
                for card in payload['currency_groups'][0]['sections'][0]['cards']}
    timings = []
    def parity(label, actor=reader):
        start_time = perf_counter()
        payload = actor.baseer_financial_register_cash_kpis(list(cash_domain))
        timings.append(round((perf_counter()-start_time)*1000, 3))
        actual = values(payload)
        native = reference(actor.env)
        expected = {key: Decimal(native[refkey]) for key, refkey in
                    [('receipts', 'receipts'), ('payments', 'payments'), ('net', 'actual_net_movement')]}
        check(label + ' cards equal reference exact totals', actual == expected)
        records = actor.search(cash_domain)
        rows = records.read(cash_fields)
        row_sums = {key: sum((dec(row[field]) for row in rows), Decimal('0'))
                    for key, field in zip(('receipts', 'payments', 'net'), cash_fields)}
        check(label + ' native row allocations equal cards', row_sums == actual)
        check(label + ' each row reconciles its signed amounts', all(dec(row[cash_fields[0]])+dec(row[cash_fields[1]]) == dec(row[cash_fields[2]]) for row in rows))
        return payload, records
    payload, visible = parity('8000/5000 sample')
    check('sample native cash rows are original posted entries', set(visible.ids) == {receipt.id, payment.id})
    check('single same-area response contains exactly three cards', len(payload['currency_groups']) == 1 and len(payload['currency_groups'][0]['sections']) == 1 and len(payload['currency_groups'][0]['sections'][0]['cards']) == 3)
    check('action fixes one authorized company and requested month', action['context']['allowed_company_ids'] == company.ids and action['context']['baseer_register_cash_month'] == month)
    for card in payload['currency_groups'][0]['sections'][0]['cards']:
        selected = reader.search(cash_domain & Domain(card['domain']))
        expected_ids = {'receipts': receipt.ids, 'payments': payment.ids, 'net': (receipt|payment).ids}[card['key']]
        check('card drill ' + card['key'], set(selected.ids) == set(expected_ids))
    narrowed = values(reader.baseer_financial_register_cash_kpis(list(cash_domain & Domain('ref', '=', receipt.ref))))
    check('native reference facet narrows rows and cards together', narrowed == {'receipts': Decimal('8000'), 'payments': Decimal('0'), 'net': Decimal('8000')})

    draft = entry('draft excluded', [(cash, 123), (income, -123)], post=False)
    cancelled = entry('cancelled excluded', [(cash, 234), (income, -234)])
    cancelled.button_draft()
    cancelled.button_cancel()
    parity('draft and cancellation excluded')
    check('cancelled and draft absent from visible cash rows', not reader.search(cash_domain & Domain('id', 'in', (draft|cancelled).ids)))
    pure_transfer = entry('same-entry internal transfer', [(cash, -700), (cash2, 700)])
    left = entry('transfer out', [(cash, -300), (clearing, 300)])
    right = entry('transfer in', [(cash2, 300), (clearing, -300)])
    (left.line_ids | right.line_ids).filtered(lambda line: line.account_id == clearing).reconcile()
    parity('evidenced internal transfers')
    check('reference-excluded transfers are absent from cash rows', not reader.search(cash_domain & Domain('id', 'in', (pure_transfer|left|right).ids)))

    sale_journal = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'sale')], limit=1)
    invoice = admin['account.move'].create({'move_type': 'out_invoice', 'company_id': company.id,
        'journal_id': sale_journal.id, 'partner_id': partner.id, 'date': today, 'invoice_date': today,
        'invoice_line_ids': [Command.create({'name': 'FL2 unpaid then partial', 'quantity': 1,
            'price_unit': 1000, 'account_id': income.id, 'tax_ids': [Command.clear()]})]})
    invoice.action_post()
    parity('unpaid invoice excluded')
    check('unpaid invoice not a cash register row', invoice.id not in reader.search(cash_domain).ids)
    method = treasury.inbound_payment_method_line_ids.filtered(lambda method: method.code == 'manual')[:1]
    method.payment_account_id = cash
    wizard = admin['account.payment.register'].with_context(active_model='account.move', active_ids=invoice.ids).create({
        'journal_id': treasury.id, 'payment_method_line_id': method.id, 'amount': 200, 'payment_date': today,
        'installments_mode': 'full', 'payment_difference_handling': 'open'})
    partial_payment = wizard._create_payments()
    check('native partial fixture remains partly due', invoice.payment_state == 'partial' and dec(invoice.amount_residual) == Decimal('800'))
    partial_payload, partial_rows = parity('partial invoice payment')
    check('partial payment uses cash move not full invoice value', partial_payment.move_id.id in partial_rows.ids and invoice.id not in partial_rows.ids and values(partial_payload)['receipts'] == Decimal('8200'))

    extra_out = entry('reversal original', [(expense, 250), (cash, -250)])
    reversal = extra_out._reverse_moves(default_values_list=[{'date': today}], cancel=True)
    parity('native posted reversal policy')
    check('posted reversal cash effect is retained per reference', reversal.state == 'posted' and dec(reversal.line_ids.filtered(lambda line: line.account_id == cash).balance) == Decimal('250'))
    mixed = entry('mixed zero net', [(cash, 600), (cash2, -600), (income, -200), (expense, 200)])
    parity('mixed zero-net external movement')
    mixed_row = reader.browse(mixed.id).read(cash_fields)[0]
    check('mixed zero-net row retains both allocated directions', dec(mixed_row[cash_fields[0]]) == Decimal('200') and dec(mixed_row[cash_fields[1]]) == Decimal('-200') and dec(mixed_row[cash_fields[2]]) == 0)

    public_before = values(reader.baseer_financial_register_cash_kpis(list(cash_domain)))
    salary = entry('private salary', [(company.baseer_salary_expense_id, 400), (cash, -400)])
    parity('accountant salary privacy')
    check('hidden salary leaves public cards unchanged', public_before == values(reader.baseer_financial_register_cash_kpis(list(cash_domain))))
    check('hidden salary absent from native cash row search', not reader.search(cash_domain & Domain('id', '=', salary.id)))
    deny('hidden salary row read denied', lambda: reader.browse(salary.id).read(cash_fields))
    parity('owner full permitted cash scope', owner)
    check('owner sees legitimate additional salary cash', values(owner.baseer_financial_register_cash_kpis(list(cash_domain)))['payments'] == public_before['payments'] - Decimal('400'))
    for label, call in [('KPI', lambda: cashier.baseer_financial_register_cash_kpis([])),
                        ('action', lambda: cashier.action_open_register_cash(month)),
                        ('row computed fields', lambda: cashier.browse(receipt.id).read(cash_fields))]:
        deny('cashier cash ' + label + ' denied', call)
    # Native domain optimization may retain the initial collection-validation
    # UserError after the scalar fallback raises the role AccessError.
    deny('cashier visibility search returns no rows', lambda: cashier.search([('baseer_register_cash_visible', '=', True)]), errors=(AccessError, UserError))
    for malformed in ('2026-13', '2026-00', '0000-01', '2026-9', '../2026-01', ['2026-01'], 202601):
        deny('malformed month rejected ' + str(malformed), lambda malformed=malformed: reader.action_open_register_cash(malformed), errors=(UserError, ValidationError))
    deny('forged allowed company denied', lambda: reader.with_context(allowed_company_ids=[999999]).baseer_financial_register_cash_kpis([]))
    deny('forged private ORM operator denied', lambda: reader.baseer_financial_register_cash_kpis([('line_ids', 'any!', [('id', '>', 0)])]))
    forged = reader.with_context(baseer_register_rows={receipt.id: {'receipts': 999999}},
        baseer_register_capture=True, baseer_include_tax=False).baseer_financial_register_cash_kpis(list(cash_domain))
    check('client context cannot supply cash amounts or tax policy', values(forged) == public_before)
    empty = values(reader.baseer_financial_register_cash_kpis(list(cash_domain & Domain('id', '=', -1))))
    check('empty native facet gives honest zero cards', all(value == 0 for value in empty.values()))
    previous_month = (start-timedelta(days=1)).strftime('%Y-%m')
    previous = values(reader.with_context(baseer_register_cash_month=previous_month).baseer_financial_register_cash_kpis([]))
    check('month context recomputes independent empty scope', all(value == 0 for value in previous.values()))
    result['timings_ms'] = timings
    result['capacity_note'] = 'Small native accounting fixture, one reader; not a large-ledger capacity claim'
    result['reference_sample'] = {key: oracle[key] for key in ('receipts', 'payments', 'actual_net_movement')}
    result['status'] = 'PASS'
except Exception as error:
    result.update(error=str(error), error_type=type(error).__name__, traceback=traceback.format_exc())
finally:
    env.cr.rollback()
    guard.stop()
    env.invalidate_all()
    after = counts()
    result['rollback'] = after == before
    result['rollback_counts'] = {'before': before, 'after': after}
    result['modules_preserved'] = modules == sorted(env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name'))
    result['commit_guard'] = True
    result['passed'] = len(checks)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf8')
    print('FL2_CASH_CHECKS', result['status'], len(checks), 'ROLLBACK', result['rollback'])
assert result['status'] == 'PASS' and result['rollback'] and result['modules_preserved'], result.get('error', 'FL2 checks failed')
