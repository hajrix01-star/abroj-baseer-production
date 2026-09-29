"""AR2 native new-user form reproduction; only isolated rollback fixtures."""
import json
import traceback
from pathlib import Path
from unittest.mock import patch
from lxml import etree
from odoo import Command
from odoo.exceptions import AccessError, ValidationError

assert env.cr.dbname.startswith('baseer_ar1_') and env.su
OUT = Path('/mnt/qa-evidence/ar2-role-checks.json')
results, violations = [], []
result = {'status': 'FAIL', 'checks': results, 'violations': violations, 'rollback': False}


class RollbackProbe(Exception):
    pass


def identities(groups):
    xmlids = groups.get_external_id()
    return [xmlids.get(group.id) or 'group-id:' + str(group.id) for group in groups]


before = env['res.users'].with_context(active_test=False).search_count([])
try:
    admin_user = env.ref('base.user_admin')
    companies = admin_user.company_ids[:3]
    assert len(companies) == 3, 'AR2 reproduction requires administrator with at least 3 companies'
    actor = env(user=admin_user.id, su=False, context={'allowed_company_ids': companies.ids,
                'lang': 'en_US', 'no_reset_password': True, 'tracking_disable': True})
    assert actor.user.has_group('base.group_system') and not actor.su
    Users = actor['res.users']
    original_validate = type(Users)._baseer_validate_roles

    def inspect_validate(records):
        for user in records.sudo().filtered(lambda user: user.baseer_access_role in ('accountant', 'cashier')):
            marker = user.env.ref('baseer_access_roles.group_' + user.baseer_access_role)
            allowed = marker.all_implied_ids | user.env.ref('base.group_multi_company') | user.env.ref('mail.group_mail_notification_type_inbox')
            excess = user.all_group_ids - allowed
            if excess:
                violations.append({'scenario': current[0], 'extra_groups': identities(excess),
                                   'explicit_groups': identities(user.group_ids),
                                   'role': user.baseer_access_role})
        return original_validate(records)

    view = Users.get_view(view_id=actor.ref('base.view_users_form').id, view_type='form')
    field_names = sorted({node.get('name') for node in etree.fromstring(view['arch'].encode()).xpath('.//field')
                          if node.get('name') in Users._fields})
    defaults = Users.default_get(field_names)
    result['default_keys'] = sorted(defaults)
    result['default_group_xmlids'] = identities(Users._default_groups())
    current = ['']
    scenarios = []
    for role in ('accountant', 'cashier'):
        for count in (1, 3):
            for shape in ('minimal', 'form_defaults', 'native_user_role', 'native_admin_role'):
                for notification in ('email', 'inbox'):
                    scenarios.append((role, count, shape, notification))
    with patch.object(type(Users), '_baseer_validate_roles', inspect_validate):
        for index, (role, count, shape, notification) in enumerate(scenarios):
            label = role + '/' + str(count) + '-companies/' + shape + '/' + notification
            current[0] = label
            vals = dict(defaults) if shape != 'minimal' else {}
            vals.update(name='AR2 ROLLBACK form probe', login='ar2-rollback-form-' + str(index),
                        baseer_access_role=role, company_id=companies[0].id,
                        company_ids=[Command.set(companies[:count].ids)], notification_type=notification)
            if shape == 'native_user_role':
                vals['role'] = 'group_user'
            if shape == 'native_admin_role':
                vals['role'] = 'group_system'
            try:
                with env.cr.savepoint():
                    user = Users.create(vals)
                    expected = actor.ref('baseer_access_roles.group_' + role)
                    allowed = expected.all_implied_ids | actor.ref('base.group_multi_company') | actor.ref('mail.group_mail_notification_type_inbox')
                    assert not user.all_group_ids - allowed
                    assert user.baseer_access_role == role
                    assert user.notification_type == notification
                    assert set(user.company_ids.ids) == set(companies[:count].ids)
                    results.append({'check': label, 'passed': True,
                                    'explicit_groups': identities(user.group_ids)})
                    raise RollbackProbe()
            except RollbackProbe:
                pass
            except Exception as error:
                results.append({'check': label, 'passed': False, 'error_type': type(error).__name__,
                                'error': str(error), 'traceback': traceback.format_exc()})
    def check(label, operation):
        try:
            with env.cr.savepoint():
                operation()
                results.append({'check': label, 'passed': True})
                raise RollbackProbe()
        except RollbackProbe:
            pass
        except Exception as error:
            results.append({'check': label, 'passed': False, 'error_type': type(error).__name__,
                            'error': str(error), 'traceback': traceback.format_exc()})

    def denied(operation):
        try:
            with env.cr.savepoint():
                operation()
        except (AccessError, ValidationError):
            return
        raise AssertionError('Unauthorized access change succeeded')

    for role in ('accountant', 'cashier'):
        fixture = Users.create({'name': 'AR2 preference fixture', 'login': 'ar2-preference-' + role,
                                'baseer_access_role': role, 'company_id': companies[0].id,
                                'company_ids': [Command.set(companies.ids)], 'notification_type': 'email'})
        own_env = env(user=fixture.id, su=False, context=dict(actor.context))
        own = own_env['res.users'].browse(fixture.id)
        assert not own.env.su
        inbox = actor.ref('mail.group_mail_notification_type_inbox')

        def toggle(record):
            original = record.sudo().all_group_ids - inbox
            record.write({'notification_type': 'inbox'})
            assert record.notification_type == 'inbox'
            assert inbox in record.sudo().group_ids
            assert record.sudo().all_group_ids - inbox == original
            record.write({'notification_type': 'email'})
            assert record.notification_type == 'email'
            assert inbox not in record.sudo().group_ids
            assert record.sudo().all_group_ids == original

        check(role + '/admin-notification-toggle', lambda: toggle(fixture))
        check(role + '/self-notification-toggle', lambda: toggle(own))
        check(role + '/self-direct-inbox-group-denied', lambda: denied(lambda: own.write({'group_ids': [Command.link(inbox.id)]})))
        check(role + '/self-inbox-plus-admin-escalation-denied', lambda: denied(lambda: own.write({
            'notification_type': 'inbox', 'group_ids': [Command.link(actor.ref('base.group_system').id)]})))
        check(role + '/self-role-escalation-denied', lambda: denied(lambda: own.write({'notification_type': 'inbox', 'baseer_access_role': 'owner'})))
        check(role + '/self-company-escalation-denied', lambda: denied(lambda: own.write({'notification_type': 'inbox', 'company_ids': [Command.set(companies[:1].ids)]})))
        check(role + '/other-user-preference-denied', lambda: denied(lambda: own_env['res.users'].browse(admin_user.id).write({'notification_type': 'inbox'})))
        def replace_role():
            fixture.write({'notification_type': 'inbox'})
            fixture.write({'baseer_access_role': 'owner'})
            fixture.write({'baseer_access_role': role})
            assert fixture.notification_type == 'inbox'
            assert not fixture.has_group('base.group_system')
            allowed = actor.ref('baseer_access_roles.group_' + role).all_implied_ids | actor.ref('base.group_multi_company') | inbox
            assert not fixture.all_group_ids - allowed
        check(role + '/role-reapply-preserves-notification-not-admin', replace_role)
        def clear_role():
            fixture.write({'notification_type': 'inbox'})
            fixture.write({'baseer_access_role': False})
            assert not fixture.baseer_access_role and fixture.notification_type == 'inbox'
            allowed = actor.ref('base.group_user').all_implied_ids | actor.ref('base.group_multi_company') | inbox
            assert not fixture.all_group_ids - allowed
        check(role + '/manual-clear-preserves-preference-removes-role', clear_role)
        for preference in ('email', 'inbox'):
            def preview():
                record = Users.new({'baseer_access_role': role, 'notification_type': preference,
                                    'company_id': companies[0].id, 'company_ids': [Command.set(companies.ids)],
                                    # Native notification preference is a computed projection of this group.
                                    'group_ids': [Command.set((actor.ref('base.group_user')
                                                  | (inbox if preference == 'inbox' else inbox.browse())).ids)]})
                record._onchange_baseer_access_role()
                assert record.notification_type == preference
                assert actor.ref('baseer_access_roles.group_' + role) in record.group_ids._origin
                assert not (record.all_group_ids._origin - (actor.ref('baseer_access_roles.group_' + role).all_implied_ids
                            | actor.ref('base.group_multi_company') | inbox))
                assert actor.ref('point_of_sale.group_pos_user') in record.all_group_ids._origin
            check(role + '/onchange-preview/' + preference, preview)

    def mixed_preferences():
        pair = Users.create([{'name': 'AR2 bulk preference', 'login': 'ar2-bulk-' + preference,
                              'baseer_access_role': 'owner', 'notification_type': preference,
                              'company_id': companies[0].id} for preference in ('email', 'inbox')])
        before_preferences = {user.id: user.notification_type for user in pair}
        pair.write({'baseer_access_role': 'accountant'})
        assert {user.id: user.notification_type for user in pair} == before_preferences
        assert all(user.baseer_access_role == 'accountant' and not user.has_group('base.group_system') for user in pair)
    check('bulk-role-change-preserves-each-preference', mixed_preferences)

    result['status'] = 'PASS' if all(row['passed'] for row in results) else 'FAIL'
except Exception as error:
    result.update(error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
finally:
    env.cr.rollback()
    env.invalidate_all()
    result['rollback'] = env['res.users'].with_context(active_test=False).search_count([]) == before
    result['passed'] = sum(row['passed'] for row in results)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print('AR2_ROLE_FORMS', result['status'], result['passed'], 'OF', len(results), 'ROLLBACK', result['rollback'])
assert result['status'] == 'PASS', 'AR2 native role form case failed; see evidence'
