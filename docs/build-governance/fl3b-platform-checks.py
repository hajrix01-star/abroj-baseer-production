"""Isolated FL3B native platform recognition/settlement contract checks."""
import hashlib
import json
import traceback
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.baseer_pos_summary.models.common import native_quote

assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
checks = []
result = {'status': 'FAIL', 'checks': checks, 'rollback': False, 'database': env.cr.dbname, 'timings_ms': []}
MODELS = ('res.users', 'res.partner', 'pos.config', 'pos.session', 'pos.order', 'pos.payment',
          'account.move', 'account.move.line', 'account.payment', 'account.partial.reconcile', 'baseer.pos.summary')
def counts():
    return {name: env[name].with_context(active_test=False).search_count([]) for name in MODELS}
def check(label, value):
    assert value, label
    checks.append(label)
def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))
def deny(label, action):
    try:
        with env.cr.savepoint():
            action()
    except (AccessError, UserError, ValidationError):
        checks.append(label)
        return
    raise AssertionError(label + ': unexpectedly allowed')
before = counts()
versions = {m.name: m.latest_version for m in env['ir.module.module'].search([('state', '=', 'installed')])}
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('FL3B fixtures cannot commit'))
guard.start()
try:
    config = env['pos.config'].search([('baseer_summary_only', '=', True)]).filtered(
        lambda c: c.company_id.currency_id.name == 'SAR' and {'cash', 'bank', 'platform'}.issubset(
            set(c.payment_method_ids.filtered('active').mapped('baseer_category_id.kind'))))[:1]
    company = config.company_id
    ctx = {'allowed_company_ids': company.ids, 'lang': 'en_US', 'tz': 'Asia/Riyadh',
           'tracking_disable': True, 'no_reset_password': True, 'generate_pdf': False}
    admin = env(context=ctx)
    actors = {}
    for role in ('accountant', 'cashier'):
        user = admin['res.users'].create({'name': 'FL3B rollback ' + role, 'login': 'fl3b-rollback-' + role,
            'baseer_access_role': role, 'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        actors[role] = env(user=user.id, su=False, context=ctx)
    actor = actors['accountant']
    product, tax = config.baseer_summary_product_id, config.baseer_summary_tax_id
    methods = [config.payment_method_ids.filtered(lambda m: m.active and m.baseer_category_id.kind == kind)[:1]
               for kind in ('cash', 'bank', 'platform')]
    clearing = methods[2].outstanding_account_id
    bank = methods[1].outstanding_account_id
    receivable = methods[0].receivable_account_id or company.account_default_pos_receivable_account_id
    expense = admin['account.account'].create({'name': 'FL3B ordinary settlement fee', 'code': '699987',
        'account_type': 'expense', 'company_ids': [Command.set(company.ids)]})

    def summary(day, values):
        source = actor['baseer.pos.summary'].create({'company_id': company.id, 'config_id': config.id,
            'business_date': day, 'day_schedule': 'all', 'period_scope': 'all', 'customer_count': 12,
            'allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': value})
                               for method, value in zip(methods, values)]})
        source.action_approve()
        return source

    def values(label, month, moves, expected):
        model = actor['account.move'].with_context(baseer_register_cash_month=month)
        started = perf_counter()
        payload = model.baseer_financial_register_cash_kpis([('id', 'in', moves.ids)])
        result['timings_ms'].append(round((perf_counter() - started) * 1000, 2))
        cards = payload['currency_groups'][0]['sections'][0]['cards']
        actual = [Decimal(card['display'].replace(',', '')) for card in cards]
        check(label + ' actual=' + repr(actual), actual == [money(v) for v in expected])
        for card in cards:
            selected = model.search([('id', 'in', moves.ids)] + card['domain'])
            actual_rows = sum((money(move['baseer_register_cash_' + card['key']]) for move in selected), Decimal(0))
            check(label + ' ' + card['key'] + ' row/card/drill', actual_rows == Decimal(card['display'].replace(',', '')))
        return payload

    def native(month):
        year, number = map(int, month.split('-'))
        import calendar
        options = {'company_ids': company.ids, 'posted_only': True, 'baseer_include_tax': True,
            'date': {'mode': 'range', 'date_from': date(year, number, 1).isoformat(),
                     'date_to': date(year, number, calendar.monthrange(year, number)[1]).isoformat()}}
        return actor['eh.account.dynamic.report.handler.baseer_cash_categories']._compute_report(options)

    def settlement(day, gross, fee=0, account=clearing):
        move = admin['account.move'].create({'move_type': 'entry', 'company_id': company.id,
            'journal_id': methods[1].journal_id.id, 'date': day,
            'line_ids': [Command.create({'name': 'FL3B native bank', 'account_id': bank.id,
                                        'balance': gross-fee}),
                         Command.create({'name': 'FL3B native clearing', 'account_id': account.id, 'balance': -gross})]
                + ([Command.create({'name': 'FL3B native fee', 'account_id': expense.id, 'balance': fee})] if fee else [])})
        move.action_post()
        return move

    native_before = native('2026-02')['meta']['exact_totals']
    source = summary(date(2026, 2, 1), (400, 490, 690))
    originals = source._native_moves()
    values('890 actual plus690 Applications equals1580', '2026-02', originals, (1580, 0, 1580))
    native_after = native('2026-02')['meta']['exact_totals']
    check('original cash report still adds only890',
          Decimal(native_after['receipts']) - Decimal(native_before['receipts']) == 890)
    origin_line = admin['account.move'].browse(originals.ids).line_ids.filtered(lambda l: l.account_id == clearing)
    first = settlement(date(2026, 2, 2), 200)
    (origin_line | first.line_ids.filtered(lambda l:l.account_id == clearing)).reconcile()
    values('same month200 collection not duplicated', '2026-02', originals | first, (1580, 0, 1580))
    second = settlement(date(2026, 3, 1), 300, 30)
    (origin_line | second.line_ids.filtered(lambda l:l.account_id == clearing)).reconcile()
    values('following month300 collection leaves native30 fee', '2026-03', second, (-30, 0, -30))
    third = settlement(date(2026, 3, 2), 190)
    (origin_line | third.line_ids.filtered(lambda l:l.account_id == clearing)).reconcile()
    values('following month final190 collection is zero', '2026-03', third, (0, 0, 0))
    unrelated = settlement(date(2026, 3, 3), 50, account=expense)
    values('unrelated receipt remains50', '2026-03', unrelated, (50, 0, 50))

    cancelled = summary(date(2026, 2, 6), (0, 0, 345))
    cancellation = actor['baseer.pos.summary.correction'].browse(cancelled.action_open_correction()['res_id'])
    cancellation.write({'operation': 'cancel', 'reason': 'FL3B native cancellation', 'acknowledge_bookkeeping': True})
    cancellation.action_correct()
    values('primary cancellation nets Applications to zero', '2026-02', cancelled._native_moves() | cancelled.reversal_move_ids, (0,0,0))

    # Actual native negative POS sale and subsequent platform cash refund.
    ordinary = admin['pos.config'].create({'name': 'FL3B native refund POS', 'company_id': company.id,
        'journal_id': config.journal_id.id, 'invoice_journal_id': config.invoice_journal_id.id,
        'payment_method_ids': [Command.set(methods[2].ids)], 'cash_control': False, 'use_presets': False})
    def ordinary_sale(gross):
        session = admin['pos.session'].create({'config_id': ordinary.id})
        session.set_opening_control(0, 'FL3B fixture')
        quote = native_quote(abs(money(gross)), tax, product, company)
        sign = -1 if gross < 0 else 1
        order = admin['pos.order'].create({'session_id': session.id, 'company_id': company.id,
            'amount_total': gross, 'amount_tax': sign*float(quote['tax']), 'amount_paid': 0, 'amount_return': 0, 'is_refund': sign < 0,
            'lines': [Command.create({'product_id': product.id, 'qty': sign, 'price_unit': float(quote['unit_price']),
                'price_subtotal': sign*float(quote['net']), 'price_subtotal_incl': gross,
                'tax_ids': [Command.set(tax.ids)], 'full_product_name': 'FL3B native sale'})]})
        admin['pos.payment'].create({'pos_order_id': order.id, 'payment_method_id': methods[2].id, 'amount': gross})
        order.lines._onchange_amount_line_all()
        order._compute_prices()
        order.action_pos_order_paid()
        session._compute_cash_balance()
        session.cash_register_balance_end_real = session.cash_register_balance_end
        session.action_pos_session_closing_control()
        return session

    positive = ordinary_sale(230)
    positive_moves = positive._get_related_account_moves()
    platform_payment = admin['account.payment'].search([('pos_session_id', '=', positive.id),
        ('pos_payment_method_id', '=', methods[2].id)])
    receipt_reverse = platform_payment.move_id._reverse_moves(default_values_list=[{'date': positive.move_id.date}], cancel=True)
    values('receipt-only reversal leaves230 sale recognized', positive.move_id.date.strftime('%Y-%m'),
           positive_moves | receipt_reverse, (230,0,230))

    session = ordinary_sale(-115)
    refund_moves = session._get_related_account_moves()
    refund_month = session.move_id.date.strftime('%Y-%m')
    values('native platform negative sale recognized', refund_month, refund_moves, (-115,0,-115))
    negative_line = refund_moves.line_ids.filtered(lambda l:l.account_id == clearing)
    refund = settlement(session.move_id.date, -115)
    (negative_line | refund.line_ids.filtered(lambda l:l.account_id == clearing)).reconcile()
    values('refund outgoing retained without duplicate negative', refund_month, refund_moves | refund, (0,-115,-115))
    values('refund settlement adjustment row offsets actual outgoing', refund_month, refund, (115,-115,0))

    delayed_session = ordinary_sale(-230)
    delayed_moves = delayed_session._get_related_account_moves()
    delayed_clear = delayed_moves.line_ids.filtered(lambda l:l.account_id == clearing)
    partial_refund = settlement(delayed_session.move_id.date, -100)
    (delayed_clear | partial_refund.line_ids.filtered(lambda l:l.account_id == clearing)).reconcile()
    values('partial refund has one negative recognition', refund_month, delayed_moves | partial_refund, (-130,-100,-230))
    delayed_refund = settlement(date(2026,10,1), -130)
    (delayed_clear | delayed_refund.line_ids.filtered(lambda l:l.account_id == clearing)).reconcile()
    values('next month remaining refund settlement nets zero', '2026-10', delayed_refund, (130,-130,0))

    primary_reverse = positive.move_id._reverse_moves(default_values_list=[{'date': date(2026,10,2)}], cancel=False)
    primary_reverse.action_post()
    values('primary reversal outside original month recognized once', '2026-10', primary_reverse, (-230,0,-230))

    unmatched = settlement(date(2026,3,5), 70)
    incomplete = values('unmatched Applications receipt retained', '2026-03', unmatched, (70,0,70))
    check('unproven platform cash allocation visibly warns', bool(incomplete.get('coverage_warning')))
    unmatched_outgoing = settlement(date(2026,3,6), -20)
    values('unproven outgoing gets no fabricated refund adjustment', '2026-03', unmatched_outgoing, (0,-20,-20))

    customer = admin['res.partner'].create({'name':'FL3B ordinary unpaid customer', 'company_id':company.id,
        'property_account_receivable_id':receivable.id})
    invoice = admin['account.move'].create({'move_type':'out_invoice', 'company_id':company.id,
        'partner_id':customer.id, 'journal_id':config.invoice_journal_id.id, 'invoice_date':date(2026,3,7),
        'date':date(2026,3,7), 'invoice_line_ids':[Command.create({'product_id':product.id,
            'quantity':1, 'price_unit':100, 'tax_ids':[Command.set(tax.ids)]})]})
    invoice.action_post()
    values('ordinary unpaid invoice is not Applications incoming', '2026-03', invoice, (0,0,0))
    other_company = admin['res.company'].search([('id','!=',company.id)],limit=1)
    deny('unauthorized company header is rejected', lambda:actor['account.move'].with_context(
        allowed_company_ids=other_company.ids).baseer_financial_register_cash_kpis([]))

    deny('cashier cannot read Incoming/outgoing', lambda: actors['cashier']['account.move'].baseer_financial_register_cash_kpis([]))
    deny('cashier cannot directly search operational money', lambda: actors['cashier']['account.move'].search([('baseer_register_cash_receipts','!=',0)]))
    deny('forged private domain rejected', lambda: actor['account.move'].baseer_financial_register_cash_kpis([('line_ids','any!',[('id','!=',False)])]))
    move_rule = admin['ir.rule'].create({'name': 'FL3B hide source', 'model_id': admin['ir.model']._get_id('account.move'),
        'domain_force': repr([('id','!=',source.move_id.id)]), 'perm_read': True})
    deny('hidden primary source keeps native controlled denial', lambda: values('hidden primary', '2026-02', originals, (890,0,890)))
    move_rule.unlink()
    aml_rule = admin['ir.rule'].create({'name': 'FL3B hide clearing', 'model_id': admin['ir.model']._get_id('account.move.line'),
        'domain_force': repr([('id','not in',origin_line.ids)]), 'perm_read': True})
    deny('hidden clearing keeps native controlled denial', lambda: values('hidden clearing', '2026-02', originals, (890,0,890)))
    aml_rule.unlink()
    env.flush_all()
    snapshot = counts()
    native_snapshot = native('2026-02')
    values('read-only repeat remains1580', '2026-02', originals, (1580,0,1580))
    env.flush_all()
    check('report performs no business writes', counts() == snapshot)
    native_repeat = native('2026-02')
    result['native_changed_keys'] = [key for key in native_repeat if native_repeat[key] != native_snapshot[key]]
    check('private decoration cannot change native exact totals',
          native_repeat['meta']['exact_totals'] == native_snapshot['meta']['exact_totals'])
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    guard.stop()
    result['rollback'] = before == counts()
    result['modules_preserved'] = versions == {m.name:m.latest_version for m in env['ir.module.module'].search([('state','=','installed')])}
    result['hard_commit_guard'] = True
    result['passed'] = len(checks)
    result['source_sha256'] = {name:hashlib.sha256(Path('/mnt/ic1-addons/baseer_financial_register/models/'+name).read_bytes()).hexdigest()
                               for name in ('cash_register.py','platform.py','projection.py')}
    Path('/mnt/qa-evidence/fl3b-platform-checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
assert result['status'] == 'PASS' and result['rollback'] and result['modules_preserved']

