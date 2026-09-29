"""Bounded operator journeys against the completed SIM90 dataset, always rollback.

Prepared separately from seeding. Run only after purchases and sales complete.
No role is granted to a test actor, and no product code is changed.
"""
import hashlib
import json
import traceback
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch
from odoo import api, Command
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.cr.dbname == 'baseer_sim90_20260910'
ROOT = Path('/tmp/sim90')
info = json.loads((ROOT / 'context.json').read_text(encoding='utf8'))
assert info['company_id'] == 2 and info['other_company_id'] == 3
assert (info['user_id'], info['roles']['accountant'], info['roles']['cashier']) == (5, 6, 7)
HR = json.loads((ROOT / 'hr-manifest.json').read_text(encoding='utf8'))
DAY = date(2026, 3, 31)
result = {'database': env.cr.dbname, 'status': 'FAIL', 'checks': [], 'hard_commit_guard': True,
          'rollback': False, 'scope': 'Cashier batches, bounded advance entry, correction toggle and company isolation'}


def q(x):
    return Decimal(str(x)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def check(label, condition, **evidence):
    result['checks'].append({'name': label, 'passed': bool(condition), **evidence})
    assert condition, label


def deny(label, callback, exceptions=(AccessError, UserError, ValidationError)):
    try:
        with env.cr.savepoint():
            callback()
    except exceptions as error:
        check(label, True, denial=type(error).__name__)
    else:
        check(label, False)


def actor(uid, company=2):
    return api.Environment(env.cr, uid, {'allowed_company_ids': [company], 'lang': 'en_US',
        'tz': 'Asia/Riyadh', 'tracking_disable': True, 'mail_create_nolog': True,
        'mail_create_nosubscribe': True, 'mail_notify_force_send': False}, su=False)


def snapshot():
    models = ['res.users', 'hr.employee', 'hr.version', 'hr.payslip', 'hr.payslip.run',
              'baseer.advance.entry', 'baseer.hr.loan', 'baseer.hr.loan.line',
              'baseer.hr.loan.allocation', 'baseer.purchase.batch', 'baseer.purchase.batch.line',
              'account.move', 'account.move.line', 'account.payment', 'res.partner',
              'baseer.financial.correction.audit']
    state = {}
    for model in models:
        records = env[model].with_context(active_test=False).search([], order='id')
        rows = records.read(['write_date'])
        state[model] = {'count': len(records), 'identity_and_write_date_sha256': hashlib.sha256(
            json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()}
    grants = env['res.users'].browse([5, 6, 7]).read([
        'baseer_access_role', 'baseer_allow_financial_correction', 'group_ids', 'company_ids'])
    state['roles_sha256'] = hashlib.sha256(json.dumps(grants, sort_keys=True).encode()).hexdigest()
    return state


before = snapshot()
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('SIM90 role journeys must never commit'))
guard.start()
try:
    owner, accountant, cashier = actor(5), actor(6), actor(7)
    company = owner['res.company'].browse(2)
    check('all business actors use real non-superuser roles', all(not a.su for a in (owner, accountant, cashier)))
    check('cashier and accountant lack payroll manager authority', all(
        not a.user.has_group('om_hr_payroll.group_hr_payroll_manager') for a in (accountant, cashier)))
    check('dense three-month HR data loaded', len(HR['employees']) == 24 and len(HR['runs']) == 3)
    own = cashier['baseer.purchase.batch'].search([('company_id', '=', 2), ('state', '=', 'draft')])
    own_ids = owner['baseer.purchase.batch'].search([('company_id', '=', 2), ('create_uid', '=', 7), ('state', '=', 'draft')]).ids
    check('cashier sees all own seeded draft batches', len(own) >= 3 and set(own.ids) == set(own_ids))
    check('cashier search contains no other creator batches', all(b.create_uid.id == 7 for b in cashier['baseer.purchase.batch'].search([])))
    foreign_creator = owner['baseer.purchase.batch'].search([('company_id', '=', 2), ('create_uid', '=', 5), ('state', '=', 'approved')], limit=1)
    check('owner approved production-volume batch present', bool(foreign_creator))
    deny('cashier cannot directly read owner batch', lambda: cashier['baseer.purchase.batch'].browse(foreign_creator.id).read(['name']))
    deny('cashier cannot directly read owner batch row', lambda: cashier['baseer.purchase.batch.line'].browse(foreign_creator.line_ids[:1].id).read(['gross_amount']))
    pending = own[:1]
    pending.write({'entry_date': DAY})
    pending.line_ids.write({'invoice_date': DAY})
    deny('cashier cannot approve even own purchase batch', pending.action_approve)
    check('denied cashier approval creates no source bills', not pending.move_ids and pending.state == 'draft')
    accountant_batch = accountant['baseer.purchase.batch'].browse(pending.id)
    expected_batch = sum((q(line.gross_amount) for line in accountant_batch.line_ids), q(0))
    accountant_batch.action_approve()
    pending.invalidate_recordset()
    check('accountant approves cashier draft through batch workflow', accountant_batch.state == 'approved'
          and accountant_batch.approved_by_id.id == 6 and accountant_batch.create_uid.id == 7)
    check('accountant approval posts exact batch gross', all(m.state == 'posted' for m in accountant_batch.move_ids)
          and sum((q(m.amount_total) for m in accountant_batch.move_ids), q(0)) == expected_batch)
    check('cashier retains read-only view of own reviewed batch', pending.read(['state'])[0]['state'] == 'approved')
    deny('cashier cannot edit approved own batch input', lambda: pending.line_ids.write({'gross_amount': 999}))

    employee_id = HR['employees'][0]['id']
    salary_id = next(row['id'] for row in HR['manifest'] if row['model'] == 'hr.payslip')
    treasury = owner['account.journal'].browse(info['cash_journal_id'])
    def advance_values(**extra):
        return dict({'name': 'SIM90 ROLE ROLLBACK employee advance', 'company_id': 2,
            'employee_id': employee_id, 'amount': 100.01, 'date': DAY, 'first_due_date': DAY,
            'installment_count': 3, 'journal_id': treasury.id}, **extra)
    for a, label in ((cashier, 'cashier'), (accountant, 'accountant')):
        check(label + ' advance employee field is public projection',
              a['baseer.advance.entry']._fields['employee_id'].comodel_name == 'hr.employee.public')
        check(label + ' public employee search supports advance workflow',
              employee_id in a['hr.employee.public'].search([('id', '=', employee_id)]).ids)
        deny(label + ' employee wage read denied', lambda a=a: a['hr.employee'].browse(employee_id).read(['baseer_salary_total']), (AccessError,))
        deny(label + ' payroll version wage read denied', lambda a=a: a['hr.version'].browse(owner['hr.employee'].browse(employee_id).version_id.id).read(['wage']), (AccessError,))
        deny(label + ' payslip read denied', lambda a=a: a['hr.payslip'].browse(salary_id).read(['baseer_net']), (AccessError,))
        entry = a['baseer.advance.entry'].create(advance_values())
        loans_before = owner['baseer.hr.loan'].search_count([('company_id', '=', 2)])
        payments_before = owner['account.payment'].search_count([('company_id', '=', 2)])
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Advance workflow attempted external request')):
            entry.action_disburse()
        loan = owner['baseer.advance.entry'].browse(entry.id).loan_id
        check(label + ' disbursement creates one native posted loan', loan.state == 'running'
              and loan.move_id.state == 'posted' and owner['baseer.hr.loan'].search_count([('company_id', '=', 2)]) == loans_before + 1)
        check(label + ' disbursement preserves real creator', entry.create_uid.id == a.uid
              and loan.create_uid.id == a.uid and loan.move_id.create_uid.id == a.uid)
        check(label + ' native loan and public balance match declared amount', q(loan.amount) == q('100.01')
              and q(entry.balance) == q('100.01') and q(loan.balance) == q('100.01'))
        principal = loan.move_id.line_ids.filtered(lambda l: l.account_id == company.baseer_loan_account_id)
        liquidity = loan.move_id.line_ids.filtered(lambda l: l.account_id == treasury.default_account_id)
        check(label + ' bounded workflow records balanced principal and disbursement',
              len(principal) == len(liquidity) == 1 and q(principal.debit) == q('100.01')
              and q(liquidity.credit) == q('100.01') and q(sum(loan.move_id.line_ids.mapped('balance'))) == 0)
        check(label + ' installment rounding conserves cents',
              [q(l.amount) for l in loan.line_ids.sorted('sequence')] == [q('33.34'), q('33.34'), q('33.33')])
        check(label + ' no external bank payment or salary record created',
              owner['account.payment'].search_count([('company_id', '=', 2)]) == payments_before
              and owner['hr.payslip'].search_count([('company_id', '=', 2)]) == 71)
        entry.action_disburse()
        check(label + ' repeat disbursement is idempotent',
              owner['baseer.hr.loan'].search_count([('company_id', '=', 2)]) == loans_before + 1)
        deny(label + ' private loan relation remains inaccessible', lambda entry=entry: entry.read(['loan_id']), (AccessError,))
        deny(label + ' native loan read remains inaccessible', lambda a=a, loan=loan: a['baseer.hr.loan'].browse(loan.id).read(['amount']), (AccessError,))
        deny(label + ' issued advance amount is immutable', lambda entry=entry: entry.write({'amount': 200}))

    # Ordinary invoice fixture deliberately avoids payroll accounts, so it exercises the shared correction path.
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_deduction_account_id | company.baseer_loan_account_id
    def plain_bill(a, amount, ref):
        expense = a['account.account'].search([('company_ids', 'in', a.company.ids), ('account_type', '=', 'expense'), ('id', 'not in', private.ids)], limit=1)
        payable = a['account.account'].search([('company_ids', 'in', a.company.ids), ('account_type', '=', 'liability_payable'), ('id', 'not in', private.ids)], limit=1)
        partner = a['res.partner'].create({'name': ref, 'company_id': a.company.id, 'supplier_rank': 1,
                                          'property_account_payable_id': payable.id})
        bill = a['account.move'].create({'move_type': 'in_invoice', 'company_id': a.company.id,
            'partner_id': partner.id, 'invoice_date': DAY, 'date': DAY, 'ref': ref,
            'invoice_line_ids': [Command.create({'name': ref, 'quantity': 1, 'price_unit': amount,
                'account_id': expense.id, 'tax_ids': [Command.clear()]})]})
        bill.action_post()
        return bill
    bill = plain_bill(owner, 400, 'SIM90 ROLE ROLLBACK correction')
    owner['res.users'].browse(6).write({'baseer_allow_financial_correction': True})
    action = accountant['account.move'].browse(bill.id).action_baseer_correct_operation()
    wizard = accountant[action['res_model']].browse(action['res_id'])
    wizard.write({'reason': 'SIM90 permission revocation rollback-only probe'})
    wizard.line_ids.write({'price_unit_input': '500'})
    owner['res.users'].browse(6).write({'baseer_allow_financial_correction': False})
    check('owner disabling accountant permission hides correction entry',
          not accountant['account.move'].browse(bill.id).baseer_can_correct_operation)
    deny('disabled accountant cannot reopen correction', lambda: accountant['account.move'].browse(bill.id).action_baseer_correct_operation())
    deny('permission revoked after opening prevents confirmation', wizard.action_confirm)
    deny('accountant cannot self-enable correction permission', lambda: accountant['res.users'].browse(6).write({'baseer_allow_financial_correction': True}), (AccessError,))
    owner['res.users'].browse(7).write({'baseer_allow_financial_correction': True})
    deny('cashier cannot open financial correction even with enabled flag', lambda: cashier['account.move'].browse(bill.id).action_baseer_correct_operation(), (AccessError,))
    deny('cashier cannot confirm another correction wizard', lambda: cashier['baseer.financial.correction'].browse(wizard.id).action_confirm(), (AccessError,))
    owner['res.users'].browse(6).write({'baseer_allow_financial_correction': True})
    enabled = accountant['account.move'].browse(bill.id).action_baseer_correct_operation()
    confirmed = accountant[enabled['res_model']].browse(enabled['res_id'])
    confirmed.write({'reason': 'SIM90 owner reenabled correction; transaction rollback'})
    confirmed.line_ids.write({'price_unit_input': '500'})
    confirmed.action_confirm()
    bill.invalidate_recordset()
    check('reenabled accountant correction applies through native workflow', confirmed.completed
          and bill.state == 'posted' and q(bill.amount_total) == q(500))
    check('correction audit identifies the real accountant', confirmed.audit_id.user_id.id == 6)

    # Admin prepares company 3 sentinels; restricted actors retain their original memberships.
    admin_other = actor(env.ref('base.user_admin').id, 3)
    other_bill = plain_bill(admin_other, 987.65, 'SIM90 ROLE ROLLBACK company 3 sentinel')
    other_employee = admin_other['hr.employee'].create({'name': 'SIM90 ROLE ROLLBACK foreign employee',
        'company_id': 3, 'baseer_payroll_enabled': False})
    other_map = admin_other['baseer.purchase.category.map'].search([('company_id', '=', 3), ('active', '=', True)], limit=1)
    assert other_map
    other_batch = admin_other['baseer.purchase.batch'].create({'company_id': 3, 'entry_date': DAY,
        'line_ids': [Command.create({'invoice_date': DAY, 'partner_id': other_bill.partner_id.id,
            'supplier_ref': 'SIM90 ROLE ROLLBACK foreign batch row', 'entry_type': 'expense',
            'category_map_id': other_map.id, 'gross_amount': 100, 'is_credit': True, 'tax_id': False})]})
    other_journal = admin_other['account.journal'].search([('company_id', '=', 3), ('type', '=', 'cash')], limit=1)
    for a, label in ((cashier, 'cashier'), (accountant, 'accountant')):
        check(label + ' foreign batch absent from search', other_batch.id not in a['baseer.purchase.batch'].search([]).ids)
        deny(label + ' foreign batch direct read denied', lambda a=a: a['baseer.purchase.batch'].browse(other_batch.id).read(['name']), (AccessError,))
        check(label + ' public employee search excludes other company', other_employee.id not in a['hr.employee.public'].search([]).ids)
        deny(label + ' foreign public employee direct read denied', lambda a=a: a['hr.employee.public'].browse(other_employee.id).read(['name']), (AccessError,))
        deny(label + ' cannot issue advance for foreign employee', lambda a=a: a['baseer.advance.entry'].create(advance_values(employee_id=other_employee.id)))
        deny(label + ' cannot issue advance from foreign treasury', lambda a=a: a['baseer.advance.entry'].create(advance_values(journal_id=other_journal.id)))
        deny(label + ' forged company context cannot grant advance authority', lambda a=a: actor(a.uid, 3)['baseer.advance.entry'].create(advance_values(company_id=3, employee_id=other_employee.id, journal_id=other_journal.id)))
        deny(label + ' foreign posted bill direct read denied', lambda a=a: a['account.move'].browse(other_bill.id).read(['amount_total']), (AccessError,))
    check('accountant company scoped invoice search excludes sentinel', other_bill.id not in accountant['account.move'].search([('move_type', '=', 'in_invoice')]).ids)
    deny('accountant correction cannot cross company boundary', lambda: accountant['account.move'].browse(other_bill.id).action_baseer_correct_operation(), (AccessError,))
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    guard.stop()
    after = snapshot()
    result['rollback'] = before == after
    result['before'] = before
    result['after'] = after
    result['passed'] = sum(c['passed'] for c in result['checks'])
    (ROOT / 'role-journeys.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    print('SIM90_ROLE_JOURNEYS', result['status'], result['passed'], 'ROLLBACK', result['rollback'], flush=True)
assert result['status'] == 'PASS' and result['rollback'], result.get('error', 'Role journey rollback comparison failed')
