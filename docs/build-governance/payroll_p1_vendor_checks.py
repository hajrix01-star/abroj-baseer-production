"""Vendor characterization only. Run in QA Odoo shell; every fixture rolls back."""
import json
import traceback
from pathlib import Path
from unittest.mock import patch

results = {'scope': 'vendor characterization, not acceptance', 'checks': [], 'mail_calls_suppressed': 0}

def check(name, value, detail=None):
    results['checks'].append({'name': name, 'observed': bool(value), 'detail': detail})
    assert value, name

def suppress_mail(*args, **kwargs):
    results['mail_calls_suppressed'] += 1
    return False

try:
    with patch.object(type(env['mail.template']), 'send_mail', suppress_mail), patch.object(type(env['mail.mail']), 'send', suppress_mail):
        company = env['res.company'].browse(6)
        E = env(context=dict(env.context, allowed_company_ids=[company.id], tracking_disable=True, mail_create_nolog=True))
        expense = E['account.account'].create({'name': 'QA payroll expense rollback', 'code': '998871', 'account_type': 'expense', 'company_ids': [(6, 0, company.ids)]})
        liability = E['account.account'].create({'name': 'QA payroll liability rollback', 'code': '998872', 'account_type': 'liability_current', 'company_ids': [(6, 0, company.ids)]})
        journal = E['account.journal'].create({'name': 'QA payroll rollback', 'code': 'QPY1', 'type': 'general', 'company_id': company.id, 'default_account_id': liability.id})
        employee = E['hr.employee'].create({'name': 'QA payroll vendor rollback', 'company_id': company.id, 'work_email': 'payroll-fixture@example.invalid'})
        version = E['hr.version'].search([('employee_id', '=', employee.id)], limit=1)
        if not version:
            version = E['hr.version'].create({'employee_id': employee.id, 'date_version': '2026-09-01'})
        category = E['hr.salary.rule.category'].create({'name': 'QA Net', 'code': 'NET', 'company_id': company.id})
        rule = E['hr.salary.rule'].create({'name': 'QA fixed net', 'code': 'NET', 'category_id': category.id, 'company_id': company.id, 'amount_select': 'fix', 'amount_fix': 1000, 'account_debit_id': expense.id, 'account_credit_id': liability.id})
        structure = E['hr.payroll.structure'].create({'name': 'QA fixed structure', 'code': 'QAVENDOR', 'company_id': company.id, 'parent_id': False, 'rule_ids': [(6, 0, rule.ids)]})
        version.write({'struct_id': structure.id})
        slip = E['hr.payslip'].create({'name': 'QA salary vendor rollback', 'employee_id': employee.id, 'company_id': company.id, 'contract_id': version.id, 'struct_id': structure.id, 'journal_id': journal.id, 'date_from': '2026-09-01', 'date_to': '2026-09-30'})
        try:
            with E.cr.savepoint():
                slip.action_payslip_done()
        except AttributeError as exc:
            check('BLOCKER shipped approval fails missing net_wage', 'net_wage' in str(exc), str(exc))
        else:
            raise AssertionError('Expected shipped missing net_wage blocker changed')
        # TEST PROCESS ONLY: bypass the missing attribute to expose downstream behavior.
        # No vendor source, registry field or persistent data is changed by this patch.
        net_patch = patch.object(type(slip), 'net_wage', 1000.0, create=True)
        net_patch.start()
        results['downstream_test_only_shim'] = 'temporary class net_wage=1000; first unmodified call failed'
        slip.action_payslip_done()
        first = slip.move_id
        check('native salary first approval posts 1000', first.state == 'posted' and sum(first.line_ids.mapped('debit')) == 1000, {'move_id': first.id})
        slip.action_payslip_done()
        second = slip.move_id
        check('DEFECT repeated approval posts another 1000 and overwrites link', second != first and first.state == second.state == 'posted' and sum(second.line_ids.mapped('debit')) == 1000, {'first': first.id, 'second': second.id})
        slip.write({'date_to': '2026-09-29'})
        check('DEFECT posted payslip source date remains writable', str(slip.date_to) == '2026-09-29' and second.state == 'posted')
        loan = E['hr.loan'].create({'employee_id': employee.id, 'company_id': company.id, 'currency_id': company.currency_id.id, 'loan_amount': 100, 'installment': 1, 'payment_date': '2026-09-15'})
        loan.action_compute_installment()
        loan.action_submit()
        check('loan submit reaches submitted with mail hooks intercepted', loan.state == 'waiting_approval_1')
        loan.loan_lines.write({'paid': True})
        loan.action_cancel()
        check('DEFECT loan cancel retains paid flag', loan.state == 'cancel' and all(loan.loan_lines.mapped('paid')))
        check('mail transport never executed', results['mail_calls_suppressed'] > 0, results['mail_calls_suppressed'])
        # Characterize native posted-cancel outcome without leaving an error transaction.
        try:
            with E.cr.savepoint():
                slip.action_payslip_cancel()
                results['cancel_outcome'] = {'state': slip.state, 'latest_move_exists': bool(second.exists()), 'earlier_move_exists': bool(first.exists())}
        except Exception as exc:
            results['cancel_outcome'] = {'error_type': type(exc).__name__, 'error': str(exc)}
        results['status'] = 'characterization_complete'
except Exception:
    results['status'] = 'fixture_failed'
    results['error'] = traceback.format_exc()
finally:
    if 'net_patch' in globals():
        net_patch.stop()
    env.cr.rollback()
    results['rolled_back'] = True
    Path('/mnt/qa-evidence/payroll_p1_vendor_checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))
