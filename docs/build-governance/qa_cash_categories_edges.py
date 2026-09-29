"""QA probes with synthetic ledger/company/configuration mutations rolled back.

Requires the committed showcase company (ID 9). Never runs the original
fixture again. The script never commits its transaction. Vendor failure-audit
records use an independent transaction and may remain in the QA database.
"""
import json
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from odoo import Command
from odoo.exceptions import AccessError, UserError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
c = env['res.company'].browse(9).exists()
assert c and c.name == 'QA الفئات النقدية'
ctx = dict(env.context, allowed_company_ids=c.ids, tracking_disable=True)
scoped = env(context=ctx)
admin = env.ref('base.user_admin')
report = scoped['eh.account.dynamic.report'].with_user(admin).with_company(c).search([
    ('code', '=', 'baseer_cash_categories')], limit=1)
assert report
options = {'date': {'mode': 'range', 'date_from': '2026-09-01', 'date_to': '2026-09-30'},
    'company_ids': c.ids, 'posted_only': True, 'baseer_include_tax': True,
    'lazy_expand': True, 'unfold_all': True}
checks = []


def decimal(value):
    return Decimal(str(value)).quantize(Decimal('0.01'))


def money(actual, expected, label):
    assert decimal(actual) == decimal(expected), (label, actual, expected)
    checks.append({'check': label, 'actual': str(decimal(actual)), 'expected': str(decimal(expected))})


def passed(condition, label):
    assert condition, label
    checks.append({'check': label, 'passed': True})


class RollbackCase(Exception):
    pass


@contextmanager
def rollback_case():
    try:
        with env.cr.savepoint():
            yield
            raise RollbackCase()
    except RollbackCase:
        pass


def render(include_tax=True, use_cache=False, **extra):
    return report.render(dict(options, baseer_include_tax=include_tax, **extra), use_cache=use_cache)


def category_amount(payload, category):
    ident = 'payments/category-%s' % category.id
    line = next((line for line in payload['lines'] if line['id'] == ident), None)
    return decimal(line['columns'][0]['value']) if line else Decimal('0.00')


try:
    journals = scoped['account.journal'].with_company(c)
    cash = journals.search([('company_id', '=', c.id), ('type', '=', 'cash')], limit=1)
    bank = journals.search([('company_id', '=', c.id), ('name', '=', 'بنك تجريبي')], limit=1)
    card = journals.search([('company_id', '=', c.id), ('name', '=', 'شبكة تجريبية')], limit=1)
    general = journals.search([('company_id', '=', c.id), ('type', '=', 'general')], limit=1)
    partner = scoped['res.partner'].search([('company_id', '=', c.id), ('name', '=', 'طرف تجريبي للفئات')], limit=1)
    accounts = scoped['account.account'].with_company(c)
    expense = accounts.search([('company_ids', 'in', c.ids), ('account_type', '=', 'expense')], limit=1)
    tax = env.ref('account.%s_sa_purchase_tax_15' % c.id)
    moves = scoped['account.move'].with_company(c)

    def product(name):
        category = scoped['product.category'].create({'name': name})
        item = scoped['product.product'].with_company(c).create({
            'name': name, 'type': 'consu', 'categ_id': category.id,
            'property_account_expense_id': expense.id,
            'supplier_taxes_id': [Command.clear()], 'taxes_id': [Command.clear()],
        })
        return item, category

    def invoice(specifications):
        m = moves.create({'move_type': 'in_invoice', 'partner_id': partner.id,
            'invoice_date': '2026-09-15', 'date': '2026-09-15',
            'invoice_line_ids': [Command.create({'product_id': item.id,
                'name': item.name, 'account_id': expense.id, 'quantity': 1,
                'price_unit': amount, 'tax_ids': [Command.set(tax.ids if taxed else [])],
            }) for item, amount, taxed in specifications]})
        m.action_post()
        return m

    def pay(m, amount):
        wizard = scoped['account.payment.register'].with_company(c).with_context(
            active_model='account.move', active_ids=m.ids).create({
                'journal_id': cash.id, 'payment_method_line_id': cash.outbound_payment_method_line_ids[0].id,
                'amount': amount, 'payment_date': '2026-09-20'})
        payment = wizard._create_payments()
        passed(bool(payment) and all(item.move_id.state == 'posted' for item in payment), 'native edge-case payment posted')
        return payment

    def entry(lines):
        m = moves.create({'date': '2026-09-20', 'journal_id': general.id,
            'ref': 'QA rollback-only edge case',
            'line_ids': [Command.create({'name': 'QA transfer', 'account_id': account.id,
                'debit': debit, 'credit': credit}) for account, debit, credit in lines]})
        m.action_post()
        return m

    base = render()
    money(base['totals']['displayed_net_movement'], -271, 'committed showcase unchanged initially')
    for journal, expected in [(cash, 115), (bank, 230), (card, 115)]:
        ident = 'receipts/journal-%s' % journal.id
        row = next(line for line in base['lines'] if line['id'] == ident)
        money(row['columns'][0]['value'], expected, 'distinct receipt channel ' + journal.name)

    with rollback_case():
        items = [product('QA cent category %s' % index) for index in range(4)]
        bill = invoice([(item, 0.01, False) for item, _category in items])
        money(bill.amount_total, 0.04, 'four equal cent lines total')
        pay(bill, 0.02)
        payload = render()
        allocations = [category_amount(payload, category) for _item, category in items]
        for index, value in enumerate(allocations):
            passed(Decimal('-0.01') <= value <= Decimal('0.00'), 'cent category %s keeps payment sign and line bound' % index)
        money(sum(allocations), -0.02, 'all four category cents preserve payment')
        money(payload['totals']['payments'], decimal(base['totals']['payments']) - Decimal('0.02'), 'cent payment total')
        money(payload['totals']['balance_check'], 0, 'cent categories reconcile ledger')

    with rollback_case():
        charge, charge_category = product('QA charge with VAT')
        discount, discount_category = product('QA signed discount with VAT')
        bill = invoice([(charge, 200, True), (discount, -100, True)])
        money(bill.amount_total, 115, 'signed discount invoice native gross')
        pay(bill, 57.5)
        gross, net = render(), render(False)
        money(category_amount(gross, charge_category), -115, 'signed charge proportional gross')
        money(category_amount(gross, discount_category), 57.5, 'signed discount reduces expense')
        money(category_amount(net, charge_category), -100, 'signed charge excludes actual VAT')
        money(category_amount(net, discount_category), 50, 'signed discount VAT reduction')
        money(gross['totals']['balance_check'], 0, 'discount allocation cash reconciliation')

    with rollback_case():
        charge, charge_category = product('QA zero-net charge with VAT')
        discount, discount_category = product('QA zero-net untaxed discount')
        bill = invoice([(charge, 100, True), (discount, -100, False)])
        money(bill.amount_total, 15, 'zero-net invoice still has evidenced VAT')
        pay(bill, 15)
        net = render(False)
        money(category_amount(net, charge_category), -100, 'zero-net invoice retains charge category')
        money(category_amount(net, discount_category), 100, 'zero-net invoice retains offset category')
        money(net['totals']['displayed_net_movement'], -277, 'zero-net invoice category amounts offset')
        money(net['totals']['balance_check'], 0, 'zero-net invoice still reconciles actual cash')

    with rollback_case():
        clearing = accounts.create({'code': 'QAT999', 'name': 'QA transfer clearing',
            'account_type': 'asset_current', 'company_ids': [Command.set(c.ids)], 'reconcile': True})
        outgoing = entry([(clearing, 30, 0), (cash.default_account_id, 0, 30)])
        unpaired = render()
        money(unpaired['totals']['payments'], decimal(base['totals']['payments']) - Decimal('30'), 'unpaired transfer remains visible')
        money(unpaired['totals']['actual_net_movement'], -301, 'unpaired transfer decreases cash')
        money(unpaired['totals']['balance_check'], 0, 'unpaired transfer remains reconciled')
        incoming = entry([(bank.default_account_id, 30, 0), (clearing, 0, 30)])
        (outgoing.line_ids + incoming.line_ids).filtered(lambda row: row.account_id == clearing).reconcile()
        paired = render()
        money(paired['totals']['receipts'], base['totals']['receipts'], 'paired clearing transfer excluded from receipts')
        money(paired['totals']['payments'], base['totals']['payments'], 'paired clearing transfer excluded from payments')
        money(paired['totals']['actual_net_movement'], -271, 'paired clearing transfer has zero net cash')
        money(paired['totals']['balance_check'], 0, 'paired transfer reconciles')

    for label, override in [
        ('unposted draft option', {'posted_only': False}),
        ('unsupported journal slicing', {'journal_ids': cash.ids}),
        ('unsupported account type slicing', {'account_type_ids': ['expense']}),
        ('unsupported analytic slicing', {'analytic_account_ids': [999999]}),
        ('unsupported comparison', {'comparison': 'previous_period'}),
        ('invalid tax toggle', {'baseer_include_tax': 'false'}),
        ('unsupported multi-company view', {'company_ids': [9, 6]}),
        ('unsupported foreign presentation currency', {'presentation_currency_id': env.ref('base.USD').id}),
    ]:
        try:
            with env.cr.savepoint():
                report.render(dict(options, **override), use_cache=False)
        except UserError:
            checks.append({'check': label + ' rejected', 'passed': True})
        else:
            raise AssertionError(label + ' was silently accepted')

    with rollback_case():
        unauthorized = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'QA No Report Role', 'login': 'qa_edges_no_report_role',
            'company_id': c.id, 'company_ids': [Command.set(c.ids)],
            'group_ids': [Command.set([env.ref('base.group_user').id])],
        })
        try:
            with env.cr.savepoint():
                report.with_user(unauthorized).render(options, use_cache=False)
        except AccessError:
            checks.append({'check': 'internal user without report role denied', 'passed': True})
        else:
            raise AssertionError('Unprivileged internal user read financial report')

    with rollback_case():
        # No ledger write: native category change must still refresh its label.
        water_category = scoped['product.category'].search([('name', '=', 'مياه')], limit=1)
        cached = render(use_cache=True)
        passed(any(line['name'] == water_category.name for line in cached['lines']), 'cache baseline category label visible')
        changed_label = 'مياه QA تغيير اسم للاختبار فقط'
        water_category.name = changed_label
        fresh = render(use_cache=True)
        passed(any(line['name'] == changed_label for line in fresh['lines']), 'category rename visible without ledger edit')
        money(fresh['totals']['displayed_net_movement'], -271, 'renaming category does not change cash')
        money(render(False, use_cache=True)['totals']['displayed_net_movement'], -277, 'cached tax toggle uses distinct amounts')

    final = render()
    money(final['totals']['displayed_net_movement'], -271, 'all edge cases rolled back cleanly')
    money(final['totals']['closing_cash_balance'], 729, 'showcase closing cash preserved')
    env.cr.rollback()
    Path('/mnt/qa-evidence/cash_categories_edge_checks.json').write_text(
        json.dumps({'company_id': 9, 'synthetic_ledger_company_config_changes_committed': False,
            'audit_retention_note': 'Vendor durable failure audit may remain in the QA database through independent transactions.',
            'checks': checks}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('CASH_CATEGORIES_EDGES_SUCCESS', len(checks), 'checks; synthetic ledger/company/config changes rolled back; durable failure audit may remain in QA')
except Exception:
    env.cr.rollback()
    raise
