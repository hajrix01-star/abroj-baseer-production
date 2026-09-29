"""Read-only public website/login identity diagnostic, after SIM90 QA cutover."""
import json
from pathlib import Path
from odoo import api

assert env.cr.dbname == 'baseer_ic1_20260910'
env.cr.execute('SET TRANSACTION READ ONLY')
public = env.ref('base.public_user')
websites = env['website'].search([])
result = {'database': env.cr.dbname, 'read_only': True, 'public_user_xmlid': public.id,
    'users': [], 'websites': websites.read(['name', 'company_id', 'user_id', 'domain']), 'website_acl': []}
users = public | websites.user_id
for user in users:
    actor = api.Environment(env.cr, user.id, {'allowed_company_ids': user.company_ids.ids,
        'lang': 'en_US'}, su=False)
    item = {'id': user.id, 'name': user.name, 'active': user.active, 'share': user.share,
        'company_id': user.company_id.id, 'company_ids': user.company_ids.ids,
        'groups': [{'id': group.id, 'name': group.name} for group in user.group_ids],
        'public_group': actor.user.has_group('base.group_public'),
        'portal_group': actor.user.has_group('base.group_portal'),
        'internal_group': actor.user.has_group('base.group_user')}
    try:
        item['website_read_test'] = actor['website'].search([]).read(['name', 'company_id'])
    except Exception as error:
        item['website_read_error'] = {'type': type(error).__name__, 'message': str(error)}
    result['users'].append(item)
for acl in env['ir.model.access'].search([('model_id.model', '=', 'website')]):
    result['website_acl'].append({'name': acl.name, 'active': acl.active, 'group_id': acl.group_id.id,
        'group': acl.group_id.name, 'perm_read': acl.perm_read, 'perm_write': acl.perm_write})
result['public_group_id'] = env.ref('base.group_public').id
env.cr.rollback()
Path('/tmp/sim90/login-diagnostic.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print('SIM90_LOGIN_DIAG', json.dumps(result, ensure_ascii=True), flush=True)
