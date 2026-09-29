"""HRS1 reviewer-authored acceptance cases; QA fixtures always rolled back.

Run only after installation. Uses native posting/payment/reversal; no mocked states.
The independent release review must disclose reviewer participation in these tests.
"""
import json
import traceback
from pathlib import Path
from odoo import api, Command
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA only'
OUT = Path('/mnt/qa-evidence/hr_services_extended_checks.json')
R = {'status': 'started', 'checks': [], 'cases': [], 'pdf': None}

def check(name, value):
    R['checks'].append({'name': name, 'passed': bool(value)})
    assert value, name

def rejected(name, fn):
    try:
        with env.cr.savepoint():
            fn()
    except (AccessError, UserError, ValidationError):
        check(name, True)
    else:
        check(name, False)

def fingerprint():
    result = {}
    for table in ('account_move', 'account_move_line', 'account_payment', 'account_partial_reconcile',
                  'account_account', 'account_payment_method_line', 'hr_employee', 'hr_payslip',
                  'baseer_hr_loan', 'baseer_hr_service', 'res_users'):
        env.cr.execute("SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM " + table + ' t')
        result[table] = env.cr.fetchone()
    return result

before = fingerprint()
try:
    C = api.Environment(env.cr, env.ref('base.user_admin').id,
                        {'allowed_company_ids': [10], 'lang': 'en_US', 'tracking_disable': True})
    Service = C['baseer.hr.service']
    employee = C['hr.employee'].create({'name': 'HRS1 extended QA employee', 'company_id': 10})
    provider = C.ref('baseer_service_seed.provider_passports_company_10')
    defaults = {'employee_id': employee.id, 'service_type': 'iqama_issue', 'partner_id': provider.id,
                'issue_date': '2026-08-20', 'invoice_date': '2026-08-20', 'gross_amount': 100,
                'service_reference': 'HRS1-EXTENDED'}

    def make(**values):
        return Service.create(dict(defaults, **values))

    def refresh(service):
        env.flush_all()
        service.invalidate_recordset()
        service.bill_id.invalidate_recordset()

    def pay(service, amount, outstanding=False):
        journal = C['account.journal'].search([
            ('company_id', '=', 10), ('type', '=', 'bank'), ('active', '=', True)], limit=1)
        method = journal.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')[:1]
        assert journal.default_account_id and method
        if outstanding:
            account = C['account.account'].create({
                'name': 'HRS1 QA outstanding payments', 'code': 'HRS1EXT01',
                'account_type': 'asset_current', 'reconcile': True, 'company_ids': [Command.set([10])]})
            method.payment_account_id = account
        else:
            method.payment_account_id = journal.default_account_id
        action = service.action_register_payment()
        wizard = C['account.payment.register'].with_context(action.get('context', {})).create({
            'journal_id': journal.id, 'payment_method_line_id': method.id, 'amount': amount,
            'payment_date': '2026-08-20', 'group_payment': True})
        result = wizard._create_payments()
        refresh(service)
        return result

    def run_case(name, fn):
        try:
            with env.cr.savepoint():
                fn()
            R['cases'].append({'name': name, 'passed': True})
        except Exception:
            R['cases'].append({'name': name, 'passed': False, 'traceback': traceback.format_exc()})

    def hr_projection():
        user = C['res.users'].create({'name': 'HRS1 extended HR only', 'login': 'hrs1.extended.hr',
            'company_id': 10, 'company_ids': [Command.set([10])],
            'group_ids': [Command.set([C.ref('hr.group_hr_user').id])]})
        H = Service.with_user(user).with_context(allowed_company_ids=[10])
        check('hr_fixture_has_no_account_invoice', not user.has_group('account.group_account_invoice'))
        draft = H.create(defaults)
        draft.write({'notes': 'HR-only draft update', 'gross_amount': 115, 'vat_enabled': True})
        check('hr_creates_and_edits_own_draft', draft.notes == 'HR-only draft update')
        # All displayed/hidden business fields, including net/tax and Many2one display names.
        names = ['name', 'company_id', 'currency_id', 'employee_id', 'partner_id', 'service_type',
                 'category_map_id', 'gross_amount', 'net_amount', 'tax_amount', 'vat_enabled',
                 'tax_id', 'bill_id', 'bill_name', 'bill_state', 'payment_state', 'balance',
                 'has_posted_refund', 'notes', 'state', 'issue_date', 'invoice_date', 'expiry_date']
        check('hr_draft_full_form_projection', len(draft.read(names)) == 1)
        issued = Service.browse(draft.id)
        issued.action_approve()
        pay(issued, 115)
        view = H.browse(issued.id)
        values = view.read(names)[0]
        check('hr_approved_full_form_projection', values['payment_state'] == 'paid' and values['balance'] == 0)
        rejected('hr_native_invoice_read_denied', lambda: issued.bill_id.with_user(user).read(['invoice_line_ids']))
        rejected('hr_native_invoice_action_denied', view.action_view_bill)
        rejected('hr_native_payment_action_denied', view.action_register_payment)
        rejected('hr_payroll_history_denied', lambda: employee.with_user(user).read(['baseer_financial_slip_ids']))
        check('hr_statement_projection', view._report_data()['gross'] == '115.00')
        check('hr_paid_filter', view.id in H.search([('payment_state', '=', 'paid')]).ids)
        check('hr_unpaid_filter', view.id not in H.search([('bill_state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial', 'in_payment'])]).ids)
        no_bill = H.create(defaults)
        unpaid = make()
        unpaid.action_approve()
        trio = [('id', 'in', [view.id, no_bill.id, unpaid.id])]
        check('hr_balance_positive_filter', H.search(trio + [('balance', '>', 0)]).ids == [unpaid.id])
        check('hr_balance_zero_includes_unbilled', set(H.search(trio + [('balance', '=', 0)]).ids) == {view.id, no_bill.id})
        check('hr_bill_state_false_unbilled_only', H.search(trio + [('bill_state', '=', False)]).ids == [no_bill.id])
        check('hr_bill_state_false_membership', H.search(trio + [('bill_state', 'in', [False])]).ids == [no_bill.id])
        check('hr_payment_state_false_unbilled_only', H.search(trio + [('payment_state', '=', False)]).ids == [no_bill.id])
        try:
            H.search(trio + [('balance', 'INVALID_HRS_OPERATOR', 0)])
        except (ValueError, ValidationError):
            check('invalid_summary_operator_rejected', True)
        else:
            check('invalid_summary_operator_rejected', False)

    def hr_manager_no_account():
        user = C['res.users'].create({'name': 'HRS1 HR manager only', 'login': 'hrs1.extended.manager',
            'company_id': 10, 'company_ids': [Command.set([10])],
            'group_ids': [Command.set([C.ref('hr.group_hr_manager').id])]})
        check('hr_manager_fixture_no_account', not user.has_group('account.group_account_invoice'))
        service = make()
        rejected('hr_manager_without_account_cannot_approve', lambda: service.with_user(user).action_approve())
        check('rejected_approval_creates_no_bill', not service.bill_id and service.state == 'draft')

    def native_in_payment():
        service = make()
        service.action_approve()
        payments = pay(service, 100, outstanding=True)
        check('native_outstanding_payment_exists', bool(payments) and bool(payments.move_id))
        native_hook = service.bill_id._get_invoice_in_payment_state()
        R['native_payment_behavior'] = {
            'invoice_hook': native_hook, 'invoice_payment_state': service.bill_id.payment_state,
            'service_payment_state': service.payment_state,
            'payment_states': payments.mapped('state'), 'matched': payments.mapped('is_matched'),
            'actual_in_payment_observed': service.bill_id.payment_state == 'in_payment',
            'limitation': ('Community account native hook returns paid; no natural invoice in_payment '
                           'transition is available in this installed configuration. No state is mocked.')
                          if native_hook == 'paid' else None,
        }
        check('native_zero_residual_follows_installed_hook', service.bill_id.amount_residual == 0 and service.bill_id.payment_state == native_hook)
        check('hr_projection_matches_native_not_independent_state', service.balance == 0 and service.payment_state == service.bill_id.payment_state)

    def partial_reversal():
        service = make()
        service.action_approve()
        credit = service.bill_id._reverse_moves([{'date': '2026-08-20', 'invoice_date': '2026-08-20'}], cancel=False)
        credit.invoice_line_ids.write({'price_unit': 40})
        credit.action_post()
        lines = (service.bill_id.line_ids | credit.line_ids).filtered(
            lambda l: l.account_id.account_type == 'liability_payable' and not l.reconciled)
        if len(lines) > 1:
            lines.reconcile()
        refresh(service)
        check('partial_native_credit_40', credit.state == 'posted' and credit.amount_total == 40 and not credit.baseer_hr_service_id)
        check('partial_credit_not_full_cancellation', service.payment_state != 'reversed' and round(service.balance, 2) == 60)
        check('partial_credit_disclosed', service.has_posted_refund)
        rejected('partial_refund_service_cannot_cancel', service.action_cancel)
        rejected('partial_refund_service_cannot_delete', service.unlink)

    def full_reversal():
        service = make()
        service.action_approve()
        credit = service.bill_id._reverse_moves([{'date': '2026-08-20', 'invoice_date': '2026-08-20'}], cancel=True)
        refresh(service)
        check('full_native_reversal_posts', credit.state == 'posted' and not credit.baseer_hr_service_id)
        check('full_native_reversed_status', service.payment_state == 'reversed' and service.balance == 0)
        service.action_cancel()
        check('full_reversed_service_cancel_allowed', service.state == 'cancel' and bool(service.bill_id))
        rejected('reversed_service_history_cannot_delete', service.unlink)
        rejected('reversed_service_cannot_reopen', service.action_reset_draft)

    def arabic_pdf():
        employee.name = 'موظف تجربة خدمات الموارد البشرية'
        service = make(service_type='visa', visa_type='extend', gross_amount=115, vat_enabled=True)
        service.action_approve()
        arabic = service.with_context(lang='ar_001')
        pdf, kind = C['ir.actions.report'].with_context(lang='ar_001')._render_qweb_pdf(
            'baseer_hr_services.action_report_baseer_hr_service', res_ids=arabic.ids)
        check('arabic_pdf_native_render', kind == 'pdf' and pdf.startswith(b'%PDF') and len(pdf) > 1000)
        target = Path('/mnt/qa-evidence/hr_services_extended_arabic.pdf')
        target.write_bytes(pdf)
        R['pdf'] = {'path': str(target), 'bytes': len(pdf), 'synthetic_fixture_only': True}

    def suggested_provider():
        expected = {
            'iqama_issue': 'passports', 'iqama_renewal': 'passports', 'visa': 'passports',
            'work_permit_issue': 'hrsd', 'work_permit_renewal': 'hrsd',
            'employee_transfer': 'hrsd', 'profession_change': 'hrsd',
            'health_certificate_issue': 'balady', 'health_certificate_renewal': 'balady',
        }
        for service_type, key in expected.items():
            check('provider_mapping_' + service_type, Service._suggested_provider(service_type) ==
                  C.ref('baseer_service_seed.provider_' + key + '_company_10'))
        check('provider_default_get', Service.default_get(['service_type', 'partner_id'])['partner_id'] == provider.id)
        values = dict(defaults)
        values.pop('partner_id')
        automatic = Service.create(values)
        check('provider_automatic_create', automatic.partner_id == provider)
        check('provider_suggestion_does_not_enable_vat', not automatic.vat_enabled and not automatic.tax_id)
        alternative = C.ref('baseer_service_seed.provider_hrsd_company_10')
        manual = Service.create(dict(values, partner_id=alternative.id))
        check('provider_explicit_create_preserved', manual.partner_id == alternative)
        manual.write({'partner_id': provider.id})
        check('provider_draft_manually_editable', manual.partner_id == provider)
        contextual = Service.with_context(default_partner_id=alternative.id).create(values)
        check('provider_explicit_context_preserved', contextual.partner_id == alternative)
        form = Service.new(dict(defaults, service_type='work_permit_issue', vat_enabled=True))
        form._onchange_service_type()
        check('provider_onchange_proposes_hrsd', form.partner_id == alternative)
        check('provider_onchange_preserves_vat_choice', form.vat_enabled)
        form.service_type = 'ticket'
        form._onchange_service_type()
        check('provider_unknown_service_keeps_manual_choice_required', not form.partner_id)
        check('provider_foreign_company_not_suggested', not Service._suggested_provider('iqama_issue', C['res.company'].browse(6)))
        check('provider_company6_scoped', Service.with_context(allowed_company_ids=[6])._suggested_provider('iqama_issue') ==
              C.ref('baseer_service_seed.provider_passports_company_6'))
        provider.active = False
        check('provider_archived_not_suggested', not Service._suggested_provider('iqama_issue'))
        provider.active = True

    for name, fn in [('hr_projection', hr_projection), ('hr_manager_no_account', hr_manager_no_account),
                     ('native_in_payment', native_in_payment), ('partial_reversal', partial_reversal),
                     ('full_reversal', full_reversal), ('arabic_pdf', arabic_pdf),
                     ('suggested_provider', suggested_provider)]:
        run_case(name, fn)
    R['status'] = 'passed' if all(c['passed'] for c in R['cases']) else 'failed'
except Exception:
    R['status'] = 'failed'
    R['traceback'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    R['rolled_back'] = True
    preserved = fingerprint() == before
    R['checks'].append({'name': 'all_financial_hr_master_fixtures_rolled_back', 'passed': preserved})
    if not preserved:
        R['status'] = 'failed'
    R['check_count'] = len(R['checks'])
    OUT.write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False))
