"""Freeze WS4 on accepted WS3, then promote with coherent backup/projection checks."""
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
import environment_backups as b

OUT = b.ROOT / 'docs/releases/2026-09-09-schedule-edit'
BACK = b.ROOT / '.local-backups/schedule-edit-20260909'
SOURCE = BACK / 'candidate'
OLD = b.ROOT / '.local-backups/duration-display-20260909/candidate'
MODULE = 'baseer_work_schedule'
OUT.mkdir(parents=True, exist_ok=True)


def freeze():
    previous = json.loads((b.ROOT / 'docs/releases/2026-09-09-duration-display/candidate.json').read_text())
    assert all(b.sha(OLD / rel) == h for rel, h in previous['files'].items())
    SOURCE.mkdir(parents=True, exist_ok=False)
    for rel in previous['files']:
        dest = SOURCE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OLD / rel, dest)
    for path in (b.ROOT / 'custom_addons' / MODULE).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            dest = SOURCE / path.relative_to(b.ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    files = {p.relative_to(SOURCE).as_posix(): b.sha(p) for p in SOURCE.rglob('*') if p.is_file()}
    changed = [rel for rel, h in files.items() if previous['files'].get(rel) != h]
    assert all(rel.startswith('custom_addons/' + MODULE + '/') for rel in changed)
    with zipfile.ZipFile(OUT / 'candidate-source.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files): z.write(SOURCE / rel, rel)
    b.run(['git','init','--initial-branch=codex/ws4-schedule-edit',str(SOURCE)], capture_output=True)
    b.run(['git','-C',str(SOURCE),'config','core.autocrlf','false'], capture_output=True)
    b.run(['git','-C',str(SOURCE),'add','.'], capture_output=True)
    b.run(['git','-C',str(SOURCE),'-c','user.name=Codex Release','-c','user.email=codex-release@localhost','commit','-qm','WS4 edit schedule templates with dated employee history'], capture_output=True)
    commit = b.run(['git','-C',str(SOURCE),'rev-parse','HEAD'], capture_output=True,text=True).stdout.strip()
    b.save(OUT / 'candidate.json', dict(commit=commit, parent=previous['commit'], image=previous['image'], files=files,
        changed_files=changed, source_directory=str(SOURCE), archive_sha256=b.sha(OUT / 'candidate-source.zip')))
    for name in ('ws4_checks.json', 'ws4-ui.json', 'ws4_concurrency.json'):
        shutil.copy2(b.ROOT / 'docs/build-governance' / name, OUT / name)
    print('FROZEN', commit, len(files), len(changed), flush=True)


def columns():
    return json.loads(b.sql(b.MAIN, "SELECT json_object_agg(table_name,cols) FROM (SELECT table_name,json_agg(column_name ORDER BY ordinal_position) cols FROM information_schema.columns WHERE table_schema='public' AND (table_name LIKE 'account_%' OR table_name LIKE 'baseer_%' OR table_name LIKE 'hr_%' OR table_name LIKE 'pos_%' OR table_name LIKE 'resource_%' OR table_name IN ('res_company','res_partner')) GROUP BY table_name)t"))


def projection(cols):
    parts = []
    for table, names in sorted(cols.items()):
        fields = ','.join('"' + n.replace('"', '""') + '"' for n in names)
        parts.append("SELECT '%s' name,count(*) rows,md5(coalesce(string_agg(h,'' ORDER BY h),'')) hash FROM (SELECT md5(row_to_json(t)::text) h FROM (SELECT %s FROM \"%s\")t)s" % (table, fields, table))
    return json.loads(b.sql(b.MAIN, 'SELECT json_agg(t) FROM (' + ' UNION ALL '.join(parts) + ')t'))


def publish():
    assert (OUT / 'PREDEPLOY-GO.md').is_file()
    candidate = json.loads((OUT / 'candidate.json').read_text())
    assert all(b.sha(SOURCE / r) == h for r, h in candidate['files'].items())
    inventory = {p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    assert inventory == set(candidate['files']), 'Frozen source inventory differs'
    assert b.sha(OUT / 'candidate-source.zip') == candidate['archive_sha256']
    b.run(['docker','stop','--timeout','60',b.MAIN_CONTAINER], capture_output=True)
    b.save(OUT / 'main-backup.json', b.backup(b.MAIN))
    cols = columns()
    before = projection(cols)
    b.save(OUT / 'protected-columns.json', cols)
    b.save(OUT / 'protected-before.json', before)
    for filename in ('compose.yaml','compose.main-release.yaml'):
        path = b.ROOT / filename
        shutil.copy2(path, BACK / (filename + '.before'))
        content = path.read_text(encoding='utf8')
        assert content.count('./.local-backups/duration-display-20260909/candidate/') == 3
        path.write_text(content.replace('./.local-backups/duration-display-20260909/candidate/', './.local-backups/schedule-edit-20260909/candidate/'), encoding='utf8')
    with (OUT / 'main-install.log').open('wb') as log:
        b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','run','--rm','--no-deps','-T','odoo','odoo',
            '--config=/etc/odoo/odoo.local.conf',
            '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
            '--database='+b.MAIN,'--update='+MODULE,'--stop-after-init','--no-http','--max-cron-threads=0'], stdout=log, stderr=log)
    after = projection(cols)
    b.save(OUT / 'protected-after.json', after)
    assert before == after, 'Existing business rows changed; keep original stopped for investigation'
    b.save(OUT / 'main-preservation.json', dict(protected_tables=len(cols), existing_columns_exact=True, existing_rows_exact=True,
        added_schema='Additive calendar revision metadata and transient edit fields; existing business rows and old columns unchanged', candidate=candidate['commit']))
    helper = b.ROOT / 'docs/build-governance/environment_backups.py'
    shutil.copy2(helper, BACK / 'environment_backups.py.before')
    helper.write_text(helper.read_text(encoding='utf8').replace('2026-09-09-duration-display','2026-09-09-schedule-edit')
        .replace('duration-display-20260909','schedule-edit-20260909'), encoding='utf8')
    b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','up','-d','--no-deps','odoo'], capture_output=True)
    for attempt in range(30):
        try:
            if urllib.request.urlopen('http://127.0.0.1:18069/web/login', timeout=3).status == 200: break
        except OSError: pass
        time.sleep(2)
    else: raise RuntimeError('MAIN healthcheck failed')
    verify_runtime()
    print('PUBLISHED', flush=True)


def verify_runtime():
    candidate = json.loads((OUT / 'candidate.json').read_text())
    assert urllib.request.urlopen('http://127.0.0.1:18069/web/login', timeout=5).status == 200
    runtime = b.inspect(b.MAIN_CONTAINER)
    assert runtime['Config']['Image'] == candidate['image'], 'Image differs from accepted candidate'
    for destination, folder in [('/mnt/baseer-addons', 'custom_addons'), ('/mnt/extra-addons', 'custom_addons'), ('/mnt/third-party-addons', 'third_party_addons')]:
        mount = next(m for m in runtime['Mounts'] if m['Destination'] == destination)
        assert not mount['RW'] and mount['Source'].replace('\\', '/').lower().endswith('/schedule-edit-20260909/candidate/' + folder), mount
    installed = b.sql(b.MAIN, "SELECT state || '|' || latest_version FROM ir_module_module WHERE name='baseer_work_schedule'")
    assert installed == 'installed|19.0.1.1.0', installed
    assert b.sql(b.MAIN, "SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')") == '0'
    b.save(OUT / 'runtime.json', dict(http=200, mounts=runtime['Mounts'], image=runtime['Config']['Image'], installed=installed, no_pending_modules=True, candidate=candidate['commit']))
    print('RUNTIME_VERIFIED', flush=True)


if __name__ == '__main__':
    {'freeze': freeze, 'publish': publish, 'verify-runtime': verify_runtime}[sys.argv[1]]()


