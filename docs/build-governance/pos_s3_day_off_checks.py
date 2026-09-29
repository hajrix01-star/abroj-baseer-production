"""DAY OFF closure/archive acceptance, with no committed QA fixtures."""
import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

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
        qa = env(context=dict(env.context, allowed_company_ids=[6], lang='en_US'))
        Entry, Closure, Archive, Summary = (qa[name] for name in ('baseer.pos.day.entry', 'baseer.pos.closure', 'baseer.pos.day.archive', 'baseer.pos.summary'))
        initial = (Summary.search_count([]), qa['pos.order'].search_count([]), qa['account.move'].search_count([]))

        def entry(first=date(2026, 8, 27), last=date(2026, 8, 29), **extras):
            return Entry.create(dict({'day_off': True, 'business_date': first, 'date_to': last, 'closure_reason': 'eid', 'closure_notes': 'Eid holiday / إجازة العيد'}, **extras))

        holiday = entry()
        holiday.action_save_and_approve()
        source = holiday.saved_closure_id
        check('DAY OFF saves a confirmed native closure', source and source.state == 'confirmed' and source.period_scope == 'all' and holiday.state == 'approved')
        check('DAY OFF preserves inclusive dates reason and notes', source.date_from == date(2026, 8, 27) and source.date_to == date(2026, 8, 29) and source.reason == 'eid' and 'إجازة' in source.notes)
        check('DAY OFF creates no summary POS order or accounting', (Summary.search_count([]), qa['pos.order'].search_count([]), qa['account.move'].search_count([])) == initial and not holiday.saved_summary_ids)
        qa.flush_all()
        Archive.invalidate_model()
        days = Archive.search([('closure_id', '=', source.id)])
        check('Archive expands a three-day closure inclusively', len(days) == 3 and set(days.mapped('business_date')) == {date(2026, 8, 27), date(2026, 8, 28), date(2026, 8, 29)})
        check('Closure archive IDs are distinct negative bigint values', set(days.ids) == {-(source.id * 1000 + offset) for offset in range(3)})
        check('Closure archive rows have explicit closed state', all(row.is_day_off and row.state == 'closed' for row in days))
        qa.cr.execute('SELECT amount_total, customer_total, morning_total, evening_total FROM baseer_pos_day_archive WHERE closure_id=%s', [source.id])
        check('Closure amounts remain SQL NULL rather than fabricated zero sales', all(all(value is None for value in row) for row in qa.cr.fetchall()))
        opened = Entry.browse(days[:1].action_open()['res_id'])
        check('Closed archive day reopens original readonly range', opened.day_off and opened.saved_closure_id == source and opened.business_date == source.date_from and opened.date_to == source.date_to and opened.saved)
        rejected('Reopened DAY OFF cannot edit original closure', lambda: opened.write({'closure_notes': 'changed'}))
        count = Closure.search_count([])
        holiday.action_save_and_approve()
        check('Repeated DAY OFF save reuses the same closure', Closure.search_count([]) == count and holiday.saved_closure_id == source)

        qa.flush_all()
        qa.cr.execute("UPDATE baseer_pos_day_entry SET write_date=NOW()-INTERVAL '2 hours' WHERE id=%s", [opened.id])
        Entry._transient_clean_rows_older_than(3600)
        restored = Entry.browse(days[:1].action_open()['res_id'])
        check('Closed day survives transient vacuum and reopens without recreation', not opened.exists() and restored.saved_closure_id == source and Closure.search_count([]) == count)
        share = restored.action_share_whatsapp()
        query = parse_qs(urlsplit(share['url']).query)
        message = query['text'][0]
        check('Closure WhatsApp prepares only text with dates and reason', set(query) == {'text'} and 'DAY OFF' in message and '2026-08-27' in message and '2026-08-29' in message and 'Eid' in message and 'إجازة العيد' in message)
        check('Closure WhatsApp does not claim zero sales', 'Gross sales' not in message and 'Customers:' not in message and '0.00' not in message)
        rejected('Other closure reason requires explanatory notes', lambda: entry(date(2026, 8, 30), date(2026, 8, 30), closure_reason='other', closure_notes=' ').action_save_and_approve())
        rejected('DAY OFF rejects reversed dates', lambda: entry(date(2026, 8, 30), date(2026, 8, 29)).action_save_and_approve())
        rejected('DAY OFF rejects more than 366 inclusive dates', lambda: entry(date(2028, 1, 1), date(2028, 1, 1) + timedelta(days=366)).action_save_and_approve())
        longest = entry(date(2028, 1, 1), date(2028, 1, 1) + timedelta(days=365))
        longest.action_save_and_approve()
        qa.flush_all()
        max_days = Archive.search([('closure_id', '=', longest.saved_closure_id.id)])
        check('Maximum valid closure creates exactly 366 archive dates', len(max_days) == 366 and len(set(max_days.ids)) == 366 and min(max_days.mapped('business_date')) == date(2028, 1, 1) and max(max_days.mapped('business_date')) == date(2028, 12, 31))
        count = Closure.search_count([])
        rejected('Overlapping closure rejects the entire requested range', lambda: entry(date(2026, 8, 28), date(2026, 8, 31)).action_save_and_approve())
        check('Overlap failure leaves no partial closure', Closure.search_count([]) == count)
        zero = Summary.create({'business_date': date(2026, 8, 26), 'day_schedule': 'all', 'period_scope': 'all', 'zero_sales': True})
        zero.action_approve()
        rejected('DAY OFF cannot overlap an approved zero-sales operation', lambda: entry(date(2026, 8, 26), date(2026, 8, 26)).action_save_and_approve())
        data = qa['baseer.pos.daily.report']._aggregate_days(qa.company, date(2026, 8, 26), date(2026, 8, 29))
        check('Three closed dates do not increase the operating-day denominator', data['totals']['operating_days'] == 1 and data['totals']['closed_days'] == 3 and data['totals']['missing_days'] == 0)
        check('Actual zero operation remains a complete day alongside closures', data['days'][0]['status'] == 'complete' and data['days'][0]['has_sales'])

        source.write({'cancellation_reason': 'Reopening test'})
        source.action_cancel()
        qa.flush_all()
        Archive.invalidate_model()
        check('Cancelled closure disappears from the daily archive', not Archive.search([('closure_id', '=', source.id)]))
        count = Closure.search_count([])
        rejected('Expired readonly closure entry cannot recreate a cancelled closure', lambda: restored.action_save_and_approve())
        rejected('Cancelled closure cannot generate a stale WhatsApp notice', lambda: restored.action_share_whatsapp())
        rejected('Cancelled closure cannot be reconstructed by the private factory', lambda: Entry._from_closure(source))
        check('Cancelled-entry attempts create no replacement closure', Closure.search_count([]) == count)

        other = qa(context=dict(qa.context, allowed_company_ids=[7]))
        check('Foreign-company fixture has no dedicated summary POS', not other['baseer.pos.summary']._default_config())
        independent = other['baseer.pos.day.entry'].create({'day_off': True, 'business_date': date(2026, 8, 27), 'date_to': date(2026, 8, 27), 'closure_reason': 'holiday'})
        independent.action_save_and_approve()
        check('DAY OFF works without POS configuration in its own company', not independent.config_id and independent.saved_closure_id.company_id.id == 7)
        qa.flush_all()
        isolated = Archive.search([('closure_id', '=', independent.saved_closure_id.id)])
        rejected('Archive reopening requires the closure active company', lambda: isolated.action_open())
        foreign = qa['res.users'].with_context(no_reset_password=True).create({
            'name': 'DAY OFF company rollback operator', 'login': 'day-off-company-rollback', 'company_id': 6, 'company_ids': [Command.set([6])],
            'group_ids': [Command.set([qa.ref('base.group_user').id, qa.ref('point_of_sale.group_pos_user').id])],
        })
        rejected('Company record rules protect DAY OFF archive rows', lambda: isolated.with_user(foreign).read(['business_date']))
        check('All closure operations leave native financial counts unchanged', qa['pos.order'].search_count([]) == initial[1] and qa['account.move'].search_count([]) == initial[2])
        result = {'passed': len(checks), 'checks': checks, 'fixtures': 'rolled back', 'external_send': False}
        raise RollbackFixtures()
except RollbackFixtures:
    pass

print('POS_S3_DAY_OFF_RESULT=' + json.dumps(result, ensure_ascii=False))
