"""Prepare focused rollback checks and release helper from proven local harnesses."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
folder = root / 'docs/build-governance'
test = (folder / 'pos_s6_checks.py').read_text(encoding='utf8')
test = test.replace("check('Default split selects Morning and Evening only'", "check('Explicit split selects Morning and Evening only'")
test = test.replace("alias_only.day_schedule == 'split' and not alias_only.pick_all", "not alias_only.day_schedule and not alias_only.pick_all")
anchor = "        transitions = [("
addition = '''        default_vals = Entry.default_get(['day_schedule', 'pick_morning', 'pick_evening', 'pick_all'])
        fresh = Entry.new(default_vals)
        check('Fresh form has no canonical or checked shift', not fresh.day_schedule and not any((fresh.pick_morning, fresh.pick_evening, fresh.pick_all)))
        for flag, scope in [('pick_morning', 'morning'), ('pick_evening', 'evening'), ('pick_all', 'all')]:
            fresh = blank(False)
            click(fresh, flag, True)
            check('First selection from empty: ' + scope, fresh.day_schedule == scope)
        pending = Entry.create({'business_date': date(2026, 3, 18)})
        before = (qa['baseer.pos.summary'].search_count([]), qa['account.move'].search_count([]))
        for method in ('action_save', 'action_save_and_approve', 'action_save_and_share'):
            try:
                with env.cr.savepoint():
                    getattr(pending.with_context(lang='ar_001'), method)()
            except ValidationError as error:
                check('Missing shift rejected in Arabic by ' + method, str(error) == 'اختر الشفت قبل حفظ المبيعات.')
            else:
                raise AssertionError('Missing shift accepted by ' + method)
        check('Rejected sales saves have no summary or accounting effects', before == (qa['baseer.pos.summary'].search_count([]), qa['account.move'].search_count([])))
        closure = Entry.create({'day_off': True, 'business_date': date(2026, 3, 19), 'date_to': date(2026, 3, 19)})
        closure.action_save_and_approve()
        check('DAY OFF saves without sales shift', not closure.day_schedule and closure.saved_closure_id.state == 'confirmed')
        check('Closure has no accounting effect', before[1] == qa['account.move'].search_count([]))
'''
assert anchor in test
test = test.replace(anchor, addition + anchor)
test = test.replace('POS_S6_RESULT=', 'POS_EMPTY_SHIFT_RESULT=')
(folder / 'pos_empty_shift_checks.py').write_text(test, encoding='utf8')

release = (folder / 'ws4a_release.py').read_text(encoding='utf8')
# Replace both old/current release names atomically through placeholders.
for old, marker in [('2026-09-09-current-schedules','NEW_RELEASE'), ('current-schedules-20260909','NEW_BACK'), ('2026-09-09-schedule-edit','OLD_RELEASE'), ('schedule-edit-20260909','OLD_BACK')]:
    release = release.replace(old, marker)
for marker, value in [('NEW_RELEASE','2026-09-09-pos-empty-shift'), ('NEW_BACK','pos-empty-shift-20260909'), ('OLD_RELEASE','2026-09-09-current-schedules'), ('OLD_BACK','current-schedules-20260909')]:
    release = release.replace(marker, value)
release = release.replace('baseer_work_schedule', 'baseer_pos_summary').replace('19.0.1.1.1', '19.0.1.4.1')
release = release.replace('ws4a-ui.json', 'pos-empty-shift-ui.json')
release = release.replace('codex/ws4a-schedule-edit', 'codex/pos-empty-shift')
release = release.replace('WS4A edit schedule templates with dated employee history', 'Require explicit initial POS shift selection and simplify entry copy')
release = release.replace('UI metadata only; native calendar action default search filter; no business schema or rows changed', 'Transient day_schedule becomes nullable; explicit sales-save guard. Existing business rows unchanged')
release = release.replace('Freeze WS4A on accepted WS4', 'Freeze POS empty-shift change on accepted WS4A')
(folder / 'pos_empty_shift_release.py').write_text(release, encoding='utf8')
print('Prepared rollback checks and release helper')
