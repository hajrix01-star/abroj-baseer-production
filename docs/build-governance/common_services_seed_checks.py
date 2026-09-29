"""CSS1 native integration checks. Run in Odoo shell on QA; always rollback.

The assertions use business expectations independently of the seed catalogue.
No commits, installations, outbound requests, bills or payments are made.
"""
import hashlib
import json
import time
import traceback
from pathlib import Path

from odoo.exceptions import AccessError, UserError, ValidationError

TARGET = 'baseer_reports_qa_20260907'
if env.cr.dbname != TARGET:
    raise RuntimeError('CSS1 checks are restricted to ' + TARGET)
OUTPUT = Path('/mnt/qa-evidence/common_services_seed_checks.json')
R = {'database': TARGET, 'status': 'started', 'checks': [], 'timings_seconds': {}}
CONTEXT = {'lang': 'en_US', 'active_test': False, 'tracking_disable': True,
           'mail_notrack': True, 'mail_create_nosubscribe': True,
           'mail_notify_force_send': False}
FINANCIAL_TABLES = ('account_move', 'account_move_line', 'account_payment',
                    'account_partial_reconcile', 'account_full_reconcile')
EXPECTED_VAT = {'300000361310003', '300000157210003', '300000699600003'}
EXPECTED_NATIVE = {
    'iqama_issue': None, 'iqama_renewal': None, 'work_permit_issue': None,
    'work_permit_renewal': None, 'employee_transfer': None, 'profession_change': None,
    'visa': '400014', 'health_certificate_issue': '400075', 'health_certificate_renewal': '400075',
    'medical_exam': '400075', 'ticket': '400006', 'insurance_issue': '400009', 'insurance_renewal': '400009',
    'processing': '400075', 'other_employee': '400075', 'electricity': '400018', 'water': '400018',
    'telecom': '400020', 'internet': '400023', 'mudad_subscription': '400045',
    'muqeem_subscription': '400045', 'qiwa_subscription': '400045',
    'municipal_license': '400032', 'commercial_register': '400032', 'attestation': '400031', 'legal_services': '400031',
}


def check(name, condition):
    R['checks'].append({'name': name, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(name)


def blocked(name, operation):
    try:
        with env.cr.savepoint():
            operation()
    except (AccessError, UserError, ValidationError):
        check(name, True)
    else:
        check(name, False)


def fingerprint(tables):
    env.flush_all()
    values = {}
    for table in tables:
        # Table names are a fixed harness allowlist, never user input.
        env.cr.execute('SELECT row_to_json(t)::text FROM "' + table + '" t ORDER BY id')
        rows = env.cr.fetchall()
        digest = hashlib.sha256()
        for row in rows:
            digest.update(row[0].encode())
            digest.update(b'\n')
        values[table] = {'count': len(rows), 'sha256': digest.hexdigest()}
    return values


def identities(E, company_id=None, model=None):
    domain = [('module', '=', 'baseer_service_seed')]
    if company_id is not None:
        domain.append(('name', '=like', '%_company_' + str(company_id)))
    if model:
        domain.append(('model', '=', model))
    return E['ir.model.data'].search(domain, order='name')


def owned_records(E, company_id, model):
    return E[model].browse(identities(E, company_id, model).mapped('res_id')).exists()


def company_snapshot(company):
    E = company.env
    out = {'chart': company.chart_template, 'currency': company.currency_id.id,
           'country': company.country_id.id,
           'identities': identities(E, company.id).read(['name', 'model', 'res_id', 'noupdate'])}
    fields_by_model = {
        'res.partner': ['name', 'active', 'company_id', 'vat', 'supplier_rank', 'category_id', 'baseer_purchase_category_map_id'],
        'product.product': ['name', 'active', 'company_id', 'categ_id', 'type', 'sale_ok', 'purchase_ok',
                            'property_account_expense_id', 'taxes_id', 'supplier_taxes_id'],
        'baseer.purchase.category.map': ['active', 'company_id', 'category_id', 'product_id'],
    }
    for model, names in fields_by_model.items():
        records = owned_records(E, company.id, model)
        out[model] = records.read(names)
    accounts = E['account.account'].search([('company_ids', 'in', company.id)], order='id')
    out['accounts'] = accounts.read(['name', 'code', 'company_ids', 'account_type', 'reconcile', 'active'])
    out['journals'] = E['account.journal'].search([('company_id', '=', company.id)], order='id').read(
        ['name', 'code', 'company_id', 'type', 'active', 'default_account_id'])
    return out


def validate_company(company, label):
    E = company.env
    partners = owned_records(E, company.id, 'res.partner')
    products = owned_records(E, company.id, 'product.product')
    mappings = owned_records(E, company.id, 'baseer.purchase.category.map')
    check(label + '_twenty_providers', len(partners) == 20)
    check(label + '_private_providers', all(p.company_id == company and p.supplier_rank > 0 for p in partners))
    check(label + '_only_three_verified_vat', set(partners.filtered('vat').mapped('vat')) == EXPECTED_VAT
          and len(partners.filtered('vat')) == 3)
    check(label + '_all_providers_have_classification', all(p.category_id for p in partners))
    check(label + '_exactly_26_approved_services', len(products) == 26)
    check(label + '_one_mapping_per_seed_product', len(mappings) == len(products)
          and set(mappings.mapped('product_id').ids) == set(products.ids))
    check(label + '_unique_selectable_leaf', len(mappings.category_id) == len(mappings))
    check(label + '_private_service_products', all(p.company_id == company and p.type == 'service'
          and p.purchase_ok and not p.sale_ok for p in products))
    check(label + '_no_forced_product_taxes', all(not p.taxes_id and not p.supplier_taxes_id for p in products))
    check(label + '_owned_expense_accounts', all(p.property_account_expense_id
          and company in p.property_account_expense_id.company_ids
          and p.property_account_expense_id.account_type == 'expense' for p in products))
    check(label + '_no_asset_in_expense_mapping', all(m._validated_expense_account().account_type == 'expense'
          and m.product_id.categ_id == m.category_id and m.company_id == company for m in mappings))
    check(label + '_category_hierarchy_present', all(m.category_id.parent_id for m in mappings))
    check(label + '_canonical_noupdate_identities', all(d.noupdate for d in identities(E, company.id)))
    # Government bodies with several different operations must not imply an expense nature.
    government = partners.filtered(lambda p: any(word in p.name.lower() for word in
        ('zakat', 'gosi', 'social insurance', 'ministry', 'zatca', 'التأمينات', 'الزكاة', 'وزارة')))
    check(label + '_government_parties_present', len(government) >= 6)
    check(label + '_no_government_forced_purchase_category', all(not p.baseer_purchase_category_map_id for p in government))
    expected_product_ids = set()
    permit_accounts = set()
    for key, code in EXPECTED_NATIVE.items():
        product = E.ref(f'baseer_service_seed.product_{key}_company_{company.id}')
        category = E.ref('baseer_service_seed.category_' + key)
        expected_product_ids.add(product.id)
        check(label + '_leaf_' + key, product.categ_id == category)
        if company.chart_template == 'sa' and code:
            account = E.ref(f'account.{company.id}_sa_account_{code}')
            check(label + '_native_account_' + key, product.property_account_expense_id == account)
        if code is None:
            permit_accounts.add(product.property_account_expense_id.id)
    check(label + '_only_approved_product_identities', set(products.ids) == expected_product_ids)
    check(label + '_one_permit_account_shared_across_variants', len(permit_accounts) == 1)
    return partners, products, mappings


try:
    E = env(user=env.ref('base.user_admin').id, context=dict(CONTEXT, allowed_company_ids=[10]), su=True)
    financial_before = fingerprint(FINANCIAL_TABLES)
    roots = E['res.company'].search([('parent_id', '=', False), ('chart_template', '!=', False)])
    companies = roots.filtered(lambda c: c.currency_id.name == 'SAR')
    non_sar = roots - companies
    foreign_before = {c.id: company_snapshot(c.with_company(c)) for c in non_sar}
    check('five_existing_sar_companies_available', len(companies) == 5)
    original = {}
    all_partner_ids, all_product_ids = set(), set()
    shared_categories = None
    for company in companies:
        company = company.with_company(company)
        partners, products, mappings = validate_company(company, 'existing_' + str(company.id))
        check('existing_' + str(company.id) + '_separate_partner_and_product_records',
              not all_partner_ids.intersection(partners.ids) and not all_product_ids.intersection(products.ids))
        all_partner_ids.update(partners.ids)
        all_product_ids.update(products.ids)
        if shared_categories is None:
            shared_categories = set(mappings.category_id.ids)
        check('existing_' + str(company.id) + '_same_shared_service_categories',
              set(mappings.category_id.ids) == shared_categories)
        original[company.id] = company_snapshot(company)
    began = time.monotonic()
    roots._baseer_prepare_accounting()
    env.flush_all()
    R['timings_seconds']['rerun_existing_companies'] = round(time.monotonic() - began, 6)
    check('existing_rerun_preserves_all_seed_configuration', all(
        company_snapshot(c.with_company(c)) == original[c.id] for c in companies))
    check('existing_non_sar_no_seed_or_change', bool(non_sar) and all(
        not identities(E, c.id) and company_snapshot(c.with_company(c)) == foreign_before[c.id] for c in non_sar))

    # Native create + queued callbacks + flush, with no manual call to the initializer.
    began = time.monotonic()
    company = E['res.company'].create({'name': 'CSS1 QA native new company',
        'country_id': E.ref('base.sa').id, 'currency_id': E.ref('base.SAR').id})
    env.cr.precommit.run()
    env.flush_all()
    R['timings_seconds']['new_sa_create_precommit_flush'] = round(time.monotonic() - began, 6)
    company = company.with_company(company)
    C = company.env
    partners, products, mappings = validate_company(company, 'new_sa')
    check('new_sa_native_chart_automatic', company.chart_template == 'sa')
    check('new_sa_no_financial_transactions', not C['account.move'].search_count([('company_id', '=', company.id)])
          and not C['account.payment'].search_count([('company_id', '=', company.id)]))
    fresh = company_snapshot(company)
    began = time.monotonic()
    company._baseer_prepare_accounting()
    env.flush_all()
    R['timings_seconds']['localized_company_rerun'] = round(time.monotonic() - began, 6)
    check('new_company_repeat_exactly_stable', company_snapshot(company) == fresh)
    check('localized_seed_timing_under_15s', R['timings_seconds']['localized_company_rerun'] < 15)

    # A new generic chart follows native chart loading; never load Saudi accounts over it.
    generic = E['res.company'].create({'name': 'CSS1 QA generic company', 'country_id': False,
                                      'currency_id': E.ref('base.SAR').id})
    generic.env['account.chart.template']._load('generic_coa', generic, install_demo=False)
    # Native generic_coa declares fiscal country US and _pre_load_data sets USD
    # while there is no accounting history. Explicitly configure this synthetic
    # generic-chart/SAR company before native creation precommit callbacks run.
    check('generic_native_template_initially_sets_usd', generic.currency_id.name == 'USD')
    generic.write({'currency_id': E.ref('base.SAR').id})
    env.cr.precommit.run()
    env.flush_all()
    generic = generic.with_company(generic)
    validate_company(generic, 'new_generic')
    check('new_generic_chart_preserved', generic.chart_template == 'generic_coa')

    foreign = E['res.company'].create({'name': 'CSS1 QA foreign currency', 'country_id': False,
                                      'currency_id': E.ref('base.USD').id})
    foreign.env['account.chart.template']._load('generic_coa', foreign, install_demo=False)
    env.cr.precommit.run()
    env.flush_all()
    check('new_non_sar_native_company_does_not_fail_or_seed', foreign.chart_template == 'generic_coa'
          and foreign.currency_id.name == 'USD' and not identities(E, foreign.id))

    # Expense is an input suggestion; users retain an explicit Purchase choice.
    energy = C.ref(f'baseer_service_seed.provider_energy_company_{company.id}')
    service_map = C.ref(f'baseer_service_seed.mapping_electricity_company_{company.id}')
    row_values = {'partner_id': energy.id, 'category_map_id': service_map.id, 'supplier_ref': 'CSS1-ROW-1',
                  'invoice_date': '2026-09-08', 'gross_amount': 100, 'is_credit': True}
    batch = C['baseer.purchase.batch'].create({'company_id': company.id,
                                               'line_ids': [(0, 0, row_values)]})
    check('seed_category_create_defaults_expense', batch.line_ids.entry_type == 'expense')
    Lines = C['baseer.purchase.batch.line']
    provider_values = dict(row_values, batch_id=batch.id, supplier_ref='CSS1-ROW-2')
    provider_values.pop('category_map_id')
    provider_row = Lines.create(provider_values)
    check('provider_default_category_creates_expense', provider_row.category_map_id == service_map
          and provider_row.entry_type == 'expense')
    explicit = Lines.create(dict(row_values, batch_id=batch.id, supplier_ref='CSS1-ROW-3', entry_type='purchase'))
    check('explicit_user_purchase_choice_preserved', explicit.entry_type == 'purchase')
    ordinary_category = C['product.category'].create({'name': 'CSS1 ordinary category'})
    ordinary_product = C['product.product'].create({'name': 'CSS1 ordinary service', 'type': 'service',
        'company_id': company.id, 'categ_id': ordinary_category.id,
        'property_account_expense_id': service_map.product_id.property_account_expense_id.id,
        'taxes_id': [(5, 0, 0)], 'supplier_taxes_id': [(5, 0, 0)]})
    ordinary_map = C['baseer.purchase.category.map'].create({'company_id': company.id,
                         'category_id': ordinary_category.id, 'product_id': ordinary_product.id})
    ordinary = Lines.create(dict(row_values, batch_id=batch.id, supplier_ref='CSS1-ROW-4', category_map_id=ordinary_map.id))
    check('ordinary_unseeded_category_keeps_purchase', ordinary.entry_type == 'purchase')
    form_row = Lines.new({'batch_id': batch.id, 'partner_id': energy.id,
                          'category_map_id': service_map.id, 'entry_type': 'purchase'})
    form_row._onchange_baseer_service_category()
    check('category_onchange_suggests_expense', form_row.entry_type == 'expense')
    form_row.entry_type = 'purchase'
    form_row._onchange_partner_default_category()
    check('provider_onchange_suggests_expense', form_row.entry_type == 'expense' and form_row.category_map_id == service_map)
    form_row.entry_type = 'purchase'
    check('user_can_override_onchange_suggestion', form_row.entry_type == 'purchase')
    # Capture input type before seed retry; do not migrate historical row choices.
    row_types = {row.id: row.entry_type for row in batch.line_ids}
    company._baseer_prepare_accounting()
    check('seed_retry_does_not_reclassify_saved_rows', row_types == {row.id: row.entry_type for row in batch.line_ids})

    # Only synthetic fixture records are customized. Preserve identities even when archived.
    partner, product, mapping = partners[:1], products[:1], mappings[:1]
    partner.write({'name': 'CSS1 renamed provider', 'vat': '300007358110003', 'active': False})
    product.write({'name': 'CSS1 renamed service', 'active': False})
    # Use the mapping for that product; the native validator intentionally rejects inactive products.
    product_mapping = mappings.filtered(lambda m: m.product_id == product)
    product_mapping.write({'active': False})
    customized = company_snapshot(company)
    company._baseer_prepare_accounting()
    env.flush_all()
    check('rename_archive_existing_vat_preserved_without_duplicates', company_snapshot(company) == customized)
    product.active = True
    product_mapping.active = True
    replacement = C['product.product'].create({'name': 'CSS1 chosen replacement service', 'type': 'service',
        'company_id': company.id, 'categ_id': product_mapping.category_id.id, 'sale_ok': False,
        'property_account_expense_id': product.property_account_expense_id.id,
        'taxes_id': [(5, 0, 0)], 'supplier_taxes_id': [(5, 0, 0)]})
    product_mapping.product_id = replacement
    configured = company_snapshot(company)
    company._baseer_prepare_accounting()
    env.flush_all()
    check('configured_category_product_choice_preserved', company_snapshot(company) == configured
          and product_mapping.product_id == replacement)
    check('all_other_company_configuration_unchanged', all(
        company_snapshot(c.with_company(c)) == original[c.id] for c in companies))

    foreign_product = owned_records(generic.env, generic.id, 'product.product')[:1]
    blocked('cross_company_product_mapping_rejected', lambda: product_mapping.write({'product_id': foreign_product.id}))
    viewer = E['res.users'].create({'name': 'CSS1 single company viewer', 'login': 'css1-viewer@example.invalid',
        'company_id': company.id, 'company_ids': [(6, 0, [company.id])],
        'group_ids': [(6, 0, [E.ref('base.group_user').id])]})
    V = E(user=viewer.id, context=dict(CONTEXT, allowed_company_ids=[company.id]), su=False)
    other_partner_ids = owned_records(generic.env, generic.id, 'res.partner').ids
    check('ordinary_user_cannot_search_other_company_providers', not V['res.partner'].search([('id', 'in', other_partner_ids)]))
    check('ordinary_user_cannot_search_other_company_products', not V['product.product'].search([('id', '=', foreign_product.id)]))
    def tampered_identity():
        identity = identities(C, company.id, 'res.partner')[:1]
        identity.res_id = other_partner_ids[0]
        company._baseer_prepare_accounting()
    blocked('foreign_owned_seed_identity_rejected', tampered_identity)
    # A contaminated context must not replace canonical names, owners or taxes.
    before_pollution = company_snapshot(company)
    company.with_context(default_name='BAD CSS1 injected', default_company_id=10,
                         default_active=False)._baseer_prepare_accounting()
    check('caller_default_context_does_not_mutate_seed', company_snapshot(company) == before_pollution)

    check('no_existing_or_new_financial_history_mutations', fingerprint(FINANCIAL_TABLES) == financial_before)
    R['fixture_company_ids'] = [company.id, generic.id, foreign.id]
    R['status'] = 'passed'
except Exception:
    R['status'] = 'failed'
    R['traceback'] = traceback.format_exc()
    raise
finally:
    env.cr.rollback()
    R['rolled_back'] = True
    R['check_count'] = len(R['checks'])
    OUTPUT.write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False, indent=2))
