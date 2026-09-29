"""Freeze reviewed PP1 on the accepted BP1 source; publish only after candidate GO.

Commands: freeze, publish, verify-runtime. Freeze does not contact Docker or MAIN.
Publish intentionally leaves MAIN stopped if installation/preservation checks fail;
recover using main-backup.json and the saved compose files, not an automatic downgrade.
"""
import argparse
import ast
import importlib
import json
import shutil
import time
import urllib.request
import zipfile
from pathlib import PurePosixPath

import environment_backups as b

MODULE = 'baseer_partner_priority'
OLD_RELEASE = '2026-09-09-browser-print'
NEW_RELEASE = '2026-09-10-partner-priority-main'
OLD_FOLDER = 'browser-print-20260909'
NEW_FOLDER = 'partner-priority-main-20260910'
OUT = b.ROOT / 'docs/releases' / NEW_RELEASE
BACK = b.ROOT / '.local-backups' / NEW_FOLDER
SOURCE = BACK / 'candidate'
OLD = b.ROOT / '.local-backups' / OLD_FOLDER / 'candidate'
BASELINE = b.ROOT / 'docs/releases' / OLD_RELEASE / 'candidate.json'
PARENT = '80ab864153b9e337090d5a1286150e7a64ad6319'
PREFIX = 'custom_addons/' + MODULE + '/'
REVIEWED = b.ROOT / 'docs/releases/2026-09-09-partner-priority/candidate.json'
MOUNTS = (('/mnt/baseer-addons', 'custom_addons'),
          ('/mnt/extra-addons', 'custom_addons'),
          ('/mnt/third-party-addons', 'third_party_addons'))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def inventory(root):
    return {p.relative_to(root).as_posix(): b.sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not {'.git', '__pycache__'}.intersection(p.parts)
            and p.suffix != '.pyc'}


def baseline():
    previous = read_json(BASELINE)
    require(previous['commit'] == PARENT and len(previous['files']) == 1126,
            'Expected the accepted BP1 commit and exactly 1126 files')
    require(not any(rel.startswith(PREFIX) for rel in previous['files']),
            'Partner priority addon must be new to the baseline')
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
            and manifest.get('depends') == ['account', 'baseer_purchase_batch'], 'Expected reviewed partner priority manifest')
    reviewed = read_json(REVIEWED)
    require(reviewed['candidate'] == '9424da9a50ecda8d0462dc44ce2e7f0ab4012427', 'Reviewed PP1 identity differs')
    approved = {item['path']: item['sha256'] for item in reviewed['files']}
    require(len(approved) == 9 and all(b.sha(b.ROOT / r) == h for r, h in approved.items()),
            'Working addon must match all nine independently approved files')
    require(not SOURCE.exists() and not (OUT / 'candidate.json').exists(),
            'Candidate already exists; do not overwrite a frozen release')
    SOURCE.mkdir(parents=True, exist_ok=False)
    OUT.mkdir(parents=True, exist_ok=True)
    for rel in previous['files']:
        target = SOURCE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OLD / rel, target)
    for rel in inventory(addon):
        target = SOURCE / PREFIX / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(addon / rel, target)
    files = inventory(SOURCE)
    added = sorted(rel for rel, digest in files.items() if previous['files'].get(rel) != digest)
    require(added and all(rel.startswith(PREFIX) for rel in added), 'Only new partner priority addon may be added')
    require(set(previous['files']).issubset(files), 'No baseline file may disappear')
    require(all(files.get(rel) == digest for rel, digest in previous['files'].items()),
            'All 1126 baseline files must remain byte-identical')
    with zipfile.ZipFile(OUT / 'candidate-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for rel in sorted(files):
            archive.write(SOURCE / rel, rel)
    b.run(['git', 'init', '--initial-branch=codex/browser-print', str(SOURCE)], capture_output=True)
    b.run(['git', '-C', str(SOURCE), 'config', 'core.autocrlf', 'false'], capture_output=True)
    b.run(['git', '-C', str(SOURCE), 'add', '.'], capture_output=True)
    b.run(['git', '-C', str(SOURCE), '-c', 'user.name=Codex Release', '-c',
           'user.email=codex-release@localhost', 'commit', '-qm',
           'Company supplier favorites and recent usage on current BP1 source'], capture_output=True)
    commit = b.run(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                   capture_output=True, text=True).stdout.strip()
    b.save(OUT / 'candidate.json', dict(commit=commit, parent=previous['commit'],
        image=previous['image'], files=files, changed_files=added, preserved_files=len(files) - len(added),
        source_directory=str(SOURCE), module=MODULE, module_version=manifest['version'],
        archive_sha256=b.sha(OUT / 'candidate-source.zip')))
    require({r: files[r] for r in added} == approved, 'Composite delta must be exactly the reviewed nine files')
    b.save(OUT / 'integration.json', dict(reviewed_candidate=reviewed['candidate'],
        main_parent=previous['commit'], main_files_preserved=1126, reviewed_files_identical=9))
    print('FROZEN', commit, len(files), 'preserved=' + str(len(files) - len(added)), 'added=' + str(len(added)), flush=True)


def verify_candidate():
    candidate = read_json(OUT / 'candidate.json')
    previous = baseline()
    require(candidate['parent'] == previous['commit'], 'Candidate parent differs')
    require(inventory(SOURCE) == candidate['files'], 'Frozen source inventory/hash differs')
    require(all(candidate['files'].get(r) == h for r, h in previous['files'].items()),
            'An existing baseline source file changed')
    require(all(r.startswith(PREFIX) for r in set(candidate['files']) - set(previous['files'])),
            'Unexpected new source outside partner priority addon')
    reviewed = read_json(REVIEWED)
    require({r: h for r, h in candidate['files'].items() if r.startswith(PREFIX)} ==
            {item['path']: item['sha256'] for item in reviewed['files']}, 'Reviewed PP1 hashes differ')
    require(candidate['module'] == MODULE and candidate['module_version'] == '19.0.1.0.0',
            'Candidate module/version differs')
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


def publish():
    candidate = verify_candidate()
    go = OUT / 'PREDEPLOY-GO.md'
    require(go.is_file() and candidate['commit'] in go.read_text(encoding='utf-8-sig'),
            'PREDEPLOY-GO.md must identify the accepted candidate commit')
    require(not (OUT / 'main-backup.json').exists(), 'Publish already started; inspect evidence before recovery')
    verify_mounts(b.inspect(b.MAIN_CONTAINER), OLD_FOLDER, candidate['image'])
    require(read_sql("SELECT state FROM ir_module_module WHERE name='" + MODULE + "'")
            in ('', 'uninstalled'), 'Partner priority module must not already be installed')
    require(read_sql("SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')")
            == '0', 'Pending module operations exist')
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
        handle.write('PP1 MAIN publish ' + candidate['commit'])
    try:
        b.run(['docker', 'stop', '--timeout', '60', b.MAIN_CONTAINER], capture_output=True)
        b.save(OUT / 'main-backup.json', b.backup(b.MAIN))
        cols = columns()
        require(len(cols) == 367, 'Expected the accepted 367 protected business tables')
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
        b.save(OUT / 'main-preservation.json', dict(protected_tables=len(cols),
            existing_columns_exact=True, existing_rows_exact=True, candidate=candidate['commit'],
            added_schema='Added company-dependent res_partner.baseer_is_favorite JSONB; no business seed or transaction migration'))
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
    require(read_sql("SELECT state || '|' || latest_version FROM ir_module_module WHERE name='baseer_browser_print'")
            == 'installed|19.0.1.0.0', 'Existing browser printing must remain installed')
    require(read_sql("SELECT count(*) FROM res_partner WHERE coalesce(baseer_is_favorite, '{}'::jsonb) <> '{}'::jsonb")
            == '0', 'Unexpected favorite seed in MAIN')
    b.save(OUT / 'runtime.json', dict(http=200, mounts=runtime['Mounts'],
        image=runtime['Config']['Image'], installed=installed, no_pending_modules=True,
        candidate=candidate['commit']))
    print('RUNTIME_VERIFIED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'publish', 'verify-runtime'))
    args = parser.parse_args()
    {'freeze': freeze, 'publish': publish, 'verify-runtime': verify_runtime}[args.command]()
