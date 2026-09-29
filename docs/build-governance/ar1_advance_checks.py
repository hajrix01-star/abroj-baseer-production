"""AR1 bounded employee-advance authority checks, isolated clone and rollback.

Run with Odoo shell env in baseer_ar1_* after the roles/payroll update.
Keeps the separate role/batch suite intact. No real external transfer is made.
"""
import hashlib
import json
import traceback
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError

assert env.cr.dbname.startswith('baseer_ar1_'), 'Only isolated AR1 clones are authorized'
assert env.su

OUT = Path('/mnt/qa-evidence/ar1-advance-checks.json')
PREFIX = 'AR1 ADVANCE ROLLBACK '
checks, timings = [], []
result = {'status': 'FAIL', 'checks': checks, 'timings': timings, 'rollback': False,
          'scope': 'Native advance ledger and access checks; no external transfer, no payroll execution'}


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


def cents(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))


def snapshot():
    models = ('res.users', 'hr.employee', 'baseer.advance.entry', 'baseer.hr.loan',
              'baseer.hr.loan.line', 'baseer.hr.loan.allocation', 'account.move',
              'account.move.line', 'account.payment', 'hr.payslip')
    counts = {model: env[model].with_context(active_test=False).search_count([]) for model in models}
    users = env['res.users'].with_context(active_test=False).search([]).read(
        ['baseer_access_role', 'group_ids', 'company_id', 'company_ids'])
    counts['user_grants_sha256'] = hashlib.sha256(json.dumps(users, sort_keys=True, default=str).encode()).hexdigest()
    return counts


def scoped(user, company):
    actor = env(user=user.id, su=False, context={'allowed_company_ids': company.ids,
                'lang': 'en_US', 'tz': 'Asia/Riyadh', 'tracking_disable': True})
    assert not actor.su
    return actor


def make_user(label, role, company):
    return env['res.users'].with_context(no_reset_password=True).create({
        'name': PREFIX + label, 'login': 'ar1-advance-rollback-' + label,
        'baseer_access_role': role, 'company_id': company.id,
        'company_ids': [Command.set(company.ids)],
    })


before = snapshot()
try:
    companies = env['res.company'].search([('currency_id.name', '=', 'SAR')])
    company = companies.filtered(lambda company: company.baseer_loan_account_id)[:1]
    assert company, 'Clone needs one seeded employee-advance receivable account'
    other = (companies - company)[:1]
    assert other, 'Clone needs a second company'
    admin = env(context={'allowed_company_ids': company.ids, 'lang': 'en_US', 'tracking_disable': True})
    foreign_admin = env(context={'allowed_company_ids': other.ids, 'lang': 'en_US', 'tracking_disable': True})
    journals = admin['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank']), ('active', '=', True)])
    journal = journals.filtered(lambda journal: journal.default_account_id.account_type == 'asset_cash' and (not journal.currency_id or journal.currency_id == company.currency_id))[:1]
    assert journal, 'Clone needs a native cash/bank journal with company-currency liquidity'
    other_journal = foreign_admin['account.journal'].search([('company_id', '=', other.id), ('type', 'in', ['cash', 'bank'])], limit=1)
    assert other_journal, 'Clone needs a second-company cash/bank journal'
    general_journal = admin['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'general')], limit=1)
    assert general_journal
    contact = admin['res.partner'].create({'name': PREFIX + 'work contact', 'company_id': company.id})
    employee = admin['hr.employee'].create({'name': PREFIX + 'employee', 'company_id': company.id,
                                           'work_contact_id': contact.id, 'private_email': 'ar1-private@example.invalid'})
    other_contact = foreign_admin['res.partner'].create({'name': PREFIX + 'other work contact', 'company_id': other.id})
    other_employee = foreign_admin['hr.employee'].create({'name': PREFIX + 'other employee', 'company_id': other.id,
                                                        'work_contact_id': other_contact.id})
    cashier = make_user('cashier-a', 'cashier', company)
    other_cashier = make_user('cashier-b', 'cashier', company)
    accountant = make_user('accountant', 'accountant', company)
    a, b, acc = (scoped(user, company) for user in (cashier, other_cashier, accountant))
    today = fields.Date.today()
    serial = 0

    def values(**extra):
        global serial
        serial += 1
        vals = {'name': PREFIX + str(serial), 'company_id': company.id,
                'employee_id': employee.id, 'amount': 100.01, 'date': today,
                'first_due_date': today, 'installment_count': 3, 'journal_id': journal.id}
        vals.update(extra)
        return vals

    def entry(actor, **extra):
        return actor['baseer.advance.entry'].create(values(**extra))

    check('advance input employee uses public model', a['baseer.advance.entry']._fields['employee_id'].comodel_name == 'hr.employee.public')
    check('neither limited role receives payroll manager', not a.user.has_group('om_hr_payroll.group_hr_payroll_manager') and not acc.user.has_group('om_hr_payroll.group_hr_payroll_manager'))
    first = entry(a)
    second = entry(b)
    acc_entry = entry(acc)
    check('cashier sees own draft entry', first.read(['name', 'amount'])[0]['name'] == first.name)
    check('cashier search excludes another cashier entry', second.id not in a['baseer.advance.entry'].search([]).ids)
    deny('cashier direct other entry read denied', lambda: a['baseer.advance.entry'].browse(second.id).read(['name', 'amount']))
    deny('cashier direct other entry write denied', lambda: a['baseer.advance.entry'].browse(second.id).write({'amount': 200}))
    deny('cashier other entry deletion denied', lambda: a['baseer.advance.entry'].browse(second.id).unlink())
    deny('cashier cannot disburse another cashier entry', lambda: a['baseer.advance.entry'].browse(second.id).action_disburse())
    check('accountant can inspect company entry drafts', {first.id, second.id, acc_entry.id}.issubset(set(acc['baseer.advance.entry'].search([]).ids)))

    for actor, label in ((a, 'cashier'), (acc, 'accountant')):
        deny(label + ' cannot use other-company employee', lambda actor=actor: entry(actor, employee_id=other_employee.id), (UserError,))
        deny(label + ' cannot use other-company journal', lambda actor=actor: entry(actor, journal_id=other_journal.id), (UserError,))
        deny(label + ' cannot spoof target company', lambda actor=actor: entry(actor, company_id=other.id), (UserError,))
        deny(label + ' forged allowed_company_ids cannot grant company', lambda actor=actor: entry(actor(context={'allowed_company_ids': other.ids}), company_id=other.id, employee_id=other_employee.id, journal_id=other_journal.id), (UserError,))
        deny(label + ' general journal cannot disburse', lambda actor=actor: entry(actor, journal_id=general_journal.id), (UserError,))
        for field, value in (('loan_id', 1), ('state', 'running'), ('balance', 999), ('loan_reference', 'FORGED')):
            deny(label + ' cannot inject protected ' + field, lambda actor=actor, field=field, value=value: entry(actor, **{field: value}), (UserError,))
        deny(label + ' private employee email denied', lambda actor=actor: actor['hr.employee'].browse(employee.id).read(['private_email']))
        deny(label + ' payroll data access denied', lambda actor=actor: actor['hr.payslip'].check_access('read'))
        salary_field = next((name for name in ('baseer_salary_total', 'baseer_monthly_gross', 'wage') if name in employee._fields), None)
        if salary_field:
            deny(label + ' salary field denied', lambda actor=actor, salary_field=salary_field: actor['hr.employee'].browse(employee.id).read([salary_field]))
        deny(label + ' cannot create native loan directly', lambda actor=actor: actor['baseer.hr.loan'].create(values()), (UserError,))
        deny(label + ' boolean internal context cannot grant native loan authority', lambda actor=actor: actor['baseer.hr.loan'].with_context(baseer_payroll_internal=True, baseer_advance_disburse=True).create(values()), (UserError,))

    for amount in (0, -1, 1.001):
        deny('invalid amount cannot be disbursed ' + str(amount), lambda amount=amount: entry(a, amount=amount).action_disburse(), (UserError,))
    for count in (0, 121):
        deny('invalid installment count cannot be disbursed ' + str(count), lambda count=count: entry(a, installment_count=count).action_disburse(), (UserError,))
    deny('installment before disbursement rejected', lambda: entry(a, first_due_date=today - timedelta(days=1)).action_disburse(), (UserError,))
    deny('caller defaults cannot inject financial history', lambda: entry(a(context=dict(a.context, default_loan_id=1, default_state='running', default_balance=999))))
    deny('creator spoof rejected by input allowlist', lambda: entry(a, create_uid=other_cashier.id))

    for actor, label, record in ((a, 'cashier', first), (acc, 'accountant', acc_entry)):
        native_before = snapshot()
        record.write({'amount': 100.01})
        started = perf_counter()
        # This path records a journal entry. HTTP transfer APIs must not be used.
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected external HTTP in advance posting')):
            record.action_disburse()
        timings.append({'operation': label + '_native_advance_disbursement', 'seconds': round(perf_counter() - started, 4)})
        loan = record.sudo().loan_id
        check(label + ' interface creates exactly one native loan', bool(loan) and snapshot()['baseer.hr.loan'] == native_before['baseer.hr.loan'] + 1)
        check(label + ' native advance is outstanding and posted', loan.state == 'running' and loan.move_id.state == 'posted')
        check(label + ' creator retained on entry loan and journal', record.create_uid.id == actor.uid and loan.create_uid.id == actor.uid and loan.move_id.create_uid.id == actor.uid)
        move = loan.move_id
        principal = move.line_ids.filtered(lambda line: line.account_id == company.baseer_loan_account_id)
        cash = move.line_ids.filtered(lambda line: line.account_id == journal.default_account_id)
        check(label + ' principal receivable debit equals amount', len(principal) == 1 and cents(principal.debit) == Decimal('100.01') and cents(principal.credit) == 0)
        check(label + ' cash/bank liquidity credit equals amount', len(cash) == 1 and cents(cash.credit) == Decimal('100.01') and cents(cash.debit) == 0)
        check(label + ' native ledger balanced with two lines', len(move.line_ids) == 2 and sum((cents(line.balance) for line in move.line_ids), Decimal(0)) == 0)
        check(label + ' installments conserve exact principal', len(loan.line_ids) == 3 and sum((cents(line.amount) for line in loan.line_ids), Decimal(0)) == Decimal('100.01'))
        check(label + ' native rounding residual goes to last installment', [cents(line.amount) for line in loan.line_ids.sorted('sequence')] == [Decimal('33.34'), Decimal('33.34'), Decimal('33.33')])
        check(label + ' no payment transfer or payroll allocation created', snapshot()['account.payment'] == native_before['account.payment'] and snapshot()['baseer.hr.loan.allocation'] == native_before['baseer.hr.loan.allocation'] and snapshot()['hr.payslip'] == native_before['hr.payslip'])
        check(label + ' public projection shows own amount/reference only', record.read(['amount', 'balance', 'loan_reference'])[0]['loan_reference'] == loan.name and cents(record.balance) == Decimal('100.01'))
        deny(label + ' private native loan relation cannot be read', lambda record=record: record.read(['loan_id']))
        deny(label + ' private native loan record cannot be read', lambda actor=actor, loan=loan: actor['baseer.hr.loan'].browse(loan.id).read(['amount', 'balance']))
        deny(label + ' native installment history cannot be read', lambda actor=actor, loan=loan: actor['baseer.hr.loan.line'].browse(loan.line_ids[:1].id).read(['amount']))
        deny(label + ' cannot repay native loan through forged context', lambda actor=actor, loan=loan: actor['baseer.hr.loan'].browse(loan.id).with_context(baseer_advance_disburse=True, baseer_payroll_internal=True).action_repay(), (UserError,))
        once = snapshot()
        record.action_disburse()
        check(label + ' repeated disbursement is idempotent', snapshot() == once)
        deny(label + ' issued entry amount cannot change', lambda record=record: record.write({'amount': 200}), (UserError,))
        deny(label + ' issued entry cannot be deleted', lambda record=record: record.unlink(), (UserError,))
        deny(label + ' cannot replace issued native loan link', lambda record=record: record.write({'loan_id': 1}), (UserError,))
    deny('cashier cannot read native advance ledger directly', lambda: a['account.move'].browse(first.sudo().loan_id.move_id.id).read(['line_ids']))
    check('accountant sees company advance entries without HR access', first.id in acc['baseer.advance.entry'].search([]).ids and not acc['hr.employee'].has_access('read'))
    result['status'] = 'PASS'
except Exception as error:
    result.update(error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
finally:
    env.cr.rollback()
    env.invalidate_all()
    result['rollback'] = snapshot() == before
    result['passed'] = len(checks)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print('AR1_ADVANCE_CHECKS', result['status'], result['passed'], 'ROLLBACK', result['rollback'])

assert result['status'] == 'PASS', result.get('error', 'AR1 advance checks failed')
assert result['rollback'], 'Advance test fixtures did not roll back'
