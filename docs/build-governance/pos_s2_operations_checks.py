"""Run in QA Odoo shell after upgrade; all fixtures and results roll back."""
import json
import time
from datetime import date, timedelta
from decimal import Decimal

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError

checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def rejected(name, callback):
    try:
        with env.cr.savepoint():
            callback()
    except (ValidationError, UserError, AccessError):
        checks.append(name)
    else:
        raise AssertionError(name)


class RollbackFixtures(Exception):
    pass


try:
    with env.cr.savepoint():
        company = env['res.company'].browse(6)
        scoped = env(context=dict(env.context, allowed_company_ids=[company.id]))
        Summary = scoped['baseer.pos.summary']
        Closure = scoped['baseer.pos.closure']
        Report = scoped['baseer.pos.daily.report']
        config = scoped['pos.config'].search([('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
        method = config.payment_method_ids.filtered(lambda m: m.journal_id.type == 'cash')[:1]
        assert config and method
        start = date(2026, 7, 1)
        assert not Summary.search_count([('company_id', '=', company.id), ('business_date', '>=', start), ('business_date', '<=', start + timedelta(days=30))])

        def summary(offset, period='all', schedule='all', gross=0, customers=0, approve=True):
            values = dict(business_date=start + timedelta(days=offset), period_scope=period,
                          day_schedule=schedule, config_id=config.id, zero_sales=not gross, customer_count=customers)
            if gross:
                values['allocation_ids'] = [Command.create({'payment_method_id': method.id, 'amount': gross})]
            row = Summary.create(values)
            if approve:
                row.action_approve()
            return row

        def closure(first, last=None, period='all', confirm=True):
            row = Closure.create({'date_from': start + timedelta(days=first), 'date_to': start + timedelta(days=last if last is not None else first), 'period_scope': period, 'reason': 'eid', 'notes': 'S2 rollback fixture'})
            if confirm:
                row.action_confirm()
            return row

        moves_before = scoped['account.move'].search_count([('company_id', '=', company.id)])
        zero = summary(0)
        check('Explicit zero approved without a POS order', zero.state == 'approved' and not zero.order_id)
        check('Explicit zero has no accounting entry', scoped['account.move'].search_count([('company_id', '=', company.id)]) == moves_before)
        summary(1, 'morning', 'split', 115, 10)
        summary(1, 'evening', 'split', 230, 20)
        summary(2, 'morning', 'morning', 115, 5)
        summary(3, 'morning', 'split', 115, 10)
        summary(3, 'evening', 'split', 230, 20, approve=False)
        summary(4, 'morning', 'split')
        closure(4, period='evening')
        closure(5, 7)
        closure(8, period='morning')
        closure(8, period='evening')
        closure(9, period='morning')
        data = Report._aggregate_days(company, start, start + timedelta(days=10))
        totals, rows = data['totals'], data['days']
        check('Two shifts count as one day', rows[1]['status'] == 'complete' and rows[1]['sales'] == 345 and rows[1]['customers'] == 30)
        check('Single planned shift completes one day', rows[2]['status'] == 'complete')
        check('Split day missing approved evening is incomplete', rows[3]['status'] == 'incomplete' and rows[3]['sales'] == 115 and rows[3]['customers'] == 10)
        check('Draft evening excluded from recorded totals', totals['recorded_sales'] == Decimal('575.00'))
        check('Closure completes the other half of split day', rows[4]['status'] == 'complete')
        check('Multi-day closure expands inclusively', all(rows[i]['status'] == 'closed' for i in (5, 6, 7)))
        check('Two half closures become full closed day', rows[8]['status'] == 'closed')
        check('A lone half closure does not impersonate a full closure', rows[9]['status'] == 'missing')
        check('No entry is missing, not zero sales', rows[10]['status'] == 'missing' and not rows[10]['has_sales'])
        check('Explicit zero remains genuine operating sales', rows[0]['has_sales'] and rows[0]['sales'] == 0 and rows[0]['status'] == 'complete')
        check('Complete operating date denominator includes zero days', totals['operating_days'] == 4)
        check('Daily average sales uses complete dates only', totals['average_daily_sales'] == Decimal('115.00'))
        check('Daily customer average uses complete date totals', totals['average_daily_customers'] == Decimal('8.75'))
        check('Status counts reconcile entire inclusive period', totals['closed_days'] == 4 and totals['incomplete_days'] == 1 and totals['missing_days'] == 2)
        rejected('Closure refuses an approved summary', lambda: closure(1))
        rejected('Closure refuses a draft summary', lambda: closure(3, period='evening'))
        rejected('Summary refuses a confirmed closure', lambda: summary(6))
        rejected('Closure refuses duplicate overlapping range', lambda: closure(7, 9))
        rejected('Closure refuses more than 366 inclusive days', lambda: closure(20, 386))
        rejected('Report refuses more than 366 inclusive days', lambda: Report._aggregate_days(company, start, start + timedelta(days=366)))
        rejected('Report refuses reversed range', lambda: Report._aggregate_days(company, start, start - timedelta(days=1)))
        closed = closure(12)
        injected = Closure.with_context(default_state='confirmed', default_company_id=7, default_confirmed_by_id=1).create({'date_from': start + timedelta(days=13), 'date_to': start + timedelta(days=13)})
        check('Hostile closure context cannot confirm or change company', injected.state == 'draft' and injected.company_id == company and not injected.confirmed_by_id)
        injected_report = Report.with_context(default_recorded_sales=999, default_company_id=7).create({})
        check('Hostile report context cannot forge totals or company', injected_report.recorded_sales == 0 and injected_report.company_id == company)
        rejected('Closure cannot create for foreign active company', lambda: Closure.create({'company_id': 7}))
        operator = scoped['res.users'].with_context(no_reset_password=True).create({
            'name': 'S2 closure rollback operator', 'login': 's2-closure-rollback-operator',
            'company_id': company.id, 'company_ids': [Command.set([company.id])],
            'group_ids': [Command.set([scoped.ref('base.group_user').id, scoped.ref('point_of_sale.group_pos_user').id])],
        })
        rejected('Nonmanager cannot cancel a closure', lambda: closed.with_user(operator).action_cancel())
        rejected('Nonmanager cannot alter cancellation reason', lambda: closed.with_user(operator).write({'cancellation_reason': 'forged'}))
        foreign = scoped['res.users'].with_context(no_reset_password=True).create({
            'name': 'S2 foreign rollback operator', 'login': 's2-foreign-rollback-operator',
            'company_id': 7, 'company_ids': [Command.set([7])],
            'group_ids': [Command.set([scoped.ref('base.group_user').id, scoped.ref('point_of_sale.group_pos_user').id])],
        })
        rejected('Foreign company operator cannot read a closure', lambda: closed.with_user(foreign).with_context(allowed_company_ids=[7]).read(['notes']))
        rejected('Confirmed closure is immutable', lambda: closed.write({'notes': 'edited'}))
        rejected('Confirmed closure cannot be deleted', lambda: closed.unlink())
        rejected('Closure cancel requires reason', lambda: closed.action_cancel())
        closed.write({'cancellation_reason': 'Entered wrong date'})
        closed.action_cancel()
        check('Cancellation preserves approval and cancellation audit', closed.state == 'cancelled' and closed.confirmed_by_id and closed.cancelled_by_id and closed.cancellation_reason)
        summary(12)
        check('Cancelled closure releases the day', Report._aggregate_days(company, start + timedelta(days=12), start + timedelta(days=12))['days'][0]['status'] == 'complete')
        report = Report.create({'date_from': start, 'date_to': start + timedelta(days=10)})
        report.action_generate()
        rejected('Another operator cannot read private report results', lambda: report.with_user(operator).read(['recorded_sales']))
        check('Native report persisted exactly one result per date', len(report.line_ids) == 11)
        check('Report totals use aggregation authority', report.average_daily_sales == 115 and report.average_daily_customers == 8.75)
        rejected('RPC cannot forge report money', lambda: report.write({'recorded_sales': 999}))
        rejected('RPC cannot forge report rows', lambda: scoped['baseer.pos.daily.report.line'].create({'report_id': report.id, 'company_id': company.id, 'sales': 999}))
        rejected('RPC cannot alter report row money', lambda: report.line_ids[:1].write({'sales': 999}))
        action = report.action_timeline()
        check('Timeline excludes noncomplete days', ('status', '=', 'complete') in action['domain'])
        check('Timeline prevents temporal zero filling', action['context']['graph_groupbys'] == ['date_label'])
        source = report.line_ids.filtered(lambda r: r.business_date == start + timedelta(days=1)).action_summaries()
        check('Source drilldown scopes company and exact summaries', ('company_id', '=', company.id) in source['domain'] and len(source['domain'][0][2]) == 2)
        no_data = Report._aggregate_days(company, start + timedelta(days=15), start + timedelta(days=15))
        check('No complete days has no denominator', no_data['totals']['operating_days'] == 0)
        t0 = time.perf_counter()
        full_year = Report._aggregate_days(company, start, start + timedelta(days=365))
        elapsed = time.perf_counter() - t0
        check('366-day bounded report returns every date', len(full_year['days']) == 366)
        check('366-day local calculation under 2 seconds', elapsed < 2)
        result = {'passed': len(checks), 'checks': checks, 'capacity_366_days_seconds': round(elapsed, 6), 'fixtures': 'rolled back'}
        raise RollbackFixtures()
except RollbackFixtures:
    pass

print('POS_S2_OPERATIONS_RESULT=' + json.dumps(result, ensure_ascii=False))
