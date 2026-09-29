"""Isolated source-route/access checks; no source correction is confirmed."""
import json
from pathlib import Path
from unittest.mock import patch
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError

assert env.su and env.cr.dbname.startswith('baseer_ic1_')
out = Path('/mnt/qa-evidence/ic1-source-checks.json')
checks = []
result = {'status': 'FAIL', 'database': env.cr.dbname, 'checks': checks, 'rollback': False,
          'scope': 'Native dispatcher and existing source action routing/access only; synthetic source linkage, no financial correction execution'}
models = ('res.users', 'account.move', 'account.move.line', 'account.payment', 'hr.payslip',
          'baseer.hr.loan', 'baseer.pos.summary', 'baseer.financial.correction.audit')
def counts():
    return {name: env[name].with_context(active_test=False).search_count([]) for name in models}
def check(label, condition):
    assert condition, label
    checks.append(label)
def deny(label, callback):
    try:
        with env.cr.savepoint():
            callback()
    except (AccessError, UserError):
        checks.append(label)
        return
    raise AssertionError(label + ': allowed')
before = counts()
modules_before = env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('Source fixtures cannot commit'))
guard.start()
try:
    company = env['res.company'].search([('currency_id.name', '=', 'SAR')]).filtered(lambda c: c.baseer_salary_expense_id)[:1]
    ctx = {'allowed_company_ids': company.ids, 'lang': 'en_US', 'tracking_disable': True, 'no_reset_password': True}
    admin = env(context=ctx)
    actors = {}
    for role in ('owner', 'accountant', 'cashier'):
        user = admin['res.users'].search([('baseer_access_role', '=', role), ('company_ids', 'in', company.ids)], limit=1)
        if not user:
            user = admin['res.users'].create({'name': 'IC1 route ' + role, 'login': 'ic1-route-' + role,
                'baseer_access_role': role, 'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        actors[role] = env(user=user.id, su=False, context=ctx)
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_deduction_account_id | company.baseer_loan_account_id
    expense = admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', 'expense'), ('id', 'not in', private.ids)], limit=1)
    cash = admin['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank'])]).filtered(lambda j: j.default_account_id.account_type == 'asset_cash')[:1]
    employee = admin['hr.employee'].search([('company_id', '=', company.id)], limit=1)
    config = admin['pos.config'].search([('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
    assert expense and cash and employee and config
    today = fields.Date.context_today(admin['account.move'])
    def move():
        record = admin['account.move'].create({'company_id': company.id, 'journal_id': cash.id,
            'date': today, 'ref': 'IC1 ROUTE FIXTURE', 'line_ids': [Command.create({'name': 'route', 'account_id': expense.id, 'debit': 1}),
                Command.create({'name': 'route', 'account_id': cash.default_account_id.id, 'credit': 1})]})
        record.action_post()
        return record
    plain = move()
    payslip = admin['hr.payslip'].create({'name': 'IC1 route payslip', 'employee_id': employee.id,
        'company_id': company.id, 'date_from': today, 'date_to': today,
        'journal_id': cash.id, 'struct_id': False, 'version_id': False, 'payslip_run_id': False})
    loan = admin['baseer.hr.loan'].create({'name': 'IC1 route loan', 'employee_id': employee.id,
        'company_id': company.id, 'amount': 1, 'date': today, 'first_due_date': today,
        'installment_count': 1, 'journal_id': cash.id})
    summary = admin['baseer.pos.summary'].create({'company_id': company.id, 'config_id': config.id,
        'business_date': today, 'period_scope': 'morning', 'day_schedule': 'morning', 'zero_sales': True})
    # This isolates dispatch from already-certified source posting engines. Only
    # synthetic source/link state is supplied, not financial correctness evidence.
    env.cr.execute('UPDATE baseer_pos_summary SET state=%s WHERE id=%s', ['approved', summary.id])
    summary.invalidate_recordset()
    source_cases = [('POS', 'baseer_pos_summary_id', summary, 'baseer.pos.summary.correction'),
                    ('payslip', 'baseer_payslip_id', payslip, 'baseer.payroll.correction'),
                    ('loan', 'baseer_loan_id', loan, 'baseer.payroll.correction')]
    documents = []
    for label, field, source, destination in source_cases:
        record = move()
        env.cr.execute('UPDATE account_move SET ' + field + '=%s WHERE id=%s', [source.id, record.id])
        record.invalidate_recordset()
        documents.append(record)
        with patch.object(type(admin['baseer.financial.correction']), '_open_for_source', side_effect=AssertionError('Protected source entered generic correction')):
            result_action = actors['owner']['account.move'].browse(record.id).action_baseer_correct_operation()
        check(label + ' routes to existing source correction model', result_action['res_model'] == destination)
        check(label + ' does not create generic wizard', result_action['res_model'] != 'baseer.financial.correction')
        deny(label + ' accountant cannot gain source-manager rights', lambda: actors['accountant']['account.move'].browse(record.id).action_baseer_correct_operation())
        deny(label + ' cashier central entry denied', lambda: actors['cashier']['account.move'].browse(record.id).action_baseer_correct_operation())
        deny(label + ' direct generic source eligibility denied', lambda: actors['owner']['account.move'].browse(record.id)._baseer_assert_correction_eligible())
    action = actors['owner']['account.move'].browse(plain.id).action_baseer_correct_operation()
    check('independent journal uses native reversal wizard', action['res_model'] == 'account.move.reversal')
    deny('cashier native journal central entry denied', lambda: actors['cashier']['account.move'].browse(plain.id).action_baseer_correct_operation())
    other_company = admin['res.company'].search([('id', '!=', company.id)], limit=1)
    deny('owner source current-company mismatch denied', lambda: actors['owner']['account.move'].with_context(allowed_company_ids=other_company.ids).browse(plain.id).action_baseer_correct_operation())
    check('routing leaves source entries posted and unchanged', all(r.state == 'posted' and sum(r.line_ids.mapped('balance')) == 0 and len(r.line_ids) == 2 for r in documents + [plain]))
    check('routing creates no generic correction audit', admin['baseer.financial.correction.audit'].search_count([]) == before['baseer.financial.correction.audit'])
    result['status'] = 'PASS'
except Exception as error:
    result['error'] = str(error)
    raise
finally:
    env.cr.rollback()
    guard.stop()
    env.invalidate_all()
    result['rollback'] = counts() == before
    result['commit_guard'] = True
    result['modules_preserved'] = modules_before == env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
    result['passed'] = len(checks)
    out.write_text(json.dumps(result, indent=2), encoding='utf8')
    print('IC1_SOURCE_CHECKS=' + json.dumps(result))
