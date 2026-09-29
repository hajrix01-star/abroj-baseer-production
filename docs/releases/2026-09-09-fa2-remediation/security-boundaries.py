"""FA2 RPC boundary regression, exclusively on disposable security clone."""
import json, traceback
from pathlib import Path
from odoo import api, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.service.model import call_kw

assert env.cr.dbname == 'baseer_fix_security_20260909'
R = {'database': env.cr.dbname, 'status': 'started', 'checks': [], 'observations': []}
def check(n, v, evidence=None): R['checks'].append({'name': n, 'passed': bool(v), 'evidence': evidence})
def reject(n, fn):
    try:
        with env.cr.savepoint(): value = fn()
    except (AccessError, UserError, ValidationError) as error: check(n, True, type(error).__name__)
    else: check(n, False, str(value)[:300])
def rpc(E, model, method, args, kwargs=None): return call_kw(E[model], method, args, kwargs or {})
def fingerprint():
    out = {}
    for t in ('res_users', 'hr_employee', 'hr_payslip', 'hr_payslip_line', 'baseer_purchase_batch', 'baseer_pos_summary', 'baseer_pos_closure', 'account_move', 'account_move_line'):
        env.cr.execute('SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,\'\' ORDER BY id),\'\')) FROM ' + t + ' t')
        out[t] = env.cr.fetchone()
    return out
before = fingerprint()
try:
    admin = env.ref('base.user_admin').id
    def ce(cid, uid=admin): return api.Environment(env.cr, uid, {'allowed_company_ids': [cid], 'lang': 'en_US', 'tracking_disable': True})
    A, B = ce(6), ce(10)
    def user(name, groups, companies=(6,)):
        u = A['res.users'].create({'name': 'Security Boundary ' + name, 'login': 'security.boundary.' + name,
            'company_id': companies[0], 'company_ids': [Command.set(companies)],
            'group_ids': [Command.set([A.ref(g).id for g in set(groups) | {'base.group_user'}])]})
        return ce(companies[0], u.id)
    P = user('pos', ['point_of_sale.group_pos_user'])
    O = user('officer', ['om_hr_payroll.group_hr_payroll_user'])
    I = user('invoice', ['account.group_account_invoice'])
    H = user('hr', ['hr.group_hr_user'])
    M = user('multi', ['hr.group_hr_manager', 'account.group_account_manager', 'point_of_sale.group_pos_manager', 'om_hr_payroll.group_hr_payroll_manager'], (6, 10))
    config = A['pos.config'].search([('company_id', '=', 6), ('baseer_summary_only', '=', True)], limit=1)
    R['observations'].append({'name': 'pos_fixture_config_exists', 'exists': bool(config)})
    if config:
        summary_id = rpc(P, 'baseer.pos.summary', 'create', [{'config_id': config.id, 'business_date': '2024-01-22', 'period_scope': 'all', 'day_schedule': 'all', 'zero_sales': True}])
        check('pos_user_can_create_draft_summary', bool(summary_id))
        reject('pos_user_without_invoice_cannot_approve', lambda: rpc(P, 'baseer.pos.summary', 'action_approve', [[summary_id]]))
        reject('pos_user_cannot_archive', lambda: rpc(P, 'baseer.pos.summary', 'action_archive', [[summary_id]]))
        reject('pos_user_cannot_forge_approved_state', lambda: rpc(P, 'baseer.pos.summary', 'write', [[summary_id], {'state': 'approved'}], {'context': {'baseer_pos_internal': True}}))
        reject('summary_cannot_change_company', lambda: rpc(M, 'baseer.pos.summary', 'write', [[summary_id], {'company_id': 10}]))
        reject('hr_user_cannot_read_sales_summary', lambda: rpc(H, 'baseer.pos.summary', 'read', [[summary_id], ['amount_gross']]))
        reject('pos_native_session_cannot_forge_summary_link', lambda: rpc(P, 'pos.session', 'create', [{'config_id': config.id, 'baseer_summary_id': summary_id}]))
        # Cleaned defaults should create a draft, so record the actual state separately.
        sid = rpc(P, 'baseer.pos.summary', 'create', [{'config_id': config.id, 'business_date': '2024-01-24', 'zero_sales': True}], {'context': {'default_state': 'approved', 'default_order_id': 999999}})
        check('caller_default_state_and_link_are_discarded', A['baseer.pos.summary'].browse(sid).state == 'draft' and not A['baseer.pos.summary'].browse(sid).order_id)
    closure = rpc(P, 'baseer.pos.closure', 'create', [{'date_from': '2024-02-02', 'date_to': '2024-02-02', 'reason': 'maintenance'}])
    rpc(P, 'baseer.pos.closure', 'action_confirm', [[closure]])
    check('policy_pos_user_can_confirm_closure', A['baseer.pos.closure'].browse(closure).state == 'confirmed')
    reject('pos_user_cannot_cancel_confirmed_closure', lambda: rpc(P, 'baseer.pos.closure', 'action_cancel', [[closure]]))
    foreign_closure = B['baseer.pos.closure'].create({'date_from': '2024-02-03', 'date_to': '2024-02-03'})
    reject('pos_user_cannot_read_other_company_closure', lambda: rpc(P, 'baseer.pos.closure', 'read', [[foreign_closure.id], ['date_from']]))
    reject('inactive_allowed_company_closure_mutation_rejected', lambda: rpc(M, 'baseer.pos.closure', 'write', [[foreign_closure.id], {'notes': 'Security scope probe'}], {'context': {'allowed_company_ids': [6, 10]}}))
    provider = A.ref('baseer_service_seed.provider_passports')
    mapping = A.ref('baseer_service_seed.mapping_iqama_issue_company_6')
    provider.baseer_purchase_category_map_id = mapping
    vals = {'line_ids': [Command.create({'partner_id': provider.id, 'category_map_id': mapping.id,
        'supplier_ref': 'SECURITY-BOUNDARY-ONLY', 'invoice_date': '2026-09-01', 'gross_amount': 50, 'is_credit': True})]}
    try:
        with env.cr.savepoint():
            batch = rpc(I, 'baseer.purchase.batch', 'create', [vals])
        check('invoice_operator_can_create_with_service_default', A['baseer.purchase.batch'].browse(batch).line_ids.entry_type == 'expense')
    except AccessError as error:
        check('invoice_operator_can_create_with_service_default', False, str(error))
    supplier_default_vals = {'line_ids': [Command.create({k:v for k,v in vals['line_ids'][0][2].items() if k != 'category_map_id'})]}
    try:
        with env.cr.savepoint():
            default_batch = rpc(I, 'baseer.purchase.batch', 'create', [supplier_default_vals])
        check('invoice_operator_supplier_default_category_create_works', A['baseer.purchase.batch'].browse(default_batch).line_ids.entry_type == 'expense')
    except AccessError as error:
        check('invoice_operator_supplier_default_category_create_works', False, str(error))
    vals['line_ids'][0][2]['entry_type'] = 'expense'
    batch = rpc(I, 'baseer.purchase.batch', 'create', [vals])
    check('invoice_operator_explicit_entry_type_create_works', bool(batch))
    for changed in ('category_map_id', 'partner_id'):
        try:
            with env.cr.savepoint():
                result = rpc(I, 'baseer.purchase.batch.line', 'onchange', [[],
                    {'batch_id': batch, 'partner_id': provider.id, 'category_map_id': mapping.id, 'entry_type': 'purchase', 'gross_amount': 50, 'is_credit': True},
                    [changed], {'entry_type': {}, 'category_map_id': {}, 'partner_id': {}}])
            check('invoice_operator_onchange_' + changed + '_works', result.get('value', {}).get('entry_type') == 'expense', result)
        except AccessError as error:
            check('invoice_operator_onchange_' + changed + '_works', False, str(error))
    reject('hr_user_cannot_read_purchase_batch', lambda: rpc(H, 'baseer.purchase.batch', 'read', [[batch], ['name']]))
    reject('invoice_user_cannot_forge_batch_state', lambda: rpc(I, 'baseer.purchase.batch', 'write', [[batch], {'state': 'approved'}]))
    reject('batch_company_immutable', lambda: rpc(M, 'baseer.purchase.batch', 'write', [[batch], {'company_id': 10}]))
    reject('invoice_user_cannot_forge_bill_link', lambda: rpc(I, 'baseer.purchase.batch.line', 'write', [A['baseer.purchase.batch'].browse(batch).line_ids.ids, {'move_id': 999999}]))
    e = B['hr.employee'].create({'name': 'Security Boundary Foreign Employee', 'company_id': 10})
    slip = B['hr.payslip'].create({'name': 'Security Boundary Foreign Slip', 'employee_id': e.id, 'version_id': e.version_id.id, 'company_id': 10, 'date_from': '2026-08-01', 'date_to': '2026-08-31'})
    rule = B['hr.salary.rule'].search([('company_id', '=', 10)], limit=1)
    line = B['hr.payslip.line'].create({'slip_id': slip.id, 'salary_rule_id': rule.id,
        'name': 'Security Boundary Foreign Salary', 'code': 'SEC_FOREIGN', 'company_id': 10,
        'category_id': rule.category_id.id, 'amount': 6543.21})
    reject('officer_cannot_read_foreign_company_salary_child', lambda: rpc(O, 'hr.payslip.line', 'read', [[line.id], ['amount']]))
    check('foreign_company_child_search_hidden', not rpc(O, 'hr.payslip.line', 'search_read', [[('id', '=', line.id)]], {'fields': ['amount']}))
    # Manager allowance must still intersect the global company rule.
    limited_manager = user('limited_manager', ['om_hr_payroll.group_hr_payroll_manager'])
    reject('manager_cannot_read_foreign_company_salary_child', lambda: rpc(limited_manager, 'hr.payslip.line', 'read', [[line.id], ['amount']]))
    check('manager_foreign_company_child_search_hidden', not rpc(limited_manager, 'hr.payslip.line', 'search_read', [[('id', '=', line.id)]], {'fields': ['amount']}))
    # Capture deployed ACL/rules as evidence, no user/employee business data.
    models = ['hr.payslip', 'hr.payslip.line', 'hr.payslip.input', 'hr.payslip.worked_days']
    R['rules'] = A['ir.rule'].sudo().search([('model_id.model', 'in', models)]).read(['name', 'domain_force', 'groups', 'perm_read', 'active'])
    R['status'] = 'completed'
except Exception:
    R['status'] = 'error'; R['traceback'] = traceback.format_exc()
finally:
    env.cr.rollback(); env.invalidate_all()
    check('all_boundary_database_writes_rolled_back', before == fingerprint())
    R['check_count'] = len(R['checks']); R['failed_checks'] = [x['name'] for x in R['checks'] if not x['passed']]
    Path('/mnt/qa-evidence/security-boundaries-result.json').write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in R.items() if k not in ('checks','rules','observations')}, ensure_ascii=False))
