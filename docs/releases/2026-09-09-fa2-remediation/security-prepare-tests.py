"""Copy the frozen FA1 reproductions into FA2 without altering FA1 evidence."""
from pathlib import Path

root = Path(__file__).resolve().parents[3]
source = root / 'docs/audits/2026-09-09-full'
target = Path(__file__).parent

for filename in ('security-runtime.py', 'security-boundaries.py'):
    text = (source / filename).read_text(encoding='utf-8')
    text = text.replace('baseer_audit_security_20260909', 'baseer_fix_security_20260909')
    text = text.replace('Independent security audit', 'FA2 security remediation regression')
    text = text.replace('Second independent RPC boundary matrix', 'FA2 RPC boundary regression')
    if filename == 'security-runtime.py':
        text = text.replace("R['observations'].append({'name': 'restricted_child_search_read_' + model, 'rows': result})", "check('officer_restricted_child_search_hidden_' + model, not result)")
        anchor = "    reject('officer_cannot_write_salary_child'"
        insertion = '''    children = [('hr.payslip.line', line, ['name', 'amount', 'total']),
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
'''
        assert anchor in text
        text = text.replace(anchor, insertion + anchor)
    else:
        anchor = "    # Capture deployed ACL/rules as evidence, no user/employee business data."
        insertion = '''    # Manager allowance must still intersect the global company rule.
    limited_manager = user('limited_manager', ['om_hr_payroll.group_hr_payroll_manager'])
    reject('manager_cannot_read_foreign_company_salary_child', lambda: rpc(limited_manager, 'hr.payslip.line', 'read', [[line.id], ['amount']]))
    check('manager_foreign_company_child_search_hidden', not rpc(limited_manager, 'hr.payslip.line', 'search_read', [[('id', '=', line.id)]], {'fields': ['amount']}))
'''
        assert anchor in text
        text = text.replace(anchor, insertion + anchor)
        # The FA1 error path remains as a regression failure; now require the actual suggestion.
        text = text.replace("check('invoice_operator_onchange_' + changed + '_works', True)", "check('invoice_operator_onchange_' + changed + '_works', result.get('value', {}).get('entry_type') == 'expense', result)")
        text = text.replace("check('invoice_operator_can_create_with_service_default', True)", "check('invoice_operator_can_create_with_service_default', A['baseer.purchase.batch'].browse(batch).line_ids.entry_type == 'expense')")
        text = text.replace("check('invoice_operator_supplier_default_category_create_works', True)", "check('invoice_operator_supplier_default_category_create_works', A['baseer.purchase.batch'].browse(default_batch).line_ids.entry_type == 'expense')")
    (target / filename).write_text(text, encoding='utf-8')
print('FA2 security regressions generated; FA1 source and evidence unchanged')
