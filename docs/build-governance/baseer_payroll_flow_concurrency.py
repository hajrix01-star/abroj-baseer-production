"""QA-only October completion: concurrent settlement replay and stale snapshot.

Run only after the UI fixture has paid 500 to each of its two employees.
The two final salary payments are intentionally committed to the QA preview.
"""
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier

from odoo import api, fields
from odoo.exceptions import UserError, AccessError, ValidationError
from odoo.service.model import retrying
from odoo.addons.baseer_payroll.models.common import money


SOURCE = Path('/mnt/qa-evidence/baseer_payroll_flow_preview.json')
OUTPUT = Path('/mnt/qa-evidence/baseer_payroll_flow_concurrency.json')
R = {'status': 'started', 'checks': [], 'purpose': 'Complete the October QA payroll exactly once'}


def check(name, condition):
    R['checks'].append({'name': name, 'passed': bool(condition)})
    assert condition, name


def save():
    OUTPUT.write_text(json.dumps(R, ensure_ascii=False, indent=2), encoding='utf-8')


try:
    check('exact_qa_database', env.cr.dbname == 'baseer_reports_qa_20260907')
    preview = json.loads(SOURCE.read_text(encoding='utf-8'))
    run_id = preview['run_id']
    check('explicit_preview_run', isinstance(run_id, int) and run_id > 0)
    check('preview_company', preview.get('company_id', 10) == 10)
    admin = env.ref('base.user_admin')
    context = {
        'allowed_company_ids': [10], 'lang': 'en_US', 'tracking_disable': True,
        'mail_notrack': True, 'mail_create_nosubscribe': True, 'mail_notify_force_send': False,
    }
    E = env(user=admin.id, context=context, su=False)
    run = E['hr.payslip.run'].browse(run_id).exists()
    check('single_existing_run', len(run) == 1)
    check('run_company_and_month', run.company_id.id == 10 and run.baseer_month == fields.Date.to_date('2026-10-01'))
    check('approved_partial_preview', run.baseer_managed and run.state == 'done' and run.baseer_payment_state == 'partial')
    slips = run.slip_ids.sorted('id')
    check('two_preview_employees', len(slips) == 2 and len(slips.employee_id) == 2)
    check('ui_initial_payment_500_each', all(money(slip.baseer_paid) == Decimal('500.00') for slip in slips))
    check('positive_remaining_each', all(money(slip.baseer_residual) > 0 for slip in slips))
    bank = E['account.journal'].browse(132)
    method = E['account.payment.method.line'].browse(110)
    check('existing_direct_bank_configuration',
          bank.company_id.id == 10 and bank.type == 'bank'
          and method in bank.outbound_payment_method_line_ids
          and method.payment_method_id.code == 'manual'
          and method.payment_account_id == bank.default_account_id
          and bank.default_account_id.account_type == 'asset_cash')
    before_payment_ids = set(E['account.payment'].search([('company_id', '=', 10)]).ids)
    expected = {slip.id: str(money(slip.baseer_residual)) for slip in slips}
    expected_total = sum((Decimal(amount) for amount in expected.values()), Decimal('0'))
    values = {'run_id': run.id, 'journal_id': bank.id, 'payment_method_line_id': method.id,
              'payment_date': '2026-10-31'}
    wizard = E['baseer.payroll.settlement'].create(values)
    stale = E['baseer.payroll.settlement'].create(values)
    check('matching_prepared_snapshots', len(wizard.line_ids) == 2 and len(stale.line_ids) == 2
          and money(wizard.amount_total) == expected_total and money(stale.amount_total) == expected_total)
    R.update({
        'status': 'prepared', 'database': env.cr.dbname, 'run_id': run.id, 'company_id': 10,
        'wizard_id': wizard.id, 'stale_wizard_id': stale.id,
        'slip_ids': slips.ids, 'employee_ids': slips.employee_id.ids,
        'expected_remaining_by_slip': expected, 'expected_final_payment_total': str(expected_total),
        'before_company_payment_ids': sorted(before_payment_ids),
    })
    # Separate cursors must see the same wizard and immutable remaining snapshots.
    env.cr.commit()
    save()

    barrier = Barrier(2)

    def confirm_same_wizard(index):
        with env.registry.cursor() as cr:
            isolated = api.Environment(cr, admin.id, context)
            barrier.wait(timeout=20)

            def operation():
                record = isolated['baseer.payroll.settlement'].browse(wizard.id)
                result = record.action_confirm()
                return {'worker': index, 'res_model': result.get('res_model'),
                        'run_id': result.get('res_id'), 'payment_ids': sorted(record.payment_ids.ids)}

            return retrying(operation, isolated)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm_same_wizard, [1, 2]))
    R['workers'] = results
    env.invalidate_all()
    check('both_return_same_run', all(result['res_model'] == 'hr.payslip.run' and result['run_id'] == run.id for result in results))
    check('both_reuse_identical_native_payments', results[0]['payment_ids'] == results[1]['payment_ids'] and len(results[0]['payment_ids']) == 2)
    payment_ids = results[0]['payment_ids']
    payments = E['account.payment'].browse(payment_ids)
    after_payment_ids = set(E['account.payment'].search([('company_id', '=', 10)]).ids)
    check('exactly_two_new_native_payments', after_payment_ids - before_payment_ids == set(payment_ids))
    check('one_batch_for_entire_remaining', sum((money(payment.amount) for payment in payments), Decimal('0')) == expected_total)
    check('native_payments_posted_and_paid', all(payment.state == 'paid' and payment.move_id.state == 'posted'
          and payment.date == fields.Date.to_date('2026-10-31') and payment.company_id.id == 10 for payment in payments))
    check('run_and_employees_fully_paid', run.baseer_payment_state == 'paid' and money(run.baseer_residual) == 0
          and all(slip.baseer_payment_state == 'paid' and money(slip.baseer_residual) == 0 for slip in slips))
    check('native_history_has_exact_final_payments', set(payment_ids).issubset(set(slips.move_id._get_reconciled_payments().ids)))
    check('source_wizard_completed', wizard.state == 'done' and set(wizard.payment_ids.ids) == set(payment_ids))
    try:
        with env.cr.savepoint():
            stale.action_confirm()
    except (UserError, AccessError, ValidationError) as error:
        R['stale_error'] = str(error)
        check('stale_snapshot_rejected', 'balance changed' in str(error).lower())
    else:
        check('stale_snapshot_rejected', False)
    check('stale_wizard_did_not_generate_payments', stale.state == 'draft' and not stale.payment_ids)
    check('no_extra_payments_after_stale_attempt', set(E['account.payment'].search([('company_id', '=', 10)]).ids) == after_payment_ids)
    R.update({'status': 'passed', 'payment_ids': payment_ids,
              'payment_move_ids': payments.move_id.ids,
              'final_state': run.baseer_payment_state, 'final_remaining': str(money(run.baseer_residual)),
              'final_paid': str(money(run.baseer_paid)), 'non_sudo_user_id': admin.id})
    env.cr.commit()
    save()
    print(json.dumps(R, ensure_ascii=False))
except Exception:
    env.cr.rollback()
    R['status'] = 'failed'
    R['traceback'] = traceback.format_exc()
    # Successful concurrent workers may already have committed their intended QA payment.
    R['retry_warning'] = 'Inspect recorded payment IDs and payroll residuals before rerunning this script.'
    save()
    print(json.dumps(R, ensure_ascii=False))
    raise
