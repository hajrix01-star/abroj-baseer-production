"""FA2 native contribution action, handler and full HTML/PDF rendering regression."""
import json, traceback
from pathlib import Path
from odoo import api, Command
from odoo.service.model import call_kw
from odoo.addons.baseer_payroll.models.common import INTERNAL

assert env.cr.dbname == 'baseer_fix_security_20260909'
R = {'database': env.cr.dbname, 'status': 'started', 'checks': [],
     'fixture_limit': 'Synthetic approved-state formatter fixture uses the private in-process capability; it is not a payroll posting or accounting calculation test.'}
def check(name, value, evidence=None): R['checks'].append({'name': name, 'passed': bool(value), 'evidence': evidence})
def fp():
    result = {}
    for table in ('res_users', 'res_partner', 'hr_employee', 'hr_payslip', 'hr_payslip_line', 'hr_contribution_register', 'account_move', 'account_move_line'):
        env.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,\'\' ORDER BY id),\'\')) FROM ' + table + ' t')
        result[table] = env.cr.fetchone()
    return result
before = fp()
try:
    A = api.Environment(env.cr, env.ref('base.user_admin').id, {'allowed_company_ids': [6], 'lang': 'en_US', 'tracking_disable': True})
    manager = A['res.users'].create({'name': 'FA2 Report Manager', 'login': 'fa2.security.report.manager',
        'company_id': 6, 'company_ids': [Command.set([6])],
        'group_ids': [Command.set([A.ref('base.group_user').id, A.ref('om_hr_payroll.group_hr_payroll_manager').id])]})
    E = api.Environment(env.cr, manager.id, {'allowed_company_ids': [6], 'lang': 'en_US'})
    employee = A['hr.employee'].create({'name': 'FA2 Contribution Employee', 'company_id': 6})
    register = A['hr.contribution.register'].create({'name': 'FA2 Contribution Register', 'company_id': 6})
    category = A['hr.salary.rule.category'].create({'name': 'FA2 Contribution Category', 'code': 'FA2C', 'company_id': 6})
    rule = A['hr.salary.rule'].create({'name': 'FA2 Contribution Rule', 'code': 'FA2C', 'company_id': 6,
        'category_id': category.id, 'register_id': register.id, 'amount_select': 'fix'})
    slip = A['hr.payslip'].create({'name': 'FA2 Contribution Payslip', 'employee_id': employee.id,
        'version_id': employee.version_id.id, 'company_id': 6, 'date_from': '2026-08-01', 'date_to': '2026-08-31'})
    line = A['hr.payslip.line'].create({'slip_id': slip.id, 'salary_rule_id': rule.id, 'company_id': 6,
        'name': 'FA2 Render Contribution', 'code': 'FA2C', 'category_id': category.id,
        'register_id': register.id, 'amount': 239.70, 'quantity': 1})
    # No financial posting is needed to isolate the report namespace/formatter.
    slip.with_context(baseer_payroll_internal=INTERNAL).write({'state': 'done'})
    env.flush_all()
    wizard = E['payslip.lines.contribution.register'].create({'date_from': '2026-08-01', 'date_to': '2026-08-31'})
    context = {'allowed_company_ids': [6], 'active_ids': [register.id], 'active_model': 'hr.contribution.register'}
    action = call_kw(E[wizard._name], 'print_report', [[wizard.id]], {'context': context})
    check('nonadmin_native_report_action', action['report_name'] == 'om_hr_payroll.report_contribution_register')
    check('report_handler_matches_action', 'report.' + action['report_name'] in E.registry)
    report = E['ir.actions.report'].with_context(context)
    values = E['report.om_hr_payroll.report_contribution_register'].with_context(context)._get_report_values([], action['data'])
    check('full_report_contains_selected_line', values['lines_data'][register.id].ids == line.ids)
    check('full_report_total_239_70', round(values['lines_total'][register.id], 2) == 239.70)
    for language in ('en_US', 'ar_001'):
        rendered = report.with_context(lang=language)
        html, _kind = rendered._render_qweb_html(action['report_name'], [], data=action['data'])
        check('html_contains_real_fixture_' + language, b'FA2 Render Contribution' in html and b'239.70' in html)
        pdf, kind = rendered._render_qweb_pdf(action['report_name'], [], data=action['data'])
        check('full_native_pdf_' + language, kind == 'pdf' and pdf.startswith(b'%PDF-') and len(pdf) > 1000, {'bytes': len(pdf)})
        Path('/mnt/qa-evidence/security-contribution-' + language + '.pdf').write_bytes(pdf)
        Path('/mnt/qa-evidence/security-contribution-' + language + '.html').write_bytes(html)
    R['status'] = 'completed'
except Exception:
    R['status'] = 'error'; R['traceback'] = traceback.format_exc()
finally:
    env.cr.rollback(); env.invalidate_all()
    check('report_fixtures_fully_rolled_back', before == fp())
    R['failed_checks'] = [x['name'] for x in R['checks'] if not x['passed']]
    Path('/mnt/qa-evidence/security-report-render-result.json').write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in R.items() if k != 'checks'}, ensure_ascii=False))
