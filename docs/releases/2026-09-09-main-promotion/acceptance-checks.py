"""MP3 read-only acceptance. Run only after root authorizes the upgraded target.

No business create/write/unlink, action approvals, seed hooks, report rendering,
or lazy salary-structure creation. PostgreSQL enforces a read-only transaction.
"""
import hashlib
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from odoo.tools import config
from odoo.addons.baseer_payroll.models.end_service import POLICY
from odoo.addons.baseer_hr_services.models.service import HR_SERVICES

ALLOWED_DATABASES = {'baseer_main_rehearsal_20260909', 'baseer_dev'}
assert env.cr.dbname in ALLOWED_DATABASES, 'MP3 acceptance database is not allowlisted'
R = {'database': env.cr.dbname, 'started_utc': datetime.now(timezone.utc).isoformat(),
     'checks': [], 'companies': [], 'read_only': True,
     'source_candidate': '807712c3dd78db4bdbec15d6a264b5b72feec951'}


def check(name, condition, evidence=None):
    row = {'name': name, 'passed': bool(condition)}
    if evidence is not None:
        row['evidence'] = evidence
    R['checks'].append(row)


def probe(name, action):
    try:
        with env.cr.savepoint():
            action()
    except Exception:
        check(name, False, traceback.format_exc())


try:
    env.cr.rollback()
    env.invalidate_all(flush=False)
    env.cr.execute('SET TRANSACTION READ ONLY')
    env.cr.execute('SHOW transaction_read_only')
    check('PostgreSQL transaction is read only', env.cr.fetchone()[0] == 'on')

    expected_versions = {
        'baseer_cash_categories': '19.0.1.3.1', 'baseer_category_display': '19.0.1.0.0',
        'baseer_company_setup': '19.0.1.0.0', 'baseer_hr_services': '19.0.1.1.0',
        'baseer_legion_compat': '19.0.1.0.0', 'baseer_payroll': '19.0.1.5.0',
        'baseer_pos_summary': '19.0.1.4.0', 'baseer_purchase_batch': '19.0.1.2.3',
        'baseer_report_layout': '19.0.1.1.1', 'baseer_service_seed': '19.0.1.1.1',
        'baseer_web_navigation': '19.0.1.1.0',
        'om_hr_payroll': '19.0.1.1', 'om_hr_payroll_account': '19.0.0.0',
    }
    for name, version in expected_versions.items():
        module = env['ir.module.module'].search([('name', '=', name)], limit=1)
        actual = {'state': module.state, 'version': module.latest_version}
        check(name + ' installed expected version', module.state == 'installed'
              and module.latest_version == version, actual)
    R['installed_modules'] = env['ir.module.module'].search_count([('state', '=', 'installed')])

    companies = env['res.company'].search([
        ('active', '=', True), ('parent_id', '=', False),
        ('chart_template', '=', 'sa'), ('currency_id.name', '=', 'SAR')], order='id')
    check('at least one eligible Saudi company', bool(companies), companies.ids)
    # MAIN company 3 is the explicitly requested acceptance target, not a QA id.
    check('requested MAIN company 3 is an eligible configured company', 3 in companies.ids)

    def company_checks(company):
        C = company.with_company(company).with_context(allowed_company_ids=[company.id])
        C._baseer_check_payroll_configuration()  # validator only; never _baseer_structure()
        prefix = 'company %s ' % C.id
        check(prefix + 'payroll configuration', True)
        check(prefix + 'EOS purchase journal', bool(C.baseer_eos_journal_id)
              and C.baseer_eos_journal_id.active
              and C.baseer_eos_journal_id.company_id == C
              and C.baseer_eos_journal_id.type == 'purchase')
        expense = C.baseer_eos_expense_id
        check(prefix + 'EOS expense scope and type', bool(expense) and expense.active
              and C in expense.company_ids and expense.account_type == 'expense')
        mappings = C.env['baseer.purchase.category.map'].search([('company_id', '=', C.id)])
        check(prefix + 'purchase mappings exist', bool(mappings), len(mappings))
        missing, invalid = [], []
        for key, _english, _arabic, _purpose in HR_SERVICES:
            mapping = C.env.ref('baseer_service_seed.mapping_%s_company_%s' % (key, C.id),
                                raise_if_not_found=False)
            if not mapping:
                missing.append(key)
                continue
            product = mapping.product_id.with_company(C)
            account = product.property_account_expense_id
            if (mapping.company_id != C or not product.active
                    or product.company_id != C or product.type != 'service'
                    or not product.purchase_ok or not account or not account.active
                    or C not in account.company_ids or account.account_type != 'expense'):
                invalid.append(key)
        check(prefix + 'all 15 HR services seeded', not missing,
              {'expected': len(HR_SERVICES), 'missing': missing})
        check(prefix + 'HR service products and expense accounts scoped', not invalid, invalid)
        R['companies'].append({'id': C.id, 'currency': C.currency_id.name,
                              'chart': C.chart_template, 'payroll_journal_id': C.baseer_payroll_journal_id.id,
                              'eos_journal_id': C.baseer_eos_journal_id.id,
                              'proration': C.baseer_proration, 'mapping_count': len(mappings),
                              'salary_structure_present': bool(C.baseer_structure_id)})
        # A missing structure may be lazily created by normal authorized payroll
        # workflow. This acceptance script must never initialize one itself.
        if C.baseer_structure_id:
            structure = C.baseer_structure_id
            expected = {'BP_BASIC': ('baseer_basic', C.baseer_salary_expense_id, C.baseer_salary_payable_id),
                        'BP_OT': ('baseer_overtime', C.baseer_salary_expense_id, C.baseer_salary_payable_id),
                        'BP_ALLOW': ('baseer_allowance', C.baseer_salary_expense_id, C.baseer_salary_payable_id),
                        'BP_DEDUCT': ('baseer_deduction', C.baseer_salary_payable_id, C.baseer_deduction_account_id),
                        'BP_LOAN': ('baseer_loan_amount', C.baseer_salary_payable_id, C.baseer_loan_account_id)}
            valid = structure.company_id == C and not structure.parent_id and len(structure.rule_ids) == 5
            for code, (field, debit, credit) in expected.items():
                rule = structure.rule_ids.filtered(lambda rec: rec.code == code)
                valid = valid and len(rule) == 1 and rule.active and rule.company_id == C
                valid = valid and rule.account_debit == debit and rule.account_credit == credit
                valid = valid and rule.amount_select == 'code' and rule.amount_python_compute == 'result = payslip.' + field
            check(prefix + 'existing salary structure and five rule mappings', valid)

    for company in companies:
        probe('company %s configuration probe' % company.id, lambda company=company: company_checks(company))

    E = env(context={'allowed_company_ids': companies.ids or env.companies.ids,
                     'lang': 'en_US', 'active_test': True})
    check('PB2 new employee inclusion default',
          E['hr.employee'].default_get(['baseer_payroll_enabled']).get('baseer_payroll_enabled') is True)
    check('PB2 explicit authorized default False',
          E['hr.employee'].with_context(default_baseer_payroll_enabled=False)
          .default_get(['baseer_payroll_enabled']).get('baseer_payroll_enabled') is False)
    check('PB2 inclusion group remains payroll manager',
          E['hr.employee']._fields['baseer_payroll_enabled'].groups == 'om_hr_payroll.group_hr_payroll_manager')
    check('PB2 readiness fields and protected refresh flag',
          all(name in E['hr.payslip']._fields for name in
              ('baseer_readiness', 'baseer_readiness_warning', 'baseer_needs_refresh'))
          and E['hr.payslip']._fields['baseer_needs_refresh'].readonly
          and E['hr.payslip']._fields['baseer_needs_refresh'].store)
    check('PB2 report readiness hook loaded', 'report.baseer_payroll.report_payslips' in E)
    defaults = E['baseer.hr.eos'].default_get(['policy_version', 'service_end_inclusive', 'gregorian_confirmed'])
    check('EOS v2 new-document policy and explicit confirmation',
          defaults.get('policy_version') == POLICY
          and defaults.get('service_end_inclusive') is True
          and not defaults.get('gregorian_confirmed'), defaults)
    check('contribution report namespace', bool(E.ref('om_hr_payroll.action_contribution_register'))
          and 'report.om_hr_payroll.report_contribution_register' in E)
    provider = E.ref('baseer_service_seed.provider_water', raise_if_not_found=False)
    check('shared water provider', bool(provider) and not provider.company_id)

    forms = [('baseer.purchase.batch', None), ('baseer.hr.service', None),
             ('baseer.hr.loan', None), ('baseer.hr.eos', 'baseer_payroll.view_baseer_eos_form'),
             ('hr.payslip.run', 'baseer_payroll.view_baseer_payroll_run_form'),
             ('hr.employee', 'hr.view_employee_form'), ('baseer.pos.summary', None),
             ('baseer.pos.day.entry', None), ('baseer.payroll.correction', 'baseer_payroll.view_baseer_payroll_correction')]

    def view_checks(lang):
        L = E(context=dict(E.context, lang=lang))
        for model, xmlid in forms:
            view_id = L.ref(xmlid).id if xmlid else None
            result = L[model].get_view(view_id=view_id, view_type='form')
            arch = result['arch']
            check('%s %s native form compiles' % (lang, model), bool(arch))
            if model == 'hr.payslip.run':
                check(lang + ' run readiness field and warning',
                      'baseer_readiness_warning' in arch and 'baseer_pending_setup_count' in arch)
                phrase = 'أكمل بيانات الموظف' if lang == 'ar_001' else 'Complete employee setup'
                check(lang + ' run explanatory warning translated', phrase in arch)
            if model == 'hr.employee':
                phrase = 'للعقد غير محدد المدة' if lang == 'ar_001' else 'For an open-ended contract'
                check(lang + ' native open-ended contract explanation', phrase in arch)
        labels = dict(L['hr.payslip']._fields['baseer_readiness']._description_selection(L))
        check(lang + ' compact readiness badge', labels.get('pending') ==
              ('بيانات ناقصة' if lang == 'ar_001' else 'Needs setup'), labels)
    for language in ('en_US', 'ar_001'):
        check(language + ' language active', bool(E['res.lang'].search_count([('code', '=', language), ('active', '=', True)])))
        probe(language + ' view probe', lambda language=language: view_checks(language))

    # Check every referenced filestore object, deduplicating physical file reads.
    # Database-backed payloads are covered by root's PostgreSQL backup/integrity
    # projection; URLs and content-free metadata have no filestore checksum.
    def attachment_checks():
        root = Path(config.filestore(env.cr.dbname)).resolve()
        env.cr.execute("SELECT id,store_fname,checksum,file_size FROM ir_attachment WHERE type='binary' AND store_fname IS NOT NULL ORDER BY id")
        rows = env.cr.fetchall()
        cache, problems = {}, []
        for ident, store_name, expected_hash, expected_size in rows:
            location = (root / store_name).resolve()
            if not location.is_relative_to(root) or not location.is_file():
                problems.append({'id': ident, 'problem': 'missing or out-of-scope file'})
                continue
            if store_name not in cache:
                digest = hashlib.sha1()
                with location.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                cache[store_name] = (digest.hexdigest(), location.stat().st_size)
            actual_hash, actual_size = cache[store_name]
            if actual_hash != expected_hash or actual_size != expected_size:
                problems.append({'id': ident, 'problem': 'checksum or size mismatch',
                                 'expected_checksum': expected_hash, 'actual_checksum': actual_hash,
                                 'expected_size': expected_size, 'actual_size': actual_size})
        env.cr.execute("SELECT count(*) FROM ir_attachment WHERE type='binary' AND store_fname IS NULL AND db_datas IS NOT NULL")
        R['attachments'] = {'filestore_rows': len(rows), 'unique_files_read': len(cache),
                            'database_payload_rows': env.cr.fetchone()[0], 'problems': problems}
        check('all referenced filestore SHA1 and sizes match attachment metadata', not problems, R['attachments'])
    probe('attachment integrity probe', attachment_checks)
    R['status'] = 'passed' if all(row['passed'] for row in R['checks']) else 'failed'
except Exception:
    R['status'] = 'error'
    R['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    R['rolled_back'] = True
    R['finished_utc'] = datetime.now(timezone.utc).isoformat()
    output = Path('/mnt/qa-evidence/acceptance-' + env.cr.dbname + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False, indent=2))

assert R['status'] == 'passed', 'MP3 acceptance failed; inspect the JSON result'
