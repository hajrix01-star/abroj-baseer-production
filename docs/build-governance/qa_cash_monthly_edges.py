"""Independent BASEER-CASH-3 boundary/provenance tests in QA only.

Synthetic ledger changes always roll back. Vendor durable failure audits may
remain in QA. Limit patches live only in this shell process and are restored.
"""
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
c = env['res.company'].browse(9).exists()
assert c and c.name == 'QA الفئات النقدية'
scoped = env(context=dict(env.context, allowed_company_ids=c.ids,
                         tracking_disable=True, lang='en_US'))
report = scoped['eh.account.dynamic.report'].search([('code', '=', 'baseer_cash_categories')], limit=1)
handler = scoped['eh.account.dynamic.report.handler.baseer_cash_categories']
assert report
checks = []
output = Path('/mnt/qa-evidence/cash_monthly_edge_checks.json')
options = {'date': {'mode': 'range', 'date_from': '2026-01-01', 'date_to': '2026-03-31'},
           'company_ids': c.ids, 'posted_only': True, 'baseer_include_tax': True,
           'baseer_months': ['2026-01', '2026-03']}


def check(ok, name, **evidence):
    assert ok, (name, evidence)
    checks.append({'check': name, 'passed': True, **evidence})


def money(actual, expected, name):
    actual, expected = Decimal(str(actual)), Decimal(str(expected))
    check(actual == expected, name, actual=str(actual), expected=str(expected))


def rejected(callback, name, errors=(UserError, AccessError)):
    try:
        with env.cr.savepoint():
            callback()
    except errors as error:
        check(True, name, exception=type(error).__name__, message=str(error))
    else:
        raise AssertionError(name + ': silently accepted')


def render(**changes):
    return report.render(dict(options, **changes), use_cache=False)


def cell(payload, ident, expression):
    row = next(row for row in payload['lines'] if row['id'] == ident)
    return next(cell for cell in row['columns'] if cell['expression_label'] == expression)


def source_moves(action):
    model = scoped[action['res_model']]
    records = model.browse(action['res_id']).exists() if action.get('res_id') else model.search(action['domain'])
    check(all(record.company_id == c for record in records), 'source action stays in fixture company')
    return records if records._name == 'account.move' else records.move_id


try:
    # Validate public input independently of fixture creation.
    bad_months = [[], ['2026-13'], ['0000-01'], ['2026-1'], [202601],
                  ['2026-01', '2026-01'], ['2024-01', '2026-01'],
                  ['2025-%02d' % month for month in range(1, 13)] + ['2026-01']]
    for months in bad_months:
        rejected(lambda months=months: render(baseer_months=months),
                 'invalid months rejected: ' + repr(months))
    boundary = render(baseer_months=['2024-04', '2026-03'])
    check(boundary['meta']['baseer_months'] == ['2024-04', '2026-03'], 'inclusive 24-month span accepted')
    leap = render(baseer_months=['2028-02'])
    check(leap['columns'][1]['scope']['date_to'] == '2028-02-29', 'leap February ends on 29')
    ordinary = render(baseer_months=['2026-02'])
    check(ordinary['columns'][1]['scope']['date_to'] == '2026-02-28', 'ordinary February ends on 28')

    restricted = env['res.users'].search([('login', '=', 'qa_cash_categories_restricted')], limit=1)
    assert restricted and 9 in restricted.company_ids.ids and 6 not in restricted.company_ids.ids
    limited = report.with_user(restricted).with_context(allowed_company_ids=c.ids)
    check(bool(limited.render(options, use_cache=False)['columns']), 'restricted authorized-company baseline works')
    rejected(lambda: limited.render(dict(options, company_ids=[6]), use_cache=False),
             'single unauthorized company render denied', (AccessError,))
    rejected(lambda: limited.get_drilldown_for_line(dict(options, company_ids=[6]), 'payments'),
             'single unauthorized company source denied', (AccessError,))

    # An authorized report selection may differ from the Odoo header company.
    # Use a real nonsuperuser administrator so this cannot pass via sudo mode.
    admin = env.ref('base.user_admin')
    assert 6 in admin.company_ids.ids and 9 in admin.company_ids.ids
    alternate = report.with_user(admin).with_context(allowed_company_ids=[9])
    assert not alternate.env.su
    alternate_options = dict(options, baseer_months=['2026-09'], company_ids=[6])
    switched = alternate.render(alternate_options, use_cache=False)
    check(switched['meta']['company_ids'] == [6], 'authorized report company6 overrides header company9')
    company6_env = env(user=admin.id, context=dict(env.context, allowed_company_ids=[6]))
    cash_lines6 = company6_env['account.move.line'].search([
        ('company_id', '=', 6), ('parent_state', '=', 'posted'),
        ('account_id.account_type', '=', 'asset_cash'),
        ('date', '>=', '2026-09-01'), ('date', '<=', '2026-09-30')])
    actual_cash6 = sum((Decimal(str(line.balance)) for line in cash_lines6), Decimal('0'))
    money(switched['totals']['actual_net_movement'], actual_cash6,
          'switched-company amount equals its independent posted cash ledger')
    switched_action = alternate.get_drilldown_for_line(
        dict(alternate_options, baseer_drill_column='month_2026_09'),
        'baseer-total-actual_net_movement')
    check(switched_action['context']['allowed_company_ids'] == [6], 'switched source action uses company6')
    source_model6 = company6_env[switched_action['res_model']]
    source6 = (source_model6.browse(switched_action['res_id']).exists() if switched_action.get('res_id')
               else source_model6.search(switched_action['domain']))
    check(source6._name == 'account.move.line' and set(source6.ids) == set(cash_lines6.ids),
          'switched source action contains exactly company6 posted cash items')
    check(alternate.env.companies.ids == [9], 'report selection does not mutate header environment')

    journals = scoped['account.journal'].with_company(c)
    cash = journals.search([('company_id', '=', c.id), ('type', '=', 'cash')], limit=1)
    partner = scoped['res.partner'].search([('company_id', '=', c.id), ('name', '=', 'طرف تجريبي للفئات')], limit=1)
    accounts = scoped['account.account'].with_company(c)
    income = accounts.search([('company_ids', 'in', c.ids), ('account_type', '=', 'income')], limit=1)
    expense = accounts.search([('company_ids', 'in', c.ids), ('account_type', '=', 'expense')], limit=1)
    moves = scoped['account.move'].with_company(c)
    assert cash and partner and income and expense
    existing_future = moves.search_count([('company_id', '=', c.id), ('state', '=', 'posted'),
                                         ('date', '>=', '2026-01-01'), ('date', '<=', '2026-03-31')])
    assert not existing_future, 'Expected clean synthetic future interval'

    def invoice(kind, amount, day):
        account = income if kind == 'out_invoice' else expense
        record = moves.create({'move_type': kind, 'partner_id': partner.id,
            'invoice_date': day, 'date': day,
            'invoice_line_ids': [Command.create({'name': 'QA monthly independent source',
                'quantity': 1, 'price_unit': amount, 'account_id': account.id,
                'tax_ids': [Command.clear()]})]})
        record.action_post()
        return record

    def pay(record, amount, day):
        methods = cash.inbound_payment_method_line_ids if record.move_type == 'out_invoice' else cash.outbound_payment_method_line_ids
        wizard = scoped['account.payment.register'].with_company(c).with_context(
            active_model='account.move', active_ids=record.ids).create({
                'journal_id': cash.id, 'payment_method_line_id': methods[0].id,
                'amount': amount, 'payment_date': day})
        result = wizard._create_payments()
        check(bool(result) and all(payment.move_id.state == 'posted' for payment in result),
              'independent native payment posted ' + day)
        return result.move_id

    sales, bills, receipts, payments = {}, {}, {}, {}
    for month, sale, purchase, paid in [('01', 100, 40, 20), ('02', 999, 1554, 777), ('03', 300, 360, 180)]:
        day = '2026-%s-15' % month
        sales[month] = invoice('out_invoice', sale, day)
        bills[month] = invoice('in_invoice', purchase, day)
        receipts[month] = pay(sales[month], sale, day)
        payments[month] = pay(bills[month], paid, day)
        money(bills[month].amount_residual, paid, 'partial bill retains half unpaid ' + month)

    payload = render(baseer_months=['2026-03', '2026-01'])
    check(payload['meta']['baseer_months'] == ['2026-01', '2026-03'], 'unsorted input canonical order')
    for month, incoming, outgoing in [('01', 100, -20), ('03', 300, -180)]:
        expression = 'month_2026_' + month
        money(cell(payload, 'receipts', expression)['value'], incoming, 'noncontiguous month receipts ' + month)
        money(cell(payload, 'payments', expression)['value'], outgoing, 'noncontiguous month payments ' + month)
        action = report.get_drilldown_for_line(dict(options, baseer_drill_column=expression), 'payments')
        actual_sources = source_moves(action)
        check(set(actual_sources.ids) == set(bills[month].ids), 'monthly outgoing original bill provenance ' + month,
              actual=actual_sources.ids, expected=bills[month].ids, model=action['res_model'])
    money(payload['totals']['receipts'], 400, 'skipped February 999 excluded from receipts')
    money(payload['totals']['payments'], -200, 'skipped February 777 excluded from payments')
    money(payload['totals']['sales_collections'], 400, 'skipped February excluded from sales denominator')
    money(cell(payload, 'payments', 'receipt_share')['value'], 50, 'ratio of sums is50, not average40')
    money(payload['totals']['actual_net_movement'], 200, 'selected movement excludes gap')
    check(cell(payload, 'baseer-total-opening_cash_balance', 'amount')['value'] is None,
          'opening snapshots never summed across gap')
    check(cell(payload, 'baseer-total-closing_cash_balance', 'amount')['value'] is None,
          'closing snapshots never summed across gap')
    for expression in ('amount', 'receipt_share'):
        action = report.get_drilldown_for_line(dict(options, baseer_drill_column=expression), 'payments')
        check(set(source_moves(action).ids) == set((bills['01'] + bills['03']).ids),
              'total/percentage provenance union excludes February ' + expression)
    for expression in ('month_2026_02', 'month_2026_13', 'month_2026_01__forged', '__proto__', 1):
        rejected(lambda expression=expression: report.get_drilldown_for_line(
            dict(options, baseer_drill_column=expression), 'payments'), 'forged column rejected ' + repr(expression))

    # Lower limits in the shell process to exercise real guards without creating
    # thousands of records or loading the shared PostgreSQL server.
    with patch.object(type(handler), '_BASEER_AGGREGATE_LIMIT', 1):
        rejected(lambda: render(), 'aggregate read budget raises, never truncates')
    with patch.object(type(handler), '_BASEER_ROW_LIMIT', 1):
        rejected(lambda: render(), 'canonical row budget raises, never truncates')
    check(handler._BASEER_AGGREGATE_LIMIT == 30000 and handler._BASEER_ROW_LIMIT == 1000,
          'temporary capacity limits restored')
    money(render()['totals']['receipts'], 400, 'normal rendering resumes after guard probes')

finally:
    env.cr.rollback()

check(not scoped['account.move'].search_count([('company_id', '=', c.id),
      ('date', '>=', '2026-01-01'), ('date', '<=', '2026-03-31'),
      ('invoice_line_ids.name', '=', 'QA monthly independent source')]),
      'synthetic independent monthly invoices rolled back')
output.write_text(json.dumps({'checks': checks, 'scope': 'QA only',
    'ledger_configuration_changes_rolled_back': True,
    'audit_note': 'Vendor durable failure audits may remain in QA.'}, ensure_ascii=False, indent=2), encoding='utf-8')
print('MONTHLY_INDEPENDENT_EDGES_SUCCESS', len(checks), 'checks; synthetic ledger rolled back')
