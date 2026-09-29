"""Isolated AR1 install/update/uninstall checks using the existing snapshot; no MAIN writes."""
import json
from pathlib import Path
import environment_backups as b
import ar1_release as r

DATABASE = 'baseer_ar1_lifecycle_20260910'
OUT = b.ROOT / 'docs/build-governance/ar1-lifecycle-checks.json'
BACK = b.ROOT / '.local-backups/access-roles-20260910'
DUMP = BACK / 'qa-source.dump'
assert DATABASE.startswith('baseer_ar1_lifecycle_') and DATABASE not in (b.MAIN, 'baseer_reports_qa_20260907')
assert DUMP.is_file()
assert b.sql('postgres', "SELECT count(*) FROM pg_database WHERE datname='" + DATABASE + "'") == '0'
checks = []
result = {'status': 'FAIL', 'database': DATABASE, 'checks': checks, 'source_files': r.inventory(b.ROOT/'custom_addons/baseer_access_roles')}
result['payroll_patch_files'] = {rel: b.sha(b.ROOT / rel) for rel in sorted(r.PAYROLL_PATCHES)}

def sql(query):
    return b.run(['docker','exec','-i',b.DB,'psql','-U','odoo','-d',DATABASE,'-qAt','-v','ON_ERROR_STOP=1'],
                 input='BEGIN READ ONLY;\n'+query+';\nROLLBACK;',capture_output=True,text=True,encoding='utf8').stdout.strip()

def check(label, value):
    assert value,label
    checks.append(label)

def memberships():
    return {name:sql(query) for name,query in {
        'groups': "SELECT coalesce(json_agg(t ORDER BY uid,gid)::text,'[]') FROM (SELECT uid,gid FROM res_groups_users_rel)t",
        'companies': "SELECT coalesce(json_agg(t ORDER BY user_id,cid)::text,'[]') FROM (SELECT user_id,cid FROM res_company_users_rel)t"}.items()}

def run_odoo(label, extra, code=None):
    args=['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','-f','compose.roles-qa.yaml','run','--rm','--no-deps','-T','roles_qa','odoo']
    if code is not None: args += ['shell']
    args += ['--config=/etc/odoo/odoo.local.conf',
             '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/role-addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
             '--database='+DATABASE,'--no-http','--max-cron-threads=0']+extra
    with (BACK/('lifecycle-'+label+'.log')).open('wb') as log:
        if code is None:b.run(args,cwd=b.ROOT,stdout=log,stderr=log)
        else:b.run(args,cwd=b.ROOT,input=code.encode('utf8'),stdout=log,stderr=log)

try:
    b.run(['docker','exec',b.DB,'createdb','-U','odoo','-O','odoo','--template=template0',DATABASE],capture_output=True)
    with DUMP.open('rb') as stream:
        b.run(['docker','exec','-i',b.DB,'pg_restore','-U','odoo','--no-owner','--exit-on-error','-d',DATABASE],stdin=stream,capture_output=True)
    r.read_sql = sql
    cols=r.columns(); original=r.projection(cols); prior_members=memberships()
    check('source snapshot has no installed role addon',sql("SELECT count(*) FROM ir_module_module WHERE name='baseer_access_roles' AND state='installed'")=='0')
    run_odoo('install',['--init=baseer_access_roles','--update=baseer_payroll','--stop-after-init'])
    check('clean isolated installation succeeds',sql("SELECT state FROM ir_module_module WHERE name='baseer_access_roles'")=='installed')
    check('reviewed payroll capability version installed',sql("SELECT latest_version FROM ir_module_module WHERE name='baseer_payroll'")=='19.0.1.5.1')
    check('installation preserves original business rows and columns',r.projection(cols)==original)
    check('installation preserves original explicit group and company memberships',memberships()==prior_members)
    check('installation assigns no existing user role',sql("SELECT count(*) FROM res_users WHERE baseer_access_role IS NOT NULL")=='0')
    run_odoo('fixtures',[],"""from odoo import Command
assert env.cr.dbname.startswith('baseer_ar1_lifecycle_')
for role in ('cashier','accountant','owner'):
    env['res.users'].with_context(no_reset_password=True).create({'name':'AR1 Lifecycle '+role,'login':'ar1-lifecycle-'+role,'baseer_access_role':role,'company_id':env.company.id,'company_ids':[Command.set(env.company.ids)]})
env.cr.commit()
""")
    role_members=memberships()
    role_rows=sql("SELECT json_agg(t ORDER BY id)::text FROM (SELECT id,baseer_access_role FROM res_users WHERE login LIKE 'ar1-lifecycle-%')t")
    run_odoo('update',['--update=baseer_access_roles','--stop-after-init'])
    check('module update retains selected role users and memberships',memberships()==role_members and sql("SELECT json_agg(t ORDER BY id)::text FROM (SELECT id,baseer_access_role FROM res_users WHERE login LIKE 'ar1-lifecycle-%')t")==role_rows)
    check('update has no duplicate role marker groups',sql("SELECT count(*) FROM ir_model_data WHERE module='baseer_access_roles' AND model='res.groups'")=='3')
    run_odoo('uninstall',[],"""assert env.cr.dbname.startswith('baseer_ar1_lifecycle_')
module=env['ir.module.module'].search([('name','=','baseer_access_roles')])
module.button_immediate_uninstall()
env.cr.commit()
""")
    check('isolated uninstall succeeds',sql("SELECT state FROM ir_module_module WHERE name='baseer_access_roles'")=='uninstalled')
    check('uninstall removes owned groups rules and views metadata',sql("SELECT count(*) FROM ir_model_data WHERE module='baseer_access_roles'")=='0')
    check('uninstall preserves fixture user identities',sql("SELECT count(*) FROM res_users WHERE login LIKE 'ar1-lifecycle-%'")=='3')
    result['uninstall_role_user_groups']=sql("SELECT coalesce(json_agg(t ORDER BY u.login,g.gid)::text,'[]') FROM res_users u LEFT JOIN res_groups_users_rel g ON u.id=g.uid CROSS JOIN LATERAL (SELECT u.login,g.gid)t WHERE u.login LIKE 'ar1-lifecycle-%'")
    result['uninstall_note']='Preset-assigned users may lose app grants when owned marker groups are removed; clear roles and explicitly grant manual access before uninstalling on a real system.'
    check('no pending module operation after uninstall',sql("SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')")=='0')
    result['status']='PASS'
except Exception as exc:
    result.update(error_type=type(exc).__name__,error=str(exc))
    raise
finally:
    b.save(OUT,result)
    print('AR1_LIFECYCLE',result['status'],len(checks),flush=True)
