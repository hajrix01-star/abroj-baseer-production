"""Synthetic QA fixture; run only through Odoo shell in the reports QA DB.

Creates one showcase company only after every assertion passes. Error paths
rollback the entire fixture; independent edge cases run inside rolled-back
savepoints. Never import this as production module data.
"""
import json
from decimal import Decimal
from pathlib import Path

from odoo import Command
from odoo.exceptions import AccessError

assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA database required'
COMPANY_NAME = 'QA الفئات النقدية'
assert not env['res.company'].search([('name', '=', COMPANY_NAME)]), 'Fixture already exists; do not duplicate'
checks = []
out = Path('/mnt/qa-evidence')


def money(actual, expected, label):
    actual = Decimal(str(actual)).quantize(Decimal('0.01'))
    expected = Decimal(str(expected)).quantize(Decimal('0.01'))
    assert actual == expected, (label, str(actual), str(expected))
    checks.append({'check': label, 'actual': str(actual), 'expected': str(expected)})


class RollbackEdgeCase(Exception):
    pass


try:
    admin = env.ref('base.user_admin')
    c = env['res.company'].create({
        'name': COMPANY_NAME, 'country_id': env.ref('base.sa').id,
        'currency_id': env.ref('base.SAR').id, 'city': 'Al Khobar',
        'iap_enrich_auto_done': True,
    })
    env['account.chart.template'].with_company(c)._load('sa', c, install_demo=False)
    admin.write({'company_ids': [Command.link(c.id)]})
    ctx = dict(env.context, allowed_company_ids=[c.id], tracking_disable=True)
    scoped = env(context=ctx)
    accounts = scoped['account.account'].with_company(c)
    journals = scoped['account.journal'].with_company(c)
    moves = scoped['account.move'].with_company(c)

    def account(kind):
        result = accounts.search([('company_ids', 'in', [c.id]), ('account_type', '=', kind)], limit=1)
        assert result, kind
        return result

    def new_account(code, name, kind, reconcile=False):
        return accounts.create({'code': code, 'name': name, 'account_type': kind,
            'company_ids': [Command.set([c.id])], 'reconcile': reconcile})

    income, expense = account('income'), account('expense')
    ar, ap = account('asset_receivable'), account('liability_payable')
    equity = new_account('QA3000', 'رأس مال افتتاحي تجريبي', 'equity')
    rent = new_account('QA6001', 'إيجارات', 'expense')
    utility = new_account('QA6002', 'كهرباء ومرافق', 'expense')
    fees = new_account('QA6003', 'رسوم بنكية', 'expense')
    salary = new_account('QA6004', 'رواتب الموظفين', 'expense')
    telecom = new_account('QA6005', 'اتصالات وإنترنت', 'expense')
    operating_group = scoped['account.group'].with_company(c).create({
        'name': 'مصاريف تشغيلية تجريبية', 'code_prefix_start': 'QA6',
        'code_prefix_end': 'QA6', 'company_id': c.id,
    })
    advance = new_account('QA1201', 'سلف ودفعات مقدمة', 'asset_current', True)
    outstanding = new_account('QA1202', 'تحصيلات معلقة تجريبية', 'asset_current', True)
    general = journals.search([('company_id', '=', c.id), ('type', '=', 'general')], limit=1)
    cash = journals.search([('company_id', '=', c.id), ('type', '=', 'cash')], limit=1)
    bank = journals.search([('company_id', '=', c.id), ('type', '=', 'bank')], limit=1)
    cash = cash or journals.create({'name': 'كاش تجريبي', 'code': 'QAC', 'type': 'cash', 'company_id': c.id})
    bank = bank or journals.create({'name': 'بنك تجريبي', 'code': 'QAB', 'type': 'bank', 'company_id': c.id})
    cash.name = 'كاش تجريبي'
    bank.name = 'بنك تجريبي'
    card = journals.create({'name': 'شبكة تجريبية', 'code': 'QAD', 'type': 'bank', 'company_id': c.id})
    for journal in cash + bank + card:
        for method in journal.inbound_payment_method_line_ids + journal.outbound_payment_method_line_ids:
            method.payment_account_id = journal.default_account_id

    partner = scoped['res.partner'].with_company(c).create({
        'name': 'طرف تجريبي للفئات', 'company_id': c.id,
        'property_account_receivable_id': ar.id, 'property_account_payable_id': ap.id,
    })
    tax_sale = env.ref('account.%s_sa_sales_tax_15' % c.id)
    tax_buy = env.ref('account.%s_sa_purchase_tax_15' % c.id)
    assert tax_sale.amount == 15 and tax_buy.amount == 15
    categories = scoped['product.category']
    drinks = categories.create({'name': 'مشروبات'})
    soft = categories.create({'name': 'مشروبات غازية', 'parent_id': drinks.id})
    water_cat = categories.create({'name': 'مياه', 'parent_id': drinks.id})
    food_cat = categories.create({'name': 'مواد غذائية'})

    def product(name, category):
        return scoped['product.product'].with_company(c).create({
            'name': name, 'type': 'consu', 'categ_id': category.id,
            'property_account_income_id': income.id,
            'property_account_expense_id': expense.id,
            'taxes_id': [Command.set(tax_sale.ids)],
            'supplier_taxes_id': [Command.set(tax_buy.ids)],
        })

    water = product('ماء تجريبي', water_cat)
    pepsi = product('بيبسي تجريبي', soft)
    food = product('مواد غذائية تجريبية صفرية الضريبة', food_cat)

    def entry(date, lines, journal=None, ref='QA synthetic cash categories'):
        m = moves.create({'date': date, 'journal_id': (journal or general).id,
            'ref': ref, 'line_ids': [Command.create({
                'name': ref, 'account_id': a.id, 'debit': debit, 'credit': credit,
                'partner_id': partner.id,
            }) for a, debit, credit in lines]})
        m.action_post()
        return m

    def invoice(kind, specifications, date='2026-09-03'):
        tax = tax_sale if kind in ('out_invoice', 'out_refund') else tax_buy
        line_values = []
        for item, amount, taxed, ledger in specifications:
            vals = {'name': item.name if item else ledger.name, 'quantity': 1,
                'price_unit': amount, 'account_id': ledger.id,
                'tax_ids': [Command.set(tax.ids if taxed else [])]}
            if item:
                vals['product_id'] = item.id
            line_values.append(Command.create(vals))
        m = moves.create({'move_type': kind, 'partner_id': partner.id,
            'invoice_date': date, 'date': date, 'invoice_line_ids': line_values})
        m.action_post()
        return m

    def pay(m, amount, journal=None, date='2026-09-10'):
        journal = journal or cash
        inbound = m.move_type in ('out_invoice', 'in_refund')
        methods = journal.inbound_payment_method_line_ids if inbound else journal.outbound_payment_method_line_ids
        wizard = scoped['account.payment.register'].with_company(c).with_context(
            active_model='account.move', active_ids=m.ids).create({
                'journal_id': journal.id, 'payment_method_line_id': methods[0].id,
                'amount': amount, 'payment_date': date})
        payments = wizard._create_payments()
        assert payments and all(p.move_id.state == 'posted' for p in payments)
        return payments

    report = scoped['eh.account.dynamic.report'].with_user(admin).with_company(c).search([
        ('code', '=', 'baseer_cash_categories')], limit=1)
    assert report, 'Install Baseer cash categories before running fixture'
    options = {'date': {'mode': 'range', 'date_from': '2026-09-01', 'date_to': '2026-09-30'},
        'company_ids': [c.id], 'posted_only': True, 'baseer_include_tax': True,
        'show_zero': False, 'lazy_expand': True, 'unfold_all': True}

    def render(include_tax=True):
        return report.render(dict(options, baseer_include_tax=include_tax), use_cache=False)

    def total(payload, key):
        aliases = {'net_cash': 'displayed_net_movement', 'cash_in': 'receipts',
            'cash_out': 'payments', 'opening_cash': 'opening_cash_balance',
            'closing_cash': 'closing_cash_balance', 'vat_bridge': 'excluded_tax_bridge'}
        value = payload['totals'][aliases.get(key, key)]
        return -value if key == 'cash_out' else value

    empty = render()
    money(total(empty, 'net_cash'), 0, 'empty company has no cash movement')
    entry('2026-08-31', [(cash.default_account_id, 1000, 0), (equity, 0, 1000)])
    for journal, amount in [(cash, 100), (bank, 200), (card, 100)]:
        sale = invoice('out_invoice', [(water, amount, True, income)])
        pay(sale, amount * 1.15, journal)
    mixed = invoice('in_invoice', [(water, 100, True, expense), (pepsi, 200, True, expense), (food, 100, False, expense)])
    money(mixed.amount_total, 445, 'mixed VAT bill gross')
    pay(mixed, 222.5)
    money(mixed.amount_residual, 222.5, 'mixed bill half remains unpaid')
    rental = invoice('in_invoice', [(None, 1000, True, rent)])
    pay(rental, 115)
    refund = invoice('out_refund', [(water, 10, True, income)])
    # The showcase refund is an actual payment, not an offset against an invoice.
    refund.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_receivable').remove_move_reconcile()
    pay(refund, 11.5)
    entry('2026-09-10', [(utility, 25, 0), (cash.default_account_id, 0, 25)])
    entry('2026-09-10', [(salary, 200, 0), (cash.default_account_id, 0, 200)])
    telecom_bill = invoice('in_invoice', [(None, 50, True, telecom)])
    pay(telecom_bill, 57.5)
    entry('2026-09-10', [(advance, 40, 0), (cash.default_account_id, 0, 40)])
    entry('2026-09-10', [(bank.default_account_id, 30, 0), (fees, 2, 0), (cash.default_account_id, 0, 32)])
    old_bill = invoice('in_invoice', [(None, 100, True, expense)], date='2026-08-25')
    pay(old_bill, 57.5)
    before_unpaid = render()
    invoice('out_invoice', [(pepsi, 900, True, income)])
    invoice('in_invoice', [(pepsi, 700, True, expense)])
    gross, net = render(True), render(False)
    money(total(gross, 'net_cash'), total(before_unpaid, 'net_cash'), 'unpaid invoices do not affect cash')
    for payload, label, expected_in, expected_out, expected_net in [
        (gross, 'gross', 460, 731, -271), (net, 'net VAT', 400, 677, -277),
    ]:
        money(total(payload, 'cash_in'), expected_in, label + ' receipts')
        money(total(payload, 'cash_out'), expected_out, label + ' payments')
        money(total(payload, 'net_cash'), expected_net, label + ' net movement')
    money(total(gross, 'opening_cash'), 1000, 'opening cash balance')
    money(total(gross, 'closing_cash'), 729, 'closing cash balance')
    money(total(net, 'vat_bridge'), 6, 'excluded VAT bridge back to cash')
    money(total(gross, 'balance_check'), 0, 'cash ledger reconciliation')
    line_names = [line['name'] for line in gross['lines']]
    for category in [drinks, soft, water_cat, food_cat]:
        assert any(category.name == label for label in line_names), ('category missing', category.name)
        checks.append({'check': 'category visible ' + category.name, 'passed': True})
    child = next(line for line in gross['lines'] if line['name'] == soft.name)
    mother = next(line for line in gross['lines'] if line['id'] == child.get('parent_id'))
    assert mother['name'] == drinks.name, 'subcategory parent label incorrect'
    assert child.get('parent_id') == mother['id'], 'category parent hierarchy incorrect'
    checks.append({'check': 'parent category owns subcategory', 'passed': True})
    for ledger, amount in [(salary, -200), (utility, -25), (telecom, -57.5), (rent, -115)]:
        line = next(line for line in gross['lines'] if line['id'].endswith('/ledger-%s' % ledger.id))
        money(line['columns'][0]['value'], amount, 'paid expense shown separately: ' + ledger.name)
        group_line = next(parent for parent in gross['lines'] if parent['id'] == line['parent_id'])
        assert group_line['name'] == operating_group.name, 'operating expense group missing'
    for category, amount in [(soft, -115), (water_cat, -57.5), (food_cat, -50)]:
        line = next(line for line in gross['lines'] if line['id'].startswith('payments/category-') and line['id'].endswith('category-%s' % category.id))
        money(line['columns'][0]['value'], amount, 'half-paid category allocation: ' + category.name)

    # Outstanding-account payment: no cash until the later bank-book entry.
    try:
        with env.cr.savepoint():
            baseline = render()
            bank.inbound_payment_method_line_ids[0].payment_account_id = outstanding
            outstanding_sale = invoice('out_invoice', [(water, 100, True, income)])
            payment = pay(outstanding_sale, 115, bank)
            money(total(render(), 'cash_in'), total(baseline, 'cash_in'), 'outstanding receipt not yet cash')
            settlement = entry('2026-09-20', [(bank.default_account_id, 115, 0), (outstanding, 0, 115)], bank)
            (payment.move_id.line_ids + settlement.line_ids).filtered(lambda line: line.account_id == outstanding).reconcile()
            money(total(render(), 'cash_in'), Decimal(str(total(baseline, 'cash_in'))) + Decimal('115'), 'bank settlement recognized once')
            money(total(render(False), 'cash_in'), Decimal(str(total(net, 'cash_in'))) + Decimal('100'), 'bank settlement traces invoice VAT')
            raise RollbackEdgeCase()
    except RollbackEdgeCase:
        pass

    # Tiny half-paid mixed-tax lines expose independently rounded allocation drift.
    try:
        with env.cr.savepoint():
            baseline = render()
            tiny = invoice('in_invoice', [(water, 0.05, True, expense), (pepsi, 0.05, True, expense), (food, 0.05, False, expense)])
            pay(tiny, 0.08)
            tiny_result = render()
            money(total(tiny_result, 'cash_out'), Decimal(str(total(baseline, 'cash_out'))) + Decimal('0.08'), 'cent allocation preserves payment')
            money(total(tiny_result, 'balance_check'), 0, 'cent allocation reconciles cash')
            raise RollbackEdgeCase()
    except RollbackEdgeCase:
        pass

    restricted = env['res.users'].with_context(no_reset_password=True).create({
        'name': 'QA Cash Categories Restricted', 'login': 'qa_cash_categories_restricted',
        'company_id': c.id, 'company_ids': [Command.set(c.ids)],
        'group_ids': [Command.set([env.ref('base.group_user').id, env.ref('eh_account_base.group_eh_user').id])],
    })
    restricted_report = report.with_user(restricted).with_context(allowed_company_ids=c.ids)
    money(total(restricted_report.render(options, use_cache=False), 'net_cash'), -271, 'restricted user own company')
    other = env['res.company'].search([('id', '!=', c.id)], limit=1)
    try:
        with env.cr.savepoint():
            restricted_report.render(dict(options, company_ids=other.ids), use_cache=False)
    except AccessError:
        checks.append({'check': 'other company access rejected', 'passed': True})
    else:
        raise AssertionError('Cross-company read permitted')

    # Savepoints must not leave edge-case transactions in the showcase.
    gross, net = render(True), render(False)
    money(total(gross, 'net_cash'), -271, 'showcase clean after edge-case rollback')
    out.mkdir(exist_ok=True)
    artifacts = {'cash_categories_gross.json': gross, 'cash_categories_net.json': net,
        'cash_categories_checks.json': {'company': {'id': c.id, 'name': c.name}, 'checks': checks,
            'synthetic': True, 'tax_policy': 'Native Saudi 15%; explicitly zero-tax synthetic food line',
            'options': options}}
    for filename, value in artifacts.items():
        (out / filename).write_text(json.dumps(value, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    env.cr.commit()
    print('CASH_CATEGORIES_QA_SUCCESS', len(checks), 'checks; company', c.id)
except Exception:
    env.cr.rollback()
    raise
