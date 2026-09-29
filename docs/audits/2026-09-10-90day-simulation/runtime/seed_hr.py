"""Synthetic HR operations, public ORM workflows only; caller owns transaction.

No product imports are used to calculate expected salary or loan amounts.
Expected money uses Decimal and the declared fixture terms, not report outputs.
"""
import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP


def seed_hr(env, ctx):
    assert env.cr.dbname == 'baseer_sim90_20260910', 'Only the isolated simulation staging database'
    assert ctx['start_date'] in (date(2026, 1, 1), '2026-01-01')
    assert ctx['end_date'] in (date(2026, 3, 31), '2026-03-31')
    company, bank, cash = ctx['company'], ctx['bank_journal'], ctx['cash_journal']
    assert env.company == company and not env.su
    assert bank.company_id == cash.company_id == company
    prefix = ctx.get('prefix', 'SIM90')
    assert prefix == 'SIM90' and company.id == 2 and company.name == 'بصير التجريبية — محاكاة 90 يوماً', 'Synthetic company required'
    assert not env['hr.employee'].search_count([('company_id', '=', company.id)])
    assert company.baseer_proration == 'calendar'
    out = {'manifest': [], 'events': [], 'employees': [], 'runs': [], 'leaves': [],
           'schedules': [], 'attendance_ids': [], 'assumptions': [
               'Calendar-day proration; included allowances; wages denominated in company currency.',
               'All identities and operational documents are synthetic QA fixtures.',
               'Salary settlement reduces native payable; advance payroll recovery is noncash.',
               'No production employee or payroll profile is updated.'], 'counts': {}}
    def q(value):
        return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    def add(rec, expected, moves=None):
        row = {'model': rec._name, 'id': rec.id, 'expected': {
            k: str(v) if isinstance(v, Decimal) else v for k, v in expected.items()},
            'move_ids': (moves or env['account.move']).ids}
        out['manifest'].append(row)
        return row
    def event(key, day, kind, rec, moves, cash_in=0, cash_out=0, supplier=0, residual=None):
        row = {'key': prefix + '-HR-' + key, 'date': str(day), 'kind': kind,
               'model': rec._name, 'id': rec.id, 'move_ids': moves.ids,
               'expected_cash_in': str(q(cash_in)), 'expected_cash_out': str(-abs(q(cash_out))),
               'expected_operational_in': str(q(cash_in)), 'expected_supplier_total': str(q(supplier))}
        if residual is not None:
            row['expected_residual'] = str(q(residual))
        out['events'].append(row)
        return row
    def pay_bill(bill, amount, day, key, journal=bank):
        amount = q(amount)
        register = env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids).create({
                'journal_id': journal.id,
                'payment_method_line_id': journal.outbound_payment_method_line_ids.filtered(
                    lambda x: x.code == 'manual')[:1].id,
                'payment_date': day, 'amount': float(amount), 'group_payment': True,
                'payment_difference_handling': 'open'})
        payments = register._create_payments()
        assert len(payments) == 1
        add(payments, {'amount': amount, 'state': 'paid'}, payments.move_id)
        event(key, day, 'hr_bill_payment', payments, payments.move_id, cash_out=amount)
        return amount

    # Exercise the installed work-schedule wizard, including split daily periods.
    workdays = env['baseer.schedule.day'].search([('weekday', '!=', 4)])
    schedules = {}
    for hours in (8, 10):
        wizard = env['baseer.schedule.wizard'].create({
            'name': '%s جدول تجريبي %s ساعات' % (prefix, hours), 'company_id': company.id,
            'effective_date': '2020-01-01', 'day_ids': [(6, 0, workdays.ids)],
            'period_ids': [(0, 0, {'time_from': '08:00', 'time_to': '12:00'}),
                           (0, 0, {'time_from': '13:00', 'time_to': '17:00' if hours == 8 else '19:00'})]})
        wizard.action_apply()
        schedules[hours] = wizard.applied_calendar_id
        out['schedules'].append(wizard.applied_calendar_id.id)
        add(wizard.applied_calendar_id, {'hours_per_day': q(hours), 'baseer_is_template': True})

    workers = []
    for i in range(24):
        start = date(2026, 1, 15) if i == 20 else date(2026, 2, 10) if i == 21 else date(2020, 1, 1)
        end = date(2026, 3, 20) if i == 22 else date(2026, 3, 31) if i == 23 else None
        hours = 10 if i % 3 == 0 else 8
        mode = 'inclusive' if hours == 10 else 'fixed'
        wage, allowance = q(2400 + 125 * i), q(300 + 25 * (i % 5))
        emp = env['hr.employee'].create({'name': '%s موظف تجريبي %02d' % (prefix, i + 1),
            'company_id': company.id, 'baseer_payroll_enabled': False,
            'work_email': 'sim90.employee%02d@example.invalid' % (i + 1)})
        emp.version_id.write({'date_version': start, 'contract_date_start': start,
            'contract_date_end': end or False, 'resource_calendar_id': schedules[hours].id,
            'wage': float(wage), 'baseer_salary_mode': mode,
            'baseer_allowance_total': float(allowance), 'baseer_work_days': 26})
        if not emp.work_contact_id:
            emp.work_contact_id = env['res.partner'].create({'name': emp.name, 'company_id': company.id})
        emp.work_contact_id.with_company(company).property_account_payable_id = company.baseer_salary_payable_id
        emp.baseer_payroll_enabled = True
        worker = {'index': i, 'record': emp, 'start': start, 'end': end, 'hours': hours,
            'wage': wage, 'allowance': allowance, 'mode': mode, 'absence': {}, 'leave_days': set()}
        workers.append(worker)
        out['employees'].append({'id': emp.id, 'index': i, 'start': str(start), 'end': str(end) if end else None,
            'wage': str(wage), 'allowance': str(allowance), 'hours': hours, 'salary_mode': mode})
        add(emp, {'baseer_salary_total': wage, 'baseer_allowance_total': allowance})

    # Approved full-day/half-day unpaid leave and paid leave; no payroll deduction guessed from attendance.
    leave_types = {}
    for kind, unpaid, unit in [('unpaid', True, 'day'), ('half_unpaid', True, 'half_day'), ('paid', False, 'day')]:
        leave_types[kind] = env['hr.leave.type'].create({'name': prefix + ' ' + kind,
            'requires_allocation': False, 'leave_validation_type': 'no_validation',
            'baseer_unpaid': unpaid, 'request_unit': unit})
    for worker in workers:
        i, emp = worker['index'], worker['record']
        for month in (1, 2, 3):
            day = date(2026, month, 16 + i % 3)
            if day.weekday() == 4:
                day += timedelta(days=1)
            if day < worker['start'] or worker['end'] and day > worker['end']:
                continue
            kind = ('unpaid', 'half_unpaid', 'paid')[i % 3]
            values = {'name': '%s إجازة %s %s' % (prefix, kind, day), 'employee_id': emp.id,
                      'holiday_status_id': leave_types[kind].id, 'request_date_from': day, 'request_date_to': day}
            if kind == 'half_unpaid':
                values.update(request_date_from_period='am', request_date_to_period='am')
            leave = env['hr.leave'].create(values)
            if leave.state != 'validate':
                leave.action_validate()
            worker['absence'][day] = Decimal('1') if kind == 'unpaid' else Decimal('.5') if kind == 'half_unpaid' else Decimal(0)
            worker['leave_days'].add(day)
            out['leaves'].append(leave.id)
            add(leave, {'state': 'validate', 'number_of_days': Decimal('.5') if kind == 'half_unpaid' else Decimal(1)})

    # One source advance per employee, with six distinct recovery paths.
    loan_plans = []
    for worker in workers:
        i, emp = worker['index'], worker['record']
        principal, pattern = q(600 + i * 30), i % 6
        loan_day = max(date(2026, 1, 5 + i % 8), worker['start'])
        due = date(2026, 4, 30) if pattern < 3 else date(2026, 2, 28) if pattern == 5 else date(2026, 1, 31)
        if due < loan_day:
            due = date(2026, 2, 28)
        loan = env['baseer.hr.loan'].create({'name': '%s سلفة %02d نمط %d' % (prefix, i + 1, pattern),
            'employee_id': emp.id, 'company_id': company.id, 'amount': float(principal), 'date': loan_day,
            'first_due_date': due, 'installment_count': 1 if pattern < 3 else 3,
            'journal_id': cash.id if i % 2 else bank.id})
        loan.action_disburse()
        row = add(loan, {'amount': principal, 'paid_amount': q(0), 'balance': principal, 'state': 'running'}, loan.move_id)
        event('loan-%d' % i, loan_day, 'advance_disbursement', loan, loan.move_id, cash_out=principal)
        installments = []
        for offset in range(1 if pattern < 3 else 3):
            m = due.month + offset
            d = date(2026, m, min(due.day, calendar.monthrange(2026, m)[1]))
            installments.append({'due': d, 'remaining': principal if pattern < 3 else q(principal / 3)})
        loan_plans.append({'worker': worker, 'record': loan, 'principal': principal,
            'pattern': pattern, 'remaining': principal, 'row': row, 'installments': installments})

    def recover_direct(plan, amount, day):
        wizard = env['baseer.hr.loan.repay'].create({'loan_id': plan['record'].id,
            'amount': float(amount), 'date': day, 'journal_id': bank.id})
        wizard.action_confirm()
        pending = amount
        for part in plan['installments']:
            take = min(pending, part['remaining'])
            part['remaining'] -= take
            pending -= take
        assert pending == 0
        plan['remaining'] -= amount
        event('repay-%s-%s' % (plan['record'].id, day), day, 'advance_direct_repayment',
              plan['record'], wizard.move_id, cash_in=amount)
    pending_payroll = []
    slip_expected = {}
    def settle_run(run, amounts, day, suffix):
        if not any(amounts.values()):
            return
        wizard = env['baseer.payroll.settlement'].create({'run_id': run.id, 'journal_id': bank.id,
            'payment_method_line_id': bank.outbound_payment_method_line_ids.filtered(lambda x: x.code == 'manual')[:1].id,
            'payment_date': day})
        for line in wizard.line_ids:
            line.amount = float(amounts.get(line.slip_id.id, q(0)))
        wizard.action_confirm()
        for line in wizard.line_ids.filtered(lambda x: x.amount):
            amount = amounts[line.slip_id.id]
            state = slip_expected[line.slip_id.id]
            state['paid'] += amount
            state['row']['expected'].update(baseer_paid=str(state['paid']),
                baseer_residual=str(state['net'] - state['paid']))
            assert len(line.payment_ids) == 1
            payment = line.payment_ids
            add(payment, {'amount': amount, 'state': 'paid'}, payment.move_id)
            event('salary-%s-%s' % (suffix, line.slip_id.id), day, 'salary_payment', payment,
                  payment.move_id, cash_out=amount)

    providers = [env['res.partner'].create({'name': '%s مزود خدمات موظفين %d' % (prefix, i + 1),
                 'company_id': company.id, 'supplier_rank': 1}) for i in range(3)]
    service_keys = ['iqama_issue', 'iqama_renewal', 'work_permit_issue', 'work_permit_renewal',
        'employee_transfer', 'profession_change', 'visa', 'health_certificate_issue',
        'health_certificate_renewal', 'medical_exam', 'ticket', 'insurance_issue',
        'insurance_renewal', 'processing', 'other_employee']
    pending_services = []
    for month in (1, 2, 3):
        first = date(2026, month, 1)
        last = date(2026, month, calendar.monthrange(2026, month)[1])
        for plan in loan_plans:
            loan_day = plan['record'].date
            if plan['pattern'] == 0 and loan_day.month == month:
                recover_direct(plan, plan['principal'], max(loan_day, date(2026, month, 20)))
            if plan['pattern'] == 1 and loan_day.month == month:
                recover_direct(plan, q(plan['principal'] * Decimal('.4')), max(loan_day, date(2026, month, 20)))
            if plan['pattern'] == 1 and month == loan_day.month + 1:
                recover_direct(plan, q(plan['principal'] * Decimal('.6')), date(2026, month, 10))
        for old_run, amounts in pending_payroll:
            settle_run(old_run, amounts, date(2026, month, 5), 'late-%s' % month)
        pending_payroll = []
        for bill, amount, row, ev in pending_services:
            pay_bill(bill, amount, date(2026, month, 8), 'service-late-%s' % bill.id)
            row['expected']['balance'] = '0.00'
            ev['expected_residual'] = '0.00'
            for item in out['manifest']:
                if item['model'] == 'account.move' and item['id'] == bill.id:
                    item['expected']['amount_residual'] = '0.00'
        pending_services = []
        for worker in workers:
            i, emp = worker['index'], worker['record']
            day = max(date(2026, month, 11 + i % 12), worker['start'])
            if day > last or worker['end'] and day > worker['end']:
                continue
            kind = service_keys[(i + month * 4) % len(service_keys)]
            gross = q(115 + i * 23 + month * 46)
            taxable = kind in ('medical_exam', 'ticket', 'insurance_issue', 'insurance_renewal', 'processing', 'other_employee')
            service = env['baseer.hr.service'].create({'employee_id': emp.id, 'company_id': company.id,
                'service_type': kind, 'visa_type': 'issue' if kind == 'visa' else False,
                'partner_id': providers[i % 3].id, 'service_reference': '%s-HRS-%s-%02d' % (prefix, month, i),
                'issue_date': day, 'invoice_date': day, 'gross_amount': float(gross), 'vat_enabled': taxable,
                'notes': 'خدمة تشغيلية تجريبية لا تمثل موظفاً أو معاملة حقيقية'})
            service.action_approve()
            paid = q(0)
            if i % 4 == 0:
                paid = pay_bill(service.bill_id, gross, day, 'service-paid-%s' % service.id)
            elif i % 4 in (1, 2):
                paid = pay_bill(service.bill_id, q(gross / 2), day, 'service-part-%s' % service.id)
                if i % 4 == 1:
                    paid += pay_bill(service.bill_id, gross - paid, last, 'service-same-%s' % service.id)
            row = add(service, {'gross_amount': gross, 'state': 'approved', 'balance': gross - paid}, service.bill_id)
            net = q(gross / Decimal('1.15')) if taxable else gross
            add(service.bill_id, {'state': 'posted', 'amount_total': gross, 'amount_untaxed': net,
                                 'amount_tax': gross - net, 'amount_residual': gross - paid}, service.bill_id)
            ev = event('service-%s' % service.id, day, 'hr_service_bill', service, service.bill_id,
                       supplier=gross, residual=gross - paid)
            if i % 4 == 2 and month < 3:
                pending_services.append((service.bill_id, gross - paid, row, ev))

        run = env['hr.payslip.run'].create({'baseer_managed': True, 'baseer_month': first})
        assert set(run.slip_ids.employee_id.ids) == {w['record'].id for w in workers if w['start'] <= last}
        initial_pay, next_month_pay = {}, {}
        for slip in run.slip_ids:
            worker = next(w for w in workers if w['record'] == slip.employee_id)
            i = worker['index']
            begin, end = max(first, worker['start']), min(last, worker['end'] or last)
            days = Decimal((end - begin).days + 1) - sum(
                (v for d, v in worker['absence'].items() if begin <= d <= end), Decimal(0))
            ratio = days / Decimal(last.day)
            gross, allowance = q(worker['wage'] * ratio), q(worker['allowance'] * ratio)
            if worker['mode'] == 'fixed':
                basic, overtime = gross - allowance, q(0)
            else:
                k = Decimal((worker['hours'] - 8) * 26) / Decimal(208)
                original_basic = q((worker['wage'] - worker['allowance'] * (1 + k)) / (1 + Decimal('1.5') * k))
                basic = q(original_basic * ratio)
                overtime = gross - basic - allowance
            deduction = q(25 + i * 3 + month * 7) if i % 4 == 0 else q(0)
            plan = loan_plans[i]
            defer = plan['pattern'] == 4 and month == 1
            due_parts = [part for part in plan['installments'] if part['due'] <= last and part['remaining'] > 0]
            loan_deduction = q(0) if defer else sum((part['remaining'] for part in due_parts), q(0))
            if defer:
                for part in due_parts:
                    part['due'] = date(2026, month + 1, min(last.day, calendar.monthrange(2026, month + 1)[1]))
            else:
                for part in due_parts:
                    part['remaining'] = q(0)
                plan['remaining'] -= loan_deduction
            slip.write({'baseer_deduction': float(deduction),
                'baseer_deduction_reason': 'خصم تشغيلي تجريبي موثق' if deduction else False,
                'baseer_defer_loan': defer})
            slip.compute_sheet()
            net = gross - deduction - loan_deduction
            row = add(slip, {'baseer_gross': gross, 'baseer_basic': basic, 'baseer_allowance': allowance,
                'baseer_overtime': overtime, 'baseer_deduction': deduction, 'baseer_loan_amount': loan_deduction,
                'baseer_net': net, 'baseer_paid': q(0), 'baseer_residual': net, 'state': 'done'})
            slip_expected[slip.id] = {'net': net, 'paid': q(0), 'row': row}
            pay = net if i % 4 in (0, 1) else q(net / 2) if i % 4 == 2 else q(0)
            initial_pay[slip.id] = pay
            if i % 4 in (2, 3) and month < 3:
                next_month_pay[slip.id] = net - pay
        run.action_approve()
        for slip in run.slip_ids:
            slip_expected[slip.id]['row']['move_ids'] = slip.move_id.ids
            event('accrual-%s' % slip.id, last, 'salary_accrual', slip, slip.move_id)
        settle_run(run, initial_pay, last, 'month-%s' % month)
        if next_month_pay:
            pending_payroll.append((run, next_month_pay))
        out['runs'].append(run.id)

    for plan in loan_plans:
        remaining = plan['remaining']
        plan['row']['expected'].update(balance=str(remaining), paid_amount=str(plan['principal'] - remaining),
            state='closed' if remaining == 0 else 'running')
        plan['row']['move_ids'] = (plan['record'].move_id | plan['record'].allocation_ids.move_id).ids
    for run in env['hr.payslip.run'].browse(out['runs']):
        expected = {}
        for field in ('baseer_gross', 'baseer_deduction', 'baseer_loan_amount', 'baseer_net', 'baseer_paid', 'baseer_residual'):
            expected[field] = sum((Decimal(slip_expected[s.id]['row']['expected'][field]) for s in run.slip_ids), q(0))
        expected['state'] = 'done'
        add(run, expected, run.slip_ids.move_id)

    # End of service: native departures after all payroll accruals, with full and partial award settlement.
    for worker in workers[-2:]:
        emp, end = worker['record'], worker['end']
        departure = env['hr.departure.wizard'].with_context(employee_termination=True).create({
            'employee_ids': [(6, 0, emp.ids)], 'departure_reason_id': env.ref('hr.departure_fired').id,
            'departure_date': end, 'set_date_end': True, 'remove_related_user': False})
        departure.action_register_departure()
        action = emp.action_open_departure_award()
        award = env[action['res_model']].browse(action['res_id'])
        award.write({'evidence_reference': prefix + ' synthetic Gregorian contract reviewed',
                     'approval_confirmed': True, 'gregorian_confirmed': True})
        award.action_approve_workflow()
        stop = end + timedelta(days=1)
        years = Decimal(6) + Decimal((stop - date(2026, 1, 1)).days) / Decimal(365)
        expected_award = q(worker['wage'] * (Decimal('2.5') + years - 5))
        paid = expected_award if worker['index'] == 22 else q(expected_award / 2)
        pay_bill(award.bill_id, paid, date(2026, 3, 31), 'eos-%s' % emp.id)
        add(award, {'award_amount': expected_award, 'balance': expected_award - paid,
                   'received_amount': paid, 'workflow_stage': 'paid' if paid == expected_award else 'partial'}, award.bill_id)
        event('eos-bill-%s' % emp.id, end, 'end_service_bill', award, award.bill_id,
              supplier=expected_award, residual=expected_award - paid)

    if 'hr.attendance' in env:
        # Use UTC timestamps for a Riyadh 08:00 shift; avoid approved leave days.
        attendance_values = []
        for worker in workers:
            day = max(date(2026, 1, 1), worker['start'])
            while day <= min(date(2026, 3, 31), worker['end'] or date(2026, 3, 31)):
                if day.weekday() != 4 and day not in worker['leave_days']:
                    checkin = datetime.combine(day, time(5))
                    attendance_values.append({'employee_id': worker['record'].id,
                        'check_in': checkin, 'check_out': checkin + timedelta(hours=worker['hours'])})
                day += timedelta(days=1)
        attendance = env['hr.attendance'].create(attendance_values)
        out['attendance_ids'] = attendance.ids
    else:
        out['assumptions'].append('hr.attendance is not installed; schedules and approved leave cover time inputs.')
    for model in ('hr.employee', 'hr.payslip', 'baseer.hr.loan', 'baseer.hr.service', 'baseer.hr.eos',
                  'account.payment', 'hr.leave', 'resource.calendar'):
        out['counts'][model] = sum(row['model'] == model for row in out['manifest'])
    out['counts']['hr.payslip.run'] = len(out['runs'])
    out['counts']['hr.attendance'] = len(out['attendance_ids'])
    return out
