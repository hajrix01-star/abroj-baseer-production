"""Isolated HR-ledger privacy probes; native accounting fixtures roll back."""
import json
import traceback
from pathlib import Path
from decimal import Decimal
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.addons.baseer_payroll.models.common import INTERNAL

assert env.cr.dbname.startswith('baseer_ar1_') and env.su
OUT = Path('/mnt/qa-evidence/ar1-payroll-privacy-checks.json')
checks = []
result = {'status': 'FAIL', 'checks': checks, 'rollback': False,
          'scope': 'Isolated synthetic salary ledger/report privacy, no payroll or external transfers'}


def check(label, condition):
    assert condition, label
    checks.append(label)


def deny(label, call, exceptions=(AccessError,)):
    try:
        with env.cr.savepoint():
            call()
    except exceptions:
        checks.append(label)
    else:
        raise AssertionError(label + ': unexpectedly allowed')


def stamp():
    return {model: env[model].with_context(active_test=False).search_count([]) for model in (
        'res.users', 'res.partner', 'hr.employee', 'hr.payslip', 'account.move',
        'account.move.line', 'account.payment', 'account.partial.reconcile',
        'account.full.reconcile', 'account.analytic.line', 'account.analytic.account', 'baseer.hr.eos')}


def cents(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))


before = stamp()
try:
    company = env['res.company'].search([('currency_id.name', '=', 'SAR')]).filtered(
        lambda c: c.baseer_salary_expense_id and c.baseer_salary_payable_id and c.baseer_payroll_journal_id)[:1]
    assert company, 'Clone needs seeded payroll accounts'
    ctx = {'allowed_company_ids': company.ids, 'lang': 'en_US', 'tracking_disable': True}
    admin = env(context=ctx)
    users = {}
    for role in ('cashier', 'accountant'):
        user = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'AR1 PRIVACY ROLLBACK ' + role, 'login': 'ar1-privacy-rollback-' + role,
            'baseer_access_role': role, 'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        users[role] = env(user=user.id, su=False, context=ctx)
    accountant = users['accountant']
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_deduction_account_id | company.baseer_loan_account_id
    expense = admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', 'expense'), ('id', 'not in', private.ids)], limit=1)
    payable = admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', 'liability_payable'), ('id', 'not in', private.ids)], limit=1)
    purchase = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'purchase')], limit=1)
    journals = admin['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank']), ('active', '=', True)])
    treasury = journals.filtered(lambda j: j.default_account_id and j.default_account_id.account_type == 'asset_cash')[:1]
    method = treasury.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')[:1]
    assert expense and payable and purchase and treasury and method
    method.payment_account_id = treasury.default_account_id
    partner = admin['res.partner'].create({'name': 'AR1 PRIVACY ROLLBACK employee contact', 'company_id': company.id,
        'property_account_payable_id': company.baseer_salary_payable_id.id})
    employee = admin['hr.employee'].create({'name': 'AR1 PRIVACY ROLLBACK employee', 'company_id': company.id,
                                           'work_contact_id': partner.id})
    today = fields.Date.today()

    def invoice(actor, amount, account, contact=partner, **extra):
        values = {'move_type': 'in_invoice', 'company_id': company.id,
            'journal_id': purchase.id, 'partner_id': contact.id, 'invoice_date': today, 'date': today,
            'ref': 'AR1 PRIVACY ROLLBACK', 'invoice_line_ids': [Command.create({
                'name': 'Synthetic isolated expense', 'quantity': 1, 'price_unit': amount,
                'account_id': account.id, 'tax_ids': [Command.clear()]})]}
        values.update(extra)
        bill = actor['account.move'].create(values)
        bill.action_post()
        return bill

    salary_bill = invoice(admin, 1234.56, company.baseer_salary_expense_id)
    unpaid_salary = invoice(admin, 567.89, company.baseer_salary_expense_id)
    check('salary fixture has private payable and expense without HR document tag',
          not salary_bill.baseer_payslip_id and company.baseer_salary_payable_id in salary_bill.line_ids.account_id)
    wizard = admin['account.payment.register'].with_context(active_model='account.move', active_ids=salary_bill.ids).create({
        'journal_id': treasury.id, 'payment_method_line_id': method.id, 'amount': salary_bill.amount_total,
        'payment_date': today, 'installments_mode': 'full', 'payment_difference_handling': 'open'})
    private_payment = wizard._create_payments().sudo()
    check('native wizard payment is permanently classified private', len(private_payment) == 1 and private_payment.baseer_private_hr)
    check('native salary fixture actually settled', salary_bill.payment_state == 'paid' and cents(salary_bill.amount_residual) == 0)
    payment_move = private_payment.move_id
    check('untagged payment move mixes private payable and public liquidity',
          not payment_move.baseer_payslip_id and company.baseer_salary_payable_id in payment_move.line_ids.account_id and treasury.default_account_id in payment_move.line_ids.account_id)

    slip = admin['hr.payslip'].create({'name': 'AR1 PRIVACY ROLLBACK slip marker', 'employee_id': employee.id,
        'company_id': company.id, 'date_from': today, 'date_to': today,
        'struct_id': False, 'version_id': False, 'journal_id': company.baseer_payroll_journal_id.id,
        'payslip_run_id': False})
    tagged = admin['account.move'].with_context(baseer_payroll_internal=INTERNAL).create({
        'move_type': 'entry', 'date': today, 'journal_id': company.baseer_payroll_journal_id.id,
        'company_id': company.id, 'baseer_payslip_id': slip.id,
        'line_ids': [Command.create({'name': 'AR1 private tagged debit', 'account_id': expense.id, 'debit': 10}),
                     Command.create({'name': 'AR1 private tagged credit', 'account_id': payable.id, 'credit': 10})]})
    tagged.with_context(baseer_payroll_internal=INTERNAL).action_post()
    all_private_moves = salary_bill | unpaid_salary | payment_move | tagged
    for label, actor in users.items():
        for fixture_label, move in (('salary invoice', salary_bill), ('mixed salary payment', payment_move), ('tag-only payroll journal', tagged)):
            deny(label + ' direct ' + fixture_label + ' read denied', lambda actor=actor, move=move: actor['account.move'].browse(move.id).read(['name', 'amount_total']))
            check(label + ' ' + fixture_label + ' absent from search', not actor['account.move'].search([('id', '=', move.id)]))
            deny(label + ' BOTH sides of ' + fixture_label + ' line read denied', lambda actor=actor, move=move: actor['account.move.line'].browse(move.line_ids.ids).read(['debit', 'credit']))
            check(label + ' no line from ' + fixture_label + ' leaks via search', not actor['account.move.line'].search([('move_id', '=', move.id)]))
            check(label + ' no grouped amount from ' + fixture_label, not actor['account.move.line'].read_group([('move_id', '=', move.id)], ['balance:sum'], ['move_id']))
        deny(label + ' private salary payment read denied', lambda actor=actor: actor['account.payment'].browse(private_payment.id).read(['amount']))
        if actor['account.payment'].has_access('read'):
            check(label + ' salary payment absent from search', not actor['account.payment'].search([('id', '=', private_payment.id)]))

    # The report is an SQL view. Its separate rule must preserve move privacy.
    report_rows = admin['account.invoice.report'].search([('move_id', '=', salary_bill.id)])
    check('private invoice fixture exists in SQL reporting source', bool(report_rows))
    if accountant['account.invoice.report'].has_access('read'):
        check('accountant private invoice absent from reporting view', not accountant['account.invoice.report'].search([('move_id', '=', salary_bill.id)]))
        deny('accountant private invoice reporting row direct read denied', lambda: accountant['account.invoice.report'].browse(report_rows.ids).read(['price_total']))

    partials = admin['account.partial.reconcile'].search(['|', ('debit_move_id', 'in', all_private_moves.line_ids.ids), ('credit_move_id', 'in', all_private_moves.line_ids.ids)])
    fulls = salary_bill.line_ids.full_reconcile_id
    check('native privacy fixture has actual partial/full reconciliation', bool(partials) and bool(fulls))
    for model, records, value_fields in (('account.partial.reconcile', partials, ['amount']),
                                        ('account.full.reconcile', fulls, ['reconciled_line_ids'])):
        if accountant[model].has_access('read'):
            check('accountant private ' + model + ' search denied', not accountant[model].search([('id', 'in', records.ids)]))
            deny('accountant private ' + model + ' direct read denied', lambda model=model, records=records, value_fields=value_fields: accountant[model].browse(records.ids).read(value_fields))
        else:
            deny('accountant ' + model + ' denied by ACL', lambda model=model: accountant[model].check_access('read'))

    plan = admin['account.analytic.plan'].create({'name': 'AR1 PRIVACY ROLLBACK plan'})
    analytic_account = admin['account.analytic.account'].create({'name': 'AR1 PRIVACY ROLLBACK analytic', 'plan_id': plan.id, 'company_id': company.id})
    analytic = admin['account.analytic.line'].create({'name': 'AR1 PRIVACY ROLLBACK salary analytic', 'account_id': analytic_account.id,
        'company_id': company.id, 'amount': -10, 'unit_amount': 1, 'move_line_id': tagged.line_ids.filtered(lambda l: l.debit)[:1].id})
    if accountant['account.analytic.line'].has_access('read'):
        check('accountant private salary analytic absent from search', not accountant['account.analytic.line'].search([('id', '=', analytic.id)]))
        deny('accountant private salary analytic direct read denied', lambda: accountant['account.analytic.line'].browse(analytic.id).read(['amount']))

    # Ordinary invoices still work under the same user/rule graph.
    vendor = admin['res.partner'].create({'name': 'AR1 PRIVACY ROLLBACK ordinary vendor', 'company_id': company.id,
                                         'property_account_payable_id': payable.id})
    ordinary_bill = invoice(accountant, 25, expense, vendor)
    ordinary_wizard = accountant['account.payment.register'].with_context(active_model='account.move', active_ids=ordinary_bill.ids).create({
        'journal_id': treasury.id, 'payment_method_line_id': method.id, 'amount': 25,
        'payment_date': today, 'installments_mode': 'full', 'payment_difference_handling': 'open'})
    ordinary_payment = ordinary_wizard._create_payments()
    check('accountant ordinary vendor posting and payment remain valid', ordinary_bill.payment_state == 'paid' and cents(ordinary_bill.amount_total) == 25)
    check('ordinary payment not marked private', not ordinary_payment.sudo().baseer_private_hr)
    public_unpaid = invoice(accountant, 37.25, expense, vendor)
    check('ordinary unpaid vendor fixture retains residual', cents(public_unpaid.amount_residual) == Decimal('37.25'))
    deny('limited user cannot reclassify ordinary payment private', lambda: ordinary_payment.write({'destination_account_id': company.baseer_salary_payable_id.id}), (UserError,))
    check('failed destination change rolls back atomically', ordinary_payment.sudo().destination_account_id == payable and not ordinary_payment.sudo().baseer_private_hr)
    for value in (True, False):
        deny('payment protected marker write denied ' + str(value), lambda value=value: ordinary_payment.write({'baseer_private_hr': value}))
        deny('payment protected marker create denied ' + str(value), lambda value=value: accountant['account.payment'].create({'baseer_private_hr': value}))
        deny('payment protected marker default denied ' + str(value), lambda value=value: accountant['account.payment'].with_context(default_baseer_private_hr=value).create({}))

    # Documented native partner lookup aggregates must not expose salary residuals.
    check('private fixture has unpaid salary residual for aggregate probe', cents(unpaid_salary.amount_residual) == Decimal('567.89'))
    for field in ('debit', 'credit'):
        try:
            value = accountant['res.partner'].browse(partner.id).read([field])[0][field]
        except AccessError:
            check('accountant partner ' + field + ' restricted', True)
        else:
            check('accountant partner ' + field + ' excludes private salary', cents(value) == 0)
        try:
            matches = accountant['res.partner'].search([('id', '=', partner.id), (field, '>', 0)])
        except AccessError:
            check('accountant partner ' + field + ' search restricted', True)
        else:
            check('accountant partner ' + field + ' search excludes private salary', not matches)

    # Same transaction/cache, alternating privileged and limited users.
    for index in range(2):
        check('privileged partner balance remains exact ' + str(index),
              cents(admin['res.partner'].browse(partner.id).debit) == Decimal('567.89'))
        check('limited partner cache does not reuse salary balance ' + str(index),
              cents(accountant['res.partner'].browse(partner.id).debit) == 0)
        check('public vendor balance remains exact for limited user ' + str(index),
              cents(accountant['res.partner'].browse(vendor.id).debit) == Decimal('37.25'))
        check('public vendor balance remains exact for administrator ' + str(index),
              cents(admin['res.partner'].browse(vendor.id).debit) == Decimal('37.25'))
    check('public vendor balance search retains native positive result',
          vendor.id in accountant['res.partner'].search([('id', '=', vendor.id), ('debit', '>', 37)]).ids)
    receivable = admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', 'asset_receivable'), ('id', 'not in', private.ids)], limit=1)
    assert receivable
    customer = admin['res.partner'].create({'name': 'AR1 PRIVACY ROLLBACK ordinary customer', 'company_id': company.id,
                                           'property_account_receivable_id': receivable.id})
    customer_move = admin['account.move'].create({'move_type': 'entry', 'date': today,
        'journal_id': company.baseer_payroll_journal_id.id, 'company_id': company.id,
        'line_ids': [Command.create({'name': 'AR1 public customer receivable', 'account_id': receivable.id,
                                    'partner_id': customer.id, 'debit': 48.75}),
                     Command.create({'name': 'AR1 public counterpart', 'account_id': expense.id, 'credit': 48.75})]})
    customer_move.action_post()
    check('public customer receivable native privileged value retained', cents(admin['res.partner'].browse(customer.id).credit) == Decimal('48.75'))
    check('public customer receivable native limited value retained', cents(accountant['res.partner'].browse(customer.id).credit) == Decimal('48.75'))
    check('public customer receivable search retains native positive result', customer.id in accountant['res.partner'].search([('id', '=', customer.id), ('credit', '=', 48.75)]).ids)

    eos = admin['baseer.hr.eos'].create({'employee_id': employee.id, 'company_id': company.id,
        'version_id': employee.version_id.id, 'service_start': today, 'service_end': today})
    eos_bill = invoice(admin(context=dict(ctx, baseer_payroll_internal=INTERNAL)), 12.5, expense, vendor, baseer_eos_id=eos.id)
    eos_rows = admin['account.invoice.report'].search([('move_id', '=', eos_bill.id)])
    check('tag-only EOS invoice exists in native reporting source', bool(eos_rows))
    deny('accountant tag-only EOS vendor bill denied', lambda: accountant['account.move'].browse(eos_bill.id).read(['amount_total']))
    check('accountant EOS invoice absent from SQL report', not accountant['account.invoice.report'].search([('move_id', '=', eos_bill.id)]))
    deny('accountant EOS report direct read denied', lambda: accountant['account.invoice.report'].browse(eos_rows.ids).read(['price_total']))

    for label, actor in users.items():
        for field in ('kanban_dashboard', 'kanban_dashboard_graph', 'current_statement_balance', 'has_statement_lines', 'last_statement_id'):
            if field in actor['account.journal']._fields:
                deny(label + ' journal aggregate field denied ' + field,
                     lambda actor=actor, field=field: actor['account.journal'].browse(treasury.id).read([field]))
                check(label + ' journal fields_get excludes ' + field,
                      field not in actor['account.journal'].fields_get([field]))
        for field in ('opening_debit', 'opening_credit', 'opening_balance'):
            if field in actor['account.account']._fields:
                deny(label + ' account opening aggregate denied ' + field,
                     lambda actor=actor, field=field: actor['account.account'].browse(company.baseer_salary_payable_id.id).read([field]))
                check(label + ' account fields_get excludes ' + field,
                      field not in actor['account.account'].fields_get([field]))

    owner_user = env['res.users'].with_context(no_reset_password=True).create({
        'name': 'AR1 PRIVACY ROLLBACK owner', 'login': 'ar1-privacy-rollback-owner',
        'baseer_access_role': 'owner', 'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
    owner = env(user=owner_user.id, su=False, context=ctx)
    owner_journal_fields = [field for field in ('kanban_dashboard', 'kanban_dashboard_graph', 'current_statement_balance', 'has_statement_lines', 'last_statement_id') if field in owner['account.journal']._fields]
    check('non-sudo owner retains journal aggregate metadata', set(owner_journal_fields).issubset(owner['account.journal'].fields_get(owner_journal_fields)))
    check('non-sudo owner can read journal aggregates', bool(owner['account.journal'].browse(treasury.id).read(owner_journal_fields)))
    opening_fields = [field for field in ('opening_debit', 'opening_credit', 'opening_balance') if field in owner['account.account']._fields]
    check('non-sudo owner retains opening aggregate metadata', set(opening_fields).issubset(owner['account.account'].fields_get(opening_fields)))
    check('non-sudo owner can read opening aggregates', bool(owner['account.account'].browse(payable.id).read(opening_fields)))

    check('warm privacy cache allows ordinary unpaid bill initially', bool(accountant['account.move'].search([('id', '=', public_unpaid.id)])))
    old_expense = company.baseer_salary_expense_id
    company.baseer_salary_expense_id = expense
    env.invalidate_all()
    check('changing configured private account invalidates warmed record-rule cache', not accountant['account.move'].search([('id', '=', public_unpaid.id)]))
    deny('newly private mixed expense bill direct read denied', lambda: accountant['account.move'].browse(public_unpaid.id).read(['amount_total']))
    company.baseer_salary_expense_id = old_expense
    env.invalidate_all()
    check('restoring configuration restores ordinary vendor visibility', bool(accountant['account.move'].search([('id', '=', public_unpaid.id)])))

    old_payable = company.baseer_salary_payable_id
    company.baseer_salary_payable_id = False
    env.invalidate_all()
    check('private payment marker retained after payroll account configuration changes', private_payment.baseer_private_hr)
    deny('accountant private payment still unreadable after configuration change', lambda: accountant['account.payment'].browse(private_payment.id).read(['amount']))
    deny('accountant origin payment journal still unreadable after configuration change', lambda: accountant['account.move'].browse(payment_move.id).read(['name']))
    company.baseer_salary_payable_id = old_payable
    result['status'] = 'PASS'
except Exception as error:
    result.update(error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
finally:
    env.cr.rollback()
    env.registry.clear_cache()
    env.invalidate_all()
    result['rollback'] = stamp() == before
    result['passed'] = len(checks)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print('AR1_PAYROLL_PRIVACY', result['status'], result['passed'], 'ROLLBACK', result['rollback'])
assert result['status'] == 'PASS', result.get('error')
assert result['rollback']
