"""QA-only acceptance of the shared two-card entry, with full rollback."""
import json
from datetime import date
from unittest.mock import patch
from psycopg2 import IntegrityError

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
    except (AccessError, UserError, ValidationError, IntegrityError):
        checks.append(name)
    else:
        raise AssertionError(name)


class RollbackFixtures(Exception):
    pass


try:
    with env.cr.savepoint():
        qa = env(context=dict(env.context, allowed_company_ids=[6]))
        Entry, Summary = qa['baseer.pos.day.entry'], qa['baseer.pos.summary']
        config = Summary._default_config()
        method = config.payment_method_ids.filtered(lambda row: row.journal_id.type == 'cash')[:1]
        assert config and method

        def entry(day, first=115, second=230, **extras):
            values = {'business_date': date(2026, 8, day), 'day_schedule': 'split', 'first_customers': 10, 'second_customers': 20,
                      'first_allocation_ids': [Command.create({'slot': 'first', 'payment_method_id': method.id, 'amount': first})],
                      'second_allocation_ids': [Command.create({'slot': 'second', 'payment_method_id': method.id, 'amount': second})]}
            values.update(extras)
            return Entry.create(values)

        defaults = Entry.default_get(['company_id', 'config_id', 'first_allocation_ids', 'second_allocation_ids'])
        check('Both cards prefill configured payment methods', len(defaults['first_allocation_ids']) == len(config.payment_method_ids) and len(defaults['second_allocation_ids']) == len(config.payment_method_ids))
        shared = entry(20)
        check('Independent shift totals aggregate on the entry', shared.first_total == 115 and shared.second_total == 230 and shared.amount_total == 345 and shared.customer_total == 30)
        move_count = qa['account.move'].search_count([('company_id', '=', 6)])
        shared.action_save()
        check('Single save creates two original drafts', len(shared.saved_summary_ids) == 2 and set(shared.saved_summary_ids.mapped('state')) == {'draft'})
        check('Save creates no accounting entries', qa['account.move'].search_count([('company_id', '=', 6)]) == move_count)
        check('Morning and evening retain their own customers', {row.period_scope: row.customer_count for row in shared.saved_summary_ids} == {'morning': 10, 'evening': 20})
        ids = shared.saved_summary_ids.ids
        shared.action_save()
        check('Repeated save returns original summaries only', set(shared.saved_summary_ids.ids) == set(ids))
        rejected('Saved entry inputs are immutable', lambda: shared.write({'first_customers': 11}))
        rejected('Saved payment amounts are immutable', lambda: shared.first_allocation_ids[:1].write({'amount': 999}))
        rejected('Saved entry cannot be deleted', lambda: shared.unlink())

        invalid = entry(21, second=0)
        count = Summary.search_count([])
        rejected('Invalid second card rejects the entire save', lambda: invalid.action_save())
        check('Second-card failure leaves no first-card summary', Summary.search_count([]) == count and invalid.state == 'draft' and not invalid.saved_summary_ids)
        conflict = entry(22)
        Summary.create({'business_date': date(2026, 8, 22), 'period_scope': 'evening', 'day_schedule': 'split', 'zero_sales': True})
        count = Summary.search_count([])
        rejected('Second-card overlap rejects entire shared save', lambda: conflict.action_save())
        check('Overlap failure leaves no morning draft', Summary.search_count([]) == count and not conflict.saved_summary_ids)

        original_approve = type(Summary).action_approve
        approval_calls = []

        def fail_evening(record):
            approval_calls.append(record.id)
            if len(approval_calls) == 2:
                raise UserError('Injected second-shift approval failure')
            return original_approve(record)

        with patch.object(type(Summary), 'action_approve', fail_evening):
            rejected('Late second approval failure rolls back the first approval', lambda: shared.action_approve())
        check('Late failure occurs after one real native approval', len(approval_calls) == 2)
        check('Failed paired approval leaves both drafts and no ledger', set(shared.saved_summary_ids.mapped('state')) == {'draft'} and qa['account.move'].search_count([('company_id', '=', 6)]) == move_count)
        shared.action_approve()
        check('Explicit approval posts both original summaries', shared.state == 'approved' and set(shared.saved_summary_ids.mapped('state')) == {'approved'})
        order_ids = shared.saved_summary_ids.order_id.ids
        move_after = qa['account.move'].search_count([('company_id', '=', 6)])
        shared.action_approve()
        check('Repeated approval does not duplicate native orders or ledger', set(shared.saved_summary_ids.order_id.ids) == set(order_ids) and qa['account.move'].search_count([('company_id', '=', 6)]) == move_after)
        groups = Summary._read_group([('id', 'in', ids)], ['period_scope'], ['amount_gross:sum', 'customer_count:sum'])
        check('Native monthly shift grouping keeps amounts and customers independent', {scope: (gross, customers) for scope, gross, customers in groups} == {'morning': (115, 10), 'evening': (230, 20)})
        daily = qa['baseer.pos.daily.report']._aggregate_days(qa.company, date(2026, 8, 20), date(2026, 8, 20))
        check('Two-card approval remains one complete operating date', daily['totals']['operating_days'] == 1 and daily['totals']['average_daily_sales'] == 345 and daily['totals']['average_daily_customers'] == 30)

        zero = entry(23, 0, 0, first_customers=0, second_customers=0, first_zero_sales=True, second_zero_sales=True)
        zero.action_save()
        zero.action_approve()
        check('Both explicit zero shifts approve without financial entries', zero.state == 'approved' and not zero.saved_summary_ids.order_id and qa['account.move'].search_count([('company_id', '=', 6)]) == move_after)
        full = entry(24, day_schedule='all')
        full.action_save()
        check('Full-day selection creates exactly one all-day summary', len(full.saved_summary_ids) == 1 and full.saved_summary_ids.period_scope == 'all' and full.saved_summary_ids.amount_gross == 115 and full.saved_summary_ids.customer_count == 10)
        evening = entry(25, day_schedule='evening')
        evening.action_save()
        check('Single evening selection uses first card with evening period', len(evening.saved_summary_ids) == 1 and evening.saved_summary_ids.period_scope == 'evening')
        changed = entry(26)
        changed.action_save()
        changed.saved_summary_ids[:1].write({'customer_count': 88})
        rejected('Approval refuses an externally changed original draft', lambda: changed.action_approve())
        removed = entry(27)
        removed.action_save()
        removed.saved_summary_ids[:1].unlink()
        rejected('Approval refuses a removed original draft', lambda: removed.action_approve())

        rejected('RPC cannot forge saved status', lambda: Entry.create({'state': 'saved'}))
        rejected('RPC cannot forge summary links', lambda: Entry.create({'saved_summary_ids': [Command.set(ids)]}))
        hostile = Entry.with_context(default_state='approved', default_company_id=7, default_saved_summary_ids=ids).create({})
        check('Context defaults cannot forge status company or links', hostile.state == 'draft' and hostile.company_id.id == 6 and not hostile.saved_summary_ids)
        rejected('RPC rejects excess monetary precision', lambda: entry(28, first=1.001))
        rejected('RPC rejects negative payment amount', lambda: entry(28, first=-1))
        rejected('RPC rejects fractional customers', lambda: entry(28, first_customers=1.5))
        rejected('RPC rejects a nonboolean zero declaration', lambda: entry(28, first_zero_sales='false'))
        toggled = Entry.new({'first_customers': 10, 'second_customers': 20, 'first_zero_sales': True,
                             'first_allocation_ids': [Command.create({'slot': 'first', 'payment_method_id': method.id, 'amount': 115})],
                             'second_allocation_ids': [Command.create({'slot': 'second', 'payment_method_id': method.id, 'amount': 230})]})
        toggled._onchange_zero_sales()
        check('Zero toggle clears its own shift without changing the other shift', toggled.first_customers == 0 and toggled.first_allocation_ids.amount == 0 and toggled.second_customers == 20 and toggled.second_allocation_ids.amount == 230)
        operator = qa['res.users'].with_context(no_reset_password=True).create({
            'name': 'S2 day entry rollback operator', 'login': 's2-day-entry-rollback-operator',
            'company_id': 6, 'company_ids': [Command.set([6])],
            'group_ids': [Command.set([qa.ref('base.group_user').id, qa.ref('point_of_sale.group_pos_user').id])],
        })
        rejected('Other operator cannot read private entry', lambda: hostile.with_user(operator).read(['first_customers']))
        rejected('Other operator cannot save private entry', lambda: hostile.with_user(operator).action_save())
        original_ids = shared.saved_summary_ids.ids
        aged_line = shared.first_allocation_ids[:1]
        qa.flush_all()
        qa.cr.execute("UPDATE baseer_pos_day_entry_line SET write_date = NOW() - INTERVAL '2 hours' WHERE id=%s", [aged_line.id])
        qa['baseer.pos.day.entry.line']._transient_clean_rows_older_than(3600)
        check('Native private vacuum removes aged saved entry lines', not aged_line.exists())
        qa.cr.execute("UPDATE baseer_pos_day_entry SET write_date = NOW() - INTERVAL '2 hours' WHERE id=%s", [shared.id])
        Entry._transient_clean_rows_older_than(3600)
        check('Native private vacuum removes aged approved entry without deleting original summaries', not shared.exists() and len(Summary.browse(original_ids).exists()) == 2)
        report = qa['baseer.pos.daily.report'].create({'date_from': date(2026, 8, 20), 'date_to': date(2026, 8, 20)})
        report.action_generate()
        result_line = report.line_ids
        qa.flush_all()
        qa.cr.execute("UPDATE baseer_pos_daily_report_line SET write_date = NOW() - INTERVAL '2 hours' WHERE id=%s", [result_line.id])
        qa['baseer.pos.daily.report.line']._transient_clean_rows_older_than(3600)
        check('Native private vacuum removes aged generated report lines', not result_line.exists())
        result = {'passed': len(checks), 'checks': checks, 'fixtures': 'rolled back'}
        raise RollbackFixtures()
except RollbackFixtures:
    pass

print('POS_S2_DAY_ENTRY_RESULT=' + json.dumps(result, ensure_ascii=False))
