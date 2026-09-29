"""Rollback-only computed/default-field diagnostic for AR2; no production use."""
import json
from pathlib import Path
from odoo import Command
assert env.cr.dbname.startswith('baseer_ar1_') and env.su
rows = []
admin = env.ref('base.user_admin')
companies = admin.company_ids[:3]
base = {'allowed_company_ids': companies.ids, 'lang': 'en_US', 'no_reset_password': True, 'tracking_disable': True}
class Done(Exception): pass
try:
    cases = [
        ('computed-admin-groups', {'all_group_ids': [Command.set(admin.all_group_ids.ids)]}, {}),
        ('computed-user-groups', {'all_group_ids': [Command.set(env.ref('base.group_user').ids)]}, {}),
        ('context-default-admin-groups', {}, {'default_group_ids': [Command.set(admin.group_ids.ids)]}),
        ('context-default-computed-groups', {}, {'default_all_group_ids': [Command.set(admin.all_group_ids.ids)]}),
        ('context-debug', {}, {'debug': True}),
        ('context-default-role', {}, {'default_role': 'group_system'}),
        ('notification-inbox', {'notification_type': 'inbox'}, {}),
        ('notification-email', {'notification_type': 'email'}, {}),
    ]
    for index, (label, extra, context) in enumerate(cases):
        actor = env(user=admin.id, su=False, context={**base, **context})
        values = dict(name='AR2 diagnostic', login='ar2-diagnostic-'+str(index),
                      baseer_access_role='accountant', company_id=companies[0].id,
                      company_ids=[Command.set(companies.ids)], **extra)
        try:
            with env.cr.savepoint():
                user = actor['res.users'].create(values)
                rows.append({'case': label, 'result': 'created', 'groups': list(user.all_group_ids.get_external_id().values())})
                raise Done()
        except Done:
            pass
        except Exception as error:
            rows.append({'case': label, 'result': type(error).__name__, 'message': str(error)})
finally:
    env.cr.rollback()
    Path('/mnt/qa-evidence/ar2-role-diagnostics.json').write_text(json.dumps(rows, indent=2), encoding='utf8')
    print(json.dumps(rows))
