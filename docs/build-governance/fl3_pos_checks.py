"""FL3 native POS accounting projection; isolated, hard commit guard, full rollback."""
import hashlib
import json
import traceback
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.baseer_pos_summary.models.common import native_quote

assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
out = Path('/mnt/qa-evidence/fl3-pos-checks.json')
checks = []
result = {'status': 'FAIL', 'checks': checks, 'rollback': False, 'database': env.cr.dbname, 'timings_ms': []}
MODELS = ('res.users', 'res.partner', 'pos.config', 'pos.session', 'pos.order', 'pos.payment',
          'account.move', 'account.move.line', 'account.payment', 'account.partial.reconcile', 'baseer.pos.summary')

def counts():
    return {name: env[name].with_context(active_test=False).search_count([]) for name in MODELS}

def check(label, value):
    assert value, label
    checks.append(label)

def deny(label, action):
    try:
        with env.cr.savepoint():
            action()
    except (AccessError, UserError, ValidationError):
        checks.append(label)
        return
    raise AssertionError(label + ': unexpectedly allowed')

def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))

before = counts()
versions = {m.name: m.latest_version for m in env['ir.module.module'].search([('state', '=', 'installed')])}
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('FL3 fixtures cannot commit'))
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
        user = admin['res.users'].create({'name': 'FL3 rollback ' + role, 'login': 'fl3-rollback-' + role,
            'baseer_access_role': role, 'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        actors[role] = env(user=user.id, su=False, context=ctx)
    actor = actors['accountant']
    today = fields.Date.context_today(admin['account.move'])
    product, tax = config.baseer_summary_product_id, config.baseer_summary_tax_id
    methods = [config.payment_method_ids.filtered(lambda m: m.active and m.baseer_category_id.kind == kind)[:1]
               for kind in ('cash', 'bank', 'platform')]
    receivable = methods[0].receivable_account_id or company.account_default_pos_receivable_account_id
    partner = admin['res.partner'].create({'name': 'FL3 synthetic customer', 'company_id': company.id,
                                         'property_account_receivable_id': receivable.id})

    def kpis(moves, extra=None):
        domain = [('id', 'in', moves.ids)] + (extra or [])
        start = perf_counter()
        payload = actor['account.move'].baseer_financial_register_kpis(domain)
        result['timings_ms'].append(round((perf_counter() - start) * 1000, 2))
        section = next(g for g in payload['currency_groups'] if g['currency_id'] == company.currency_id.id)['sections'][0]
        values = {c['key']: Decimal(c['display'].replace(',', '')) for c in section['cards']}
        return values, section, payload

    def parity(label, moves, expected):
        values, section, payload = kpis(moves)
        check(label + ' native sales total', values['total'] == money(expected))
        for card in section['cards']:
            domain = [('id', 'in', moves.ids)] + card['domain']
            selected = actor['account.move'].search(domain)
            if card['key'] == 'partial':
                actual = Decimal(len(selected))
            elif card['key'] == 'overdue':
                from odoo.tools import SQL
                actual = actor.execute_query(SQL('SELECT COALESCE(SUM(overdue),0) FROM (%s) p',
                    actor['account.move']._register_projection_sql(domain)))[0][0]
            else:
                field = {'total': 'baseer_register_amount', 'settled': 'baseer_register_settled',
                         'outstanding': 'baseer_register_outstanding'}[card['key']]
                actual = sum((money(m[field]) for m in selected), Decimal('0'))
            check(label + ' ' + card['key'] + ' row/drill parity', actual == values[card['key']])
        return values

    date_cursor = [today - timedelta(days=46)]
    def summary():
        while admin['baseer.pos.summary'].search_count([('company_id', '=', company.id), ('business_date', '=', date_cursor[0])]):
            date_cursor[0] += timedelta(days=1)
        day = date_cursor[0]
        date_cursor[0] += timedelta(days=1)
        source = actor['baseer.pos.summary'].create({'company_id': company.id, 'config_id': config.id,
            'business_date': day, 'day_schedule': 'all', 'period_scope': 'all', 'customer_count': 12,
            'allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': amount})
                               for method, amount in zip(methods, (115, 230, 345))]})
        source.action_approve()
        return source

    source = summary()
    source_moves = source._native_moves()
    values = parity('summary mixed cash bank platform', source_moves, 690)
    check('platform claim settled is not bank remittance', values['settled'] == 690 and values['outstanding'] == 0
          and money(sum(source_moves.line_ids.filtered(lambda l: l.account_id == methods[2].outstanding_account_id).mapped('balance'))) == 345)
    source_rows = actor['account.move'].search([('id', 'in', source_moves.ids), ('baseer_register_contributor', '=', True)])
    check('only native primary summary move contributes sales', source_rows.ids == source.move_id.ids)
    correction = actor['baseer.pos.summary.correction'].browse(source.action_open_correction()['res_id'])
    correction.write({'operation': 'edit', 'reason': 'FL3 summary projection fixture', 'acknowledge_bookkeeping': True,
        'line_ids': [Command.update(l.id, {'amount_input': str(v)}) for l,v in zip(correction.line_ids, (230,345,460))]})
    correction.action_correct()
    replacement = source.replacement_id
    family_moves = source_moves | source.reversal_move_ids | replacement._native_moves()
    parity('summary original reversal replacement', family_moves, 1035)
    cancel = actor['baseer.pos.summary.correction'].browse(replacement.action_open_correction()['res_id'])
    cancel.write({'operation': 'cancel', 'reason': 'FL3 cancel projection fixture', 'acknowledge_bookkeeping': True})
    cancel.action_correct()
    parity('summary cancellation ledger nets zero', family_moves | replacement.reversal_move_ids, 0)

    cash_journal = admin['account.journal'].create({'name': 'FL3 ordinary POS cash', 'code': 'F3C', 'type': 'cash', 'company_id': company.id})
    cash_method = admin['pos.payment.method'].create({'name': 'FL3 ordinary cash', 'company_id': company.id,
        'journal_id': cash_journal.id, 'receivable_account_id': receivable.id})
    later_method = admin['pos.payment.method'].create({'name': 'FL3 customer account', 'company_id': company.id,
        'journal_id': False, 'split_transactions': True})
    ordinary = admin['pos.config'].create({'name': 'FL3 native POS', 'company_id': company.id,
        'journal_id': config.journal_id.id, 'invoice_journal_id': config.invoice_journal_id.id,
        'payment_method_ids': [Command.set((cash_method | later_method).ids)], 'cash_control': True, 'use_presets': False})

    def session():
        result_session = admin['pos.session'].create({'config_id': ordinary.id})
        result_session.set_opening_control(0, 'FL3 fixture')
        return result_session

    def order(s, gross, allocations=None):
        quote = native_quote(abs(money(gross)), tax, product, company)
        sign = -1 if gross < 0 else 1
        result_order = admin['pos.order'].create({'session_id': s.id, 'company_id': company.id,
            'partner_id': partner.id, 'amount_total': gross, 'amount_tax': float(quote['tax']) * sign,
            'amount_paid': 0, 'amount_return': 0, 'is_refund': sign < 0,
            'lines': [Command.create({'product_id': product.id, 'qty': sign, 'price_unit': float(quote['unit_price']),
                'price_subtotal': float(quote['net']) * sign, 'price_subtotal_incl': gross,
                'tax_ids': [Command.set(tax.ids)], 'full_product_name': 'FL3 native sale'})]})
        for method, amount in allocations or [(cash_method, gross)]:
            admin['pos.payment'].create({'pos_order_id': result_order.id, 'payment_method_id': method.id, 'amount': amount})
        result_order.lines._onchange_amount_line_all()
        result_order._compute_prices()
        result_order.action_pos_order_paid()
        return result_order

    def close(s):
        s._compute_cash_balance()
        s.cash_register_balance_end_real = s.cash_register_balance_end
        s._compute_cash_balance()
        s.action_pos_session_closing_control()
        check('native session closed', s.state == 'closed' and s.move_id.state == 'posted')
        return s._get_related_account_moves()

    regular = session()
    regular_order = order(regular, 115)
    regular_moves = close(regular)
    parity('ordinary unbilled session', regular_moves, 115)
    late_invoice = regular_order.with_context(generate_pdf=False)._generate_pos_order_invoice()
    late_moves = regular._get_related_account_moves() | regular_order.reversed_move_ids | late_invoice
    check('late invoice native reclassification exists', bool(regular_order.reversed_move_ids.filtered(lambda m: m.reversed_pos_order_id == regular_order)))
    parity('late invoicing keeps net sales once', late_moves, 115)

    mixed = session()
    invoiced_order = order(mixed, 230)
    early_invoice = invoiced_order.with_context(generate_pdf=False)._generate_pos_order_invoice()
    order(mixed, 345)
    mixed_moves = close(mixed) | early_invoice
    values = parity('mixed before-close invoice plus uninvoiced sales', mixed_moves, 575)
    check('session contribution excludes early invoice230', money(actor['account.move'].browse(mixed.move_id.id).baseer_register_amount) == 345)

    fully_invoiced = session()
    fully_invoiced_order = order(fully_invoiced, 115)
    fully_invoiced_bill = fully_invoiced_order.with_context(generate_pdf=False)._generate_pos_order_invoice()
    fully_invoiced_moves = close(fully_invoiced) | fully_invoiced_bill
    parity('fully invoiced session excludes intermediary turnover', fully_invoiced_moves, 115)
    zero_row = actor['account.move'].browse(fully_invoiced.move_id.id)
    check('fully invoiced primary is valid zero not turnover or warning', not zero_row.baseer_register_contributor
          and not zero_row.baseer_register_incomplete and money(zero_row.baseer_register_amount) == 0)

    refund_session = session()
    refund_order = order(refund_session, -115)
    refund_moves = close(refund_session)
    parity('native uninvoiced refund signed', refund_moves, -115)
    refund_invoice = refund_order.with_context(generate_pdf=False)._generate_pos_order_invoice()
    parity('late refund invoice counted once', refund_session._get_related_account_moves() | refund_order.reversed_move_ids | refund_invoice, -115)

    credit = session()
    order(credit, 115, [(cash_method, 46), (later_method, 69)])
    credit_moves = close(credit)
    values = parity('native split pay-later balance', credit_moves, 115)
    check('native split customer account outstanding69 settled46', values['outstanding'] == 69 and values['settled'] == 46 and values['partial'] == 1)
    open_lines = credit.move_id.line_ids.filtered(lambda l: l.account_id == receivable and not l.reconciled)
    check('split receivable has non-payment-term native display type', bool(open_lines.filtered(lambda l: l.display_type == 'product')))
    open_lines.date_maturity = today - timedelta(days=1)
    check('overdue split receivable uses maturity without display-type heuristic', kpis(credit_moves)[0]['overdue'] == 69)
    method = cash_journal.inbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')[:1]
    method.payment_account_id = cash_journal.default_account_id
    settlement = admin['account.payment'].create({'payment_type': 'inbound', 'partner_type': 'customer',
        'partner_id': partner.id, 'amount': 23, 'date': today, 'journal_id': cash_journal.id,
        'payment_method_line_id': method.id, 'company_id': company.id, 'currency_id': company.currency_id.id})
    settlement.action_post()
    (open_lines | settlement._seek_for_lines()[1]).reconcile()
    values = parity('subsequent native partial settlement', credit_moves | settlement.move_id, 115)
    check('later settlement reduces current POS receivable', values['outstanding'] == 46 and values['settled'] == 69 and values['overdue'] == 46)

    # Native ordinary journal reversals remain signed ledger events, including a
    # second reversal. This does not invoke any report posting helper.
    reverse = mixed.move_id._reverse_moves(default_values_list=[{'date': today}], cancel=False)
    reverse.action_post()
    second_reverse = reverse._reverse_moves(default_values_list=[{'date': today}], cancel=False)
    second_reverse.action_post()
    parity('recursive POS reversal-of-reversal', mixed_moves | reverse | second_reverse, 575)

    # A wrongly typed intermediary line is still native ledger evidence; report
    # classification must warn rather than invent its missing receivable total.
    malformed_session = session()
    order(malformed_session, 115)
    malformed_moves = close(malformed_session)
    wrong_account = admin['account.account'].create({'name': 'FL3 invalid intermediary fixture', 'code': '119993',
        'account_type': 'asset_current', 'reconcile': True, 'company_ids': [Command.set(company.ids)]})
    malformed_session.move_id.line_ids.filtered(lambda l: l.account_id == receivable).remove_move_reconcile()
    malformed_session.move_id.line_ids.filtered(lambda l: l.account_id == receivable).account_id = wrong_account
    invalid_payload = kpis(malformed_moves)[2]
    check('misclassified POS source is flagged and excluded without guessing', invalid_payload['uncovered_count'] == 1
          and bool(invalid_payload['coverage_warning']) and kpis(malformed_moves)[0]['total'] == 0)

    malformed_split = session()
    order(malformed_split, 115, [(cash_method, 46), (later_method, 69)])
    malformed_split_moves = close(malformed_split)
    split_line = malformed_split.move_id.line_ids.filtered(lambda l: l.account_id == receivable and l.partner_id == partner)
    check('mixed classification fixture has a native product-type split line', len(split_line) == 1 and split_line.display_type == 'product')
    partner.property_account_receivable_id = wrong_account
    split_line.account_id = wrong_account
    check('mixed product-type misclassification warns despite other valid receivables', kpis(malformed_split_moves)[2]['uncovered_count'] == 1
          and kpis(malformed_split_moves)[0]['total'] == 0)
    partner.property_account_receivable_id = receivable

    move_rule = admin['ir.rule'].create({'name': 'FL3 rollback private move',
        'model_id': admin['ir.model']._get_id('account.move'),
        'domain_force': "[('id', '!=', %d)] if user.id == %d else [(1, '=', 1)]" % (mixed.move_id.id, actor.uid)})
    check('move rule independently removes POS contribution', kpis(mixed.move_id)[0]['total'] == 0)
    move_rule.unlink()
    line_rule = admin['ir.rule'].create({'name': 'FL3 rollback private receivable',
        'model_id': admin['ir.model']._get_id('account.move.line'),
        'domain_force': "['|', ('move_id', '!=', %d), ('account_id.account_type', '!=', 'asset_receivable')] if user.id == %d else [(1, '=', 1)]" % (mixed.move_id.id, actor.uid)})
    check('AML rule independently removes hidden receivable amounts', kpis(mixed.move_id)[0]['total'] == 0)
    line_rule.unlink()
    check('normal amounts return after fixture rules removed', kpis(mixed.move_id)[0]['total'] == 345)
    no_pos_user = admin['res.users'].create({'name': 'FL3 accounting only', 'login': 'fl3-accounting-only',
        'company_id': company.id, 'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set(admin.ref('account.group_account_readonly').ids)]})
    no_pos = env(user=no_pos_user.id, su=False, context=ctx)
    check('accounting-only fixture has no POS rights', not no_pos_user.has_group('point_of_sale.group_pos_user'))
    no_pos_values = no_pos['account.move'].baseer_financial_register_kpis([('id', '=', mixed.move_id.id)])
    check('accounting-only reader gets authorized ledger total without new POS rights',
          next(g for g in no_pos_values['currency_groups'] if g['currency_id'] == company.currency_id.id)['sections'][0]['cards'][0]['display'] == '345.00')

    deny('cashier cannot call expanded KPI', lambda: actors['cashier']['account.move'].baseer_financial_register_kpis([]))
    deny('cashier cannot directly read projected amounts', lambda: actors['cashier']['account.move'].browse(mixed.move_id.id).read(['baseer_register_amount']))
    deny('cashier cannot search projected settlement', lambda: actors['cashier']['account.move'].search([('baseer_register_has_settlement', '=', True)]))
    deny('forged private any operator denied', lambda: actor['account.move'].baseer_financial_register_kpis([('line_ids', 'any!', [('id', '!=', False)])]))
    all_fixture = source_moves | source.reversal_move_ids | replacement._native_moves() | replacement.reversal_move_ids | late_moves | mixed_moves | refund_moves | credit_moves
    env.flush_all()
    snapshot = counts()
    partner_before = partner.read(['customer_rank', 'write_date'])
    kpis(all_fixture)
    actor['account.move'].browse(all_fixture.ids).read(['baseer_register_amount', 'baseer_register_settled', 'baseer_register_outstanding'])
    env.flush_all()
    check('reporting never invokes posting/ranking helper or writes records', snapshot == counts() and partner.read(['customer_rank', 'write_date']) == partner_before)
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    guard.stop()
    result['rollback'] = before == counts()
    result['modules_preserved'] = versions == {m.name: m.latest_version for m in env['ir.module.module'].search([('state', '=', 'installed')])}
    result['hard_commit_guard'] = True
    result['passed'] = len(checks)
    result['source_sha256'] = hashlib.sha256(Path('/mnt/ic1-addons/baseer_financial_register/models/projection.py').read_bytes()).hexdigest()
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
assert result['status'] == 'PASS' and result['rollback'] and result['modules_preserved']
