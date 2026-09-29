"""Independent PP1 negative cases; isolated own QA transaction always rolled back."""
import json
from pathlib import Path
from odoo import Command
from odoo.exceptions import AccessError
assert env.cr.dbname == 'baseer_partner_priority_qa_20260909'
checks = []
def denied(label, fn):
    try:
        with env.cr.savepoint():
            fn()
    except AccessError:
        checks.append(label)
    else:
        raise AssertionError(label)
try:
    a, b = env['res.company'].search([], order='id', limit=2)
    P = env['res.partner'].with_context(allowed_company_ids=[a.id, b.id], baseer_partner_priority=True)
    denied('Create rejects explicit favorite on other-company private partner', lambda: P.create({'name':'PP1 independent rejected', 'company_id': b.id, 'baseer_is_favorite': True}))
    denied('Create rejects context-default favorite on other-company private partner', lambda: P.with_context(default_baseer_is_favorite=True).create({'name':'PP1 independent rejected default', 'company_id': b.id}))
    private = P.with_company(b).create({'name':'PP1 independent private B', 'company_id': b.id, 'baseer_is_favorite':True})
    assert not P.web_search_read([('id','=',private.id)], {'display_name':{}, 'baseer_is_favorite':{}}, limit=8)['records']
    checks.append('Search More filters private B with both companies allowed')
    peer = P.create({'name':'PP1 independent ordinary'})
    user = env['res.users'].with_context(no_reset_password=True).create({'name':'PP1 independent user','login':'pp1.independent.user', 'company_id':a.id, 'company_ids':[Command.set([a.id,b.id])], 'group_ids':[Command.set([env.ref('base.group_user').id, env.ref('base.group_partner_manager').id])]})
    env['ir.rule'].create({'name':'PP1 independent no peer writes', 'model_id':env.ref('base.model_res_partner').id, 'domain_force':"[('id','!=',%s)]" % peer.id, 'perm_read':False,'perm_write':True,'perm_create':False,'perm_unlink':False})
    denied('Favorite obeys native partner write record rule', lambda: peer.with_user(user).write({'baseer_is_favorite':True}))
    assert not peer.baseer_is_favorite
    checks.append('Denied write preserves favorite value')
    peer.baseer_is_favorite=True
    assert P.with_user(user).web_name_search('PP1 independent ordinary', {'display_name':{},'baseer_is_favorite':{}}, limit=8)[0]['baseer_is_favorite']
    checks.append('No-bill reader web autocomplete returns favorite metadata')
    print('PP1 INDEPENDENT PASS', len(checks))
finally:
    env.cr.rollback()
Path('/mnt/pp1-evidence/independent-checks.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'rolled_back':True},indent=2))
