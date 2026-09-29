"""FL1 isolated native accounting fixtures, security checks and bounded reader timing."""
import json
import traceback
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError, UserError
from odoo.fields import Domain

assert env.cr.dbname.startswith('baseer_ar1_') and env.su
OUT = Path('/mnt/qa-evidence/fl1-accounting-checks.json')
checks = []
result = {'status': 'FAIL', 'checks': checks, 'rollback': False, 'capacity': {}, 'database': env.cr.dbname,
          'scope': 'Clean MAIN clone + FL1 only; exact AR2 baseline mounts; commit guard enforced'}

def check(label, condition):
    assert condition, label
    checks.append(label)

def deny(label, call, errors=(AccessError,)):
    try:
        with env.cr.savepoint():
            call()
    except errors:
        checks.append(label)
        return
    raise AssertionError(label + ': unexpectedly allowed')

def dec(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))

def stamp():
    return {name: env[name].with_context(active_test=False).search_count([]) for name in (
        'res.users', 'res.partner', 'res.company', 'account.move', 'account.move.line',
        'account.payment', 'account.partial.reconcile', 'account.payment.term')}

def cards(data, currency, scope):
    group = next(group for group in data['currency_groups'] if group['currency_id'] == currency.id)
    section = next(section for section in group['sections'] if section['key'] == scope)
    return {card['key']: card for card in section['cards']}

def money(card):
    return Decimal(card['display'].replace(',', ''))

before = stamp()
before_modules = env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
commit_guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('FL1 fixtures must never commit'))
commit_guard.start()
try:
    company = env['res.company'].search([('currency_id.name', '=', 'SAR')]).filtered(
        lambda company: company.baseer_salary_expense_id and company.baseer_salary_payable_id)[:1]
    assert company, 'Need an existing configured synthetic QA company'
    today = fields.Date.context_today(env['account.move'])
    ctx = {'allowed_company_ids': company.ids, 'lang': 'en_US', 'tz': 'Asia/Riyadh',
           'tracking_disable': True, 'mail_create_nolog': True, 'no_reset_password': True}
    admin = env(context=ctx)
    actors = {}
    for role in ('accountant', 'cashier', 'owner'):
        user = admin['res.users'].create({'name': 'FL1 ROLLBACK ' + role,
            'login': 'fl1-rollback-' + role, 'baseer_access_role': role,
            'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        actors[role] = env(user=user.id, su=False, context=ctx)
    reader = actors['accountant']['account.move']
    owner = actors['owner']['account.move']
    cashier = actors['cashier']['account.move']
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_deduction_account_id | company.baseer_loan_account_id
    def account(kind):
        return admin['account.account'].search([('company_ids', 'in', company.ids),
            ('account_type', '=', kind), ('id', 'not in', private.ids)], limit=1)
    expense, income = account('expense'), account('income')
    payable, receivable = account('liability_payable'), account('asset_receivable')
    purchase = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'purchase')], limit=1)
    sale = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'sale')], limit=1)
    treasury = admin['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank'])]).filtered(
        lambda journal: journal.default_account_id.account_type == 'asset_cash')[:1]
    assert expense and income and payable and receivable and purchase and sale and treasury
    vendor = admin['res.partner'].create({'name': 'FL1 synthetic partner', 'company_id': company.id,
        'property_account_payable_id': payable.id, 'property_account_receivable_id': receivable.id})
    moves = admin['account.move'].browse()
    def invoice(kind, amount, **extra):
        values = {'move_type': kind, 'company_id': company.id,
            'journal_id': (purchase if kind.startswith('in_') else sale).id,
            'partner_id': vendor.id, 'invoice_date': today, 'date': today,
            'ref': 'FL1 ROLLBACK', 'invoice_line_ids': [Command.create({'name': 'Synthetic FL1 document',
                'quantity': 1, 'price_unit': amount,
                'account_id': (expense if kind.startswith('in_') else income).id, 'tax_ids': [Command.clear()]})]}
        values.update(extra)
        move = admin['account.move'].create(values)
        move.action_post()
        return move
    def pay(move, amount, pending=False):
        lines = treasury.outbound_payment_method_line_ids if move.move_type in ('in_invoice', 'out_refund', 'in_receipt') else treasury.inbound_payment_method_line_ids
        method = lines.filtered(lambda line: line.code == 'manual')[:1]
        assert method
        if not pending:
            method.payment_account_id = treasury.default_account_id
        else:
            clearing = admin['account.account'].create({'name': 'FL1 synthetic pending', 'code': 'FL1PENDING',
                'account_type': 'asset_current', 'company_ids': [Command.set(company.ids)], 'reconcile': True})
            method.payment_account_id = clearing
        wizard = admin['account.payment.register'].with_context(active_model='account.move', active_ids=move.ids).create({
            'journal_id': treasury.id, 'payment_method_line_id': method.id, 'amount': amount,
            'payment_date': today, 'installments_mode': 'full', 'payment_difference_handling': 'open'})
        return wizard._create_payments()

    customer = invoice('out_invoice', 100.10)
    supplier = invoice('in_invoice', 200.20)
    cr_customer = invoice('out_refund', 10.05)
    cr_supplier = invoice('in_refund', 20.05)
    receipts = invoice('out_receipt', 7.25) | invoice('in_receipt', 8.25)
    payments = pay(customer, 25.05) | pay(supplier, 60.05) | pay(cr_customer, 10.05)
    moves |= customer | supplier | cr_customer | cr_supplier | receipts
    domain = [('id', 'in', moves.ids + payments.move_id.ids)]
    kpi = reader.baseer_financial_register_kpis(domain)
    c, s = cards(kpi, company.currency_id, 'customer'), cards(kpi, company.currency_id, 'supplier')
    for key, expected in {'total': '97.30', 'settled': '15.00', 'outstanding': '82.30', 'partial': '1'}.items():
        check('customer signed ' + key, money(c[key]) == Decimal(expected))
    for key, expected in {'total': '188.40', 'settled': '60.05', 'outstanding': '128.35', 'partial': '1'}.items():
        check('supplier signed ' + key, money(s[key]) == Decimal(expected))
    check('native actual customer partial status', customer.payment_state == 'partial')
    check('native actual vendor partial status', supplier.payment_state == 'partial')
    check('refund settlement subtracts from customer settlement', dec(cr_customer.amount_total_signed - cr_customer.amount_residual_signed) == Decimal('-10.05'))
    check('payment moves remain register rows', set(payments.move_id.ids) <= set(reader.search(Domain(domain) & Domain('state', '=', 'posted')).ids))
    check('general payments never enter invoice cards', kpi == reader.baseer_financial_register_kpis([('id', 'in', moves.ids)]))
    for scope, section in [('customer', c), ('supplier', s)]:
        for key, card in section.items():
            selected = reader.search(Domain(domain) & Domain(card['domain']))
            if key == 'total':
                check(scope + ' total drill parity', all(move.move_type.startswith('out_' if scope == 'customer' else 'in_') for move in selected))
            elif key == 'settled':
                check(scope + ' settled drill parity', all(move.baseer_register_has_settlement for move in selected))
            elif key == 'partial':
                check(scope + ' partial drill count', len(selected) == money(card))
    check('settled refund drill includes negative contributor', cr_customer.id in reader.search(Domain(domain) & Domain(c['settled']['domain'])).ids)
    for value in (True, False):
        selected = reader.search(Domain(domain) & Domain('baseer_register_has_settlement', '=', value))
        check('computed and searched contributor parity ' + str(value), all(move.baseer_register_has_settlement == value for move in selected))

    term = admin['account.payment.term'].create({'name': 'FL1 40 past 60 future', 'line_ids': [
        Command.create({'value': 'percent', 'value_amount': 40, 'nb_days': 0}),
        Command.create({'value': 'percent', 'value_amount': 60, 'nb_days': 60})]})
    installment = invoice('out_invoice', 100, invoice_date=today-timedelta(days=30), invoice_payment_term_id=term.id)
    installment_domain = [('id', '=', installment.id)]
    terms = installment.line_ids.filtered(lambda line: line.display_type == 'payment_term')
    check('native installment fixture has past and future maturities', len(terms) == 2 and min(terms.mapped('date_maturity')) < today < max(terms.mapped('date_maturity')))
    overdue = cards(reader.baseer_financial_register_kpis(installment_domain), company.currency_id, 'customer')['overdue']
    check('only matured installment amount counted', money(overdue) == Decimal('40'))
    check('overdue drill includes partially matured invoice', reader.search(Domain(installment_domain) & Domain(overdue['domain'])) == reader.browse(installment.id))
    pay(installment, 10)
    overdue = cards(reader.baseer_financial_register_kpis(installment_domain), company.currency_id, 'customer')['overdue']
    check('matured installment partial settlement reduces overdue', money(overdue) == Decimal('30'))
    past_line = terms.filtered(lambda line: line.date_maturity < today)
    hidden_term_rule = admin['ir.rule'].create({'name': 'FL1 isolated term restriction',
        'model_id': admin['ir.model']._get_id('account.move.line'),
        'domain_force': repr([('id', 'not in', past_line.ids)]), 'groups': [Command.clear()]})
    restricted = cards(reader.baseer_financial_register_kpis(installment_domain), company.currency_id, 'customer')['overdue']
    check('overdue applies independent line access rules', money(restricted) == 0)
    check('overdue drill matches independently hidden installments', not reader.search(Domain(installment_domain) & Domain(restricted['domain'])))
    hidden_term_rule.unlink()
    check('parent filter removes overdue from endpoint', all(money(card) == 0 for card in cards(reader.baseer_financial_register_kpis([('id', '=', -1)]), company.currency_id, 'customer').values()))

    draft = customer.copy({'ref': 'FL1 draft'})
    check('draft cannot widen posted scope', money(cards(reader.baseer_financial_register_kpis(['|', ('id', '=', customer.id), ('id', '=', draft.id)]), company.currency_id, 'customer')['total']) == Decimal('100.10'))
    check('explicit draft-only filter returns zero', money(cards(reader.baseer_financial_register_kpis([('id', '=', draft.id), ('state', '=', 'draft')]), company.currency_id, 'customer')['total']) == 0)
    for label, call in [('KPI', lambda: cashier.baseer_financial_register_kpis([])), ('action', cashier.action_open_financial_register),
                        ('source', lambda: cashier.browse(customer.id).action_open_register_source())]:
        deny('cashier feature ' + label + ' denied', call)
    for malicious in [[('line_ids', 'any!', [('id', '>', 0)])], [('line_ids', 'any', [('move_id', 'any!', [('id', '>', 0)])])]]:
        deny('forged privileged domain operator rejected', lambda malicious=malicious: reader.baseer_financial_register_kpis(malicious))
    deny('forged company context rejected', lambda: reader.with_context(allowed_company_ids=[999999]).baseer_financial_register_kpis([]))

    private_partner = admin['res.partner'].create({'name': 'FL1 private contact', 'company_id': company.id,
        'property_account_payable_id': company.baseer_salary_payable_id.id})
    private_bill = invoice('in_invoice', 987.65, partner_id=private_partner.id, invoice_date=today-timedelta(days=5),
        invoice_line_ids=[Command.create({'name': 'Synthetic private salary', 'quantity': 1, 'price_unit': 987.65,
            'account_id': company.baseer_salary_expense_id.id, 'tax_ids': [Command.clear()]})])
    private_domain = [('id', '=', private_bill.id)]
    hidden = cards(reader.baseer_financial_register_kpis(private_domain), company.currency_id, 'supplier')
    check('private salary excluded from all KPI sums and counts', all(money(card) == 0 for card in hidden.values()))
    check('owner retains permitted private invoice totals', money(cards(owner.baseer_financial_register_kpis(private_domain), company.currency_id, 'supplier')['total']) == Decimal('987.65'))
    deny('accountant private source action denied', lambda: reader.browse(private_bill.id).action_open_register_source())
    check('private salary absent from record export source', not reader.search(private_domain))
    check('private salary overdue cannot leak through line aggregation', money(hidden['overdue']) == 0)

    # This deployment's native invoicing hook returns paid. Exercise compatibility with
    # the native accounting hook that returns in_payment, without changing posting logic.
    pending = invoice('out_invoice', 15.15)
    with patch.object(type(admin['account.move']), '_get_invoice_in_payment_state', lambda self: 'in_payment'):
        pay(pending, 15.15, pending=True)
        pending._compute_payment_state()
        check('native pending-payment compatibility fixture', pending.payment_state == 'in_payment' and dec(pending.amount_residual) == 0)
        pc = cards(reader.baseer_financial_register_kpis([('id', '=', pending.id)]), company.currency_id, 'customer')
        check('in_payment settlement counted without rewriting status', money(pc['settled']) == Decimal('15.15') and pending.payment_state == 'in_payment')

    foreign = env.ref('base.USD')
    foreign.active = True
    admin['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': company.id, 'name': today, 'rate': 0.2666666667})
    foreign_invoice = invoice('out_invoice', 12.34, currency_id=foreign.id)
    fc = cards(reader.baseer_financial_register_kpis([('id', '=', foreign_invoice.id)]), company.currency_id, 'customer')
    check('foreign row retains document currency', foreign_invoice.currency_id == foreign)
    check('foreign card uses booked company-currency value', money(fc['total']) == dec(foreign_invoice.amount_total_signed))
    pay(foreign_invoice, 12.34)
    check('foreign contributor computed/search parity', foreign_invoice.baseer_register_has_settlement == bool(reader.search([('id', '=', foreign_invoice.id), ('baseer_register_has_settlement', '=', True)])))

    original = invoice('out_invoice', 44.44)
    reversal = invoice('out_refund', 44.44)
    (original.line_ids | reversal.line_ids).filtered(lambda line: line.account_id == receivable).reconcile()
    reversed_data = cards(reader.baseer_financial_register_kpis([('id', 'in', (original | reversal).ids)]), company.currency_id, 'customer')
    check('native credit reconciliation creates reversed state', original.payment_state == 'reversed')
    check('reversed invoices net to zero total and settlement', money(reversed_data['total']) == 0 and money(reversed_data['settled']) == 0)

    usd_company = admin['res.company'].create({'name': 'FL1 ROLLBACK USD', 'currency_id': foreign.id,
                                              'country_id': env.ref('base.sa').id})
    # Installed Saudi localization defaults SAR during native company initialization.
    # Change the synthetic company's currency before it has any financial documents.
    usd_company.currency_id = foreign
    usd_admin = env(context=dict(ctx, allowed_company_ids=usd_company.ids))
    usd_income = usd_admin['account.account'].create({'name': 'FL1 USD income', 'code': 'FL1INC',
        'account_type': 'income', 'company_ids': [Command.set(usd_company.ids)]})
    usd_receivable = usd_admin['account.account'].create({'name': 'FL1 USD receivable', 'code': 'FL1REC',
        'account_type': 'asset_receivable', 'company_ids': [Command.set(usd_company.ids)], 'reconcile': True})
    usd_journal = usd_admin['account.journal'].create({'name': 'FL1 USD sales', 'code': 'FL1US', 'type': 'sale',
        'company_id': usd_company.id, 'default_account_id': usd_income.id})
    usd_partner = usd_admin['res.partner'].create({'name': 'FL1 USD customer', 'company_id': usd_company.id,
        'property_account_receivable_id': usd_receivable.id})
    usd_invoice = usd_admin['account.move'].create({'move_type': 'out_invoice', 'company_id': usd_company.id,
        'journal_id': usd_journal.id, 'partner_id': usd_partner.id, 'invoice_date': today, 'date': today,
        'invoice_line_ids': [Command.create({'name': 'FL1 USD fixture', 'quantity': 1, 'price_unit': 55.55,
            'account_id': usd_income.id, 'tax_ids': [Command.clear()]})]})
    usd_invoice.action_post()
    denied_usd = reader.baseer_financial_register_kpis([('id', '=', usd_invoice.id)])
    check('unauthorized company contributes no KPI amount', all(money(card) == 0 for group in denied_usd['currency_groups'] for section in group['sections'] for card in section['cards']))
    deny('unauthorized real company context denied', lambda: reader.with_context(allowed_company_ids=usd_company.ids).baseer_financial_register_kpis([]))
    admin['res.users'].browse(reader.env.uid).write({'company_ids': [Command.set((company | usd_company).ids)]})
    both = reader.with_context(allowed_company_ids=(company | usd_company).ids)
    cross_domain = [('id', 'in', (customer | usd_invoice).ids)]
    cross = both.baseer_financial_register_kpis(cross_domain)
    result['currency_fixture'] = {'new_company_currency': usd_company.currency_id.name,
        'original_currency': company.currency_id.name, 'groups': [group['currency_name'] for group in cross['currency_groups']],
        'invoice_currency': usd_invoice.currency_id.name, 'company_ids': both.env.companies.ids}
    check('different company currencies remain separate', {group['currency_id'] for group in cross['currency_groups']} == {company.currency_id.id, foreign.id})
    check('SAR group contains SAR invoice only', money(cards(cross, company.currency_id, 'customer')['total']) == Decimal('100.10'))
    check('USD group contains USD invoice only', money(cards(cross, foreign, 'customer')['total']) == Decimal('55.55'))
    check('currency drill excludes other currency documents', both.search(Domain(cross_domain) & Domain(cards(cross, foreign, 'customer')['total']['domain'])).ids == usd_invoice.ids)

    config = admin['pos.config'].search([('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
    method = config.payment_method_ids.filtered(lambda method: method.active and method.type == 'cash')[:1]
    assert config and method, 'Need existing configured QA summary POS and cash method'
    summary_date = today-timedelta(days=400)
    while admin['baseer.pos.summary'].search_count([('company_id', '=', company.id), ('business_date', '=', summary_date)]):
        summary_date -= timedelta(days=1)
    summary = admin['baseer.pos.summary'].create({'company_id': company.id, 'config_id': config.id,
        'business_date': summary_date, 'day_schedule': 'all', 'period_scope': 'all', 'customer_count': 5,
        'allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': 115})]})
    summary.action_approve()
    summary_moves = admin['account.move'].search([('baseer_pos_summary_id', '=', summary.id), ('state', '=', 'posted')])
    check('approved POS summary has posted native register rows', bool(summary_moves) and set(summary_moves.ids) <= set(reader.search([('id', 'in', summary_moves.ids)]).ids))
    source_action = reader.browse(summary_moves[0].id).action_open_register_source()
    check('POS register source opens actual approved summary', source_action['res_model'] == 'baseer.pos.summary' and source_action['res_id'] == summary.id)
    check('POS rows use their native summary classification', reader.browse(summary_moves[0].id).baseer_register_source == 'Sales summary')
    summary_kpis = reader.baseer_financial_register_kpis([('id', 'in', summary_moves.ids)])
    check('POS journal turnover does not double-count invoice cards', all(money(card) == 0 for group in summary_kpis['currency_groups'] for section in group['sections'] for card in section['cards']))

    # Representative bounded single-reader dataset; this does not certify 100k / 20 readers.
    count = 180
    start = perf_counter()
    capacity = admin['account.move'].create([{'move_type': 'out_invoice', 'company_id': company.id,
        'journal_id': sale.id, 'partner_id': vendor.id, 'invoice_date': today, 'date': today, 'ref': 'FL1 CAPACITY',
        'invoice_line_ids': [Command.create({'name': 'Synthetic capacity', 'quantity': 1,
            'price_unit': 10.01, 'account_id': income.id, 'tax_ids': [Command.clear()]})]} for index in range(count)])
    capacity.action_post()
    elapsed_setup = perf_counter()-start
    cap_domain = [('id', 'in', capacity.ids)]
    env.flush_all()
    snapshot = capacity.read(['state', 'amount_total_signed', 'amount_residual_signed', 'payment_state', 'write_date'])
    times = []
    for index in range(5):
        start = perf_counter()
        cap_result = reader.baseer_financial_register_kpis(cap_domain)
        times.append(round((perf_counter()-start)*1000, 3))
    check('capacity exact decimal sum', money(cards(cap_result, company.currency_id, 'customer')['total']) == Decimal('1801.80'))
    check('reads preserve financial source values', snapshot == capacity.read(['state', 'amount_total_signed', 'amount_residual_signed', 'payment_state', 'write_date']))
    check('bounded warm reads under 2 seconds', max(times[1:]) < 2000)
    result['capacity'] = {'fixture_moves': len(capacity), 'fixture_lines': len(capacity.line_ids),
        'visible_posted_moves': reader.search_count([('state', '=', 'posted')]), 'concurrent_readers': 1,
        'fixture_setup_seconds': round(elapsed_setup, 3), 'request_ms': times,
        'limitation': '180 native invoices, single sequential reader; not a 100k-move or 20-reader certification'}
    result['status'] = 'PASS'
except Exception as error:
    result.update(error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
finally:
    env.cr.rollback()
    commit_guard.stop()
    env.invalidate_all()
    after = stamp()
    result['rollback'] = after == before
    result['rollback_counts'] = {'before': before, 'after': after}
    result['installed_modules_preserved'] = sorted(before_modules) == sorted(env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name'))
    result['commit_guard'] = True
    result['passed'] = len(checks)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    print('FL1_REGISTER_CHECKS', result['status'], len(checks), 'ROLLBACK', result['rollback'])
assert result['status'] == 'PASS', result.get('error', 'FL1 failed')
assert result['rollback'] and result['installed_modules_preserved'], 'FL1 fixture rollback/preservation failed'
