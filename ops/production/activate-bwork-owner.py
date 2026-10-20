"""Bounded Odoo-shell operation: explicitly enable BWork for base.user_admin only.

No role/company/MFA/retention edits; no financial or messaging business writes.
Run only after the protected eight-module production deployment is verified.
"""
import hashlib
import json

FIELDS = (
    'bwork_chat_view', 'bwork_chat_send', 'bwork_media',
    'bwork_group_create', 'bwork_group_manage', 'bwork_task_view',
    'bwork_task_manage', 'bwork_order_view', 'bwork_order_create',
    'bwork_order_receive', 'bwork_dashboard_view',
)
EXPECTED_COMPANIES = [1, 2, 3, 54, 55, 56, 57]


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def other_users_digest(cr):
    # Deliberately exclude credentials, session secrets and personal content.
    names = ','.join(FIELDS)
    cr.execute('SELECT id,active,share,company_id,baseer_access_role,' + names +
               ',bwork_manage_rooms,bwork_permission_revision '
               'FROM res_users WHERE id <> 2 ORDER BY id')
    values = [cr.fetchall()]
    cr.execute('SELECT uid,gid FROM res_groups_users_rel WHERE uid <> 2 ORDER BY uid,gid')
    values.append(cr.fetchall())
    cr.execute('SELECT user_id,cid FROM res_company_users_rel WHERE user_id <> 2 ORDER BY user_id,cid')
    values.append(cr.fetchall())
    return hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


def invariant_snapshot(environment, user):
    groups = environment['res.groups'].search([], order='id')
    edges = [(group.id, sorted(group.implied_ids.ids)) for group in groups]
    environment.cr.execute("SELECT COALESCE(totp_secret <> '', FALSE) FROM res_users WHERE id=2")
    mfa_configured = environment.cr.fetchone()[0]
    return (user.active, user.share, user.baseer_access_role,
            user.company_id.id, tuple(sorted(user.company_ids.ids)),
            mfa_configured, hashlib.sha256(json.dumps(edges).encode()).hexdigest())


def activate(environment):
    require(environment.cr.dbname == 'baseer_prod', 'WRONG_DATABASE')
    require(environment.su, 'ADMIN_SHELL_REQUIRED')
    environment.cr.execute('SET LOCAL lock_timeout = %s', ['2s'])
    environment.cr.execute('SET LOCAL statement_timeout = %s', ['30s'])
    environment.cr.execute('SELECT pg_try_advisory_xact_lock(%s)', [2026102102])
    require(environment.cr.fetchone()[0], 'OWNER_ACTIVATION_BUSY')
    user = environment.ref('base.user_admin')
    require(user.id == 2 and user.active and user._is_internal(), 'OWNER_IDENTITY_MISMATCH')
    require(user.has_group('base.group_system') and
            user.has_group('baseer_access_roles.group_owner') and
            user.baseer_access_role == 'owner', 'OWNER_ROLE_MISMATCH')
    require(sorted(user.company_ids.ids) == EXPECTED_COMPANIES and
            user.company_id.id == 2, 'OWNER_COMPANY_SCOPE_CHANGED')
    expected_modules = ('baseer_bwork', 'baseer_bwork_procurement',
                        'baseer_bwork_admin', 'baseer_bwork_dashboard',
                        'baseer_sales_dashboard', 'baseer_sales_heat_calendar',
                        'baseer_access_roles', 'baseer_procurement_requests')
    states = environment['ir.module.module'].search([('name', 'in', expected_modules)])
    require(len(states) == 8 and all(row.state == 'installed' for row in states),
            'PROTECTED_DEPLOYMENT_INCOMPLETE')
    before_others = other_users_digest(environment.cr)
    before_invariants = invariant_snapshot(environment, user)
    before_groups = set(user.group_ids.ids)
    before_companies = sorted(user.company_ids.ids)
    before_values = {name: bool(user[name]) for name in FIELDS + ('bwork_manage_rooms',)}
    manager = environment.ref('baseer_bwork.group_bwork_manager')
    api_user = environment.ref('baseer_bwork.group_bwork_user')
    # ORM inverse enforces the base.user_admin-only manager restriction.
    user.write({**{name: True for name in FIELDS}, 'bwork_manage_rooms': True})
    environment.flush_all()
    user.invalidate_recordset()
    require(set(user.group_ids.ids) - before_groups <= {manager.id, api_user.id},
            'UNEXPECTED_GROUP_GRANT')
    require(before_groups <= set(user.group_ids.ids), 'EXISTING_GROUP_REMOVED')
    require(sorted(user.company_ids.ids) == before_companies and user.company_id.id == 2,
            'COMPANY_SCOPE_MUTATED')
    require(all(user[name] for name in FIELDS + ('bwork_manage_rooms',)),
            'OWNER_SWITCH_NOT_ENABLED')
    service = environment['baseer.bwork.service'].with_user(user).with_context(
        allowed_company_ids=EXPECTED_COMPANIES, tz='Asia/Riyadh')
    permissions = service._v2_bootstrap()['permissions']
    require(all(permissions.get(name) for name in (
        'chat_view', 'chat_send', 'media', 'group_create', 'group_manage',
        'task_view', 'task_manage', 'room_admin', 'order_view', 'order_create',
        'order_receive', 'dashboard_view')), 'OWNER_EFFECTIVE_PERMISSION_MISSING')
    options = service._leadership_options()
    require(options['can_view'] and
            sorted(row['id'] for row in options['companies']) == EXPECTED_COMPANIES,
            'NATIVE_REPORT_ACCESS_MISSING')
    require(other_users_digest(environment.cr) == before_others, 'OTHER_USER_MUTATED')
    require(invariant_snapshot(environment, user) == before_invariants,
            'ROLE_MFA_OR_GLOBAL_GROUP_GRAPH_MUTATED')
    environment.cr.commit()
    print(json.dumps({'ownerActivation': 'GO', 'uid': 2,
                      'companyIds': EXPECTED_COMPANIES,
                      'otherUsersUnchanged': True,
                      'previousSwitches': before_values,
                      'enabledSwitchCount': len(FIELDS) + 1,
                      'nativeDashboardAccessVerified': True}, sort_keys=True))


try:
    activate(env)
except BaseException:
    env.cr.rollback()
    print('OWNER_ACTIVATION=FAILED_ROLLED_BACK')
    raise
