"""Independent manifest-to-ledger/report QA verification; execute in Odoo shell.

Set SIMULATION_MANIFEST to a JSON path, or supply SIMULATION_DATA as a global dict.
The input root contains company_id, user_id, and sales/hr/purchases writer payloads.
Expected amounts must come from input intentions, never report read-back values.
No production database is permitted. Every report executes as a real user, su=False,
inside a PostgreSQL-enforced read-only transaction. Exceptions become failed checks.
"""
import calendar
import hashlib
import json
import os
import time
import traceback
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch

from odoo import api, fields
from odoo.exceptions import AccessError
from odoo.fields import Domain

ZERO = Decimal('0.00')
CENT = Decimal('0.01')


def dec(value):
    return Decimal(str(value or 0).replace(',', '')).quantize(CENT, rounding=ROUND_HALF_UP)


def components(data):
    yield data
    for key in ('sales', 'hr', 'purchases', 'purchase', 'finance'):
        if isinstance(data.get(key), dict):
            yield data[key]


def verify(environment, data):
    assert environment.cr.dbname in ('baseer_ic1_20260910', 'baseer_sim90_20260910'), 'QA database identity mismatch'
    environment.cr.rollback()
    environment.cr.execute('SET TRANSACTION READ ONLY')
    environment.cr.execute('SHOW transaction_read_only')
    assert environment.cr.fetchone()[0] == 'on'
    checks, timings, endpoint_timings, samples = [], [], [], {}
    check_scope = []
    selected_sections = {item.strip() for item in os.environ.get('SIMULATION_VERIFY_SECTIONS', '').split(',') if item.strip()}
    if not selected_sections:
        selected_sections = set(data.get('_verify_sections', []))
    pieces = list(components(data))
    events = [event for part in pieces for event in part.get('events', [])]
    summaries = [row for part in pieces for row in part.get('summaries', [])]
    field_manifest = [row for part in pieces for row in part.get('manifest', [])]
    documents = [row for part in pieces for row in part.get('documents', [])]
    inactive_invoices = {int(row['id']): row for part in pieces for row in part.get('invoices', [])
                         if row.get('active_expected') is False}
    company_id = int(data['company_id'])
    user_id = int(data.get('user_id') or data.get('owner_id') or environment.ref('base.user_admin').id)
    actor = api.Environment(environment.cr, user_id, {
        'allowed_company_ids': [company_id], 'lang': 'en_US', 'tz': 'Asia/Riyadh'}, su=False)
    assert not actor.su and company_id in actor.user.company_ids.ids
    company = actor['res.company'].browse(company_id)
    moves = actor['account.move']

    def equal(key, actual, expected, numeric=True):
        success = dec(actual) == dec(expected) if numeric else actual == expected
        checks.append({'key': (check_scope[-1] + '|' + key) if check_scope else key, 'status': 'PASS' if success else 'FAIL',
                       'actual': str(actual), 'expected': str(expected)})
        return success

    def run(key, operation):
        if selected_sections and key not in selected_sections:
            return
        started = time.perf_counter()
        check_scope.append(key)
        try:
            with environment.cr.savepoint(flush=False):
                operation()
        except Exception as error:
            checks.append({'key': key, 'status': 'FAIL', 'error': str(error),
                           'traceback': traceback.format_exc(limit=4)})
        finally:
            timings.append({'key': key, 'milliseconds': round((time.perf_counter() - started) * 1000, 2)})
            check_scope.pop()

    def chosen(first, last):
        return [row for row in events if first <= str(row['date'])[:10] <= last]

    def total(rows, key):
        return sum((dec(row.get(key)) for row in rows), ZERO)

    def domain(first, last):
        return [('company_id', '=', company_id), ('state', '=', 'posted'),
                ('date', '>=', first), ('date', '<=', last)]

    def cash_options(first, last):
        return {'company_ids': [company_id], 'posted_only': True, 'baseer_include_tax': True,
                'baseer_months': [f'2026-{month:02d}' for month in range(int(first[5:7]), int(last[5:7]) + 1)],
                'date': {'mode': 'range', 'date_from': first, 'date_to': last}}

    def section_cards(payload, section):
        group = next(group for group in payload['currency_groups'] if group['currency_id'] == company.currency_id.id)
        return next(item for item in group['sections'] if item['key'] == section)['cards']

    def ledger(first, last):
        rows = chosen(first, last)
        native = actor['account.move.line'].search([
            ('company_id', '=', company_id), ('parent_state', '=', 'posted'),
            ('date', '>=', first), ('date', '<=', last)])
        equal(first + ':ledger-balanced', sum((dec(row.balance) for row in native), ZERO), 0)
        treasury = native.filtered(lambda row: row.account_id.account_type == 'asset_cash')
        equal(first + ':native-cash-net-vs-input', sum((dec(row.balance) for row in treasury), ZERO),
              total(rows, 'expected_cash_in') + total(rows, 'expected_cash_out'))
        equal(first + ':ledger-company-scope', set(native.company_id.ids), {company_id}, False)
        by_move = defaultdict(lambda: ZERO)
        for line in native:
            by_move[line.move_id.id] += dec(line.balance)
        equal(first + ':every-native-move-balanced', {ident: str(amount) for ident, amount in by_move.items() if amount}, {}, False)
        samples[first + ':ledger'] = {'moves': len(native.move_id), 'lines': len(native), 'cash_lines': len(treasury)}

    def all_register(first, last):
        facets = domain(first, last)
        rows = chosen(first, last)
        started = time.perf_counter()
        payload = moves.baseer_financial_register_kpis(facets)
        endpoint_timings.append({'endpoint': 'all-kpis', 'from': first, 'to': last,
                                'milliseconds': round((time.perf_counter() - started) * 1000, 2)})
        equal(first + ':all:coverage', payload.get('uncovered_count'), 0)
        samples[first + '..' + last + ':all'] = payload
        for scope, input_key in [('customer', 'expected_sales'), ('supplier', 'expected_supplier_total')]:
            source_events = [row for row in rows if dec(row.get(input_key)) != ZERO or
                             (input_key in row and 'expected_residual' in row)]
            expected = {'total': total(source_events, input_key)}
            if source_events and all('expected_residual' in row for row in source_events):
                expected['outstanding'] = total(source_events, 'expected_residual')
                expected['settled'] = expected['total'] - expected['outstanding']
                expected['partial'] = sum(1 for row in source_events if
                    ZERO < abs(dec(row['expected_residual'])) < abs(dec(row[input_key])) and
                    dec(row['expected_residual']) * dec(row[input_key]) > ZERO)
            for card in section_cards(payload, scope):
                key = first + ':all:' + scope + ':' + card['key']
                if card['key'] in expected:
                    equal(key + ':input-oracle', card['display'], expected[card['key']])
                native_rows = moves.search(Domain(facets) & Domain(card['domain']))
                if card['key'] == 'partial':
                    equal(key + ':drill-count', card['display'], len(native_rows))
                elif card['key'] != 'overdue':
                    field = {'total': 'baseer_register_amount', 'settled': 'baseer_register_settled',
                             'outstanding': 'baseer_register_outstanding'}[card['key']]
                    equal(key + ':row-card-parity', sum((dec(row[field]) for row in native_rows), ZERO), card['display'])
                else:
                    due = native_rows.line_ids.filtered(lambda row: row.account_id.account_type in
                        ('asset_receivable', 'liability_payable') and row.date_maturity and row.date_maturity < date.today())
                    signed = sum((dec(row.amount_residual) for row in due), ZERO) * (1 if scope == 'customer' else -1)
                    equal(key + ':native-maturity', card['display'], signed)

    def cash_report(first, last):
        rows = chosen(first, last)
        handler = actor['eh.account.dynamic.report.handler.baseer_cash_categories']
        started = time.perf_counter()
        payload = handler.compute(cash_options(first, last))
        endpoint_timings.append({'endpoint': 'cash-report', 'from': first, 'to': last,
                                'milliseconds': round((time.perf_counter() - started) * 1000, 2)})
        values = payload['meta']['exact_totals']
        equal(first + ':cash:receipts-input', values['receipts'], total(rows, 'expected_cash_in'))
        equal(first + ':cash:payments-input', values['payments'], total(rows, 'expected_cash_out'))
        equal(first + ':cash:reconciliation', values['balance_check'], 0)
        if any('expected_sales_collections' in row for row in events):
            collections = total(rows, 'expected_sales_collections')
            equal(first + ':cash:collected-sales-denominator-input', values['sales_collections'], collections)
            if collections:
                for line in payload['lines']:
                    if line['id'] == 'payments' or line['id'].startswith('payments/'):
                        cells = {cell['expression_label']: cell['value'] for cell in line['columns']}
                        if cells.get('receipt_share') is not None:
                            equal(first + ':cash:collection-share:' + line['id'], cells['receipt_share'],
                                  abs(dec(cells['amount'])) * 100 / collections)
        samples[first + '..' + last + ':cash'] = {'totals': values, 'diagnostics': payload['meta'].get('diagnostics', [])}
        by_bill = {int(row['id']): row for row in documents if row.get('category_id') or row.get('category_allocations')}
        category_expected = defaultdict(lambda: ZERO)
        for payment in rows:
            bill = by_bill.get(int(payment.get('bill_id') or 0))
            if not bill or not dec(payment.get('expected_cash_out')):
                continue
            allocations = bill.get('category_allocations') or [{'category_id': bill['category_id'], 'gross': bill['gross']}]
            for allocation in allocations:
                category_expected[int(allocation['category_id'])] += dec(
                    dec(payment['expected_cash_out']) * dec(allocation['gross']) / dec(bill['gross']))
        for category, expected in category_expected.items():
            matched = [line for line in payload['lines'] if line['id'].startswith('payments/')
                       and '/customer-refunds/' not in line['id']
                       and line['id'].endswith('/category-' + str(category))]
            actual = sum((dec(cell['value']) for line in matched for cell in line['columns'] if cell['expression_label'] == 'amount'), ZERO)
            equal(first + ':cash:input-category:' + str(category), actual, expected)
        samples[first + '..' + last + ':cash']['input_categories'] = {str(key): str(value) for key, value in category_expected.items()}

    def classic_reports(first, last):
        """Native ledger independently grouped, without importing report helpers."""
        native = actor['account.move.line'].search([('company_id', '=', company_id),
            ('parent_state', '=', 'posted'), ('date', '<=', last)])
        account_values = defaultdict(lambda: {'opening': ZERO, 'debit': ZERO, 'credit': ZERO})
        period_types, closing_types = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
        for line in native:
            value = account_values[line.account_id.id]
            closing_types[line.account_id.account_type] += dec(line.balance)
            if str(line.date) < first:
                value['opening'] += dec(line.balance)
            else:
                value['debit'] += dec(line.debit)
                value['credit'] += dec(line.credit)
                period_types[line.account_id.account_type] += dec(line.balance)
        options = {'company_ids': [company_id], 'posted_only': True, 'show_zero': False,
                   'hierarchical_groups': False, 'date': {'date_from': first, 'date_to': last}}
        tb = actor['eh.account.dynamic.report.handler.trial_balance'].compute(options)
        tb_rows = {line['meta']['account_id']: line for line in tb['lines']
                   if (line.get('meta') or {}).get('account_id') and line['id'].startswith('account-')}
        equal(first + ':trial-balance:account-coverage', set(tb_rows), set(account_values), False)
        for ident, values in account_values.items():
            if ident not in tb_rows:
                continue
            actual = {cell['expression_label']: cell['value'] for cell in tb_rows[ident]['columns']}
            opening, closing = values['opening'], values['opening'] + values['debit'] - values['credit']
            expected = {'opening_debit': max(opening, ZERO), 'opening_credit': max(-opening, ZERO),
                        'period_debit': values['debit'], 'period_credit': values['credit'],
                        'closing_debit': max(closing, ZERO), 'closing_credit': max(-closing, ZERO)}
            for field, amount in expected.items():
                equal(first + ':trial-balance:' + str(ident) + ':' + field, actual[field], amount)
        for tier in ('opening', 'period', 'closing'):
            equal(first + ':trial-balance:' + tier + ':balanced', tb['totals'][tier + '_debit'], tb['totals'][tier + '_credit'])
        pl = actor['eh.account.dynamic.report.handler.profit_and_loss'].compute(options)
        income = -sum((amount for kind, amount in period_types.items() if kind.startswith('income')), ZERO)
        expense = sum((amount for kind, amount in period_types.items() if kind.startswith('expense')), ZERO)
        for field, expected in [('income', income), ('expenses', expense), ('net_profit', income - expense)]:
            equal(first + ':profit-loss:' + field + ':native-ledger', pl['totals'][field], expected)
        bs = actor['eh.account.dynamic.report.handler.balance_sheet'].compute(options)
        assets = sum((amount for kind, amount in closing_types.items() if kind.startswith('asset')), ZERO)
        liabilities = -sum((amount for kind, amount in closing_types.items() if kind.startswith('liability')), ZERO)
        equity = -sum((amount for kind, amount in closing_types.items() if kind.startswith('equity')), ZERO)
        earnings = -sum((amount for kind, amount in closing_types.items() if kind.startswith(('income', 'expense'))), ZERO)
        for field, expected in [('assets', assets), ('liabilities', liabilities), ('equity', equity),
                                ('current_year_earnings', earnings), ('balance_check', ZERO)]:
            equal(first + ':balance-sheet:' + field + ':native-ledger', bs['totals'][field], expected)
        gl = actor['eh.account.dynamic.report.handler.general_ledger'].compute(dict(options, lazy_expand=True))
        equal(first + ':general-ledger:account-coverage',
              {row['meta']['account_id'] for row in gl['lines'] if (row.get('meta') or {}).get('kind') == 'account_total'},
              set(account_values), False)
        for row in gl['lines']:
            if (row.get('meta') or {}).get('kind') != 'account_total':
                continue
            ident = row['meta']['account_id']
            values = account_values[ident]
            actual = next(cell['value'] for cell in row['columns'] if cell['expression_label'] == 'balance')
            equal(first + ':general-ledger:' + str(ident) + ':closing', actual, values['opening'] + values['debit'] - values['credit'])
        samples[first + '..' + last + ':classic'] = {'trial_balance': tb['totals'], 'profit_and_loss': pl['totals'],
            'balance_sheet': bs['totals'], 'general_ledger_account_count': len(account_values)}

    def operational(first, last):
        scoped = moves.with_context(baseer_register_cash_month=first[:7])
        rows = chosen(first, last)
        facets = domain(first, last)
        started = time.perf_counter()
        payload = scoped.baseer_financial_register_cash_kpis(facets)
        endpoint_timings.append({'endpoint': 'inout-kpis', 'from': first, 'to': last,
                                'milliseconds': round((time.perf_counter() - started) * 1000, 2)})
        expected = {'receipts': total(rows, 'expected_operational_in'), 'payments': total(rows, 'expected_cash_out')}
        expected['net'] = expected['receipts'] + expected['payments']
        samples[first + '..' + last + ':inout'] = payload
        for card in section_cards(payload, 'cash'):
            key = first + ':inout:' + card['key']
            equal(key + ':input-oracle', card['display'], expected[card['key']])
            native_rows = scoped.search(Domain(facets) & Domain([('baseer_register_cash_visible', '=', True)]) & Domain(card['domain']))
            field = {'receipts': 'baseer_register_cash_receipts', 'payments': 'baseer_register_cash_payments',
                     'net': 'baseer_register_cash_net'}[card['key']]
            equal(key + ':row-card-parity', sum((dec(row[field]) for row in native_rows), ZERO), card['display'])

    def dashboard(first, last):
        expected_rows = [row for row in summaries if row.get('active_expected', True) and first <= row['date'] <= last]
        dashboard = actor['spreadsheet.dashboard'].search([('baseer_dashboard_kind', '=', 'sales_summary'), ('is_published', '=', True)], limit=1)
        assert dashboard, 'Sales dashboard missing'
        started = time.perf_counter()
        payload = dashboard.get_baseer_sales_metrics({'preset': 'custom', 'date_from': first, 'date_to': last})
        endpoint_timings.append({'endpoint': 'sales-dashboard', 'from': first, 'to': last,
                                'milliseconds': round((time.perf_counter() - started) * 1000, 2)})
        expected_sales = total(expected_rows, 'gross')
        expected_customers = sum(int(row['customers']) for row in expected_rows)
        equal(first + ':dashboard:sales-input', payload['cards']['sales']['value'], expected_sales)
        equal(first + ':dashboard:customers-input', payload['cards']['customers']['value'], expected_customers)
        if expected_customers:
            equal(first + ':dashboard:average-bill-input', payload['cards']['average_bill']['value'], expected_sales / expected_customers)
        operating_dates = {row['date'] for row in expected_rows}
        if operating_dates and all({row['shift'] for row in expected_rows if row['date'] == day}
                                   == {'morning', 'evening'} for day in operating_dates):
            equal(first + ':dashboard:operating-days-input', payload['coverage']['operating_days'], len(operating_dates))
            equal(first + ':dashboard:average-daily-sales-input', payload['cards']['daily_sales']['value'], expected_sales / len(operating_dates))
            equal(first + ':dashboard:average-daily-customers-input', payload['cards']['daily_customers']['value'],
                  Decimal(expected_customers) / len(operating_dates))
        previous_period = payload['comparison_period']
        previous = [row for row in summaries if row.get('active_expected', True)
                    and previous_period['date_from'] <= row['date'] <= previous_period['date_to']]
        for field, expected_previous in [('sales', total(previous, 'gross')),
                                          ('customers', sum(int(row['customers']) for row in previous))]:
            comparison = payload['cards'][field]['comparison']
            equal(first + ':dashboard:previous:' + field, comparison['previous_display'], expected_previous)
            if previous and expected_rows and expected_previous:
                now = expected_sales if field == 'sales' else Decimal(expected_customers)
                equal(first + ':dashboard:comparison:' + field, comparison['display'].rstrip('%'),
                      (now - expected_previous) * 100 / abs(expected_previous))
        for point in payload['timeline']['points']:
            point_rows = [row for row in expected_rows if row['date'].startswith(point['key'])]
            equal('timeline:' + point['key'] + ':sales-input', point['sales'], total(point_rows, 'gross'))
            equal('timeline:' + point['key'] + ':customers-input', point['customers'], sum(int(row['customers']) for row in point_rows))
        category_totals = defaultdict(lambda: ZERO)
        for row in expected_rows:
            for category, amount in row.get('allocations', {}).items():
                category_totals[category] += dec(amount)
        for category in payload['payment_performance']['categories']:
            equal(first + ':dashboard:category:' + category['kind'], category['sales']['value'], category_totals[category['kind']])
        if expected_sales:
            equal(first + ':dashboard:application-share', payload['payment_performance']['application_share']['value'],
                  category_totals['platform'] * 100 / expected_sales)
        for shift in payload['shift_performance']['rows']:
            selected = [row for row in expected_rows if row['shift'] == shift['key']]
            equal(first + ':dashboard:shift:' + shift['key'] + ':sales', shift['cards']['sales']['value'], total(selected, 'gross'))
            equal(first + ':dashboard:shift:' + shift['key'] + ':customers', shift['cards']['customers']['value'], sum(int(row['customers']) for row in selected))
        actual_sources = actor['baseer.pos.summary'].search(payload['source_action']['domain'])
        equal(first + ':dashboard:drill-ids', set(actual_sources.ids), {int(row['id']) for row in expected_rows}, False)
        if first[:7] == last[:7]:
            daily = actor['baseer.pos.daily.report']._aggregate_days(company, date.fromisoformat(first), date.fromisoformat(last))
            for day in daily['days']:
                day_rows = [row for row in expected_rows if row['date'] == day['date_label']]
                equal(day['date_label'] + ':daily:sales-input', day['sales'], total(day_rows, 'gross'))
                equal(day['date_label'] + ':daily:customers-input', day['customers'], sum(int(row['customers']) for row in day_rows))
                # The sales writer explicitly intends both operating shifts daily.
                if {row['shift'] for row in day_rows} == {'morning', 'evening'}:
                    equal(day['date_label'] + ':daily:complete-shift-coverage', day['status'], 'complete', False)
        samples[first + '..' + last + ':dashboard'] = payload

    def expected_fields():
        assert field_manifest, 'No independent HR/batch field expectations provided'
        equal('input:purchase-category-expectations-present', any(row.get('category_id') or row.get('category_allocations') for row in documents), True, False)
        by_model = defaultdict(set)
        for row in field_manifest:
            by_model[row['model']].add(int(row['id']))
        prefetched = {model: {record.id: record for record in actor[model].browse(sorted(ids)).exists()}
                      for model, ids in by_model.items()}
        for row in field_manifest:
            record = prefetched[row['model']].get(int(row['id']), actor[row['model']])
            equal('manifest:' + row['model'] + ':' + str(row['id']) + ':exists', bool(record), True, False)
            record.check_access('read')
            for field, expected in row.get('expected', {}).items():
                actual = record[field]
                spec = record._fields[field]
                if spec.type == 'many2one':
                    actual = actual.id or False
                elif spec.type in ('many2many', 'one2many'):
                    actual = sorted(actual.ids)
                elif spec.type in ('date', 'datetime'):
                    actual = str(actual) if actual else False
                equal('manifest:' + row['model'] + ':' + str(row['id']) + ':' + field, actual, expected,
                      spec.type in ('monetary', 'float', 'integer'))
            expected = row.get('expected', {})
            if row['model'] == 'hr.payslip' and record.move_id:
                posting = record.move_id.line_ids
                payable = posting.filtered(lambda line: line.account_id.account_type == 'liability_payable')
                salary = posting.filtered(lambda line: line.account_id == company.baseer_salary_expense_id)
                if 'baseer_net' in expected:
                    equal('payroll:' + str(record.id) + ':native-liability-input',
                          -sum((dec(line.balance) for line in payable), ZERO), expected['baseer_net'])
                if 'baseer_gross' in expected:
                    equal('payroll:' + str(record.id) + ':native-salary-expense-input',
                          sum((dec(line.balance) for line in salary), ZERO), expected['baseer_gross'])
                if 'baseer_residual' in expected:
                    equal('payroll:' + str(record.id) + ':native-residual-input',
                          -sum((dec(line.amount_residual) for line in payable), ZERO), expected['baseer_residual'])
            if row['model'] == 'baseer.hr.loan' and record.move_id and 'balance' in expected:
                principal = record.move_id.line_ids.filtered(lambda line: line.account_id == company.baseer_loan_account_id)
                equal('loan:' + str(record.id) + ':native-residual-input',
                      sum((dec(line.amount_residual) for line in principal), ZERO), expected['balance'])
        slips = actor['hr.payslip'].browse([row['id'] for row in field_manifest if row['model'] == 'hr.payslip'])
        for employee in slips.employee_id:
            expected_slips = slips.filtered(lambda slip: slip.employee_id == employee and slip.state != 'cancel')
            equal('employee:' + str(employee.id) + ':financial-history-complete',
                  set(employee.baseer_financial_slip_ids.ids), set(expected_slips.ids), False)
        for row in events:
            model = row.get('model') or row.get('source_model')
            ident = row.get('id') or row.get('source_id')
            if model == 'account.move' and ident:
                invoice = moves.browse(int(ident))
                if invoice.move_type != 'entry' and 'gross' in row:
                    equal(str(row.get('key', ident)) + ':invoice-native-gross', abs(invoice.amount_total), abs(dec(row['gross'])))
                    if 'expected_residual' in row:
                        if int(ident) in inactive_invoices:
                            plan = inactive_invoices[int(ident)]
                            equal(str(row.get('key', ident)) + ':cancelled-invoice-state', invoice.state, 'cancel', False)
                            equal(str(row.get('key', ident)) + ':cancelled-invoice-unpaid-input', bool(plan.get('payments')), False, False)
                            # An unpaid cancelled invoice retains its native residual. Its
                            # financial-register contribution is independently checked as zero.
                            equal(str(row.get('key', ident)) + ':cancelled-invoice-native-residual',
                                  abs(invoice.amount_residual), abs(dec(plan['gross'])))
                        else:
                            equal(str(row.get('key', ident)) + ':invoice-native-residual', abs(invoice.amount_residual), abs(dec(row['expected_residual'])))
        for row in documents:
            invoice = moves.browse(int(row['id']))
            key = str(row.get('key') or 'invoice-' + str(row['id']))
            if row.get('date'):
                equal(key + ':invoice-posting-date-input', str(invoice.date), row['date'], False)
            categories = row.get('category_allocations') or ([{'category_id': row['category_id']}] if row.get('category_id') else [])
            if categories:
                equal(key + ':invoice-product-category-input',
                      set(invoice.invoice_line_ids.product_id.categ_id.ids), {int(item['category_id']) for item in categories}, False)
            if row.get('product_id'):
                equal(key + ':invoice-product-input', set(invoice.invoice_line_ids.product_id.ids), {int(row['product_id'])}, False)
            if row.get('expense_account_id'):
                equal(key + ':invoice-expense-account-input',
                      set(invoice.invoice_line_ids.filtered(lambda line: line.display_type == 'product').account_id.ids),
                      {int(row['expense_account_id'])}, False)

    def supplier_priority():
        purchase_data = next(part for part in pieces if part.get('vendor_ids'))
        vendor_ids = [int(ident) for ident in purchase_data['vendor_ids']]
        favorite_ids = set(vendor_ids[:5])  # Explicit seed_purchases input declaration.
        expected_counts = {ident: 0 for ident in vendor_ids}
        recurring = ['electricity', 'water', 'telecom', 'internet', 'rent', 'maintenance',
                     'cleaning', 'fuel', 'mudad_subscription', 'municipal_license']
        source_partners = {}
        for document in documents:
            parts = str(document.get('key') or '').split('/')
            if len(parts) < 3 or parts[0] != 'SIM90':
                continue
            if parts[1] in ('DIRECT', 'BATCH'):
                day_index = (date.fromisoformat(parts[2]) - date(2026, 1, 1)).days
                line_index = int(parts[3]) - 1
                slot = day_index + line_index * (3 if parts[1] == 'BATCH' else 1)
            elif parts[1] == 'EXPENSE':
                slot = recurring.index(parts[3]) + 8
            elif parts[1] == 'PO':
                slot = int(parts[2]) - 1
            else:
                continue
            partner_id = vendor_ids[slot % len(vendor_ids)]
            source_partners[int(document['id'])] = partner_id
            expected_counts[partner_id] += 1
        equal('supplier-priority:independent-planned-bill-count', sum(expected_counts.values()), 948)
        bill_sources = moves.browse(sorted(source_partners))
        for bill in bill_sources:
            equal('supplier-priority:bill:' + str(bill.id) + ':planned-partner', bill.partner_id.id,
                  source_partners[bill.id], False)
        priority = actor['res.partner'].with_context(baseer_partner_priority=True)
        vendors = priority.browse(vendor_ids)
        equal('supplier-priority:five-favorites-input', set(vendors.filtered('baseer_is_favorite').ids), favorite_ids, False)
        # Freeze only a read-time date default; no database date or stored value changes.
        with patch.object(fields.Date, 'context_today', return_value=date(2026, 3, 31)):
            vendors.invalidate_recordset(['baseer_recent_bill_count'], flush=False)
            for vendor in vendors:
                equal('supplier-priority:' + str(vendor.id) + ':90-day-count-at-march31',
                      vendor.baseer_recent_bill_count, expected_counts[vendor.id])
            expected_order = sorted(vendor_ids, key=lambda ident: (-int(ident in favorite_ids),
                -expected_counts[ident], vendor_ids.index(ident)))
            equal('supplier-priority:rank-at-march31',
                  priority.search([('id', 'in', vendor_ids)]).ids, expected_order, False)
        vendors.invalidate_recordset(['baseer_recent_bill_count'], flush=False)
        if date.today() > date(2026, 6, 29):
            for vendor in vendors:
                equal('supplier-priority:' + str(vendor.id) + ':actual-today-historical-outside-window',
                      vendor.baseer_recent_bill_count, 0)
        samples['supplier-priority'] = {'anchor_date': '2026-03-31', 'favorite_ids': sorted(favorite_ids),
            'expected_counts': expected_counts, 'expected_rank': expected_order,
            'date_patch_scope': 'Read-time context_today only; not a database edit.'}

    def source_contributions():
        """A batched projection, checked against each separately declared input.

        This prevents opposite errors from cancelling in a monthly grand total.
        Move identities are creation evidence; their amounts remain independent.
        """
        candidates = [row for row in events if row.get('move_ids') and
                      (dec(row.get('expected_sales')) or dec(row.get('expected_supplier_total')))]
        all_ids = sorted({ident for row in candidates for ident in row['move_ids']})
        records = moves.browse(all_ids).exists()
        records.mapped('baseer_register_amount')
        records.mapped('baseer_register_outstanding')
        amounts = {record.id: (record.baseer_register_scope, dec(record.baseer_register_amount),
                              dec(record.baseer_register_outstanding)) for record in records}
        for event in candidates:
            for scope, field in [('customer', 'expected_sales'), ('supplier', 'expected_supplier_total')]:
                if not dec(event.get(field)):
                    continue
                contributed = [amounts[ident] for ident in set(event['move_ids'])
                               if ident in amounts and amounts[ident][0] == scope]
                equal(str(event['key']) + ':source:' + scope + ':input-total',
                      sum((item[1] for item in contributed), ZERO), event[field])
                if 'expected_residual' in event:
                    equal(str(event['key']) + ':source:' + scope + ':input-residual',
                          sum((item[2] for item in contributed), ZERO), event['expected_residual'])

    def security():
        if data.get('roles', {}).get('accountant') and data.get('other_company_id'):
            accountant = api.Environment(environment.cr, int(data['roles']['accountant']),
                {'allowed_company_ids': [company_id]}, su=False)
            foreign_id = int(data['other_company_id'])
            equal('security:accountant:foreign-ledger-search-empty',
                  accountant['account.move'].search_count([('company_id', '=', foreign_id)]), 0)
            try:
                accountant['account.move'].with_context(allowed_company_ids=[foreign_id]).baseer_financial_register_kpis([])
            except AccessError:
                equal('security:accountant:forged-company-denied', True, True, False)
            else:
                equal('security:accountant:forged-company-denied', False, True, False)
        users = actor['res.users'].search([('baseer_access_role', '=', 'cashier'), ('active', '=', True), ('company_ids', 'in', [company_id])])
        equal('security:cashier-fixture-present', bool(users), True, False)
        for user in users:
            cashier = api.Environment(environment.cr, user.id, {'allowed_company_ids': [company_id]}, su=False)
            try:
                cashier['account.move'].baseer_financial_register_kpis([])
            except AccessError:
                equal('security:cashier:' + str(user.id) + ':register-denied', True, True, False)
            else:
                equal('security:cashier:' + str(user.id) + ':register-denied', False, True, False)
            try:
                cashier['account.move'].with_context(baseer_register_cash_month='2026-01').baseer_financial_register_cash_kpis([])
            except AccessError:
                equal('security:cashier:' + str(user.id) + ':inout-denied', True, True, False)
            else:
                equal('security:cashier:' + str(user.id) + ':inout-denied', False, True, False)
            employee = actor['hr.employee'].search([('company_id', '=', company_id)], limit=1)
            if employee:
                try:
                    cashier['hr.employee'].browse(employee.id).read(['baseer_salary_total'])
                except AccessError:
                    equal('security:cashier:' + str(user.id) + ':salary-field-denied', True, True, False)
                else:
                    equal('security:cashier:' + str(user.id) + ':salary-field-denied', False, True, False)
            batches = cashier['baseer.purchase.batch'].search([])
            equal('security:cashier:' + str(user.id) + ':own-purchase-only',
                  set(batches.create_uid.ids) - {user.id}, set(), False)
            if data.get('other_company_id'):
                foreign = cashier['account.move'].with_context(allowed_company_ids=[int(data['other_company_id'])])
                try:
                    foreign.baseer_financial_register_kpis([])
                except AccessError:
                    equal('security:cashier:' + str(user.id) + ':forged-company-denied', True, True, False)
                else:
                    equal('security:cashier:' + str(user.id) + ':forged-company-denied', False, True, False)
        for model in ('baseer.pos.summary', 'baseer.purchase.batch', 'hr.payslip', 'baseer.hr.loan', 'baseer.hr.service'):
            records = actor[model].search([])
            equal('security:' + model + ':active-company-isolation', set(records.company_id.ids) - {company_id}, set(), False)

    equal('input:events-present', bool(events), True, False)
    equal('input:summary-covered-calendar-days', len({row['date'] for row in summaries if row.get('active_expected', True)}), 90)
    for month in (1, 2, 3):
        first, last = f'2026-{month:02d}-01', f'2026-{month:02d}-{calendar.monthrange(2026, month)[1]}'
        for key, operation in [('ledger', ledger), ('all', all_register), ('cash', cash_report), ('inout', operational), ('dashboard', dashboard), ('classic-reports', classic_reports)]:
            run(first[:7] + ':' + key, lambda operation=operation, first=first, last=last: operation(first, last))
    for key, operation in [('all-quarter', all_register), ('cash-quarter', cash_report), ('dashboard-quarter', dashboard), ('classic-quarter', classic_reports)]:
        run(key, lambda operation=operation: operation('2026-01-01', '2026-03-31'))
    run('source-contributions', source_contributions)
    run('expected-fields', expected_fields)
    run('supplier-priority', supplier_priority)
    run('security', security)
    if selected_sections:
        equal('selected-section-coverage', {item['key'] for item in timings}, selected_sections, False)
    environment.cr.execute('SHOW transaction_read_only')
    equal('database:enforced-read-only-at-end', environment.cr.fetchone()[0], 'on', False)
    environment.cr.rollback()
    return {'status': 'FAIL' if any(row['status'] == 'FAIL' for row in checks) else ('PARTIAL_PASS' if selected_sections else 'PASS'),
            'database': environment.cr.dbname, 'user_id': user_id, 'su': False, 'company_id': company_id,
            'database_enforced_read_only': True, 'rollback': True,
            'checks': checks, 'timings': timings, 'endpoint_timings': endpoint_timings, 'samples': samples,
            'selected_sections': sorted(selected_sections) if selected_sections else 'ALL',
            'counts': {'events': len(events), 'summaries': len(summaries), 'field_manifest': len(field_manifest)},
            'limits': ['Single-reader timings only; no concurrent-load or capacity certification.',
                       'Card-row parity is secondary; manifest input amounts are the independent oracle.',
                       'Browser, print/export and mutation-denial journeys require separate evidence.']}


if 'env' in globals():
    simulation = globals().get('SIMULATION_DATA')
    if simulation is None:
        explicit = os.environ.get('SIMULATION_MANIFEST')
        if explicit:
            simulation = json.loads(Path(explicit).read_text())
        else:
            simulation = json.loads(Path('/tmp/sim90/context.json').read_text())
            for part in ('sales', 'hr', 'purchases'):
                path = Path('/tmp/sim90/' + part + '.json')
                if not path.exists():
                    path = Path('/tmp/sim90/' + part + '-manifest.json')
                loaded = json.loads(path.read_text())
                if isinstance(loaded.get('manifest'), str):
                    reference = Path(loaded['manifest'])
                    if not reference.is_absolute():
                        reference = path.parent / reference
                    loaded = json.loads(reference.read_text())
                assert isinstance(loaded.get('events'), list), 'Missing event manifest: ' + part
                assert not isinstance(loaded.get('manifest'), str), 'Unresolved manifest pointer: ' + part
                simulation[part] = loaded
            assert isinstance(simulation['sales'].get('summaries'), list), 'Sales summary input missing'
    result = verify(env, simulation)
    verifier_path = Path('/tmp/sim90/verify_simulation.py')
    result['verifier_sha256'] = hashlib.sha256(verifier_path.read_bytes()).hexdigest() if verifier_path.exists() else None
    result['manifest_sha256'] = hashlib.sha256(json.dumps(simulation, sort_keys=True, default=str).encode()).hexdigest()
    output_name = os.environ.get('SIMULATION_VERIFY_OUTPUT') or ('verification-partial.json' if result['selected_sections'] != 'ALL' else 'verification.json')
    assert Path(output_name).name == output_name and output_name.startswith('verification') and output_name.endswith('.json')
    Path('/tmp/sim90/' + output_name).write_text(json.dumps(result, default=str, ensure_ascii=False, indent=2))
    print('SIMULATION_VERIFY_JSON ' + json.dumps(result, default=str, ensure_ascii=False))
