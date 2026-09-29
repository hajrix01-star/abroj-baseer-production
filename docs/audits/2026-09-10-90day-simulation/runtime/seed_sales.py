"""Persistent QA sales scenario, using native business actions and a Decimal oracle.

Call seed_sales(env, ctx) from an Odoo shell. This module neither commits nor
deletes records and must never be used against the production database.
The caller owns database isolation, backup, transaction boundaries and output.
"""
from calendar import monthrange
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import patch

from odoo import Command, fields
from odoo.addons.baseer_pos_summary.models.common import native_quote


CENT = Decimal('0.01')
ZERO = Decimal('0.00')


def money(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


@contextmanager
def business_clock(day):
    """Date defaults during a synthetic historical native POS close, not code edits."""
    with patch.object(fields.Date, 'context_today', return_value=day), \
            patch.object(fields.Date, 'today', return_value=day), \
            patch.object(fields.Datetime, 'now', return_value=datetime.combine(day, time(12))):
        yield


def next_month(day, ordinal=5):
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(ordinal, monthrange(year, month)[1]))


def seed_sales(env, ctx):
    assert env.cr.dbname != 'baseer_dev', 'Production must never run synthetic fixtures'
    assert ctx.get('simulation_authorized') is True, 'Caller must explicitly authorize this isolated fixture'
    company = ctx['company']
    env = env(context=dict(env.context, allowed_company_ids=company.ids,
                           tracking_disable=True, generate_pdf=False,
                           lang='en_US', tz='Asia/Riyadh'))
    company = env['res.company'].browse(company.id)
    first = fields.Date.to_date(ctx.get('start_date', '2026-01-01'))
    last = fields.Date.to_date(ctx.get('end_date', '2026-03-31'))
    assert last >= first and (last - first).days <= 89
    prefix = ctx.get('prefix', 'SIM90')
    assert company.currency_id.name == 'SAR'
    config = ctx.get('summary_config') or env['pos.config'].search([
        ('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
    if not config:
        company._baseer_seed_pos_payments()
        config = env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
    assert config, 'Company requires its Baseer accounting/POS seed'
    config = env['pos.config'].browse(config.id)
    config._validate_baseer_setup()
    assert not env['baseer.pos.summary'].search_count([
        ('company_id', '=', company.id), ('business_date', '>=', first),
        ('business_date', '<=', last)]), 'This sales window has already been seeded'
    product, tax = config.baseer_summary_product_id, config.baseer_summary_tax_id
    assert money(tax.amount) == Decimal('15.00'), 'This independent oracle specifies VAT15%'
    methods = {kind: config.payment_method_ids.filtered(
        lambda m: m.active and m.baseer_category_id.kind == kind)
        for kind in ('cash', 'bank', 'platform')}
    assert all(methods.values()) and len(methods['platform']) >= 3
    cash_method, bank_method = methods['cash'][:1], methods['bank'][:1]
    apps = methods['platform'].sorted('id')[:3]
    receivable = cash_method.receivable_account_id or company.account_default_pos_receivable_account_id
    treasury = {kind: ctx.get(kind + '_journal') or methods[kind][:1].journal_id
                for kind in ('cash', 'bank')}
    for journal in treasury.values():
        assert journal.company_id == company and journal.default_account_id.account_type == 'asset_cash'
        for method in journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids:
            if method.code == 'manual' and method.payment_account_id != journal.default_account_id:
                method.payment_account_id = journal.default_account_id
    customers = ctx.get('customers') or env['res.partner'].create([
        {'name': '%s عميل %02d | Customer %02d' % (prefix, n, n),
         'company_id': company.id, 'property_account_receivable_id': receivable.id}
        for n in range(1, 19)])
    customers = env['res.partner'].browse([customer.id for customer in customers])
    fee_account = ctx.get('expense_account') or env['account.account'].create({
        'name': prefix + ' رسوم تسوية التطبيقات | Application settlement fees',
        'code': env['account.account']._search_new_account_code('699910', cache=set()),
        'account_type': 'expense', 'company_ids': [Command.set(company.ids)]})
    later_method = env['pos.payment.method'].create({
        'name': prefix + ' حساب العميل | Customer account', 'company_id': company.id,
        'journal_id': False, 'split_transactions': True})
    native_cash_journal = env['account.journal'].create({
        'name': prefix + ' صندوق نقاط البيع المباشرة | Native retail cash',
        'code': 'S90CS', 'type': 'cash', 'company_id': company.id})
    native_cash_method = env['pos.payment.method'].create({
        'name': prefix + ' نقد نقاط البيع | Retail cash', 'company_id': company.id,
        'journal_id': native_cash_journal.id, 'receivable_account_id': receivable.id,
        'baseer_category_id': cash_method.baseer_category_id.id})
    ordinary = env['pos.config'].create({
        'name': prefix + ' المبيعات المباشرة | Native retail', 'company_id': company.id,
        'journal_id': config.journal_id.id, 'invoice_journal_id': config.invoice_journal_id.id,
        'payment_method_ids': [Command.set((native_cash_method | bank_method | apps | later_method).ids)],
        'cash_control': True, 'use_presets': False})
    result = {'company_id': company.id, 'date_from': str(first), 'date_to': str(last),
              'events': [], 'summaries': [], 'closures': [], 'invoices': [], 'orders': [],
              'claims': [], 'corrections': [], 'config_id': config.id,
              'native_config_id': ordinary.id, 'customer_ids': customers.ids,
              'oracle_basis': 'Deterministic input amounts, VAT15%, independently scheduled payments; no report values'}
    claims = []
    expected_fields = ('expected_cash_in', 'expected_cash_out', 'expected_operational_in',
                       'expected_sales', 'tax', 'expected_settled', 'expected_residual')

    def event(key, day, kind, source, moves=None, **values):
        row = {'key': prefix + '-' + key, 'date': str(day), 'kind': kind,
               'model': source._name, 'id': source.id,
               'move_ids': (moves if moves is not None else env['account.move']).ids}
        row.update({field: ZERO for field in expected_fields})
        row.update(values)
        result['events'].append(row)
        return row

    def tax_of(gross):
        return money(gross - money(gross / Decimal('1.15')))

    def claim(key, day, source, moves, method, amount, mode):
        if not amount:
            return
        lines = moves.line_ids.filtered(lambda l: l.account_id == method.outstanding_account_id and not l.reconciled)
        assert lines, 'Missing actual platform claim ' + key
        claims.append({'key': key, 'date': day, 'source': source, 'lines': lines,
                       'method': method, 'amount': amount, 'mode': mode})

    def make_summary(day, index, shift, allocations, suffix=''):
        customer_count = 38 + index % 31 + (17 if shift == 'evening' else 0)
        zero_sales = not any(amount for method, amount in allocations)
        if zero_sales:
            customer_count = 0
        source = env['baseer.pos.summary'].create({
            'company_id': company.id, 'config_id': config.id, 'business_date': day,
            'day_schedule': 'split', 'period_scope': shift, 'customer_count': customer_count,
            'zero_sales': zero_sales,
            'external_reference': '%s-S-%s-%s%s' % (prefix, day, shift, suffix),
            'notes': 'محاكاة تشغيل كاملة: مبيعات شفت نقد وبنك وثلاثة تطبيقات.',
            'allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': float(value)})
                               for method, value in allocations]})
        source.action_approve()
        return source, customer_count

    def summary_snapshot(source, count, allocations):
        values = {kind: sum((amount for method, amount in allocations
                            if method.baseer_category_id.kind == kind), ZERO)
                  for kind in ('cash', 'bank', 'platform')}
        row = {'id': source.id, 'date': str(source.business_date), 'shift': source.period_scope,
               'gross': sum(values.values(), ZERO), 'customers': count,
               'allocations': values, 'allocation_by_method': {m.id: a for m, a in allocations},
               'active_expected': True}
        result['summaries'].append(row)
        return row

    def record_summary(source, row, suffix=''):
        gross, values = row['gross'], row['allocations']
        return event('SUMMARY-%s%s' % (source.id, suffix), source.business_date, 'summary', source,
                     source._native_moves(), gross=gross, tax=tax_of(gross),
                     expected_sales=gross, expected_settled=gross,
                     expected_cash_in=values['cash'] + values['bank'], expected_operational_in=gross)

    for index in range((last - first).days + 1):
        day = first + timedelta(days=index)
        with business_clock(day):
            for shift_index, shift in enumerate(('morning', 'evening')):
                boost = 4 if day.weekday() in (3, 4, 5) else 0
                allocations = [(cash_method, money(115 * (8 + index % 7 + shift_index * 4 + boost))),
                               (bank_method, money(115 * (10 + index % 9 + shift_index * 5 + boost)))]
                allocations += [(method, money(115 * (3 + (index + app_index) % 6 + shift_index * 2)))
                                for app_index, method in enumerate(apps)]
                if index in (28, 58, 88) and shift == 'morning':
                    allocations = [(method, ZERO) for method, amount in allocations]
                source, count = make_summary(day, index, shift, allocations)
                snapshot = summary_snapshot(source, count, allocations)
                record_summary(source, snapshot)
                # Exercise both immutable reverse/replacement and explicit cancel.
                edit = index % 15 == 8 and shift == 'morning'
                cancel = index % 30 == 20 and shift == 'evening'
                if edit or cancel:
                    wizard = env['baseer.pos.summary.correction'].browse(source.action_open_correction()['res_id'])
                    new_allocations = [(m, amount + (Decimal('115') if m == cash_method else ZERO))
                                       for m, amount in allocations]
                    vals = {'operation': 'cancel' if cancel else 'edit',
                            'reason': prefix + (' إلغاء إدخال مكرر' if cancel else ' تصحيح نقص النقد بمبلغ115'),
                            'acknowledge_bookkeeping': True}
                    if edit:
                        wanted = {m.id: amount for m, amount in new_allocations}
                        vals['line_ids'] = [Command.update(line.id, {'amount_input': str(wanted[line.original_allocation_id.payment_method_id.id])})
                                            for line in wizard.line_ids]
                    wizard.write(vals)
                    wizard.action_correct()
                    snapshot['active_expected'] = False
                    event('SUMMARY-REVERSE-%s' % source.id, day, 'summary_reversal', source,
                          source.reversal_move_ids, gross=-snapshot['gross'], tax=-tax_of(snapshot['gross']),
                          expected_sales=-snapshot['gross'], expected_settled=-snapshot['gross'],
                          expected_cash_out=-(snapshot['allocations']['cash'] + snapshot['allocations']['bank']),
                          expected_operational_in=-snapshot['allocations']['platform'])
                    result['corrections'].append({'model': source._name, 'id': source.id,
                        'operation': vals['operation'], 'audit_id': wizard.audit_id.id})
                    if cancel:
                        source, count = make_summary(day, index, shift, allocations, '-REENTERED')
                    else:
                        source = source.replacement_id
                        allocations = new_allocations
                    snapshot = summary_snapshot(source, count, allocations)
                    record_summary(source, snapshot, '-REPLACEMENT')
                moves = source._native_moves()
                assert all(move.date == day for move in moves)
                for app_index, method in enumerate(apps):
                    amount = dict((m.id, amount) for m, amount in allocations)[method.id]
                    claim('SUMMARY-%s-APP-%s' % (source.id, method.id), day, source, moves,
                          method, amount, (index + shift_index + app_index) % 5)

            # Five native retail orders in one historical session on every day.
            session = env['pos.session'].with_context(default_date=day).create({'config_id': ordinary.id})
            session.set_opening_control(0, prefix + ' daily opening')
            session.start_at = datetime.combine(day, time(6))
            session.stop_at = datetime.combine(day, time(20))
            native_total = native_tax = native_cash = native_bank = native_apps = native_credit = ZERO
            native_moves = env['account.move']
            late_invoice_order = None
            for number in range(5):
                amount = money(115 * (1 + (index + number) % 4))
                refund = number == 4 and index in (12, 42, 72)
                if refund:
                    amount = Decimal('-115.00')
                app_method = apps[index % 3]
                if number == 0:
                    payments = [(native_cash_method, amount)]
                elif number == 1:
                    payments = [(bank_method, amount)]
                elif number == 2 or refund:
                    payments = [(app_method, amount)]
                elif number == 3:
                    payments = [(native_cash_method, money(amount / 2)), (bank_method, money(amount / 2))]
                elif index % 3 == 0:
                    payments = [(native_cash_method, money(amount / 2)), (later_method, money(amount / 2))]
                else:
                    payments = [(native_cash_method, amount)]
                quote = native_quote(abs(amount), tax, product, company)
                sign = -1 if refund else 1
                customer = customers[(index + number) % len(customers)]
                order = env['pos.order'].create({
                    'session_id': session.id, 'company_id': company.id, 'partner_id': customer.id,
                    'date_order': datetime.combine(day, time(8 + number * 2)),
                    'pos_reference': '%s-POS-%s-%s' % (prefix, day, number),
                    'amount_total': float(amount), 'amount_tax': float(quote['tax']) * sign,
                    'amount_paid': 0, 'amount_return': 0, 'is_refund': refund,
                    'lines': [Command.create({'product_id': product.id, 'qty': sign,
                        'price_unit': float(quote['unit_price']), 'price_subtotal': float(quote['net']) * sign,
                        'price_subtotal_incl': float(amount), 'tax_ids': [Command.set(tax.ids)],
                        'full_product_name': 'وجبات ومشروبات | Meals and drinks'})]})
                for method, paid in payments:
                    env['pos.payment'].create({'pos_order_id': order.id, 'payment_method_id': method.id,
                        'amount': float(paid), 'payment_date': datetime.combine(day, time(8 + number * 2))})
                    kind = method.baseer_category_id.kind
                    if method == later_method:
                        native_credit += paid
                    elif kind == 'cash':
                        native_cash += paid
                    elif kind == 'bank':
                        native_bank += paid
                    elif kind == 'platform':
                        native_apps += paid
                order.lines._onchange_amount_line_all()
                order._compute_prices()
                order.action_pos_order_paid()
                native_total += amount
                native_tax += tax_of(amount)
                result['orders'].append({'id': order.id, 'date': str(day), 'gross': amount,
                    'session_id': session.id, 'refund': refund,
                    'payments': [{'method_id': method.id, 'amount': paid} for method, paid in payments]})
                if number == 1 and index % 5 == 0:
                    native_moves |= order.with_context(default_date=day, generate_pdf=False)._generate_pos_order_invoice()
                if number == 0 and index % 7 == 0:
                    late_invoice_order = order
            session._compute_cash_balance()
            session.cash_register_balance_end_real = session.cash_register_balance_end
            session._compute_cash_balance()
            session.with_context(default_date=day).action_pos_session_closing_control()
            assert session.state == 'closed' and session.move_id.state == 'posted'
            if late_invoice_order:
                native_moves |= late_invoice_order.with_context(default_date=day, generate_pdf=False)._generate_pos_order_invoice()
                native_moves |= late_invoice_order.reversed_move_ids
            native_moves |= session._get_related_account_moves()
            assert all(move.date == day for move in native_moves), (
                'Native POS dates leaked outside historical business day',
                [(move.id, str(move.date), move.move_type) for move in native_moves])
            pos_event = event('NATIVE-%s' % session.id, day, 'native_pos', session, native_moves,
                gross=native_total, tax=native_tax, expected_sales=native_total,
                expected_settled=native_total-native_credit, expected_residual=native_credit,
                expected_cash_in=native_cash+native_bank,
                expected_operational_in=native_cash+native_bank+native_apps)
            if native_credit and index % 9 == 0:
                # Pay-later sales stay absent from operational receipts until paid.
                payment_day = min(next_month(day, 7), last)
                paid = money(native_credit / 2)
                lines = session.move_id.line_ids.filtered(lambda l: l.account_id == receivable and not l.reconciled)
                method = treasury['bank'].inbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')[:1]
                payment = env['account.payment'].create({'payment_type': 'inbound', 'partner_type': 'customer',
                    'partner_id': customers[(index + 4) % len(customers)].id, 'amount': float(paid),
                    'date': payment_day, 'journal_id': treasury['bank'].id,
                    'payment_method_line_id': method.id, 'company_id': company.id,
                    'currency_id': company.currency_id.id})
                payment.action_post()
                (lines | payment._seek_for_lines()[1]).reconcile()
                pos_event['expected_residual'] -= paid
                pos_event['expected_settled'] += paid
                event('POS-LATER-%s' % payment.id, payment_day, 'native_pos_receipt', payment, payment.move_id,
                      gross=paid, expected_cash_in=paid, expected_operational_in=paid)
            app_method = apps[index % 3]
            claim('NATIVE-%s-APP-%s' % (session.id, app_method.id), day, session, native_moves,
                  app_method, native_apps, index % 5)

            # Two independently invoiced catering/customer sales every day.
            for number in range(2):
                mode = (index * 2 + number) % 10
                gross = money(115 * (5 + (index * 3 + number) % 16))
                quote = native_quote(gross, tax, product, company)
                invoice = env['account.move'].create({'move_type': 'out_invoice', 'company_id': company.id,
                    'journal_id': config.invoice_journal_id.id, 'partner_id': customers[(index + number) % len(customers)].id,
                    'invoice_date': day, 'date': day, 'invoice_date_due': day + timedelta(days=14),
                    'ref': '%s-INV-%s-%s' % (prefix, day, number),
                    'invoice_line_ids': [Command.create({'name': 'توريد وجبات وتموين | Catering sale',
                        'product_id': product.id, 'quantity': 1, 'price_unit': float(quote['unit_price']),
                        'tax_ids': [Command.set(tax.ids)]})]})
                invoice.action_post()
                history = []
                if mode == 8:
                    wizard = env['baseer.financial.correction'].browse(invoice.action_baseer_correct_operation()['res_id'])
                    corrected_gross = gross + Decimal('115')
                    corrected_quote = native_quote(corrected_gross, tax, product, company)
                    wizard.line_ids.write({'price_unit_input': str(money(corrected_quote['unit_price']))})
                    wizard.reason = prefix + ' تصحيح كمية تموين ناقصة'
                    wizard.action_confirm()
                    history.append({'operation': 'edit', 'old_gross': gross, 'new_gross': corrected_gross,
                                    'audit_id': wizard.audit_id.id})
                    gross = corrected_gross
                    result['corrections'].append({'model': invoice._name, 'id': invoice.id,
                        'operation': 'edit', 'audit_id': wizard.audit_id.id})
                inv_event = event('INVOICE-%s' % invoice.id, day, 'customer_invoice', invoice, invoice,
                    gross=gross, tax=tax_of(gross), expected_sales=gross, expected_residual=gross)
                invoice_manifest = {'id': invoice.id, 'date': str(day), 'gross': gross,
                    'tax': tax_of(gross), 'mode': mode, 'expected_residual': gross,
                    'history': history, 'payments': [], 'active_expected': True}
                result['invoices'].append(invoice_manifest)

                def pay_invoice(target, amount, payment_day, outgoing=False):
                    journal = treasury['cash' if mode % 2 == 0 else 'bank']
                    method_lines = journal.outbound_payment_method_line_ids if outgoing else journal.inbound_payment_method_line_ids
                    method = method_lines.filtered(lambda m: m.code == 'manual')[:1]
                    payment = env['account.payment.register'].with_context(active_model='account.move', active_ids=target.ids).create({
                        'journal_id': journal.id, 'payment_method_line_id': method.id, 'amount': float(amount),
                        'payment_date': payment_day, 'installments_mode': 'full',
                        'payment_difference_handling': 'open'})._create_payments()
                    event('CUSTOMER-PAYMENT-%s' % payment.id, payment_day,
                          'customer_refund_payment' if outgoing else 'customer_receipt', payment, payment.move_id,
                          gross=-amount if outgoing else amount,
                          expected_cash_in=ZERO if outgoing else amount,
                          expected_cash_out=-amount if outgoing else ZERO,
                          expected_operational_in=ZERO if outgoing else amount)
                    return payment

                schedules = []
                if mode in (0, 7, 8):
                    schedules = [(day, gross)]
                elif mode == 1:
                    schedules = [(day, money(gross * Decimal('.40')))]
                elif mode == 2:
                    partial = money(gross * Decimal('.35'))
                    schedules = [(day, partial), (min(day + timedelta(days=3), day.replace(day=monthrange(day.year, day.month)[1])), gross-partial)]
                elif mode == 3:
                    partial = money(gross * Decimal('.30'))
                    schedules = [(day, partial), (next_month(day, 8), gross-partial)]
                elif mode == 4:
                    schedules = [(next_month(day, 12), gross)]
                elif mode == 5:
                    schedules = [(day, money(gross * Decimal('.25')))]
                elif mode == 9:
                    # Cancelled source is retained but contributes no posted sales.
                    wizard = env['baseer.financial.correction'].browse(invoice.action_baseer_cancel_operation()['res_id'])
                    wizard.reason = prefix + ' إلغاء فاتورة تموين مكررة قبل التحصيل'
                    wizard.action_confirm()
                    inv_event.update(expected_sales=ZERO, expected_residual=ZERO, tax=ZERO)
                    invoice_manifest.update(active_expected=False, expected_residual=ZERO)
                    result['corrections'].append({'model': invoice._name, 'id': invoice.id,
                        'operation': 'cancel', 'audit_id': wizard.audit_id.id})
                for payment_day, amount in schedules:
                    if payment_day > last:
                        invoice_manifest['payments'].append({'scheduled_date': str(payment_day), 'amount': amount,
                                                             'executed': False})
                        continue
                    payment = pay_invoice(invoice, amount, payment_day)
                    invoice_manifest['payments'].append({'id': payment.id, 'date': str(payment_day),
                                                         'amount': amount, 'executed': True})
                    inv_event['expected_residual'] -= amount
                    inv_event['expected_settled'] += amount
                    invoice_manifest['expected_residual'] -= amount
                if mode == 7:
                    # Partial genuine credit note and a real customer refund.
                    refund_day = min(day + timedelta(days=2), last)
                    refund_gross = Decimal('115.00')
                    credit = invoice._reverse_moves(default_values_list=[{
                        'date': refund_day, 'invoice_date': refund_day, 'ref': prefix + ' partial catering return',
                        'auto_post': 'no'}], cancel=False)
                    credit.invoice_line_ids.filtered(lambda l: l.display_type == 'product').write({
                        'quantity': 1, 'price_unit': 115 if tax.price_include else 100})
                    credit.action_post()
                    pay_invoice(credit, refund_gross, refund_day, outgoing=True)
                    event('CREDIT-%s' % credit.id, refund_day, 'customer_credit', credit, credit,
                          gross=-refund_gross, tax=-Decimal('15'), expected_sales=-refund_gross,
                          expected_settled=-refund_gross)
                    result['invoices'].append({'id': credit.id, 'date': str(refund_day),
                        'gross': -refund_gross, 'tax': -Decimal('15'), 'mode': 'credit',
                        'expected_residual': ZERO, 'active_expected': True, 'original_id': invoice.id})
        if ctx.get('progress'):
            ctx['progress']('sales', index + 1, str(day))

    # Explicit bank settlements: receivable reduction + bank deposit + fee expense.
    # Inputs determine cash and accrual bridges before reading any report.
    for item in claims:
        amount, day, mode = item['amount'], item['date'], item['mode']
        if amount <= ZERO:
            continue
        same_month = min(day + timedelta(days=3), day.replace(day=monthrange(day.year, day.month)[1]))
        planned = []
        if mode == 0:
            planned = [(same_month, amount)]
        elif mode == 1:
            half = money(amount / 2)
            planned = [(same_month, half), (next_month(day, 6), amount-half)]
        elif mode == 2:
            planned = [(same_month, money(amount / 4))]
        elif mode == 3:
            planned = [(next_month(day, 9), amount)]
        paid_total = ZERO
        for installment, (payment_day, gross) in enumerate(planned):
            if payment_day > last:
                continue
            fee = money(gross * Decimal('.02')) if (item['source'].id + installment) % 3 == 0 else ZERO
            journal = treasury['bank']
            entries = [Command.create({'name': prefix + ' إيداع التطبيق بعد الرسوم',
                'account_id': journal.default_account_id.id, 'debit': float(gross-fee), 'credit': 0}),
                Command.create({'name': prefix + ' تسوية أصل مستحق التطبيق',
                    'account_id': item['method'].outstanding_account_id.id, 'debit': 0, 'credit': float(gross)})]
            if fee:
                entries.append(Command.create({'name': prefix + ' رسوم التطبيق',
                    'account_id': fee_account.id, 'debit': float(fee), 'credit': 0}))
            settlement = env['account.move'].create({'move_type': 'entry', 'company_id': company.id,
                'journal_id': journal.id, 'date': payment_day, 'ref': '%s-%s-%s' % (prefix, item['key'], installment),
                'line_ids': entries})
            settlement.action_post()
            (item['lines'] | settlement.line_ids.filtered(lambda l: l.account_id == item['method'].outstanding_account_id)).reconcile()
            paid_total += gross
            event('APP-SETTLEMENT-%s' % settlement.id, payment_day, 'platform_settlement', settlement, settlement,
                  gross=gross, fee=fee, original_key=item['key'],
                  expected_cash_in=gross-fee, expected_operational_in=-fee,
                  applications_settlement_adjustment=-gross)
        result['claims'].append({'key': item['key'], 'date': str(day), 'model': item['source']._name,
            'id': item['source'].id, 'method_id': item['method'].id,
            'account_id': item['method'].outstanding_account_id.id,
            'gross': amount, 'paid': paid_total, 'expected_residual': amount-paid_total})

    totals = {'daily': {}, 'monthly': {}}
    for event_row in result['events']:
        for scope, key in (('daily', event_row['date']), ('monthly', event_row['date'][:7])):
            bucket = totals[scope].setdefault(key, {field: ZERO for field in expected_fields})
            for field in expected_fields:
                bucket[field] += money(event_row.get(field))
    result['expected'] = totals
    result['counts'] = {'days': (last-first).days+1, 'summary_records': len(result['summaries']),
        'active_summaries': sum(row['active_expected'] for row in result['summaries']),
        'native_orders': len(result['orders']), 'native_sessions': (last-first).days+1,
        'customer_invoice_sources': 2*((last-first).days+1), 'invoice_and_credit_records': len(result['invoices']),
        'platform_claims': len(result['claims']),
        'platform_settlements': sum(e['kind'] == 'platform_settlement' for e in result['events']),
        'corrections': len(result['corrections']), 'events': len(result['events'])}
    env.flush_all()
    return result
