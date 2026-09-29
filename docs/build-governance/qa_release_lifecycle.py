"""Reports R1 release rehearsal: native lifecycle in a disposable main clone.

Run through Odoo shell AFTER installation, never in baseer_dev or the old QA DB.
All synthetic ledger/configuration/user writes are rolled back. Native report
execution audits may be retained by the vendor's independent audit corridor.
This script opens no second database and cannot attest to a separate main DB;
the parent release process owns the independent main fingerprint comparison.
"""
import json
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from odoo import Command
from odoo.exceptions import AccessError


DATABASE = 'baseer_release_rehearsal_20260907'
assert env.cr.dbname == DATABASE, 'STOP: release rehearsal clone required'
ARTIFACT = Path('/mnt/qa-evidence/release_lifecycle_checks.json')
PREFIX = 'R1 lifecycle synthetic'
checks, company_results, created_move_ids = [], [], []
started = perf_counter()


def passed(condition, label, **evidence):
    assert condition, (label, evidence)
    checks.append({'check': label, 'passed': True, **evidence})


def decimal(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))


def money(actual, expected, label):
    actual, expected = decimal(actual), decimal(expected)
    passed(actual == expected, label, actual=str(actual), expected=str(expected))


def fingerprint():
    return {model: env[model].search_count([]) for model in [
        'res.company', 'res.users', 'res.partner', 'account.account',
        'account.journal', 'account.move', 'account.move.line', 'account.payment',
        'account.partial.reconcile', 'product.category', 'product.template',
    ]}


baseline_fingerprint = fingerprint()
passed(not env['account.move'].search_count([('ref', 'ilike', PREFIX)]),
       'Clone starts without this synthetic fixture')
admin = env.ref('base.user_admin')
companies = env['res.company'].browse([1, 2, 3]).exists()
passed(sorted(companies.ids) == [1, 2, 3], 'All three source companies exist', companies=companies.ids)
passed(set(companies.ids).issubset(set(admin.company_ids.ids)),
       'Source administrator already has the three companies')
passed(admin.has_group('eh_account_base.group_eh_user'),
       'Installed dependency grants source administrator report access')

FIXTURE_CONTEXT = {
    'tracking_disable': True, 'mail_create_nolog': True, 'mail_notrack': True,
    'no_reset_password': True,
}


def company_env(company):
    return env(user=admin.id, context=dict(env.context, **FIXTURE_CONTEXT,
                                         allowed_company_ids=company.ids))


def report_options(company, month='09', include_tax=True):
    end = '30'
    return {
        'company_ids': company.ids, 'posted_only': True, 'baseer_include_tax': include_tax,
        'date': {'mode': 'range', 'date_from': '2026-%s-01' % month,
                 'date_to': '2026-%s-%s' % (month, end)},
    }


def snapshots(company, month='09'):
    local = company_env(company)
    passed(not local.su, '%s: report computation uses non-sudo source admin' % company.id)
    registry = local['eh.account.dynamic.report']
    options = report_options(company, month)
    cash = registry.get_by_code('baseer_cash_categories')
    pnl = registry.get_by_code('profit_and_loss')
    return {
        'gross': cash.render(options, use_cache=False),
        'net': cash.render(dict(options, baseer_include_tax=False), use_cache=False),
        'pnl': pnl.render(options, use_cache=False),
    }


def delta(result, before, report, key):
    return decimal(result[report]['totals'][key]) - decimal(before[report]['totals'][key])


def balanced(moves, label):
    for move in moves:
        passed(move.state == 'posted', label + ': posted', move_id=move.id)
        money(sum((decimal(line.balance) for line in move.line_ids), Decimal('0.00')),
              0, label + ': balanced journal entry %s' % move.id)


def expect_denied(call, label):
    try:
        with env.cr.savepoint():
            call()
    except AccessError:
        passed(True, label)
    else:
        raise AssertionError(label + ': access was allowed')


status, failure = 'failed', None
rollback_verified = False
try:
    before_all = {company.id: snapshots(company) for company in companies}
    before_monthly_sales = {
        company.id: company_env(company)['eh.account.dynamic.report'].get_by_code('baseer_cash_categories').render(
            dict(report_options(company), baseer_months=['2026-09', '2026-11']), use_cache=False
        )['totals']['sales_collections'] for company in companies
    }
    fixtures = {}
    for company in companies:
        factor = company.id
        local = company_env(company)
        accounts = local['account.account']

        def account(kind):
            result = accounts.search([('company_ids', 'in', company.ids), ('account_type', '=', kind)], limit=1)
            passed(bool(result), '%s: native %s account exists' % (company.id, kind))
            return result

        payable, receivable, expense = account('liability_payable'), account('asset_receivable'), account('expense')
        purchase_tax = local.ref('account.%s_sa_purchase_tax_15' % company.id)
        money(purchase_tax.amount, 15, '%s: native Saudi purchase tax' % company.id)
        cash = local['account.journal'].create({
            'name': '%s cash %s' % (PREFIX, company.id), 'code': 'R1C',
            'type': 'cash', 'company_id': company.id,
        })
        passed(bool(cash.default_account_id), '%s: native journal created its cash account' % company.id)
        for method in cash.inbound_payment_method_line_ids + cash.outbound_payment_method_line_ids:
            method.payment_account_id = cash.default_account_id
        partner = local['res.partner'].create({
            'name': '%s supplier %s' % (PREFIX, company.id), 'company_id': company.id,
            'property_account_payable_id': payable.id, 'property_account_receivable_id': receivable.id,
        })
        category = local['product.category'].create({'name': '%s category %s' % (PREFIX, company.id)})
        product = local['product.product'].create({
            'name': '%s service %s' % (PREFIX, company.id), 'type': 'service',
            'company_id': company.id, 'categ_id': category.id,
            'property_account_expense_id': expense.id,
            'supplier_taxes_id': [Command.set(purchase_tax.ids)],
        })

        def invoice(amount, invoice_date='2026-09-03', due_date=False):
            values = {
                'move_type': 'in_invoice', 'company_id': company.id, 'partner_id': partner.id,
                'ref': PREFIX, 'invoice_date': invoice_date, 'date': invoice_date,
                'invoice_line_ids': [Command.create({
                    'product_id': product.id, 'name': PREFIX, 'quantity': 1,
                    'price_unit': amount, 'account_id': expense.id,
                    'tax_ids': [Command.set(purchase_tax.ids)],
                })],
            }
            if due_date:
                values['invoice_date_due'] = due_date
            move = local['account.move'].create(values)
            version_before = company.eh_move_version
            move.action_post()
            company.invalidate_recordset(['eh_move_version'])
            passed(company.eh_move_version > version_before,
                   '%s: posting invalidates report input version' % company.id,
                   before=version_before, after=company.eh_move_version)
            created_move_ids.append(move.id)
            balanced(move, '%s: supplier invoice' % company.id)
            return move

        def pay(move, amount, payment_date='2026-09-10', journal=None):
            journal = journal or cash
            inbound = move.move_type == 'in_refund'
            methods = journal.inbound_payment_method_line_ids if inbound else journal.outbound_payment_method_line_ids
            passed(bool(methods), '%s: native payment method available' % company.id)
            wizard = local['account.payment.register'].with_context(
                active_model='account.move', active_ids=move.ids).create({
                    'journal_id': journal.id, 'payment_method_line_id': methods[0].id,
                    'amount': amount, 'payment_date': payment_date,
                })
            payments = wizard._create_payments()
            passed(bool(payments), '%s: native payment wizard created payment' % company.id)
            created_move_ids.extend(payments.move_id.ids)
            balanced(payments.move_id, '%s: payment' % company.id)
            return payments

        before = before_all[company.id]
        bill = invoice(100 * factor)
        money(bill.amount_total, 115 * factor, '%s: supplier invoice includes VAT' % company.id)
        unpaid = snapshots(company)
        money(delta(unpaid, before, 'gross', 'actual_net_movement'), 0,
              '%s: posted unpaid bill does not change cash' % company.id)
        money(delta(unpaid, before, 'pnl', 'net_profit'), -100 * factor,
              '%s: posted unpaid bill accrues expense excluding VAT' % company.id)

        partial = pay(bill, 46 * factor)
        money(bill.amount_residual, 69 * factor, '%s: partial payment leaves native residual' % company.id)
        matched = bill.line_ids.filtered(lambda line: line.account_id == payable)
        passed(bool(matched.matched_debit_ids | matched.matched_credit_ids),
               '%s: native partial reconciliation exists' % company.id)
        result = snapshots(company)
        money(delta(result, before, 'gross', 'payments'), -46 * factor, '%s: partial gross cash' % company.id)
        money(delta(result, before, 'net', 'payments'), -40 * factor, '%s: partial net cash' % company.id)

        remaining = pay(bill, 69 * factor, '2026-09-12')
        money(bill.amount_residual, 0, '%s: final payment clears native residual' % company.id)
        passed(all(line.reconciled for line in matched), '%s: payable lines fully reconciled' % company.id)
        result = snapshots(company)
        money(delta(result, before, 'gross', 'payments'), -115 * factor, '%s: full gross payment counted once' % company.id)
        money(delta(result, before, 'net', 'payments'), -100 * factor, '%s: full net payment' % company.id)

        reversal = local['account.move.reversal'].with_context(
            active_model='account.move', active_ids=bill.ids).create({
                'reason': PREFIX + ' partial supplier credit', 'date': '2026-09-15',
                'journal_id': bill.journal_id.id,
            })
        reversal.reverse_moves(is_modify=False)
        credit = reversal.new_move_ids
        passed(len(credit) == 1 and credit.state == 'draft' and credit.move_type == 'in_refund',
               '%s: native reversal creates draft supplier credit' % company.id)
        credit.invoice_line_ids.filtered(lambda line: line.display_type == 'product').write({'price_unit': 20 * factor})
        # Native reversal schedules future-dated credits automatically. This
        # synthetic scenario intentionally posts now to exercise the full cycle.
        credit.auto_post = 'no'
        credit.action_post()
        created_move_ids.append(credit.id)
        balanced(credit, '%s: supplier credit' % company.id)
        money(credit.amount_total, 23 * factor, '%s: supplier credit VAT' % company.id)
        refund = pay(credit, 23 * factor, '2026-09-16')
        money(credit.amount_residual, 0, '%s: actual supplier refund settles credit' % company.id)
        result = snapshots(company)
        money(delta(result, before, 'gross', 'receipts'), 23 * factor, '%s: supplier refund is actual cash in' % company.id)
        money(delta(result, before, 'gross', 'actual_net_movement'), -92 * factor, '%s: cash after supplier refund' % company.id)
        money(delta(result, before, 'net', 'displayed_net_movement'), -80 * factor, '%s: net tax basis after refund' % company.id)
        money(delta(result, before, 'pnl', 'net_profit'), -80 * factor, '%s: supplier credit reverses accrual expense' % company.id)

        late_before_november = snapshots(company, '11')
        late_bill = invoice(200 * factor, due_date='2026-11-03')
        late_unpaid = snapshots(company)
        money(delta(late_unpaid, result, 'gross', 'actual_net_movement'), 0,
              '%s: two-month credit purchase has no September cash' % company.id)
        money(delta(late_unpaid, before, 'pnl', 'net_profit'), -280 * factor,
              '%s: deferred payment does not defer expense recognition' % company.id)
        late_payment = pay(late_bill, 230 * factor, '2026-11-03')
        money(late_bill.amount_residual, 0, '%s: November settlement clears credit purchase' % company.id)
        november = snapshots(company, '11')
        money(delta(november, late_before_november, 'gross', 'payments'), -230 * factor,
              '%s: deferred payment appears in November gross cash' % company.id)
        money(delta(november, late_before_november, 'net', 'payments'), -200 * factor,
              '%s: deferred payment appears in November net cash' % company.id)
        september = snapshots(company)
        money(delta(september, before, 'gross', 'actual_net_movement'), -92 * factor,
              '%s: paying in November does not rewrite September cash' % company.id)
        for label, snapshot in [('September', september), ('November', november)]:
            for mode in ('gross', 'net'):
                money(snapshot[mode]['totals']['balance_check'], 0,
                      '%s %s %s: cash reconciles' % (company.id, label, mode))
        month_options = dict(report_options(company), baseer_months=['2026-09', '2026-11'])
        monthly = local['eh.account.dynamic.report'].get_by_code('baseer_cash_categories').render(month_options, use_cache=False)
        money(monthly['totals']['sales_collections'], before_monthly_sales[company.id],
              '%s: supplier refunds are excluded from collected sales denominator' % company.id)
        passed(monthly['totals']['opening_cash_balance'] is None and monthly['totals']['closing_cash_balance'] is None,
               '%s: disjoint month balances are not summed' % company.id)
        fixtures[company.id] = {'local': local, 'company': company, 'cash': cash, 'payable': payable,
                                'partner': partner, 'product': product, 'tax': purchase_tax,
                                'expense': expense, 'bill': bill, 'credit': credit,
                                'late_bill': late_bill, 'september': september}
        company_results.append({'company_id': company.id, 'company_name': company.name,
                                'bill_id': bill.id, 'credit_id': credit.id, 'deferred_bill_id': late_bill.id,
                                'september_totals': september['gross']['totals'],
                                'november_totals': november['gross']['totals']})

    # Native outstanding-payment -> bank settlement -> reconciliation corridor.
    fixture = fixtures[1]
    company, local = fixture['company'], fixture['local']
    outstanding = local['account.account'].create({
        'name': PREFIX + ' outstanding payments', 'code': 'R1OUT', 'account_type': 'asset_current',
        'reconcile': True, 'company_ids': [Command.set(company.ids)],
    })
    bank = local['account.journal'].create({'name': PREFIX + ' bank', 'code': 'R1B',
                                           'type': 'bank', 'company_id': company.id})
    method = bank.outbound_payment_method_line_ids[:1]
    passed(bool(method), 'Outstanding corridor has a native outbound method')
    method.payment_account_id = outstanding
    before = snapshots(company)
    bill = local['account.move'].create({
        'move_type': 'in_invoice', 'company_id': 1, 'partner_id': fixture['partner'].id,
        'ref': PREFIX, 'date': '2026-09-20', 'invoice_date': '2026-09-20',
        'invoice_line_ids': [Command.create({'product_id': fixture['product'].id, 'name': PREFIX,
            'quantity': 1, 'price_unit': 50, 'account_id': fixture['expense'].id,
            'tax_ids': [Command.set(fixture['tax'].ids)]})],
    })
    bill.action_post()
    wizard = local['account.payment.register'].with_context(active_model='account.move', active_ids=bill.ids).create({
        'journal_id': bank.id, 'payment_method_line_id': method.id, 'amount': 57.5, 'payment_date': '2026-09-21',
    })
    payment = wizard._create_payments()
    balanced(payment.move_id, 'Outstanding payment')
    registered = snapshots(company)
    money(delta(registered, before, 'gross', 'actual_net_movement'), 0,
          'Registered outstanding payment is not yet a cash movement')
    settlement = local['account.move'].create({
        'date': '2026-09-22', 'journal_id': bank.id, 'ref': PREFIX + ' settlement',
        'line_ids': [Command.create({'name': PREFIX, 'account_id': outstanding.id,
                                   'partner_id': fixture['partner'].id, 'debit': 57.5}),
                     Command.create({'name': PREFIX, 'account_id': bank.default_account_id.id,
                                     'partner_id': fixture['partner'].id, 'credit': 57.5})],
    })
    settlement.action_post()
    (settlement.line_ids + payment.move_id.line_ids).filtered(lambda line: line.account_id == outstanding).reconcile()
    created_move_ids.extend((bill + payment.move_id + settlement).ids)
    balanced(bill + settlement, 'Outstanding invoice and bank settlement')
    settled = snapshots(company)
    money(delta(settled, before, 'gross', 'payments'), -57.5, 'Bank settlement is recognized exactly once')
    money(delta(settled, before, 'net', 'payments'), -50, 'Bank settlement traces actual invoice VAT')

    for company in companies:
        current = snapshots(company)
        expected = -92 * company.id - (Decimal('57.50') if company.id == 1 else 0)
        money(delta(current, before_all[company.id], 'gross', 'actual_net_movement'), expected,
              '%s: other companies do not leak into this ledger' % company.id)

    restricted = env['res.users'].with_context(**FIXTURE_CONTEXT).create({
        'name': PREFIX + ' restricted', 'login': 'r1_release_rehearsal_restricted',
        'company_id': 1, 'company_ids': [Command.set([1])],
        'group_ids': [Command.set([env.ref('base.group_user').id, env.ref('eh_account_base.group_eh_user').id])],
    })
    restricted_report = env['eh.account.dynamic.report'].with_user(restricted).with_context(allowed_company_ids=[1]).get_by_code('baseer_cash_categories')
    passed(not restricted_report.env.su, 'Restricted report tests run without sudo')
    own_options = dict(report_options(env['res.company'].browse(1)), baseer_months=['2026-09'])
    own = restricted_report.render(own_options, use_cache=False)
    money(own['totals']['actual_net_movement'], settled['gross']['totals']['actual_net_movement'],
          'Restricted user sees only authorized company totals')
    for forbidden in (2, 3):
        forbidden_options = dict(own_options, company_ids=[forbidden])
        expect_denied(lambda: restricted_report.render(forbidden_options, use_cache=False),
                      'Restricted user cannot render company %s' % forbidden)
        expect_denied(lambda: restricted_report.get_drilldown_for_line(forbidden_options, 'payments'),
                      'Restricted user cannot open sources from company %s' % forbidden)
    foreign_bill = fixtures[2]['bill'].with_user(restricted).with_context(allowed_company_ids=[1])
    expect_denied(lambda: foreign_bill.read(['name', 'amount_total']),
                  'Native invoice record rules reject direct access to another company')
    own_action = restricted_report.get_drilldown_for_line(dict(own_options, baseer_drill_column='month_2026_09'), 'payments')
    passed(own_action['res_model'] == 'account.move' and own_action['context']['allowed_company_ids'] == [1],
           'Authorized source action opens original documents in the same company')
    source_ids = own_action['domain'][0][2]
    source_moves = env['account.move'].with_user(restricted).with_context(allowed_company_ids=[1]).browse(source_ids)
    source_moves.check_access('read')
    passed(all(move.company_id.id == 1 for move in source_moves), 'Source actions contain no foreign-company invoices')
    balanced(env['account.move'].browse(created_move_ids), 'Final synthetic ledger')
    status = 'passed'
except Exception as exc:
    failure = {'type': type(exc).__name__, 'message': str(exc)}
    raise
finally:
    env.cr.rollback()
    env.invalidate_all(flush=False)
    try:
        after = fingerprint()
        rollback_verified = after == baseline_fingerprint
        passed(rollback_verified, 'All synthetic business/configuration/user records rolled back',
               before=baseline_fingerprint, after=after)
        passed(not env['account.move'].search_count([('ref', 'ilike', PREFIX)]),
               'No synthetic ledger documents survive the rehearsal')
        passed(not env['res.users'].search_count([('login', '=', 'r1_release_rehearsal_restricted')]),
               'No synthetic restricted user survives the rehearsal')
    except Exception as exc:
        status = 'failed'
        failure = failure or {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps({
            'database': DATABASE, 'status': status, 'failure': failure,
            'checks': checks, 'companies': company_results, 'rollback_verified': rollback_verified,
            'elapsed_seconds': round(perf_counter() - started, 3),
            'main_database_accessed_by_this_script': False,
            'main_fingerprint_verified_here': False,
            'scope_note': 'Only the named rehearsal clone is used. Parent release checks main separately. Native report execution audits may persist in this disposable clone.',
        }, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print('RELEASE_LIFECYCLE_%s' % status.upper(), len(checks), 'checks;', 'rollback', rollback_verified)
