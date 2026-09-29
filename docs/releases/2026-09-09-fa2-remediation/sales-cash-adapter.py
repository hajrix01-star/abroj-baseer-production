assert env.cr.dbname=="baseer_audit_sales_20260909"
"""Real-ledger cash adapter probes for an approved synthetic 500/700/600 summary.

Call run_pos_cash_checks(env, summary) from an Odoo QA shell. All settlement
and transfer ledger mutations roll back to a savepoint, including on failure.
This helper never commits; vendor durable failure audit may remain in QA.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from odoo import Command
from odoo.exceptions import AccessError, UserError


CENT = Decimal('0.01')


def decimal(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


class _RollbackCashProbe(Exception):
    pass


def run_pos_cash_checks(env, summary):
    assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA database required'
    summary.ensure_one()
    assert summary.state == 'approved'
    company = summary.company_id
    scoped = env(context=dict(env.context, allowed_company_ids=company.ids, lang='en_US'))
    summary = scoped['baseer.pos.summary'].browse(summary.id)
    handler = scoped['eh.account.dynamic.report.handler.baseer_cash_categories']
    report = scoped['eh.account.dynamic.report'].search([('code', '=', 'baseer_cash_categories')], limit=1)
    checks = []

    def check(condition, label, **evidence):
        assert condition, (label, evidence)
        checks.append(dict(check=label, passed=True, **evidence))

    def amount(actual, expected, label):
        check(decimal(actual) == decimal(expected), label, actual=str(decimal(actual)), expected=str(decimal(expected)))

    def options(day, include_tax=True):
        return {'company_ids': company.ids, 'posted_only': True,
                'baseer_include_tax': include_tax, 'baseer_months': [day.strftime('%Y-%m')]}

    def read(day, include_tax=True):
        result = report.render(options(day, include_tax), use_cache=False)
        amount(result['totals']['balance_check'], 0, 'cash report reconciles to original ledger')
        return result

    def trace_state(day):
        return {'company_id': company.id, 'date_to': day, 'cash_ids': set(initial_cash.ids),
                'opening_cash_ids': set(), 'visits': 0, 'diagnostics': set(), 'budget': {'used': 0}}

    def action_records(action):
        check(action.get('res_model') in ('account.move', 'account.move.line'), 'drill uses native accounting model')
        model = scoped[action['res_model']]
        records = model.browse(action['res_id']).exists() if action.get('res_id') else model.search(action['domain'])
        check(all(r.company_id == company for r in records), 'source action stays in company')
        return records

    order, session = summary.order_id, summary.session_id
    check(session.order_ids == order and order.baseer_summary_id == summary, 'one native summary order in dedicated session')
    amount(order.amount_total, 1800, 'native summary gross fixture')
    amount(sum(order.payment_ids.mapped('amount')), 1800, 'native payment totals')
    methods = order.payment_ids.payment_method_id
    cash_method = methods.filtered(lambda m: m.baseer_category_id.kind == 'cash')
    bank_method = methods.filtered(lambda m: m.baseer_category_id.kind == 'bank')
    platform = methods.filtered(lambda m: m.baseer_category_id.kind == 'platform')
    check(len(cash_method) == len(bank_method) == len(platform) == 1, 'three distinct native fixture methods')
    amount(sum(order.payment_ids.filtered(lambda p: p.payment_method_id == cash_method).mapped('amount')), 500, 'native cash allocation')
    amount(sum(order.payment_ids.filtered(lambda p: p.payment_method_id == bank_method).mapped('amount')), 700, 'native bank allocation')
    amount(sum(order.payment_ids.filtered(lambda p: p.payment_method_id == platform).mapped('amount')), 600, 'native platform allocation')
    check(platform.outstanding_account_id.account_type == 'asset_current', 'platform clearing is not cash')
    related_moves = session._get_related_account_moves()
    initial_cash = related_moves.line_ids.filtered(lambda row: row.account_id.account_type == 'asset_cash')
    amount(sum(initial_cash.mapped('balance')), 1200, 'platform 600 adds zero initial cash')
    check(all(row.parent_state == 'posted' and row.date == summary.business_date for row in initial_cash), 'initial cash date and posting are native business date')
    direct = []
    state = trace_state(summary.business_date)
    for move in initial_cash.move_id:
        for line in move.line_ids.filtered(lambda row: row.account_id.account_type != 'asset_cash' and row.balance):
            direct.extend(handler._trace(line, -decimal(line.balance), state))
    owned = [fragment for fragment in direct if fragment.get('baseer_pos_order_id') == order.id]
    amount(sum((fragment['gross'] for fragment in owned), Decimal(0)), 1200, 'matched multi-method POS sale is attributed once, not per full session')
    amount(sum((fragment['net'] for fragment in owned), Decimal(0)),
           sum((decimal(Decimal(value) * decimal(order.lines.price_subtotal) / decimal(order.amount_total)) for value in (500, 700)), Decimal(0)),
           'cash and bank exclude only their evidenced proportional tax')
    check(all(fragment['sale_collection'] and not fragment['unknown'] for fragment in owned), 'POS cash contributes to evidenced collected-sales denominator')
    check(all(scoped['account.move.line'].browse(fragment['source']).move_id == session.move_id for fragment in owned), 'source IDs are original session AMLs')
    initial_gross, initial_net = read(summary.business_date), read(summary.business_date, False)
    session_receivables = session.move_id.line_ids.filtered(lambda row: row.account_id.account_type == 'asset_receivable')
    check(bool(session_receivables), 'posted session receivable evidence exists')
    fallback = handler._baseer_pos_fragment(session_receivables[0], Decimal('25.00'),
                 {'error': 'QA injected missing POS evidence'}, trace_state(summary.business_date))
    check(fallback[0]['unknown'] and 'sale_collection' not in fallback[0], 'explicit unproven-evidence fallback does not claim sales')
    amount(fallback[0]['gross'], fallback[0]['net'], 'unknown VAT remains full cash')
    try:
        bad_state = trace_state(summary.business_date)
        bad_state['budget']['used'] = handler._BASEER_AGGREGATE_LIMIT
        handler._baseer_pos_evidence(session_receivables[0], bad_state)
    except UserError:
        check(True, 'POS evidence respects existing aggregate budget')
    else:
        raise AssertionError('POS evidence bypassed aggregate budget')
    try:
        handler.with_user(scoped.ref('base.public_user')).get_drilldown_action(options(summary.business_date), 'receipts')
    except AccessError:
        check(True, 'public user cannot read summary cash sources')
    else:
        raise AssertionError('Public user read cash report')
    original_clearing = session.bank_payment_ids.move_id.line_ids.filtered(
        lambda row: row.account_id == platform.outstanding_account_id and row.balance > 0)
    amount(sum(original_clearing.mapped('balance')), 600, 'original platform clearing balance')
    check(bool(original_clearing) and not original_clearing.reconciled, 'platform starts unsettled')
    first_date = summary.business_date.replace(day=1) + timedelta(days=40)
    first_date = first_date.replace(day=10)
    second_date = first_date.replace(day=1) + timedelta(days=40)
    second_date = second_date.replace(day=10)
    before_first = {tax: read(first_date, tax) for tax in (True, False)}
    before_second = {tax: read(second_date, tax) for tax in (True, False)}
    refs = 'QA POS CASH ADAPTER %s' % summary.id
    count_before = scoped['account.move'].search_count([('ref', '=like', refs + '%')])

    def settle(day, value):
        move = scoped['account.move'].create({
            'company_id': company.id, 'journal_id': bank_method.journal_id.id,
            'date': day, 'ref': refs + ' SETTLE ' + day.isoformat(),
            'line_ids': [
                Command.create({'name': 'QA platform actual bank receipt', 'account_id': bank_method.journal_id.default_account_id.id,
                                'debit': float(value), 'credit': 0}),
                Command.create({'name': 'QA original platform clearing settlement', 'account_id': platform.outstanding_account_id.id,
                                'debit': 0, 'credit': float(value)}),
            ],
        })
        move.action_post()
        check(move.date == day and move.state == 'posted', 'native bank settlement posts on requested date')
        clearing = move.line_ids.filtered(lambda row: row.account_id == platform.outstanding_account_id)
        (original_clearing | clearing).reconcile()
        return move

    try:
        with env.cr.savepoint():
            first = settle(first_date, Decimal('300.00'))
            for tax in (True, False):
                after = read(first_date, tax)
                expected = Decimal('300.00') if tax else decimal(Decimal('300.00') * decimal(order.lines.price_subtotal) / decimal(order.amount_total))
                amount(decimal(after['totals']['receipts']) - decimal(before_first[tax]['totals']['receipts']), expected,
                       'partial platform settlement contributes actual period receipts on selected tax basis')
                amount(decimal(after['totals']['sales_collections']) - decimal(before_first[tax]['totals']['sales_collections']), expected,
                       'partial settlement enters collected sales only once')
                amount(decimal(after['totals']['actual_net_movement']) - decimal(before_first[tax]['totals']['actual_net_movement']), 300,
                       'actual bank movement remains 300 in both tax modes')
                records = action_records(report.get_drilldown_for_line(options(first_date, tax), 'receipts'))
                cash_aml = first.line_ids.filtered(lambda row: row.account_id.account_type == 'asset_cash')
                check(records._name == 'account.move.line' and set(cash_aml.ids).issubset(records.ids), 'receipt drill includes actual dated bank AML')
            vat_records = action_records(report.get_drilldown_for_line(options(first_date, False), 'baseer-total-excluded_tax_bridge'))
            check(vat_records._name == 'account.move' and session.move_id in vat_records, 'POS VAT bridge opens original posted session accounting')
            amount(read(summary.business_date)['totals']['receipts'], initial_gross['totals']['receipts'], 'later settlement does not alter original-period cash')
            amount(read(summary.business_date, False)['totals']['receipts'], initial_net['totals']['receipts'], 'later settlement does not alter original-period net cash')
            settle(second_date, Decimal('300.00'))
            check(original_clearing.reconciled, 'two partial receipts fully reconcile original platform clearing')
            for tax in (True, False):
                after = read(second_date, tax)
                expected = Decimal('300.00') if tax else decimal(Decimal('300.00') * decimal(order.lines.price_subtotal) / decimal(order.amount_total))
                amount(decimal(after['totals']['receipts']) - decimal(before_second[tax]['totals']['receipts']), expected,
                       'remaining platform settlement appears only in its own month')
            before_transfer = read(second_date)
            transfer = scoped['account.move'].create({
                'company_id': company.id, 'journal_id': bank_method.journal_id.id, 'date': second_date,
                'ref': refs + ' TRANSFER',
                'line_ids': [
                    Command.create({'name': 'QA treasury transfer', 'account_id': cash_method.journal_id.default_account_id.id, 'debit': 25.0, 'credit': 0}),
                    Command.create({'name': 'QA treasury transfer', 'account_id': bank_method.journal_id.default_account_id.id, 'debit': 0, 'credit': 25.0}),
                ],
            })
            transfer.action_post()
            after_transfer = read(second_date)
            for key in ('receipts', 'payments', 'sales_collections', 'actual_net_movement'):
                amount(after_transfer['totals'][key], before_transfer['totals'][key], 'internal transfer does not create ' + key)
            raise _RollbackCashProbe()
    except _RollbackCashProbe:
        pass
    # Follow the existing cash engine's per-receipt cent policy explicitly.
    # Three independent receipts must not silently claim full-source net
    # equality: 173.91 x 3 = 521.73 versus a single 600 allocation of 521.74.
    try:
        with env.cr.savepoint():
            rounding_before = read(first_date, False)
            for offset in range(3):
                settle(first_date + timedelta(days=offset), Decimal('200.00'))
            rounding_after = read(first_date, False)
            rounded_net = decimal(rounding_after['totals']['receipts']) - decimal(rounding_before['totals']['receipts'])
            receipt_net = decimal(Decimal('200.00') * decimal(order.lines.price_subtotal) / decimal(order.amount_total))
            source_net = decimal(Decimal('600.00') * decimal(order.lines.price_subtotal) / decimal(order.amount_total))
            amount(rounded_net, receipt_net * 3, 'three separate 200 receipts apply the disclosed per-receipt cent policy')
            amount(rounded_net - source_net, '-0.01', 'per-receipt result explicitly differs one cent from full-source proportional net')
            check(any('rounded for each actual receipt' in row['name'] for row in rounding_after['lines']),
                  'report discloses per-receipt tax rounding rather than claiming full-source equality')
            raise _RollbackCashProbe()
    except _RollbackCashProbe:
        pass
    # A real ordinary native POS session remains readable as cash by an
    # accountant without POS rights, without disclosing POS/order metadata.
    try:
        with env.cr.savepoint():
            from odoo.addons.baseer_pos_summary.models.common import native_quote
            ordinary_journal = scoped['account.journal'].create({
                'name': 'QA ordinary POS cash adapter', 'code': 'QOC', 'type': 'cash', 'company_id': company.id,
            })
            ordinary_method = scoped['pos.payment.method'].create({
                'name': 'QA ordinary cash', 'company_id': company.id, 'journal_id': ordinary_journal.id,
                'receivable_account_id': cash_method.receivable_account_id.id,
            })
            ordinary_config = scoped['pos.config'].create({
                'name': 'QA ordinary POS cash adapter', 'company_id': company.id,
                'journal_id': session.config_id.journal_id.id,
                'invoice_journal_id': session.config_id.invoice_journal_id.id,
                'payment_method_ids': [Command.set(ordinary_method.ids)], 'cash_control': True,
                'use_presets': False,
            })
            ordinary = scoped['pos.session'].create({'config_id': ordinary_config.id})
            ordinary.set_opening_control(0, 'QA ordinary POS opening')
            product = session.config_id.baseer_summary_product_id
            tax = session.config_id.baseer_summary_tax_id
            quote = native_quote(Decimal('115.00'), tax, product, company)
            ordinary_order = scoped['pos.order'].create({
                'session_id': ordinary.id, 'company_id': company.id,
                'amount_total': 115.0, 'amount_tax': float(quote['tax']), 'amount_paid': 0.0, 'amount_return': 0.0,
                'lines': [Command.create({'product_id': product.id, 'qty': 1.0,
                    'price_unit': float(quote['unit_price']), 'price_subtotal': float(quote['net']),
                    'price_subtotal_incl': 115.0, 'tax_ids': [Command.set(tax.ids)],
                    'full_product_name': 'QA ordinary POS sale'})],
            })
            scoped['pos.payment'].create({'pos_order_id': ordinary_order.id, 'payment_method_id': ordinary_method.id, 'amount': 115.0})
            ordinary_order.lines._onchange_amount_line_all()
            ordinary_order._compute_prices()
            ordinary_order.action_pos_order_paid()
            ordinary._compute_cash_balance()
            ordinary.cash_register_balance_end_real = ordinary.cash_register_balance_end
            ordinary._compute_cash_balance()
            ordinary.action_pos_session_closing_control()
            check(ordinary.state == 'closed' and ordinary_order.state == 'done' and not ordinary.baseer_summary_id,
                  'ordinary native POS remains capable of posting a sale')
            accountant = scoped['res.users'].create({
                'name': 'QA cash accountant without POS', 'login': 'qa-cash-no-pos-%s' % summary.id,
                'company_id': company.id, 'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set(scoped.ref('eh_account_base.group_eh_user').ids)],
            })
            check(not accountant.has_group('point_of_sale.group_pos_user'), 'accounting-only test identity has no POS role')
            accounting_handler = handler.with_user(accountant)
            ordinary_cash = ordinary._get_related_account_moves().line_ids.filtered(lambda row: row.account_id.account_type == 'asset_cash')
            ordinary_fragments = []
            accounting_state = trace_state(ordinary.move_id.date)
            accounting_state['cash_ids'].update(ordinary_cash.ids)
            for counterpart in ordinary_cash.move_id.line_ids.filtered(lambda row: row.account_id.account_type != 'asset_cash' and row.balance):
                ordinary_fragments.extend(accounting_handler._trace(counterpart.with_user(accountant), -decimal(counterpart.balance), accounting_state))
            amount(sum((item['gross'] for item in ordinary_fragments), Decimal(0)), 115,
                   'accounting-only ordinary POS cash does not fail or double count')
            check(all(item['unknown'] and not item.get('sale_collection') for item in ordinary_fragments),
                  'unreadable ordinary POS detail remains unclassified without tax inference')
            amount(sum((item['net'] for item in ordinary_fragments), Decimal(0)), 115,
                   'accounting-only ordinary POS preserves complete cash amount')
            safe_report = report.with_user(accountant).render(options(ordinary.move_id.date, False), use_cache=False)
            amount(safe_report['totals']['balance_check'], 0, 'accounting-only full cash report still reconciles')
            raise _RollbackCashProbe()
    except _RollbackCashProbe:
        pass
    amount(scoped['account.move'].search_count([('ref', '=like', refs + '%')]), count_before, 'synthetic settlement and transfer records rolled back')
    return {'status': 'PASS', 'summary_id': summary.id, 'company_id': company.id,
            'checks': checks, 'count': len(checks),
            'initial_gross_totals': initial_gross['totals'], 'initial_net_totals': initial_net['totals'],
            'mutations': 'Synthetic settlement and transfer ledger changes rolled back; durable vendor failure audit may remain in QA.'}

from pathlib import Path
import json,traceback
try:
    e=env(user=env.ref("base.user_admin").id,context={"allowed_company_ids":[6],"lang":"en_US"})
    # Actual upgrade supplies the separate service; no product-type fixture.
    summary=e["baseer.pos.summary"].create({"business_date":"2026-04-01","config_id":1,"customer_count":60,"allocation_ids":[Command.create({"payment_method_id":mid,"amount":amount}) for mid,amount in [(1,500),(2,700),(3,600)]]})
    summary.action_approve()
    result=run_pos_cash_checks(e,summary)
except Exception as exc: result={"status":"failed","error":str(exc),"traceback":traceback.format_exc()}
finally:env.cr.rollback()
Path("/mnt/qa-evidence/sales-cash-adapter-result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,default=str))
