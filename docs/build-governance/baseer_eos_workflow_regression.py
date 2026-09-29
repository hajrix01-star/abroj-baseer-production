"""Rollback-only EOS integration checks on the QA database; no real departure."""
from datetime import date, timedelta
from decimal import Decimal
import json
import traceback
from pathlib import Path
from odoo.exceptions import UserError, AccessError, ValidationError
from odoo.addons.baseer_payroll.models.common import money
from odoo.addons.baseer_payroll.models.end_service import eos_formula

R = {'checks': [], 'status': 'started'}


def check(name, condition):
    R['checks'].append({'name': name, 'passed': bool(condition)})
    assert condition, name


def blocked(name, operation):
    try:
        with env.cr.savepoint():
            operation()
    except (UserError, AccessError, ValidationError):
        check(name, True)
    else:
        check(name, False)


try:
    assert env.cr.dbname == 'baseer_reports_qa_20260907'
    E = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids': [10], 'tracking_disable': True,
        'mail_create_nosubscribe': True, 'mail_notify_force_send': False, 'active_test': False, 'lang': 'en_US'}, su=False)
    start = date(2020, 1, 1)
    for days, factor in [(729, Decimal(0)), (730, Decimal(1)/3), (1825, Decimal(1)/3),
                         (1826, Decimal(2)/3), (3649, Decimal(2)/3), (3650, Decimal(1))]:
        result = eos_formula(start, start + timedelta(days=days), 3000, 'resignation')
        check('resignation_day_boundary_' + str(days), result[0] == days and result[2] == factor)
    check('leap_days_and_excluded_end', eos_formula(date(2024, 2, 28), date(2024, 3, 1), 3000, 'termination')[0] == 2)
    check('five_year_full_award', eos_formula(start, start + timedelta(days=1825), 3000, 'termination')[3] == Decimal('7500.00'))
    check('article80_zero', eos_formula(start, start + timedelta(days=3000), 3000, 'article80')[3] == 0)
    blocked('zero_service_period', lambda: eos_formula(start, start, 3000, 'termination'))
    blocked('invalid_reason', lambda: eos_formula(start, start + timedelta(days=10), 3000, 'arbitrary'))
    company = E.company
    purchase = E['account.journal'].search([('company_id', '=', 10), ('type', '=', 'purchase')], limit=1)
    assert purchase and company.baseer_salary_expense_id
    company.write({'baseer_eos_journal_id': purchase.id, 'baseer_eos_expense_id': company.baseer_salary_expense_id.id})
    bank = E['account.journal'].browse(132)
    assert bank.default_account_id.account_type == 'asset_cash' and not bank.default_account_id.reconcile
    assert bank.outbound_payment_method_line_ids.filtered(lambda method: method.id == 110).payment_account_id == bank.default_account_id

    def employee(name):
        record = E['hr.employee'].create({'name': 'BP-S4 EOS QA ' + name, 'company_id': 10, 'baseer_payroll_enabled': False})
        version = record.version_id
        version.write({'date_version': '2018-01-01', 'contract_date_start': '2018-01-01', 'wage': 3000,
                       'baseer_salary_mode': 'fixed', 'baseer_allowance_total': 300})
        if not record.work_contact_id:
            record.work_contact_id = E['res.partner'].create({'name': record.name, 'company_id': 10})
        record.work_contact_id.with_company(company).property_account_payable_id = company.baseer_salary_payable_id
        return record

    person = employee('A')
    version = person.version_id
    values = {'employee_id': person.id, 'version_id': version.id, 'service_start': '2018-01-01', 'service_end': '2026-08-31'}
    moves_before = E['account.move'].search_count([])
    request = E['baseer.hr.eos'].create(values)
    request.action_calculate()
    check('active_employee_estimate_no_posting', person.active and not version.departure_date
          and not request.bill_id and E['account.move'].search_count([]) == moves_before)
    check('fixed_eos_includes_allowances', money(request.eos_wage) == Decimal('3000.00'))
    blocked('departure_required_for_bill', request.action_approve)
    blocked('forged_calculation', lambda: request.write({'award_amount': 1}))
    blocked('forged_default_state', lambda: E['baseer.hr.eos'].with_context(default_state='approved').create(values))
    blocked('forged_default_snapshot', lambda: E['baseer.hr.eos'].with_context(default_source_snapshot={'wage': '999'}).create(values))
    blocked('wrong_company', lambda: E['baseer.hr.eos'].create(dict(values, company_id=1)))
    blocked('unrecorded_service_start', lambda: E['baseer.hr.eos'].create(dict(values, service_start='2017-01-01')).action_calculate())
    version.write({'wage': 3200})
    reason = E['hr.departure.reason'].search([], limit=1)
    departure = E['hr.departure.wizard'].with_context(employee_termination=True).create({
        'employee_ids': [(6, 0, person.ids)], 'departure_reason_id': reason.id,
        'departure_date': '2026-08-31', 'set_date_end': True, 'remove_related_user': False})
    departure.action_register_departure()
    check('native_departure_recorded', version.departure_date == date(2026, 8, 31) and bool(version.departure_reason_id))
    request.write({'evidence_reference': 'QA departure record', 'approval_confirmed': True})
    blocked('stale_salary_source', request.action_approve)
    request.action_calculate()
    request.write({'evidence_reference': 'QA departure record', 'approval_confirmed': True})
    action = request.action_approve()
    bill = request.bill_id
    check('one_posted_taxfree_supplier_bill', action['res_id'] == bill.id and bill.state == 'posted' and bill.move_type == 'in_invoice'
          and bill.partner_id == person.work_contact_id and money(bill.amount_total) == money(request.award_amount)
          and money(bill.amount_tax) == 0 and not bill.invoice_line_ids.tax_ids and bill.date == date(2026, 8, 31))
    check('balanced_native_award_bill', money(sum(bill.line_ids.mapped('balance'))) == 0)
    count = E['account.move'].search_count([('baseer_eos_id', '=', request.id)])
    request.action_approve()
    check('approval_replay_one_bill', count == 1 and E['account.move'].search_count([('baseer_eos_id', '=', request.id)]) == 1)
    blocked('issued_request_mutation', lambda: request.write({'evidence_reference': 'altered'}))
    blocked('issued_request_delete', request.unlink)
    blocked('bill_amount_tamper', lambda: bill.invoice_line_ids.write({'price_unit': 1}))
    blocked('bill_partner_tamper', lambda: bill.write({'partner_id': company.partner_id.id}))
    blocked('bill_source_unlink', lambda: bill.write({'baseer_eos_id': False}))
    blocked('bill_delete_preserves_reservation', bill.unlink)
    blocked('bill_link_default_injection', lambda: E['account.move'].with_context(default_baseer_eos_id=request.id).create({'move_type': 'in_invoice', 'journal_id': purchase.id, 'partner_id': person.work_contact_id.id}))
    blocked('bill_line_default_injection', lambda: E['account.move.line'].with_context(default_move_id=bill.id).create({'name': 'tamper', 'account_id': company.baseer_salary_expense_id.id, 'debit': 1}))
    duplicate = E['baseer.hr.eos'].create(values)
    duplicate.action_calculate()
    duplicate.write({'evidence_reference': 'QA duplicate', 'approval_confirmed': True})
    blocked('duplicate_departure_event', duplicate.action_approve)
    accountant = E['res.users'].create({'name': 'EOS accountant QA', 'login': 'eos-accountant-qa@example.invalid', 'company_id': 10,
        'company_ids': [(6, 0, [10])], 'group_ids': [(6, 0, [env.ref('base.group_user').id, env.ref('account.group_account_user').id])]})
    check('accountant_without_payroll_role', not accountant.has_group('om_hr_payroll.group_hr_payroll_user'))
    blocked('accountant_no_award_access', lambda: request.with_user(accountant).read(['award_amount']))
    accounting = E(user=accountant.id, su=False)
    for amount in [Decimal('1000.00'), money(bill.amount_total) - Decimal('1000.00')]:
        payment = accounting['account.payment.register'].with_context(active_model='account.move', active_ids=bill.ids).create({
            'payment_date': '2026-08-31', 'journal_id': bank.id, 'payment_method_line_id': 110,
            'amount': float(amount), 'group_payment': True, 'payment_difference_handling': 'open'})
        payment._create_payments()
        check('native_eos_payment_' + str(amount), money(request.balance) == money(bill.amount_residual))
        if amount == Decimal('1000.00'):
            check('partial_native_bill', 0 < money(bill.amount_residual) < money(bill.amount_total))
    check('fully_paid_native_bill', money(request.balance) == 0 and request.payment_state == bill.payment_state)
    reverse = bill.with_user(accountant)._reverse_moves([{'date': date(2026, 8, 31), 'invoice_date': date(2026, 8, 31),
        'ref': 'QA reviewed award reversal'}], cancel=True)
    check('native_reversal_not_blocked', reverse.reversed_entry_id == bill and request.bill_id == bill and request.state == 'approved')
    blocked('no_reissue_after_reversal', duplicate.action_approve)
    check('employee_financial_navigation', person.action_view_eos()['res_model'] == 'baseer.hr.eos' and request in person.baseer_eos_ids)
    zero = E['baseer.hr.eos'].create(dict(values, reason='article80'))
    zero.action_calculate()
    zero.write({'reason_verified': True, 'evidence_reference': 'QA reason review', 'approval_confirmed': True})
    blocked('zero_award_not_billed', zero.action_approve)
    special = E['baseer.hr.eos'].create(dict(values, reason='article81'))
    special.action_calculate()
    special.write({'evidence_reference': 'QA special', 'approval_confirmed': True})
    blocked('special_reason_review_required', special.action_approve)
    viewer = E['res.users'].create({'name': 'EOS basic QA', 'login': 'eos-basic-qa@example.invalid', 'company_id': 10,
        'company_ids': [(6, 0, [10])], 'group_ids': [(6, 0, [env.ref('base.group_user').id])]})
    blocked('ordinary_user_award_access', lambda: request.with_user(viewer).read(['award_amount']))
    blocked('ordinary_user_award_create', lambda: E['baseer.hr.eos'].with_user(viewer).create(values))
    R['status'] = 'passed'
except Exception:
    R['status'] = 'failed'
    R['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    R['rolled_back'] = True
    Path('/mnt/qa-evidence/baseer_eos_workflow_regression.json').write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(R, ensure_ascii=False, indent=2))
