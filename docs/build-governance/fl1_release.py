"""Freeze FL1 on the accepted AR2 source; publish only after candidate GO.

Commands: freeze, publish, verify-runtime. Freeze does not contact Docker or MAIN.
Publish intentionally leaves MAIN stopped if installation/preservation checks fail;
recover using main-backup.json and the saved compose files, not an automatic downgrade.
"""
import argparse
import ast
import importlib
import json
import re
import shutil
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

import environment_backups as b

MODULE = 'baseer_financial_register'
OLD_RELEASE = '2026-09-10-access-roles-user-form'
NEW_RELEASE = '2026-09-10-financial-register'
OLD_FOLDER = 'access-roles-user-form-20260910'
NEW_FOLDER = 'financial-register-20260910'
OUT = b.ROOT / 'docs/releases' / NEW_RELEASE
BACK = b.ROOT / '.local-backups' / NEW_FOLDER
SOURCE = BACK / 'candidate'
OLD = b.ROOT / '.local-backups' / OLD_FOLDER / 'candidate'
BASELINE = b.ROOT / 'docs/releases' / OLD_RELEASE / 'candidate.json'
PARENT = '6104fc8e6f1d24b3e842f2b43bd9f410840d7759'
PREFIX = 'custom_addons/' + MODULE + '/'
EVIDENCE = ('fl1-accounting-checks.json', 'fl1-ui-checks.json')
SUPPORTING_EVIDENCE = ('fl1_register_checks.py',)
DEPENDENCIES = ('account', 'baseer_access_roles', 'baseer_report_layout')
MOUNTS = (('/mnt/baseer-addons', 'custom_addons'),
          ('/mnt/extra-addons', 'custom_addons'),
          ('/mnt/third-party-addons', 'third_party_addons'))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def review_go(path, commit=None):
    require(path.is_file(), 'Independent review missing: ' + str(path))
    text = path.read_text(encoding='utf-8-sig')
    plain = text.replace('**', '').replace('`', '')
    require(re.search(r'^\s*(?:Decision|Verdict)\s*:\s*GO\b', plain, re.M | re.I),
            'Independent review must contain an explicit Decision: GO')
    if commit:
        require(commit in text, 'Independent candidate GO must identify the exact frozen commit')


def inventory(root):
    return {p.relative_to(root).as_posix(): b.sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not {'.git', '__pycache__'}.intersection(p.parts)
            and p.suffix != '.pyc'}


def verify_ui_evidence(root, evidence):
    files = evidence.get('evidence_files', {})
    require(bool(files), 'UI screenshots/DOM evidence is missing')
    for rel, digest in files.items():
        path = PurePosixPath(rel)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in rel,
                'Unsafe UI evidence path')
        source = root.joinpath(*path.parts)
        require(not source.is_symlink() and source.resolve().is_relative_to(root.resolve()),
                'Unsafe UI evidence source')
        require(b.sha(source) == digest, 'UI evidence differs: ' + rel)
    return files


def baseline():
    previous = read_json(BASELINE)
    require(previous['commit'] == PARENT and len(previous['files']) == 1156,
            'Expected the accepted AR2 commit and exactly 1156 files')
    require(not any(rel.startswith(PREFIX) for rel in previous['files']), 'Financial register must be a new addon')
    for rel, digest in previous['files'].items():
        path = PurePosixPath(rel)
        require(not path.is_absolute() and '..' not in path.parts and
                path.parts[0] in ('custom_addons', 'third_party_addons'), 'Unsafe source path')
        require(b.sha(OLD / rel) == digest, 'Baseline file differs: ' + rel)
    return previous

def freeze():
    previous = baseline()
    addon = b.ROOT / 'custom_addons' / MODULE
    manifest = ast.literal_eval((addon / '__manifest__.py').read_text(encoding='utf-8-sig'))
    require(manifest.get('installable') and manifest.get('version') == '19.0.1.0.0'
            and set(manifest.get('depends', [])) == set(DEPENDENCIES),
            'Expected financial register 19.0.1.0.0 with reviewed installed dependencies')
    evidence = {name: read_json(b.ROOT / 'docs/build-governance' / name) for name in EVIDENCE}
    require(all(str(result.get('status')).lower() in ('pass', 'passed')
                for result in evidence.values()), 'Acceptance checks must pass before freeze')
    require(evidence['fl1-accounting-checks.json'].get('rollback') is True,
            'Financial register fixtures must be fully rolled back')
    ui_source = b.ROOT / 'docs/build-governance/fl1-ui'
    ui_files = verify_ui_evidence(ui_source, evidence['fl1-ui-checks.json'])
    review_go(b.ROOT / 'docs/build-governance/FL1-REVIEW.md')
    addon_files = inventory(addon)
    require(bool(addon_files), 'New addon source is missing')
    for rel in addon_files:
        path = addon / rel
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        elif path.suffix == '.xml':
            ET.parse(path)
    require(not SOURCE.exists() and not (OUT / 'candidate.json').exists(),
            'Candidate already exists; do not overwrite a frozen release')
    SOURCE.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    for rel in previous['files']:
        target = SOURCE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OLD / rel, target)
    for rel in addon_files:
        target = SOURCE / PREFIX / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(addon / rel, target)
    files = inventory(SOURCE)
    added = sorted(set(files) - set(previous['files']))
    require(added and all(rel.startswith(PREFIX) for rel in added), 'Only financial register source may be added')
    require(all(files.get(rel) == sha for rel, sha in previous['files'].items()),
            'All 1156 accepted baseline files must remain byte-identical')
    with zipfile.ZipFile(OUT / 'candidate-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for rel in sorted(files):
            archive.write(SOURCE / rel, rel)
    b.run(['git', 'init', '--initial-branch=codex/financial-register', str(SOURCE)], capture_output=True)
    b.run(['git', '-C', str(SOURCE), 'config', 'core.autocrlf', 'false'], capture_output=True)
    b.run(['git', '-C', str(SOURCE), 'add', '.'], capture_output=True)
    b.run(['git', '-C', str(SOURCE), '-c', 'user.name=Codex Release', '-c',
           'user.email=codex-release@localhost', 'commit', '-qm',
           'Add read-only financial operations register and invoice indicators'], capture_output=True)
    commit = b.run(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                   capture_output=True, text=True).stdout.strip()
    b.save(OUT / 'candidate.json', dict(commit=commit, parent=previous['commit'],
        image=previous['image'], files=files, changed_files=added, preserved_files=1156,
        source_directory=str(SOURCE), module=MODULE, module_version=manifest['version'],
        evidence_sha256={name: b.sha(b.ROOT / 'docs/build-governance' / name)
                         for name in EVIDENCE + SUPPORTING_EVIDENCE + ('FL1-REVIEW.md',)},
        archive_sha256=b.sha(OUT / 'candidate-source.zip')))
    for name in EVIDENCE + SUPPORTING_EVIDENCE + ('FINANCIAL-REGISTER.md', 'FL1-REVIEW.md'):
        shutil.copy2(b.ROOT / 'docs/build-governance' / name, OUT / name)
    for rel in ui_files:
        target = OUT / 'fl1-ui' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ui_source / rel, target)
    print('FROZEN', commit, len(files), 'preserved=1156 added=' + str(len(added)), flush=True)


def verify_candidate():
    candidate = read_json(OUT / 'candidate.json')
    previous = baseline()
    require(candidate['parent'] == previous['commit'], 'Candidate parent differs')
    require(inventory(SOURCE) == candidate['files'], 'Frozen source inventory/hash differs')
    require(all(candidate['files'].get(rel) == sha for rel, sha in previous['files'].items()),
            'An accepted baseline source file changed')
    added = set(candidate['files']) - set(previous['files'])
    require(added and all(rel.startswith(PREFIX) for rel in added)
            and set(candidate['changed_files']) == added and candidate['preserved_files'] == 1156,
            'Only new financial register source may be added')
    require(candidate['module'] == MODULE and candidate['module_version'] == '19.0.1.0.0',
            'Candidate module/version differs')
    for name, digest in candidate['evidence_sha256'].items():
        require(b.sha(OUT / name) == digest, 'Frozen acceptance evidence differs: ' + name)
    for name in EVIDENCE:
        require(str(read_json(OUT / name).get('status')).lower() in ('pass', 'passed'),
                'Frozen acceptance checks must pass')
    require(read_json(OUT / 'fl1-accounting-checks.json').get('rollback') is True,
            'Frozen integration rollback evidence missing')
    verify_ui_evidence(OUT / 'fl1-ui', read_json(OUT / 'fl1-ui-checks.json'))
    review_go(OUT / 'FL1-REVIEW.md')
    require(b.sha(OUT / 'candidate-source.zip') == candidate['archive_sha256'], 'Archive differs')
    return candidate


def read_sql(query):
    # Quiet mode suppresses transaction command tags; every inspection is read-only.
    return b.run(['docker', 'exec', '-i', b.DB, 'psql', '-U', 'odoo', '-d', b.MAIN,
                  '-qAt', '-v', 'ON_ERROR_STOP=1'], input='BEGIN READ ONLY;\n' + query +
                 ';\nROLLBACK;', capture_output=True, text=True, encoding='utf8').stdout.strip()


def columns():
    return json.loads(read_sql("""SELECT json_object_agg(table_name, cols) FROM (
        SELECT c.table_name, json_agg(c.column_name ORDER BY c.ordinal_position) cols
        FROM information_schema.columns c JOIN information_schema.tables t
        ON t.table_schema=c.table_schema AND t.table_name=c.table_name
        WHERE c.table_schema='public' AND t.table_type='BASE TABLE' AND
        (c.table_name ~ '^(account|baseer|hr|pos|resource|stock|sale|purchase|product)_'
         OR c.table_name IN ('res_company','res_partner','res_users'))
        GROUP BY c.table_name) tables"""))


def projection(cols):
    parts = []
    for table, names in sorted(cols.items()):
        fields = ','.join('"' + n.replace('"', '""') + '"' for n in names)
        quoted = '"' + table.replace('"', '""') + '"'
        parts.append("SELECT '%s' name,count(*) rows,md5(coalesce(string_agg(h,'' ORDER BY h),'')) hash "
                     "FROM (SELECT md5(row_to_json(t)::text) h FROM (SELECT %s FROM %s)t)s"
                     % (table.replace("'", "''"), fields, quoted))
    require(parts, 'No protected business tables discovered')
    return json.loads(read_sql('SELECT json_agg(t ORDER BY name) FROM (' + ' UNION ALL '.join(parts) + ')t'))


def verify_mounts(runtime, folder, image):
    require(runtime['Config']['Image'] == image, 'Runtime image differs')
    for destination, directory in MOUNTS:
        mount = next(m for m in runtime['Mounts'] if m['Destination'] == destination)
        require(not mount['RW'] and mount['Source'].replace('\\', '/').lower().endswith(
                '/' + folder + '/candidate/' + directory), 'Frozen readonly mount differs: ' + destination)


def security_memberships():
    return {
        'groups': read_sql("SELECT coalesce(json_agg(t ORDER BY uid,gid)::text,'[]') FROM (SELECT uid,gid FROM res_groups_users_rel)t"),
        'companies': read_sql("SELECT coalesce(json_agg(t ORDER BY user_id,cid)::text,'[]') FROM (SELECT user_id,cid FROM res_company_users_rel)t"),
    }


def installed_versions():
    return json.loads(read_sql("SELECT coalesce(json_object_agg(name,latest_version),'{}'::json) FROM ir_module_module WHERE state='installed'"))


def verify_preserved_versions(before):
    after = installed_versions()
    expected = dict(before, **{MODULE: '19.0.1.0.0'})
    require(after == expected, 'An unrelated module version or installed-module inventory changed')

def expected_protected_tables():
    old_columns = read_json(b.ROOT / 'docs/releases' / OLD_RELEASE / 'protected-columns.json')
    require(len(old_columns) == 368, 'Expected all accepted AR2 protected tables')
    return set(old_columns)


def role_assignments():
    return read_sql("SELECT coalesce(json_agg(t ORDER BY id)::text,'[]') FROM (SELECT id,baseer_access_role FROM res_users)t")


def publish():
    candidate = verify_candidate()
    go = OUT / 'PREDEPLOY-GO.md'
    review_go(go, candidate['commit'])
    require(not (OUT / 'main-backup.json').exists(), 'Publish already started; inspect evidence before recovery')
    verify_mounts(b.inspect(b.MAIN_CONTAINER), OLD_FOLDER, candidate['image'])
    require(read_sql("SELECT state FROM ir_module_module WHERE name='" + MODULE + "'")
            in ('', 'uninstalled'), 'Financial register must not already be installed')
    require(read_sql("SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')")
            == '0', 'Pending module operations exist')
    versions_before = installed_versions()
    require(all(name in versions_before for name in DEPENDENCIES),
            'Reviewed dependencies must already be installed; do not install unrelated modules on MAIN')
    require(versions_before.get('baseer_sales_dashboard') == '19.0.1.1.5'
            and versions_before.get('baseer_browser_print') == '19.0.1.0.0'
            and versions_before.get('baseer_partner_priority') == '19.0.1.0.0'
            and versions_before.get('baseer_payroll') == '19.0.1.5.1'
            and versions_before.get('baseer_access_roles') == '19.0.1.0.1',
            'Expected accepted SD7, BP1, PP1, payroll and AR2 installed versions')
    old_prefix = './.local-backups/' + OLD_FOLDER + '/candidate/'
    new_prefix = './.local-backups/' + NEW_FOLDER + '/candidate/'
    compose = {name: (b.ROOT / name).read_text(encoding='utf8')
               for name in ('compose.yaml', 'compose.main-release.yaml')}
    require(all(content.count(old_prefix) == 3 for content in compose.values()), 'Compose baseline differs')
    helper = b.ROOT / 'docs/build-governance/environment_backups.py'
    helper_text = helper.read_text(encoding='utf8')
    require(OLD_RELEASE in helper_text and OLD_FOLDER in helper_text, 'Backup source mapping differs')
    b.BACK.mkdir(parents=True, exist_ok=True)
    lock = b.BACK / 'maintenance.lock'
    with lock.open('x', encoding='utf8') as handle:
        handle.write('FL1 publish ' + candidate['commit'])
    try:
        b.run(['docker', 'stop', '--timeout', '60', b.MAIN_CONTAINER], capture_output=True)
        b.save(OUT / 'main-backup.json', b.backup(b.MAIN))
        b.save(OUT / 'installed-versions-before.json', versions_before)
        memberships_before = security_memberships()
        role_assignments_before = role_assignments()
        b.save(OUT / 'role-assignments-before.json', role_assignments_before)
        b.save(OUT / 'security-memberships-before.json', memberships_before)
        cols = columns()
        require(set(cols) == expected_protected_tables(),
                'Expected all 368 accepted protected business tables')
        before = projection(cols)
        b.save(OUT / 'protected-columns.json', cols)
        b.save(OUT / 'protected-before.json', before)
        for name, content in compose.items():
            path = b.ROOT / name
            shutil.copy2(path, BACK / (name + '.before'))
            path.write_text(content.replace(old_prefix, new_prefix), encoding='utf8')
        with (OUT / 'main-install.log').open('wb') as log:
            b.run(['docker', 'compose', '-p', 'baseer_odoo_dev', '-f', 'compose.yaml',
                   'run', '--rm', '--no-deps', '-T', 'odoo', 'odoo',
                   '--config=/etc/odoo/odoo.local.conf',
                   '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
                   '--database=' + b.MAIN, '--init=' + MODULE, '--stop-after-init',
                   '--no-http', '--max-cron-threads=0'], cwd=b.ROOT, stdout=log, stderr=log)
        after = projection(cols)
        b.save(OUT / 'protected-after.json', after)
        require(before == after, 'Business rows changed; keep MAIN stopped for investigation')
        memberships_after = security_memberships()
        b.save(OUT / 'security-memberships-after.json', memberships_after)
        require(memberships_before == memberships_after, 'Existing user memberships changed; keep MAIN stopped')
        role_assignments_after = role_assignments()
        b.save(OUT / 'role-assignments-after.json', role_assignments_after)
        require(role_assignments_before == role_assignments_after,
                'Existing role assignments changed; keep MAIN stopped')
        verify_preserved_versions(versions_before)
        b.save(OUT / 'main-preservation.json', dict(protected_tables=len(cols),
            existing_columns_exact=True, existing_rows_exact=True, candidate=candidate['commit'],
            existing_user_memberships_exact=True, existing_module_versions_exact=True,
            existing_user_presets_exact=True, no_automatic_role_assignments=True,
            added_schema='Nonstored reporting fields and view/action metadata only; no user assignment or business transaction migration'))
        shutil.copy2(helper, BACK / 'environment_backups.py.before')
        helper.write_text(helper_text.replace(OLD_RELEASE, NEW_RELEASE).replace(OLD_FOLDER, NEW_FOLDER), encoding='utf8')
        # Capture the accepted new source and filestore while MAIN remains stopped.
        importlib.reload(b)
        b.save(OUT / 'post-release-backup.json', b.backup(b.MAIN))
        b.run(['docker', 'compose', '-p', 'baseer_odoo_dev', '-f', 'compose.yaml',
               'up', '-d', '--no-deps', 'odoo'], cwd=b.ROOT, capture_output=True)
        for _ in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18069/web/login', timeout=3) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('MAIN healthcheck failed')
        verify_runtime()
        print('PUBLISHED', candidate['commit'], flush=True)
    finally:
        lock.unlink()


def verify_runtime():
    candidate = verify_candidate()
    with urllib.request.urlopen('http://127.0.0.1:18069/web/login', timeout=5) as response:
        require(response.status == 200, 'MAIN HTTP failed')
    runtime = b.inspect(b.MAIN_CONTAINER)
    verify_mounts(runtime, NEW_FOLDER, candidate['image'])
    installed = read_sql("SELECT state || '|' || latest_version FROM ir_module_module WHERE name='" + MODULE + "'")
    require(installed == 'installed|' + candidate['module_version'], 'Installed module/version differs')
    require(read_sql("SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')")
            == '0', 'Pending module operations exist')
    verify_preserved_versions(read_json(OUT / 'installed-versions-before.json'))
    groups = read_sql("""SELECT count(*) FROM ir_model_data d JOIN res_groups g ON g.id=d.res_id
        WHERE d.module='baseer_access_roles' AND d.model='res.groups'
        AND d.name IN ('group_owner','group_accountant','group_cashier')""")
    require(groups == '3', 'Three seeded role groups missing')
    dashboard = read_sql("""SELECT count(*) FROM spreadsheet_dashboard d JOIN ir_model_data m
        ON m.res_id=d.id AND m.model='spreadsheet.dashboard'
        WHERE m.module='baseer_sales_dashboard' AND m.name='dashboard_sales_summary'
        AND d.baseer_dashboard_kind='sales_summary' AND d.is_published""")
    require(dashboard == '1', 'Accepted sales dashboard missing')
    b.save(OUT / 'runtime.json', dict(http=200, mounts=runtime['Mounts'],
        image=runtime['Config']['Image'], installed=installed, no_pending_modules=True,
        existing_module_versions_exact=True, role_groups=3, published_dashboard=True,
        candidate=candidate['commit']))
    print('RUNTIME_VERIFIED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'publish', 'verify-runtime'))
    args = parser.parse_args()
    {'freeze': freeze, 'publish': publish, 'verify-runtime': verify_runtime}[args.command]()
