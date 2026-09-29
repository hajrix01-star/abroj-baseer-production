"""Native QA integration checks; all test business records roll back."""
import json
import time
from pathlib import Path
from odoo import Command
from odoo.exceptions import ValidationError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
checks = []
started = time.monotonic()
def check(label, value):
    assert value, label
    checks.append(label)

try:
    sa = env.ref('base.sa')
    companies = env['res.company'].create([
        {'name': 'QA Payment Seed A', 'country_id': sa.id, 'currency_id': sa.currency_id.id},
        {'name': 'QA Payment Seed B', 'country_id': sa.id, 'currency_id': sa.currency_id.id}])
    admin = env.ref('base.user_admin')
    admin.company_ids |= companies
    def hr_fingerprint():
        result = {}
        for table in ('hr_employee','hr_version','resource_resource','res_partner'):
            env.flush_all()
            env.cr.execute('SELECT md5(coalesce(string_agg(row_to_json(t)::text,\'\' ORDER BY id),\'\')) FROM ' + table + ' t')
            result[table] = env.cr.fetchone()[0]
        return result
    protected = hr_fingerprint()
    env.cr.precommit.run()
    after_callback = hr_fingerprint()
    print('CALLBACK_CHANGED', [name for name in protected if protected[name] != after_callback[name]], flush=True)
    check('seed does not create cashier employees', all(protected[name] == after_callback[name] for name in ('hr_employee','hr_version','resource_resource')))
    configs = env['pos.config']
    for company in companies:
        co = company.with_company(company).with_context(allowed_company_ids=company.ids)
        config = co._baseer_pos_identity('config', 'pos.config')
        check('automatic company callback ' + company.name, bool(config))
        config._validate_baseer_setup()
        check('five valid methods ' + company.name, len(config.payment_method_ids) == 5)
        check('native manager group default retained ' + company.name, config.group_pos_manager_id == env.ref('point_of_sale.group_pos_manager'))
        check('summary POS never provisions cashier employees ' + company.name, not config._get_group_pos_manager())
        check('bilingual methods ' + company.name, all(' | ' in m.name for m in config.payment_method_ids))
        apps = config.payment_method_ids.filtered(lambda m: m.baseer_category_id.kind == 'platform')
        check('three distinct application receivables ' + company.name,
              len(apps.outstanding_account_id) == 3 and all(a.account_type == 'asset_current' and a.reconcile for a in apps.outstanding_account_id))
        models = ['account.account', 'account.journal', 'pos.config', 'pos.payment.method', 'baseer.pos.payment.category']
        before = {m: co.env[m].with_context(active_test=False).search_count([]) for m in models}
        co._baseer_prepare_accounting()
        co._baseer_seed_pos_payments()
        check('repeat initialization creates nothing ' + company.name,
              all(co.env[m].with_context(active_test=False).search_count([]) == n for m,n in before.items()))
        defaults = co.env['baseer.pos.day.entry'].default_get(['first_allocation_ids','second_allocation_ids'])
        check('both shift grids contain five methods ' + company.name,
              all(len(defaults[f]) == 5 for f in ['first_allocation_ids','second_allocation_ids']))
        configs |= config
    check('company isolation', len(configs.payment_method_ids) == 10 and len(configs.payment_method_ids.outstanding_account_id) == 8)
    config = configs[0]
    co = config.company_id.with_company(config.company_id).with_context(allowed_company_ids=config.company_id.ids)
    config = co.env['pos.config'].browse(config.id)
    check('test reproduces manager without employee in existing company', not co.env['hr.employee'].search_count([('company_id','=',co.id),('user_id','=',admin.id)]))
    env['ir.model.data'].search([('module','=','baseer_pos_summary'),('name','=',f'payment_seed_config_company_{co.id}')]).unlink()
    protected_existing = hr_fingerprint()
    co._baseer_seed_pos_payments()
    check('existing company reseed preserves every HR/resource/partner row', hr_fingerprint() == protected_existing)
    ordinary = co.env['pos.config'].new({'baseer_summary_only':False,'company_id':co.id})
    check('ordinary POS retains native manager lookup', ordinary._get_group_pos_manager() == env.ref('point_of_sale.group_pos_manager'))
    check('empty default lookup retains native manager group', co.env['pos.config']._get_group_pos_manager() == env.ref('point_of_sale.group_pos_manager'))
    amounts = {m.id: 115 for m in config.payment_method_ids}
    summary = co.env['baseer.pos.summary'].create({'business_date': '2026-09-01', 'customer_count': 5,
        'period_scope': 'all', 'day_schedule': 'all',
        'allocation_ids': [Command.create({'payment_method_id': m.id, 'amount': amounts[m.id]}) for m in config.payment_method_ids]})
    summary.action_approve()
    check('native summary approved and balanced', summary.state == 'approved' and all(abs(sum(move.line_ids.mapped('balance'))) < 0.001 for move in summary._native_moves()))
    check('native revenue and VAT', summary.amount_gross == 575 and summary.amount_tax == 75)
    entries = summary._native_moves().line_ids
    for m in config.payment_method_ids:
        account = m.journal_id.default_account_id if m.is_cash_count else m.outstanding_account_id
        balance = sum(entries.filtered(lambda l: l.account_id == account).mapped('balance'))
        check('correct account debit ' + m.name, round(balance, 2) == 115)
    bank = config.payment_method_ids.filtered(lambda m: m.baseer_category_id.kind == 'bank')
    check('platforms do not inflate bank balance', round(sum(entries.filtered(lambda l: l.account_id == bank.outstanding_account_id).mapped('balance')),2) == 115)
    posted_ids = summary._native_moves().ids
    co._baseer_seed_pos_payments()
    summary.action_approve()
    check('rerun and approval do not duplicate ledger', summary._native_moves().ids == posted_ids)
    method = config.payment_method_ids.filtered(lambda m: m.baseer_category_id.kind == 'platform')[0]
    method.write({'name': 'مخصص | Custom', 'active': False})
    co._baseer_seed_pos_payments()
    check('customized archived seed preserved', not method.active and method.name == 'مخصص | Custom')
    branch = env['res.company'].create({'name': 'QA Payment Branch', 'parent_id': companies[0].id})
    branch._baseer_seed_pos_payments()
    check('branch does not get duplicate independent POS', not env['pos.config'].search_count([('company_id','=',branch.id),('baseer_summary_only','=',True)]))
    admin = env.ref('base.user_admin')
    check('actual administrator has company-create access', admin.id != 1)
    user_company = env['res.company'].with_user(admin).create({
        'name': 'QA Payment Creator', 'country_id': sa.id, 'currency_id': sa.currency_id.id})
    env.cr.precommit.run()
    user_config = env['pos.config'].search([('company_id','=',user_company.id),('baseer_summary_only','=',True)])
    check('non-superuser creation callback seeds five methods', len(user_config.payment_method_ids) == 5)
    # Deferred legacy setup must not make an unrelated company impossible to initialize.
    other = configs[1].with_company(companies[1]).with_context(allowed_company_ids=companies[1].ids)
    marker = env['ir.model.data'].search([('module','=','baseer_pos_summary'),('name','=',f'payment_seed_config_company_{companies[1].id}')])
    marker.unlink()
    co2 = other.company_id.with_company(other.company_id).with_context(allowed_company_ids=other.company_id.ids)
    draft = co2.env['baseer.pos.summary'].create({'business_date':'2026-09-02','customer_count':1,
        'allocation_ids':[Command.create({'payment_method_id':other.payment_method_ids[0].id,'amount':115})]})
    other.payment_method_ids[0].active = False
    existing_ids = other.with_context(active_test=False).payment_method_ids.ids
    co2._baseer_seed_pos_payments()
    check('invalid historical config deferred without changing methods', other.with_context(active_test=False).payment_method_ids.ids == existing_ids)
    bank2 = other.payment_method_ids.filtered(lambda m: m.baseer_category_id.kind == 'bank')[0]
    many = co2.env['pos.payment.method'].create([{
        'name': 'QA Bank %s' % i, 'company_id':co2.id, 'journal_id':bank2.journal_id.id,
        'baseer_category_id':bank2.baseer_category_id.id, 'receivable_account_id':bank2.receivable_account_id.id,
        'outstanding_account_id':bank2.outstanding_account_id.id, 'payment_method_type':'none'} for i in range(22)])
    other.payment_method_ids = many
    other._validate_baseer_setup()
    co2._baseer_seed_pos_payments()
    check('capacity includes missing cash baseline', other.payment_method_ids == many and not co2._baseer_pos_identity('config','pos.config'))
    result = {'status': 'PASS', 'count': len(checks), 'checks': checks, 'seconds': round(time.monotonic()-started,2)}
    Path('/mnt/qa-evidence/payment-seed-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('PAYMENT_SEED_PASS',len(checks),flush=True)
finally:
    env.cr.rollback()
