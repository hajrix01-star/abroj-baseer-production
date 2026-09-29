"""Unified archive/reopen and one-step posting acceptance; QA fixtures roll back."""
import json
import time
from datetime import date
from unittest.mock import patch

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
    except (AccessError, UserError, ValidationError):
        checks.append(name)
    else:
        raise AssertionError(name)


class RollbackFixtures(Exception):
    pass


try:
    with env.cr.savepoint():
        qa = env(context=dict(env.context, allowed_company_ids=[6]))
        Archive, Summary, Entry = qa['baseer.pos.day.archive'], qa['baseer.pos.summary'], qa['baseer.pos.day.entry']
        config = Summary._default_config()
        method = config.payment_method_ids.filtered(lambda row: row.journal_id.type == 'cash')[:1]
        assert config and method

        def summary(day, scope='morning', gross=115, customers=10):
            return Summary.create({'business_date': date(2026, 6, day), 'day_schedule': 'split', 'period_scope': scope,
                                   'customer_count': customers, 'zero_sales': not gross,
                                   'allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': gross})]})

        def archived(day):
            qa.flush_all()
            Archive.invalidate_model()
            return Archive.search([('company_id', '=', 6), ('business_date', '=', date(2026, 6, day))])

        first, second = summary(21), summary(21, 'evening', 230, 20)
        day = archived(21)
        check('Two original shifts produce one archive row', len(day) == 1 and day.shift_count == 2)
        check('Archive ID derives from minimum source ID', day.id == min(first.id, second.id))
        check('Archive total and customers aggregate both shifts', day.amount_total == 345 and day.customer_total == 30)
        check('Archive retains independent shift totals', day.morning_total == 115 and day.evening_total == 230)
        check('Complete draft day is not marked missing', day.state == 'draft' and not day.missing_shift)
        count_before = Summary.search_count([])
        moves_before = qa['account.move'].search_count([('company_id', '=', 6)])
        action = day.action_open()
        opened = Entry.browse(action['res_id'])
        check('Opening archive reconstructs both shift cards', opened.day_schedule == 'split' and opened.first_total == 115 and opened.second_total == 230 and opened.first_customers == 10 and opened.second_customers == 20)
        check('Reopened cards link only original summaries', set(opened.saved_summary_ids.ids) == {first.id, second.id})
        check('Reopened cards are readonly saved entries', opened.saved and opened.state == 'saved')
        rejected('Reopened input cannot change original snapshot', lambda: opened.write({'first_customers': 99}))
        check('Opening never creates sales or accounting', Summary.search_count([]) == count_before and qa['account.move'].search_count([('company_id', '=', 6)]) == moves_before)
        qa.flush_all()
        qa.cr.execute("UPDATE baseer_pos_day_entry SET write_date = NOW() - INTERVAL '2 hours' WHERE id=%s", [opened.id])
        Entry._transient_clean_rows_older_than(3600)
        check('Temporary entry can expire while original shifts survive', not opened.exists() and first.exists() and second.exists())
        restored = Entry.browse(day.action_open()['res_id'])
        check('Archive reopens both cards after transient vacuum', restored.first_total == 115 and restored.second_total == 230 and set(restored.saved_summary_ids.ids) == {first.id, second.id})

        partial = summary(22)
        partial_day = archived(22)
        partial_entry = Entry.browse(partial_day.action_open()['res_id'])
        check('Legacy partial split day is flagged incomplete', partial_day.missing_shift and partial_day.shift_count == 1)
        check('Absent second shift stays visibly missing without fabricated summary', partial_entry.second_missing and not partial_entry.first_missing and partial_entry.saved_summary_ids == partial)
        check('Partial reopen creates no zero-sale substitute', len(Summary.search([('company_id', '=', 6), ('business_date', '=', date(2026, 6, 22))])) == 1)

        zero = summary(23, gross=0, customers=0)
        zero.action_approve()
        summary(23, 'evening', 230, 20)
        mixed = archived(23)
        check('Mixed source approvals remain explicitly mixed', mixed.state == 'mixed')
        check('Mixed archive money still reflects original records', mixed.amount_total == 230 and mixed.customer_total == 20)

        existing = Summary.browse(82)
        existing.check_access('read')
        old_day = Archive.search([('company_id', '=', 6), ('business_date', '=', existing.business_date)])
        old = Entry.browse(old_day.action_open()['res_id'])
        check('Old all-day record reopens as one full-day card', old.day_schedule == 'all' and old.first_total == existing.amount_gross and old.first_customers == existing.customer_count and 82 in old.saved_summary_ids.ids)
        check('Old approved source remains approved without reposting', old.state == 'approved' and qa['account.move'].search_count([('company_id', '=', 6)]) == moves_before)

        method.write({'active': False})
        historic = Entry.browse(day.action_open()['res_id'])
        check('Historical inactive payment method is preserved on readonly reopen', method in historic.first_allocation_ids.payment_method_id and historic.first_total == 115 and historic.second_total == 230)
        method.write({'active': True})

        rejected('Archive create is denied through RPC', lambda: Archive.create({'company_id': 6}))
        rejected('Archive write is denied through RPC', lambda: day.write({'amount_total': 999}))
        rejected('Archive deletion is denied through RPC', lambda: day.unlink())
        rejected('Archive opening requires its active company', lambda: day.with_context(allowed_company_ids=[7, 6]).action_open())
        foreign = qa['res.users'].with_context(no_reset_password=True).create({
            'name': 'S3 archive foreign rollback', 'login': 's3-archive-foreign-rollback', 'company_id': 7, 'company_ids': [Command.set([7])],
            'group_ids': [Command.set([qa.ref('base.group_user').id, qa.ref('point_of_sale.group_pos_user').id])],
        })
        rejected('Foreign company cannot read archive totals', lambda: day.with_user(foreign).with_context(allowed_company_ids=[7]).read(['amount_total']))
        rejected('Foreign company cannot reopen archive day', lambda: day.with_user(foreign).with_context(allowed_company_ids=[7]).action_open())

        def entry(day_number):
            return Entry.create({'business_date': date(2026, 6, day_number), 'day_schedule': 'split', 'first_customers': 10, 'second_customers': 20,
                                 'first_allocation_ids': [Command.create({'slot': 'first', 'payment_method_id': method.id, 'amount': 115})],
                                 'second_allocation_ids': [Command.create({'slot': 'second', 'payment_method_id': method.id, 'amount': 230})]})

        failed_entry = entry(24)
        old_approve = type(Summary).action_approve
        calls = []

        def fail_second(record):
            calls.append(record.id)
            if len(calls) == 2:
                raise UserError('Injected late second approval failure')
            return old_approve(record)

        count_before = Summary.search_count([])
        with patch.object(type(Summary), 'action_approve', fail_second):
            rejected('One-step save rolls back after late second approval failure', lambda: failed_entry.action_save_and_approve())
        check('Late failure occurred after one native financial posting', len(calls) == 2)
        check('One-step failure leaves no summaries or accounting', Summary.search_count([]) == count_before and qa['account.move'].search_count([('company_id', '=', 6)]) == moves_before and failed_entry.state == 'draft' and not failed_entry.saved_summary_ids)
        final = entry(25)
        final.action_save_and_approve()
        check('One-step save approves both original summaries', final.state == 'approved' and len(final.saved_summary_ids) == 2 and set(final.saved_summary_ids.mapped('state')) == {'approved'})
        source_ids, order_ids = set(final.saved_summary_ids.ids), set(final.saved_summary_ids.order_id.ids)
        posted_count = qa['account.move'].search_count([('company_id', '=', 6)])
        final.action_save_and_approve()
        check('Repeated one-step save creates no duplicate documents', set(final.saved_summary_ids.ids) == source_ids and set(final.saved_summary_ids.order_id.ids) == order_ids and qa['account.move'].search_count([('company_id', '=', 6)]) == posted_count)
        check('Approved paired day appears once with final totals', archived(25).state == 'approved' and archived(25).amount_total == 345 and archived(25).customer_total == 30)
        t0 = time.perf_counter()
        page = Archive.search_read([('company_id', '=', 6)], ['business_date', 'amount_total', 'customer_total', 'state'], limit=80)
        elapsed = time.perf_counter() - t0
        check('Native archive pagination remains bounded', len(page) <= 80)
        check('Local archive query stays under two seconds', elapsed < 2)
        result = {'passed': len(checks), 'checks': checks, 'archive_page_seconds': round(elapsed, 6), 'fixtures': 'rolled back'}
        raise RollbackFixtures()
except RollbackFixtures:
    pass

print('POS_S3_RESULT=' + json.dumps(result, ensure_ascii=False))
