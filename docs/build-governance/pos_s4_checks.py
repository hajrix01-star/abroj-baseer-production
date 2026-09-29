"""QA navigation checks: no cashier session, financial operation, or commit."""
import json
from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

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
        config = qa['baseer.pos.summary']._default_config()
        ordinary = qa['pos.config'].search([('company_id', '=', 6), ('baseer_summary_only', '=', False)], limit=1)
        assert config and ordinary
        tracked = ['baseer.pos.day.entry', 'baseer.pos.day.entry.line', 'baseer.pos.summary', 'baseer.pos.closure', 'pos.order', 'pos.session', 'account.move']
        counts = lambda: {name: qa[name].search_count([]) for name in tracked}
        before = counts()
        hostile = config.with_context(allowed_company_ids=[6, 7], default_company_id=7, default_state='approved', default_config_id=ordinary.id, injected='untrusted')
        enter = hostile.action_baseer_enter_summary()
        check('Enter summary routes to the existing two-card entry form', enter['type'] == 'ir.actions.act_window' and enter['res_model'] == 'baseer.pos.day.entry' and enter['view_mode'] == 'form')
        check('Entry route scopes only the active company', enter['context']['allowed_company_ids'] == [6])
        check('Entry route discards hostile defaults and unrelated context', set(enter['context']) == {'allowed_company_ids', 'lang', 'tz'} and enter['context']['tz'] == 'Asia/Riyadh')
        defaults = qa['baseer.pos.day.entry'].with_context(enter['context']).default_get(['company_id', 'config_id'])
        check('Entry defaults resolve the same company and dedicated configuration', defaults['company_id'] == 6 and defaults['config_id'] == config.id)
        saved = hostile.action_baseer_saved_summaries()
        check('Saved summaries routes to the unified daily archive', saved['res_model'] == 'baseer.pos.day.archive')
        check('Archive route explicitly restricts the selected company', saved['domain'] == [('company_id', '=', 6)] and saved['context']['allowed_company_ids'] == [6])
        check('Navigation creates no entry summary closure session or accounting rows', counts() == before)
        rejected('Entry route rejects an inactive active-company selection', lambda: config.with_context(allowed_company_ids=[7, 6]).action_baseer_enter_summary())
        rejected('Archive route rejects a wrong active company even when permitted', lambda: config.with_context(allowed_company_ids=[7, 6]).action_baseer_saved_summaries())
        rejected('Ordinary cashier configuration cannot use the summary entry route', lambda: ordinary.action_baseer_enter_summary())
        rejected('Ordinary cashier configuration cannot use the archive route', lambda: ordinary.action_baseer_saved_summaries())
        config.write({'active': False})
        rejected('Inactive dedicated configuration cannot open summary entry', lambda: config.action_baseer_enter_summary())
        rejected('Inactive dedicated configuration cannot open saved summaries', lambda: config.action_baseer_saved_summaries())
        config.write({'active': True})
        user = qa['res.users'].with_context(no_reset_password=True).create({
            'name': 'S4 navigation rollback user', 'login': 's4-navigation-rollback-user', 'company_id': 6, 'company_ids': [Command.set([6])],
            'group_ids': [Command.set([qa.ref('base.group_user').id])],
        })
        check('Non-POS fixture has no POS user role', not user.has_group('point_of_sale.group_pos_user'))
        rejected('Non-POS user cannot open summary entry', lambda: config.with_user(user).action_baseer_enter_summary())
        rejected('Non-POS user cannot open summary archive', lambda: config.with_user(user).action_baseer_saved_summaries())

        dashboard = qa.ref('point_of_sale.action_pos_config_kanban')
        allowed = qa['pos.config'].with_context(allowed_company_ids=[6, 7])
        active_six = safe_eval(dashboard.domain, {'context': {'allowed_company_ids': [6, 7]}})
        active_seven = safe_eval(dashboard.domain, {'context': {'allowed_company_ids': [7, 6]}})
        records_six = allowed.search(active_six)
        records_seven = allowed.search(active_seven)
        check('Active company dashboard includes its dedicated summary card', config in records_six)
        check('Switching active company removes the prior company summary card', config not in records_seven)
        check('Ordinary cashier card remains governed by its native allowed-company scope', ordinary in records_six and ordinary in records_seven)
        check('Every dedicated dashboard card belongs to the active company', all(row.company_id.id == 6 for row in records_six if row.baseer_summary_only) and all(row.company_id.id == 7 for row in records_seven if row.baseer_summary_only))

        view = qa.ref('point_of_sale.view_pos_config_kanban')
        arch = view._get_combined_arch()
        if isinstance(arch, str):
            arch = etree.fromstring(arch.encode())

        def guarded(node):
            return any(parent.get('t-if') == '!record.baseer_summary_only.raw_value' for parent in [node] + list(node.iterancestors()))

        title = arch.xpath("//div[@name='card_title']")
        body = arch.xpath("//div[@name='card_left']")
        user_badge = arch.xpath("//t[@t-name='card']/field[@name='current_user_id']")
        check('Native cashier title body and user badge are hidden for summary configuration', title and body and user_badge and all(guarded(node) for node in title + body + user_badge))
        native_actions = arch.xpath("//button[@name='open_ui'] | //a[@name='open_ui'] | //button[@name='open_existing_session_cb'] | //a[@name='open_existing_session_cb']")
        check('Native cashier launch actions remain guarded from the summary card', native_actions and all(guarded(node) for node in native_actions))
        entry_buttons = arch.xpath("//button[@name='action_baseer_enter_summary']")
        saved_buttons = arch.xpath("//button[@name='action_baseer_saved_summaries']")
        check('Dedicated card exposes both native object navigation buttons', len(entry_buttons) == 1 and len(saved_buttons) == 1 and entry_buttons[0].get('type') == 'object' and saved_buttons[0].get('type') == 'object')
        check('Dedicated navigation buttons use a summary-only card guard', all(any(parent.get('t-if') == 'record.baseer_summary_only.raw_value' for parent in node.iterancestors()) for node in entry_buttons + saved_buttons))
        check('All route checks leave tracked business rows unchanged', counts() == before)
        result = {'passed': len(checks), 'checks': checks, 'fixtures': 'rolled back', 'financial_posting': False}
        raise RollbackFixtures()
except RollbackFixtures:
    pass

print('POS_S4_RESULT=' + json.dumps(result, ensure_ascii=False))
