"""Resume the parser-only IC1 install failure; preserve frozen source and logs."""
import importlib
import shutil
import time
import urllib.request

import ic1_release as r
import environment_backups as b

candidate = r.verify_candidate()
r.review_go(r.OUT / 'PREDEPLOY-GO.md', candidate['commit'])
r.review_go(r.OUT / 'INSTALL-RECOVERY-GO.md', candidate['commit'])
failed = (r.OUT / 'main-install.log').read_text(encoding='utf8')
r.require('i18n-overwrite option cannot be used without the update option' in failed,
          'Expected parser-only failure')
runtime = b.inspect(b.MAIN_CONTAINER)
r.require(not runtime['State']['Running'], 'MAIN must remain stopped')
r.verify_mounts(runtime, r.OLD_FOLDER, candidate['image'])
cols = r.read_json(r.OUT / 'protected-columns.json')
before = r.read_json(r.OUT / 'protected-before.json')
versions = r.read_json(r.OUT / 'installed-versions-before.json')
memberships = r.read_json(r.OUT / 'security-memberships-before.json')
presets = r.read_json(r.OUT / 'role-assignments-before.json')
r.require(r.columns() == cols and r.projection(cols) == before, 'Pre-install data differs')
r.require(r.installed_versions() == versions and r.security_memberships() == memberships
          and r.role_assignments() == presets, 'Pre-install versions/security differ')
r.require(r.read_sql("SELECT state FROM ir_module_module WHERE name='"+r.MODULE+"'") in ('','uninstalled'),
          'Module already installed')
r.require(r.read_sql("SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')") == '0',
          'Pending modules')
for name in ('compose.yaml','compose.main-release.yaml'):
    expected = (r.BACK / (name+'.before')).read_text(encoding='utf8').replace(
        './.local-backups/'+r.OLD_FOLDER+'/candidate/', './.local-backups/'+r.NEW_FOLDER+'/candidate/')
    r.require((b.ROOT/name).read_text(encoding='utf8') == expected, 'Unexpected compose change')
lock = b.BACK / 'maintenance.lock'
with lock.open('x', encoding='utf8') as handle:
    handle.write('IC1 parser-only install retry '+candidate['commit'])
try:
    with (r.OUT/'main-install-retry.log').open('wb') as log:
        b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','run','--rm','--no-deps','-T',
               'odoo','odoo','--config=/etc/odoo/odoo.local.conf',
               '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
               '--database='+b.MAIN,'--init='+r.MODULE,'--stop-after-init','--no-http','--max-cron-threads=0'],
              cwd=b.ROOT, stdout=log, stderr=log)
    after_cols = r.columns()
    r.require(all(after_cols.get(table) == names + (['baseer_allow_financial_correction']
              if table=='res_users' else []) for table,names in cols.items()), 'Existing columns differ')
    r.require(r.read_sql('SELECT count(*) FROM res_users WHERE baseer_allow_financial_correction IS NOT TRUE')=='0',
              'New setting default differs')
    r.require(r.read_sql('SELECT count(*) FROM baseer_financial_correction_audit')=='0', 'Nonempty audit')
    after = r.projection(cols)
    b.save(r.OUT/'protected-after.json',after)
    r.require(after==before,'Existing data changed; MAIN remains stopped')
    b.save(r.OUT/'security-memberships-after.json',r.security_memberships())
    b.save(r.OUT/'role-assignments-after.json',r.role_assignments())
    r.require(r.security_memberships()==memberships and r.role_assignments()==presets,'Security changed')
    r.verify_preserved_versions(versions)
    b.save(r.OUT/'main-preservation.json',dict(protected_tables=len(cols),existing_columns_exact=True,
        existing_rows_exact=True,candidate=candidate['commit'],existing_user_memberships_exact=True,
        existing_module_versions_exact=True,existing_user_presets_exact=True,no_automatic_role_assignments=True,
        initial_correction_audit_empty=True,new_correction_setting_default_exact=True,
        added_schema='Correction models and default-true user permission; all prior column values preserved',
        recovery='Parser-only failed init retried without update-only i18n-overwrite flag'))
    helper=b.ROOT/'docs/build-governance/environment_backups.py'
    text=helper.read_text(encoding='utf8')
    r.require(r.OLD_RELEASE in text and r.OLD_FOLDER in text,'Backup mapping changed')
    shutil.copy2(helper,r.BACK/'environment_backups.py.before')
    helper.write_text(text.replace(r.OLD_RELEASE,r.NEW_RELEASE).replace(r.OLD_FOLDER,r.NEW_FOLDER),encoding='utf8')
    importlib.reload(b)
    b.save(r.OUT/'post-release-backup.json',b.backup(b.MAIN))
    b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','up','-d','--no-deps','odoo'],
          cwd=b.ROOT,capture_output=True)
    for _ in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18069/web/login',timeout=3) as response:
                if response.status==200:
                    break
        except OSError:
            pass
        time.sleep(2)
    else:
        raise RuntimeError('MAIN healthcheck failed')
    r.verify_runtime()
    print('PUBLISHED',candidate['commit'],flush=True)
finally:
    lock.unlink()
