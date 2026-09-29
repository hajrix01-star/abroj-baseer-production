"""FA2 security remediation regression; disposable clone only, all database writes rolled back."""
import json
import traceback
from pathlib import Path
from odoo import api, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.service.model import call_kw, get_public_method

assert env.cr.dbname == 'baseer_fix_security_20260909', 'Exclusive disposable security clone only'
R = {'database': env.cr.dbname, 'status': 'started', 'checks': [], 'observations': []}

def check(name, condition, evidence=None):
    R['checks'].append({'name': name, 'passed': bool(condition), 'evidence': evidence})

def reject(name, fn):
    try:
        with env.cr.savepoint():
            value = fn()
    except (AccessError, UserError, ValidationError) as error:
        check(name, True, {'exception': type(error).__name__})
        return True
    else:
        check(name, False, {'returned': str(value)[:350]})
        return False

def rpc(E, model, method, args, kwargs=None):
    return call_kw(E[model], method, args, kwargs or {})

def fingerprint():
    out = {}
    for table in ('res_partner', 'res_users', 'res_company', 'hr_employee', 'hr_version',
                  'account_move', 'account_move_line', 'account_payment', 'hr_payslip',
                  'hr_payslip_line', 'baseer_hr_service', 'baseer_pos_summary'):
        env.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,\'\' ORDER BY id),\'\')) FROM ' + table + ' t')
        out[table] = env.cr.fetchone()
    return out

before = fingerprint()
try:
    admin_id = env.ref('base.user_admin').id
    def ce(cid, uid=admin_id):
        return api.Environment(env.cr, uid, {'allowed_company_ids': [cid], 'lang': 'en_US', 'tracking_disable': True, 'mail_create_nosubscribe': True})
    A, B = ce(6), ce(10)
    users = {}
    roles = {
        'internal': ['base.group_user'],
        'hr': ['hr.group_hr_user'],
        'hr_manager': ['hr.group_hr_manager'],
        'payroll_officer': ['om_hr_payroll.group_hr_payroll_user'],
        'payroll_manager': ['om_hr_payroll.group_hr_payroll_manager'],
        'pos': ['point_of_sale.group_pos_user'],
        'invoice': ['account.group_account_invoice'],
        'account_manager': ['account.group_account_manager', 'base.group_partner_manager'],
    }
    for name, group_ids in roles.items():
        user = A['res.users'].create({'name': 'Security Audit ' + name, 'login': 'security.full.audit.' + name,
            'company_id': 6, 'company_ids': [Command.set([6])],
            'group_ids': [Command.set([A.ref(g).id for g in set(group_ids) | {'base.group_user'}])]})
        users[name] = ce(6, user.id)
    check('nonadmin_test_users_are_not_sudo', all(not E.su and E.uid != admin_id for E in users.values()))
    check('payroll_officer_is_not_manager', not users['payroll_officer'].user.has_group('om_hr_payroll.group_hr_payroll_manager'))
    for model, method in [('res.company', '_baseer_consolidate_shared_providers'),
                          ('baseer.pos.day.archive', 'init'), ('eh.account.report.execution', 'start_execution')]:
        reject('private_rpc_' + model + '.' + method, lambda m=model, f=method: get_public_method(users['internal'][m], f))

    provider = A.ref('baseer_service_seed.provider_passports')
    category_a = A.ref('baseer_service_seed.mapping_iqama_issue_company_6')
    category_b = B.ref('baseer_service_seed.mapping_iqama_issue_company_10')
    for role in ('internal', 'hr', 'pos', 'invoice'):
        reject(role + '_cannot_configure_supplier_category', lambda role=role: rpc(users[role], 'res.partner', 'write', [[provider.id], {'baseer_purchase_category_map_id': category_a.id}]))
    reject('category_foreign_company_rejected', lambda: rpc(users['account_manager'], 'res.partner', 'write', [[provider.id], {'baseer_purchase_category_map_id': category_b.id}]))
    previous_b = B['res.partner'].browse(provider.id).baseer_purchase_category_map_id.id
    rpc(users['account_manager'], 'res.partner', 'write', [[provider.id], {'baseer_purchase_category_map_id': category_a.id}])
    check('shared_supplier_company_property_isolated', B['res.partner'].browse(provider.id).baseer_purchase_category_map_id.id == previous_b)
    reject('unauthorized_allowed_company_context', lambda: rpc(users['hr'], 'res.partner', 'read', [[provider.id], ['baseer_purchase_category_map_id']], {'context': {'allowed_company_ids': [10]}}))

    dept = A['hr.department'].create({'name': 'Security Audit Restricted Department', 'company_id': 6})
    employee = A['hr.employee'].create({'name': 'Security Audit Confidential Employee', 'company_id': 6, 'department_id': dept.id})
    employee_b = B['hr.employee'].create({'name': 'Security Audit Foreign Employee', 'company_id': 10})
    service_values = {'employee_id': employee.id, 'service_type': 'iqama_issue', 'gross_amount': 115,
        'vat_enabled': True, 'invoice_date': '2026-09-01', 'issue_date': '2026-09-01'}
    service = A['baseer.hr.service'].create(service_values)
    service_b = B['baseer.hr.service'].create(dict(service_values, employee_id=employee_b.id))
    for role in ('internal', 'pos', 'invoice'):
        reject(role + '_cannot_read_hr_service', lambda role=role: rpc(users[role], 'baseer.hr.service', 'read', [[service.id], ['gross_amount']]))
    for role in ('hr', 'hr_manager'):
        reject(role + '_cannot_approve_without_combined_rights', lambda role=role: rpc(users[role], 'baseer.hr.service', 'action_approve', [[service.id]]))
    reject('hr_cannot_read_other_company_service', lambda: rpc(users['hr'], 'baseer.hr.service', 'read', [[service_b.id], ['gross_amount', 'balance']]))
    reject('hr_cannot_forge_state_with_boolean_context', lambda: rpc(users['hr'], 'baseer.hr.service', 'write', [[service.id], {'state': 'approved'}], {'context': {'baseer_hr_service_internal': True}}))
    service.action_approve()
    projection = rpc(users['hr'], 'baseer.hr.service', 'read', [[service.id], ['gross_amount', 'net_amount', 'tax_amount', 'balance', 'bill_name']])
    check('hr_limited_bill_projection_available', projection[0]['gross_amount'] == 115 and projection[0]['balance'] == 115)
    reject('hr_cannot_read_projected_bill_contents', lambda: rpc(users['hr'], 'account.move', 'read', [[service.bill_id.id], ['invoice_line_ids']]))
    reject('hr_cannot_follow_bill_action', lambda: rpc(users['hr'], 'baseer.hr.service', 'action_view_bill', [[service.id]]))
    reject('hr_cannot_modify_approved_amount', lambda: rpc(users['hr'], 'baseer.hr.service', 'write', [[service.id], {'gross_amount': 116}]))
    for field in ('baseer_salary_total', 'baseer_basic_salary', 'baseer_loan_balance', 'baseer_financial_slip_ids'):
        reject('hr_protected_employee_' + field, lambda f=field: rpc(users['hr'], 'hr.employee', 'read', [[employee.id], [f]]))

    contribution_wizard = users['payroll_officer']['payslip.lines.contribution.register'].create({'date_from': '2026-08-01', 'date_to': '2026-08-31'})
    try:
        contribution_action = rpc(users['payroll_officer'], contribution_wizard._name, 'print_report', [[contribution_wizard.id]])
        check('vendor_contribution_report_action_resolves', bool(contribution_action))
    except ValueError as error:
        check('vendor_contribution_report_action_resolves', False, {'exception': type(error).__name__, 'message': str(error)})
    R['observations'].append({'name': 'vendor_contribution_handler_registry',
        'expected_model_registered': 'report.om_hr_payroll.report_contribution_register' in env.registry,
        'typo_model_registered': 'report.om_om_hr_payroll.report_contribution_register' in env.registry})

    # The officer parent rule restricts other departments; child reads must match it.
    slip = A['hr.payslip'].create({'name': 'Security Audit Restricted Payslip', 'employee_id': employee.id,
        'version_id': employee.version_id.id, 'company_id': 6, 'date_from': '2026-08-01', 'date_to': '2026-08-31'})
    rule = A['hr.salary.rule'].search([('company_id', '=', 6)], limit=1)
    if not rule:
        category = A['hr.salary.rule.category'].create({'name': 'Security Audit Salary', 'code': 'SEC', 'company_id': 6})
        rule = A['hr.salary.rule'].create({'name': 'Security Audit Salary', 'code': 'SEC', 'company_id': 6, 'category_id': category.id, 'amount_select': 'fix'})
    line = A['hr.payslip.line'].create({'slip_id': slip.id, 'salary_rule_id': rule.id,
        'name': 'Security Audit Private Salary', 'code': 'SEC_PRIVATE', 'company_id': 6,
        'category_id': rule.category_id.id, 'amount': 12345.67})
    input_row = A['hr.payslip.input'].create({'payslip_id': slip.id, 'name': 'Security Audit Private Bonus',
        'code': 'SEC_INPUT', 'version_id': employee.version_id.id, 'amount': 765.43})
    worked = A['hr.payslip.worked_days'].create({'payslip_id': slip.id, 'name': 'Security Audit Private Attendance',
        'code': 'SEC_WORK', 'version_id': employee.version_id.id, 'number_of_days': 23.5, 'number_of_hours': 188})
    reject('officer_cannot_read_unrelated_department_parent', lambda: rpc(users['payroll_officer'], 'hr.payslip', 'read', [[slip.id], ['name']]))
    for model, row, fields in [('hr.payslip.line', line, ['name', 'amount', 'total']),
                               ('hr.payslip.input', input_row, ['name', 'amount']),
                               ('hr.payslip.worked_days', worked, ['name', 'number_of_days', 'number_of_hours'])]:
        reject('officer_cannot_read_restricted_child_' + model, lambda m=model, r=row, fs=fields: rpc(users['payroll_officer'], m, 'read', [[r.id], fs]))
        parent_field = 'slip_id' if model == 'hr.payslip.line' else 'payslip_id'
        result = rpc(users['payroll_officer'], model, 'search_read', [[(parent_field, '=', slip.id)]], {'fields': fields})
        check('officer_restricted_child_search_hidden_' + model, not result)
    children = [('hr.payslip.line', line, ['name', 'amount', 'total']),
                ('hr.payslip.input', input_row, ['name', 'amount']),
                ('hr.payslip.worked_days', worked, ['name', 'number_of_days', 'number_of_hours'])]
    check('manager_can_read_restricted_department_parent', bool(rpc(users['payroll_manager'], 'hr.payslip', 'read', [[slip.id], ['name']])))
    for model, row, fields in children:
        check('manager_can_read_same_company_child_' + model, bool(rpc(users['payroll_manager'], model, 'read', [[row.id], fields])))
    # Preserve the existing parent policies: own employee, no department and managed department.
    manager_employee = A['hr.employee'].create({'name': 'FA2 Officer Employee', 'company_id': 6, 'user_id': users['payroll_officer'].uid})
    scenarios = [('own_employee', {'user_id': users['payroll_officer'].uid}, False),
                 ('no_department', {'user_id': False, 'department_id': False}, False),
                 ('managed_department', {'department_id': dept.id}, True)]
    for label, values, managed in scenarios:
        # Odoo allows only one employee per user/company, so temporarily release the manager link.
        if label == 'own_employee':
            manager_employee.user_id = False
        employee.write(values)
        if managed:
            manager_employee.user_id = users['payroll_officer'].uid
            dept.manager_id = manager_employee
        check('officer_parent_scope_' + label, bool(rpc(users['payroll_officer'], 'hr.payslip', 'read', [[slip.id], ['name']])))
        for model, row, fields in children:
            check('officer_child_scope_' + label + '_' + model, bool(rpc(users['payroll_officer'], model, 'read', [[row.id], fields])))
    check('correct_contribution_handler_registered', 'report.om_hr_payroll.report_contribution_register' in env.registry)
    check('incorrect_contribution_handler_not_registered', 'report.om_om_hr_payroll.report_contribution_register' not in env.registry)
    reject('officer_cannot_write_salary_child', lambda: rpc(users['payroll_officer'], 'hr.payslip.line', 'write', [[line.id], {'amount': 1}]))
    reject('hr_without_payroll_cannot_read_salary_child', lambda: rpc(users['hr'], 'hr.payslip.line', 'read', [[line.id], ['amount']]))
    reject('officer_cannot_read_version_wage', lambda: rpc(users['payroll_officer'], 'hr.version', 'read', [[employee.version_id.id], ['wage']]))
    R['status'] = 'completed'
except Exception:
    R['status'] = 'error'
    R['traceback'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    check('all_audit_database_writes_rolled_back', fingerprint() == before)
    R['check_count'] = len(R['checks'])
    R['failed_checks'] = [r['name'] for r in R['checks'] if not r['passed']]
    Path('/mnt/qa-evidence/security-result.json').write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in R.items() if k not in ('checks', 'observations')}, ensure_ascii=False))
