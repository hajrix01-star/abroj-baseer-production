"""Manager archive/restore and all-or-none draft deletion; QA rollback only."""
import json
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
        qa = env(context=dict(env.context, allowed_company_ids=[6], lang='en_US'))
        Summary, Closure, Archive = (qa[name] for name in ('baseer.pos.summary', 'baseer.pos.closure', 'baseer.pos.day.archive'))
        config = Summary._default_config()
        method = config.payment_method_ids.filtered(lambda row: row.journal_id.type == 'cash')[:1]
        assert method

        def summary(day, scope='morning'):
            return Summary.create({'business_date': date(2026, 4, day), 'day_schedule': 'split', 'period_scope': scope, 'customer_count': 10,
                                   'allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': 115})]})

        def day_rows(business_date):
            qa.flush_all()
            Archive.invalidate_model()
            return Archive.search([('company_id', '=', 6), ('business_date', '=', business_date)])

        first, second = summary(20), summary(20, 'evening')
        day = day_rows(first.business_date)
        check('A new paired day starts unarchived', not day.is_archived)
        first.action_archive()
        check('One archived shift does not hide the remaining shift day', not day_rows(first.business_date).is_archived)
        day.action_archive()
        check('Archive day marks all original shifts', first.is_archived and second.is_archived and day_rows(first.business_date).is_archived)
        day.action_unarchive()
        check('Restore day restores every original shift', not first.is_archived and not second.is_archived and not day_rows(first.business_date).is_archived)

        approved = Summary.browse(82)
        posted_day = day_rows(approved.business_date)
        baseline_print = approved._get_print_data()
        baseline_daily = qa['baseer.pos.daily.report']._aggregate_days(qa.company, approved.business_date, approved.business_date)
        qa.flush_all()
        qa.cr.execute("SELECT md5(string_agg(to_jsonb(m)::text, '' ORDER BY m.id)) FROM account_move m WHERE company_id=6")
        baseline_moves = qa.cr.fetchone()[0]
        qa.cr.execute("SELECT md5(string_agg(to_jsonb(l)::text, '' ORDER BY l.id)) FROM account_move_line l WHERE company_id=6")
        baseline_lines = qa.cr.fetchone()[0]
        posted_day.action_archive()
        check('Manager can archive an approved original without unposting it', approved.state == 'approved' and approved.is_archived)
        check('Archived approved amounts remain in the daily report and denominator', qa['baseer.pos.daily.report']._aggregate_days(qa.company, approved.business_date, approved.business_date) == baseline_daily)
        check('Archived approved printed data remains identical', approved._get_print_data() == baseline_print)
        check('Archived records remain searchable as original sources', Summary.search([('id', '=', 82)]) == approved)
        posted_day.action_unarchive()
        check('Restoring approved day changes no source money', not approved.is_archived and approved._get_print_data() == baseline_print)

        closure = Closure.create({'date_from': date(2026, 4, 22), 'date_to': date(2026, 4, 24), 'period_scope': 'all', 'reason': 'holiday'})
        closure.action_confirm()
        qa.flush_all()
        closed_days = Archive.search([('closure_id', '=', closure.id)])
        sources, closed_sources = closed_days._get_sources()
        check('Selecting several closure dates deduplicates their durable source', not sources and closed_sources == closure and len(closed_days) == 3)
        closed_before = qa['baseer.pos.daily.report']._aggregate_days(qa.company, closure.date_from, closure.date_to)
        closed_days.action_archive()
        check('Archiving one closure range marks all projected dates', closure.is_archived and all(day_rows(item.business_date).is_archived for item in closed_days))
        check('Archived closure remains closed and excluded from operating averages', qa['baseer.pos.daily.report']._aggregate_days(qa.company, closure.date_from, closure.date_to) == closed_before)
        closed_days.action_unarchive()
        check('Restoring closure preserves confirmation', not closure.is_archived and closure.state == 'confirmed')

        with patch.object(type(Closure), 'action_archive', lambda records: (_ for _ in ()).throw(UserError('Injected archive failure'))):
            rejected('Batch archive failure rolls back earlier source metadata', lambda: (day | closed_days).action_archive())
        check('Failed mixed-source archive leaves every original unarchived', not first.is_archived and not second.is_archived and not closure.is_archived)

        rejected('Batch deletion refuses a selection containing an approved day', lambda: (day | posted_day).action_delete_drafts())
        check('Rejected mixed deletion retains both draft shifts', first.exists() and second.exists())
        rejected('Draft deletion cannot remove a confirmed DAY OFF record', lambda: closed_days.action_delete_drafts())
        check('Rejected DAY OFF deletion retains its confirmed source', closure.exists() and closure.state == 'confirmed')
        mixed_a = Summary.create({'business_date': date(2026, 4, 25), 'day_schedule': 'split', 'period_scope': 'morning', 'zero_sales': True})
        mixed_a.action_approve()
        mixed_b = summary(25, 'evening')
        mixed_day = day_rows(mixed_a.business_date)
        rejected('Partly approved day cannot be deleted', lambda: mixed_day.action_delete_drafts())
        check('Mixed-day rejection leaves its draft shift intact', mixed_b.exists())

        user = qa['res.users'].with_context(no_reset_password=True).create({
            'name': 'S5 lifecycle rollback cashier', 'login': 's5-lifecycle-rollback-cashier', 'company_id': 6, 'company_ids': [Command.set([6])],
            'group_ids': [Command.set([qa.ref('base.group_user').id, qa.ref('point_of_sale.group_pos_user').id])],
        })
        check('Cashier fixture keeps native role without POS manager', user.has_group('point_of_sale.group_pos_user') and not user.has_group('point_of_sale.group_pos_manager'))
        rejected('Native cashier cannot archive a day', lambda: day.with_user(user).action_archive())
        rejected('Native cashier cannot restore a day', lambda: day.with_user(user).action_unarchive())
        rejected('Native cashier cannot delete a draft day', lambda: day.with_user(user).action_delete_drafts())
        rejected('Native cashier cannot archive the original source directly', lambda: first.with_user(user).action_archive())
        rejected('Lifecycle actions require the current company even when both are allowed', lambda: day.with_context(allowed_company_ids=[7, 6]).action_archive())
        rejected('Projection metadata cannot be written directly', lambda: day.write({'is_archived': True}))
        rejected('Projection cannot be deleted directly', lambda: day.unlink())

        wrapped_a, wrapped_b = summary(26), summary(26, 'evening')
        wrapped = qa['baseer.pos.day.entry']._from_summaries(wrapped_a | wrapped_b)
        wrapped.action_archive()
        check('Combined-form archive delegates to both original shifts', wrapped_a.is_archived and wrapped_b.is_archived)
        wrapped.action_unarchive()
        check('Combined-form restore preserves both original drafts', not wrapped_a.is_archived and not wrapped_b.is_archived)
        target = wrapped.action_delete_drafts()
        check('Combined-form draft deletion returns to the company archive', target['res_model'] == 'baseer.pos.day.archive' and ('company_id', '=', 6) in target['domain'] and not (wrapped_a | wrapped_b).exists())
        replacement = summary(26)
        rejected('Stale combined entry cannot archive replacement records from the same date', lambda: wrapped.action_archive())
        rejected('Stale combined entry cannot delete replacement records from the same date', lambda: wrapped.action_delete_drafts())
        check('Replacement draft survives stale-entry lifecycle attempts', replacement.exists() and not replacement.is_archived)

        draft_ids = [first.id, second.id]
        day.action_delete_drafts()
        qa.flush_all()
        check('Deleting an all-draft day removes both original shifts', not Summary.browse(draft_ids).exists())
        check('Deleted draft day disappears from the projection', not day_rows(date(2026, 4, 20)))
        check('Deleting drafts does not affect approved sources or closures', approved.exists() and closure.exists())
        qa.cr.execute("SELECT md5(string_agg(to_jsonb(m)::text, '' ORDER BY m.id)) FROM account_move m WHERE company_id=6")
        check('All lifecycle operations preserve accounting moves byte-for-byte', qa.cr.fetchone()[0] == baseline_moves)
        qa.cr.execute("SELECT md5(string_agg(to_jsonb(l)::text, '' ORDER BY l.id)) FROM account_move_line l WHERE company_id=6")
        check('All lifecycle operations preserve accounting lines byte-for-byte', qa.cr.fetchone()[0] == baseline_lines)
        result = {'passed': len(checks), 'checks': checks, 'fixtures': 'rolled back', 'financial_change': False}
        raise RollbackFixtures()
except RollbackFixtures:
    pass

print('POS_S5_LIFECYCLE_RESULT=' + json.dumps(result, ensure_ascii=False))
