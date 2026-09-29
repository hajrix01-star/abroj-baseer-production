"""CAS1 native integration checks. QA only, one transaction, always rollback."""
import json
import time
import traceback
from pathlib import Path
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.service.model import get_public_method
from odoo.addons.baseer_payroll.models.common import money

TARGET = 'baseer_reports_qa_20260907'
if env.cr.dbname != TARGET:
    raise RuntimeError('Company seed checks are restricted to the QA database')
R = {'status': 'started', 'checks': [], 'timings_seconds': {}}
OUTPUT = Path('/mnt/qa-evidence/company_accounting_seed_checks.json')
FIELDS = ['baseer_salary_expense_id', 'baseer_salary_payable_id', 'baseer_deduction_account_id',
          'baseer_loan_account_id', 'baseer_payroll_journal_id', 'baseer_eos_expense_id', 'baseer_eos_journal_id']


def check(name, condition):
    R['checks'].append({'name': name, 'passed': bool(condition)})
    assert condition, name


def blocked(name, operation):
    try:
        with env.cr.savepoint():
            operation()
    except (AccessError, UserError, ValidationError):
        check(name, True)
    else:
        check(name, False)


class FixtureRollback(Exception):
    pass


def isolated(operation):
    try:
        with env.cr.savepoint():
            operation()
            raise FixtureRollback()
    except FixtureRollback:
        pass


def snapshot(company):
    C = company.env
    return {'chart': company.chart_template, 'country': company.country_id.id, 'currency': company.currency_id.id,
            'settings': {field: company[field].id for field in FIELDS},
            'accounts': C['account.account'].with_context(active_test=False).search([('company_ids', 'in', company.id)]).ids,
            'journals': C['account.journal'].with_context(active_test=False).search([('company_id', '=', company.id)]).ids,
            'taxes': C['account.tax'].with_context(active_test=False).search([('company_id', '=', company.id)]).ids}


def validate_defaults(company, name):
    check(name + '_seven_references', all(company[field] for field in FIELDS))
    for field in FIELDS:
        record = company[field]
        owner_ok = company in record.company_ids if record._name == 'account.account' else record.company_id == company
        check(name + '_' + field + '_owned', owner_ok)
    check(name + '_salary_payable_reconcilable', company.baseer_salary_payable_id.account_type == 'liability_payable'
          and company.baseer_salary_payable_id.reconcile)
    check(name + '_advance_receivable_reconcilable', company.baseer_loan_account_id.account_type == 'asset_receivable'
          and company.baseer_loan_account_id.reconcile)
    check(name + '_expense_types', all(company[field].account_type.startswith('expense')
          for field in ['baseer_salary_expense_id', 'baseer_eos_expense_id']))
    check(name + '_journal_types', company.baseer_payroll_journal_id.type == 'general' and company.baseer_eos_journal_id.type == 'purchase')


try:
    E = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids': [10], 'lang': 'en_US',
        'active_test': False, 'tracking_disable': True, 'mail_notrack': True,
        'mail_create_nosubscribe': True, 'mail_notify_force_send': False}, su=False)
    original_companies = E['res.company'].search([('parent_id', '=', False)])
    check('six_existing_independent_companies', len(original_companies) == 6)
    # Test operator company membership is fixture-only and is rolled back.
    E.user.write({'company_ids': [(4, company.id) for company in original_companies]})
    original = {}
    for company in original_companies:
        company = company.with_company(company)
        validate_defaults(company, 'existing_' + str(company.id))
        original[company.id] = snapshot(company)
    original_moves = set(E['account.move'].sudo().search([]).ids)
    began = time.monotonic()
    original_companies._baseer_prepare_accounting()
    R['timings_seconds']['repeat_six_existing'] = round(time.monotonic() - began, 6)
    check('existing_repeat_preserves_configuration', all(snapshot(company.with_company(company)) == original[company.id] for company in original_companies))
    check('existing_seed_creates_no_financial_documents', set(E['account.move'].sudo().search([]).ids) == original_moves)

    def create_company(name, country=None, **extra):
        values = {'name': 'CAS1 QA ' + name, 'country_id': country.id if country else False}
        if country and country.code == 'SA':
            values['currency_id'] = E.ref('base.SAR').id
        values.update(extra)
        company = E['res.company'].create(values)
        # Explicit native callback execution, not a commit. All changes roll back.
        env.cr.precommit.run()
        E.user.write({'company_ids': [(4, company.id)]})
        return company.with_company(company)

    began = time.monotonic()
    company = create_company('SA AUTOMATIC', E.ref('base.sa'))
    R['timings_seconds']['new_sa_create_and_precommit'] = round(time.monotonic() - began, 6)
    C = E(context=dict(E.context, allowed_company_ids=[company.id]))
    company = C['res.company'].browse(company.id)
    validate_defaults(company, 'new_sa')
    check('sa_chart_and_currency_native', company.chart_template == 'sa' and company.currency_id == E.ref('base.SAR'))
    journals = C['account.journal'].search([('company_id', '=', company.id), ('active', '=', True)])
    check('all_starter_journal_types', {'sale', 'purchase', 'bank', 'cash', 'general'} <= set(journals.mapped('type')))
    check('new_sa_chart_has_accounts_and_tax', bool(C['account.account'].search_count([('company_ids', 'in', company.id)])
          and C['account.tax'].search_count([('company_id', '=', company.id)])))
    liquidities = journals.filtered(lambda j: j.type in ('bank', 'cash'))
    for journal in liquidities:
        manual = journal.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')
        check('new_' + journal.type + '_native_direct_payment_ready', journal.default_account_id.account_type == 'asset_cash'
              and not journal.default_account_id.reconcile and bool(manual)
              and all(method.payment_account_id == journal.default_account_id for method in manual))
    check('automatic_seed_has_no_financial_documents', not C['account.move'].search_count([('company_id', '=', company.id)])
          and not C['account.payment'].search_count([('company_id', '=', company.id)]))
    clean = snapshot(company)
    company._baseer_prepare_accounting()
    check('new_sa_repeat_no_duplicate_accounts_journals', snapshot(company) == clean)

    bank = liquidities.filtered(lambda j: j.type == 'bank')[:1]
    method = bank.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')[:1]

    def employee(name, start, enabled):
        record = C['hr.employee'].create({'name': 'CAS1 QA ' + name, 'company_id': company.id, 'baseer_payroll_enabled': False})
        record.version_id.write({'date_version': start, 'contract_date_start': start, 'wage': 1000,
                                 'baseer_salary_mode': 'fixed', 'baseer_allowance_total': 0})
        if not record.work_contact_id:
            record.work_contact_id = C['res.partner'].create({'name': record.name, 'company_id': company.id})
        record.baseer_payroll_enabled = enabled
        return record

    worker = employee('SALARY', '2026-01-01', True)
    loan = C['baseer.hr.loan'].create({'employee_id': worker.id, 'amount': 100, 'installment_count': 1,
        'date': '2026-08-01', 'first_due_date': '2026-09-30', 'journal_id': bank.id})
    loan.action_disburse()
    check('loan_seeded_ledger_disburses_100', loan.state == 'running' and money(loan.balance) == 100
          and loan.move_id.state == 'posted' and company.baseer_loan_account_id in loan.move_id.line_ids.account_id
          and bank.default_account_id in loan.move_id.line_ids.account_id)
    run = C['hr.payslip.run'].create({'baseer_managed': True, 'baseer_month': '2026-08-01'})
    check('salary_autoload_one_employee_1000', run.slip_ids.employee_id == worker and money(run.baseer_gross) == 1000)
    run.action_approve()
    action = run.action_pay()
    pay = C[action['res_model']].browse(action['res_id'])
    pay.write({'journal_id': bank.id, 'payment_method_line_id': method.id, 'payment_date': '2026-08-31'})
    pay.action_confirm()
    check('salary_seeded_defaults_paid_1000', run.baseer_payment_state == 'paid' and money(run.baseer_paid) == 1000
          and money(run.baseer_residual) == 0 and all(p.state == 'paid' for p in pay.payment_ids))

    departed = employee('EOS', '2018-01-01', False)
    C['hr.departure.wizard'].with_context(employee_termination=True).create({
        'employee_ids': [(6, 0, departed.ids)], 'departure_reason_id': C.ref('hr.departure_fired').id,
        'departure_date': '2026-08-31', 'set_date_end': True, 'remove_related_user': False,
    }).action_register_departure()
    action = departed.action_open_departure_award()
    award = C[action['res_model']].browse(action['res_id'])
    award.write({'approval_confirmed': True, 'evidence_reference': 'CAS1 QA native departure review'})
    award.action_approve_workflow()
    bill = award.bill_id
    check('eos_uses_seeded_expense_and_purchase_journal', bill.state == 'posted' and bill.journal_id == company.baseer_eos_journal_id
          and bill.invoice_line_ids.account_id == company.baseer_eos_expense_id and money(bill.amount_tax) == 0)
    C['account.payment.register'].with_context(active_model='account.move', active_ids=bill.ids).create({
        'journal_id': bank.id, 'payment_method_line_id': method.id, 'payment_date': '2026-08-31',
        'amount': bill.amount_residual, 'group_payment': True,
    })._create_payments()
    check('eos_native_seeded_payment_paid', award.workflow_stage == 'paid' and money(bill.amount_residual) == 0
          and money(award.received_amount) == money(award.award_amount))
    check('business_flow_never_changed_seeded_settings', snapshot(company) == clean)

    # Customization checks affect synthetic records only and roll back with the suite.
    account = company.baseer_deduction_account_id
    journal = company.baseer_payroll_journal_id
    account.write({'name': 'CAS1 renamed deduction', 'active': False})
    journal.write({'name': 'CAS1 renamed payroll', 'active': False})
    configured = {field: company[field].id for field in FIELDS}
    company._baseer_prepare_accounting()
    check('renamed_archived_configured_references_preserved', not account.active and not journal.active
          and account.name == 'CAS1 renamed deduction' and journal.name == 'CAS1 renamed payroll'
          and configured == {field: company[field].id for field in FIELDS})
    account.active = True
    journal.active = True
    old_loan = company.baseer_loan_account_id
    old_code = old_loan.code
    company.baseer_loan_account_id = False
    C['ir.model.data'].search([('module', '=', 'baseer_company_setup'),
        ('name', '=', 'baseer_loan_account_id_company_' + str(company.id))]).unlink()
    company.with_context(default_company_id=10, default_name='CAS1 injected account',
                         default_active=False, default_currency_id=E.ref('base.USD').id)._baseer_prepare_accounting()
    check('account_code_collision_does_not_hijack', company.baseer_loan_account_id != old_loan
          and company.baseer_loan_account_id.code != old_code and old_loan.code == old_code
          and company.baseer_loan_account_id.active and company in company.baseer_loan_account_id.company_ids)
    company.baseer_loan_account_id = old_loan
    company._baseer_prepare_accounting()
    check('explicit_configured_account_authoritative', company.baseer_loan_account_id == old_loan)
    # An unrelated journal owns the usual payroll code; do not relabel or reuse it.
    company.baseer_payroll_journal_id = False
    C['ir.model.data'].search([('module', '=', 'baseer_company_setup'),
        ('name', '=', 'payroll_company_' + str(company.id))]).unlink()
    company._baseer_prepare_accounting()
    check('journal_code_collision_does_not_hijack', company.baseer_payroll_journal_id != journal
          and company.baseer_payroll_journal_id.code != journal.code and journal.name == 'CAS1 renamed payroll')
    def modified_payroll_type():
        remembered = company.baseer_payroll_journal_id
        remembered.write({'type': 'purchase', 'default_account_id': company.baseer_salary_expense_id.id})
        company.baseer_payroll_journal_id = False
        check('remembered_journal_fixture_changed_type', remembered.type == 'purchase')
        company._baseer_prepare_accounting()
    blocked('modified_remembered_payroll_type_requires_review', modified_payroll_type)
    def archived_payroll_mapping():
        company.baseer_payroll_journal_id.active = False
        company.baseer_payroll_journal_id = False
        company._baseer_prepare_accounting()
    blocked('archived_remembered_payroll_not_mapped', archived_payroll_mapping)
    def explicit_unused_method():
        cash = liquidities.filtered(lambda j: j.type == 'cash')[:1]
        explicit = cash.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')[:1]
        check('unused_method_fixture_has_no_moves', not C['account.move'].search_count([('journal_id', '=', cash.id)]))
        explicit.payment_account_id = bank.default_account_id
        company._baseer_prepare_accounting()
        check('unused_explicit_payment_account_preserved', explicit.payment_account_id == bank.default_account_id)
    isolated(explicit_unused_method)
    def used_empty_method():
        check('used_method_fixture_has_posted_moves', bool(C['account.move'].search_count([('journal_id', '=', bank.id), ('state', '=', 'posted')])))
        method.payment_account_id = False
        company._baseer_prepare_accounting()
        check('used_journal_empty_method_not_reconfigured', not method.payment_account_id)
    isolated(used_empty_method)

    # Native initial Saudi onboarding owns its currency conversion. This boundary
    # concerns an existing uninitialized company before the companion seed runs.
    R['native_onboarding_note'] = 'Native Saudi company onboarding can select SAR before the companion callback; existing uninitialized currency conflicts must be preserved.'
    usd = create_company('EXISTING SA USD PRESERVED')
    usd.write({'country_id': E.ref('base.sa').id, 'currency_id': E.ref('base.USD').id})
    usd_before = snapshot(usd)
    usd._baseer_prepare_accounting()
    check('empty_sa_usd_not_converted_or_loaded', usd.currency_id == E.ref('base.USD') and not usd.chart_template
          and snapshot(usd) == usd_before and not any(usd[field] for field in FIELDS))

    unknown = create_company('UNKNOWN')
    unknown_before = snapshot(unknown)
    unknown._baseer_prepare_accounting()
    check('unknown_country_uninitialized_unchanged', not unknown.country_id and not unknown.chart_template
          and snapshot(unknown) == unknown_before and not any(unknown[field] for field in FIELDS))
    unknown.country_id = E.ref('base.fr')
    foreign_before = snapshot(unknown)
    unknown._baseer_prepare_accounting()
    check('uninitialized_foreign_localization_deferred', not unknown.chart_template
          and snapshot(unknown) == foreign_before and not any(unknown[field] for field in FIELDS))
    manual = create_company('MANUAL NO CHART')
    M = manual.env
    preserved = M['account.account'].create({'name': 'CAS1 manual unused account', 'code': '999090',
        'company_ids': [(6, 0, manual.ids)], 'account_type': 'expense'})
    manual.country_id = E.ref('base.sa')
    manual._baseer_prepare_accounting()
    check('manual_no_chart_setup_not_overwritten', not manual.chart_template
          and M['account.account'].search([('company_ids', 'in', manual.id)]).ids == preserved.ids
          and not any(manual[field] for field in FIELDS))
    inactive_company = create_company('INACTIVE SHARED ACCOUNT')
    inactive_account = inactive_company.env['account.account'].create({'name': 'CAS1 inactive shared account', 'code': '999091',
        'company_ids': [(6, 0, inactive_company.ids)], 'account_type': 'expense', 'active': False})
    # Native account codes are stored per root company; prepare the second code
    # through its company context before extending the account's membership.
    inactive_account.with_company(company).write({'code': '999091'})
    inactive_account.write({'company_ids': [(4, company.id)]})
    inactive_company.country_id = E.ref('base.sa')
    inactive_before = snapshot(inactive_company)
    inactive_company._baseer_prepare_accounting()
    check('inactive_shared_manual_account_blocks_chart_load', not inactive_company.chart_template and not inactive_account.active
          and snapshot(inactive_company) == inactive_before)
    taxes_company = create_company('TAXES ONLY')
    taxes_company.country_id = E.ref('base.sa')
    T = taxes_company.env
    tax_group = T['account.tax.group'].create({'name': 'CAS1 manually prepared group', 'company_id': taxes_company.id})
    tax = T['account.tax'].create({'name': 'CAS1 manual tax', 'company_id': taxes_company.id, 'type_tax_use': 'purchase',
        'amount_type': 'percent', 'amount': 15, 'tax_group_id': tax_group.id})
    taxes_before = snapshot(taxes_company)
    taxes_company._baseer_prepare_accounting()
    check('taxes_only_manual_setup_blocks_chart_load', not taxes_company.chart_template and tax.exists()
          and snapshot(taxes_company) == taxes_before)
    branch = create_company('BRANCH', E.ref('base.sa'), parent_id=company.id)
    branch_before = snapshot(branch)
    branch._baseer_prepare_accounting()
    check('branch_seed_skipped_native_setup_preserved', snapshot(branch) == branch_before
          and not any(branch[field] for field in FIELDS))
    branch_code = C['account.account']._search_new_account_code('102090', cache=set())
    branch_account = branch.env['account.account'].create({'name': 'CAS1 branch code owner', 'code': branch_code,
        'company_ids': [(6, 0, branch.ids)], 'account_type': 'expense'})
    company.baseer_loan_account_id = False
    C['ir.model.data'].search([('module', '=', 'baseer_company_setup'),
        ('name', '=', 'baseer_loan_account_id_company_' + str(company.id))]).unlink()
    company._baseer_prepare_accounting()
    check('branch_account_code_collision_preserved', company.baseer_loan_account_id.code != branch_code
          and company.baseer_loan_account_id != branch_account and branch_account.code == branch_code
          and branch_account.company_ids == branch)
    company.baseer_loan_account_id = old_loan
    company_before = snapshot(company)
    company.with_context(default_company_id=10, default_name='CAS1 injected name', default_code='BAD',
                         default_active=False, default_currency_id=E.ref('base.USD').id)._baseer_prepare_accounting()
    check('private_seed_context_pollution_cannot_replace_configuration', snapshot(company) == company_before)
    polluted = E['res.company'].with_context(default_name='CAS1 injected seed name', default_company_id=10).create({
        'name': 'CAS1 QA POLLUTED SEED', 'country_id': E.ref('base.sa').id, 'currency_id': E.ref('base.SAR').id})
    env.cr.precommit.run()
    E.user.write({'company_ids': [(4, polluted.id)]})
    polluted = polluted.with_company(polluted)
    validate_defaults(polluted, 'polluted_creation')
    check('polluted_creation_seed_has_explicit_owned_names', all(polluted[field].name != 'CAS1 injected seed name' for field in FIELDS)
          and polluted.chart_template == 'sa')
    for name in ['_baseer_prepare_accounting', '_baseer_initialize_accounting', '_baseer_default_account']:
        blocked('private_rpc_' + name, lambda method_name=name: get_public_method(E['res.company'], method_name))
    viewer = E['res.users'].create({'name': 'CAS1 basic user', 'login': 'cas1-basic@example.invalid',
        'company_id': 10, 'company_ids': [(6, 0, [10])], 'group_ids': [(6, 0, [E.ref('base.group_user').id])]})
    blocked('unauthorized_native_company_create', lambda: E['res.company'].with_user(viewer).create({
        'name': 'CAS1 forbidden company', 'country_id': E.ref('base.sa').id}))
    R['fixture_ids'] = {'company': company.id, 'run': run.id, 'loan': loan.id, 'award': award.id, 'bill': bill.id}
    R['status'] = 'passed'
except Exception:
    R['status'] = 'failed'
    R['traceback'] = traceback.format_exc()
    raise
finally:
    env.cr.rollback()
    R['rolled_back'] = True
    OUTPUT.write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False, indent=2))
