"""Local Odoo backups and narrowly scoped, authorized rehearsal retirement.

Run with Python 3 on the Docker host. No passwords are written to logs.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
BACK = ROOT / '.local-backups/environment-maintenance'
OUT = ROOT / 'docs/operations/2026-09-09-environments'
DB = 'baseer_odoo_dev-db-1'
MAIN_CONTAINER = 'baseer_odoo_dev-odoo-1'
MAIN = 'baseer_dev'
QA = 'baseer_reports_qa_20260907'
OLD = ('baseer_payroll_eval_20260908', 'baseer_promotion_rehearsal_20260908', 'baseer_release_rehearsal_20260907')
RETIRED = ('baseer_odoo_dev-pb2_review-1', 'baseer_odoo_dev-fa2_review-1', 'baseer_odoo_dev-promotion_rehearsal-1', 'baseer_odoo_dev-reports_rehearsal-1')
RESTORE = 'baseer_backup_verify_20260909'

def run(args, **kw):
    return subprocess.run(args, check=True, **kw)

def sql(database, query):
    return run(['docker', 'exec', '-i', DB, 'psql', '-U', 'odoo', '-d', database, '-At', '-v', 'ON_ERROR_STOP=1'], input=query, capture_output=True, text=True, encoding='utf8').stdout.strip()

def inspect(name):
    return json.loads(run(['docker', 'inspect', name], capture_output=True, text=True).stdout)[0]

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def signatures(database):
    tables = sql(database, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    parts = []
    for table in tables:
        q = '"' + table.replace('"', '""') + '"'
        parts.append("SELECT '" + table.replace("'", "''") + "' AS name,count(*) AS rows,md5(coalesce(string_agg(h,'' ORDER BY h),'')) AS hash FROM (SELECT md5(row_to_json(t)::text) h FROM " + q + ' t)s')
    return sorted(json.loads(sql(database, 'SELECT json_agg(x) FROM (' + ' UNION ALL '.join(parts) + ')x')), key=lambda row: row['name'])

def archive_filestore(database, path):
    # A read-only mount of the existing volume works even while MAIN is stopped.
    image = inspect(MAIN_CONTAINER)['Config']['Image']
    script = "import tarfile,sys; from pathlib import Path; p=Path('/var/lib/odoo/filestore')/sys.argv[1]; assert p.is_dir(); t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); t.add(p,arcname=p.name); t.close()"
    with path.open('wb') as f:
        run(['docker', 'run', '--rm', '--network', 'none', '--volumes-from', MAIN_CONTAINER + ':ro', '--entrypoint', 'python3', image, '-c', script, database], stdout=f, stderr=subprocess.PIPE)

def verify_archive(database, path):
    refs = json.loads(sql(database, "SELECT coalesce(json_agg(t),'[]') FROM (SELECT store_fname,checksum,file_size FROM ir_attachment WHERE store_fname IS NOT NULL)t"))
    required = {database + '/' + r['store_fname']: r for r in refs}
    assert all(required[database + '/' + r['store_fname']] == r for r in refs), 'Conflicting attachment metadata'
    found = set()
    with tarfile.open(path, 'r|gz') as tar:
        for member in tar:
            p = PurePosixPath(member.name)
            assert not p.is_absolute() and '..' not in p.parts and p.parts[0] == database
            assert member.isfile() or member.isdir(), 'Unexpected archive link'
            if member.name in required:
                ref = required[member.name]
                assert member.isfile() and member.size == ref['file_size']
                with tar.extractfile(member) as f:
                    assert hashlib.file_digest(f, 'sha1').hexdigest() == ref['checksum']
                found.add(member.name)
    assert found == set(required), 'Attachment file missing'
    return len(refs)

def restore_check(dest, expected, metadata):
    assert sql('postgres', "SELECT count(*) FROM pg_database WHERE datname='" + RESTORE + "'") == '0'
    run(['docker', 'exec', DB, 'createdb', '-U', 'odoo', '-O', 'odoo', '--template=template0', '--lc-collate=' + metadata['datcollate'], '--lc-ctype=' + metadata['datctype'], RESTORE], capture_output=True)
    try:
        with (dest / 'database.dump').open('rb') as f:
            run(['docker', 'exec', '-i', DB, 'pg_restore', '-U', 'odoo', '--no-owner', '--exit-on-error', '-d', RESTORE], stdin=f, capture_output=True)
        actual = signatures(RESTORE)
        if actual != expected:
            save(dest / 'restore-difference.json', {'expected': expected, 'actual': actual})
        assert actual == expected, 'Restored rows differ'
    finally:
        run(['docker', 'exec', DB, 'dropdb', '-U', 'odoo', RESTORE], capture_output=True)

def backup(database, restore=False):
    assert database in (MAIN,) + OLD
    assert sql('postgres', "SELECT count(*) FROM pg_stat_activity WHERE datname='" + database + "'") == '0', 'Database has active clients; do not back up/delete concurrently'
    dest = BACK / (database + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    dest.mkdir(parents=True, exist_ok=False)
    expected = signatures(database)
    metadata = json.loads(sql('postgres', "SELECT row_to_json(d) FROM (SELECT datcollate,datctype,pg_encoding_to_char(encoding) AS encoding FROM pg_database WHERE datname='" + database + "')d"))
    save(dest / 'database-metadata.json', metadata)
    with (dest / 'database.dump').open('wb') as f:
        run(['docker', 'exec', DB, 'pg_dump', '-U', 'odoo', '-Fc', database], stdout=f, stderr=subprocess.PIPE)
    archive_filestore(database, dest / 'filestore.tar.gz')
    assert signatures(database) == expected, 'Database changed during backup'
    references = verify_archive(database, dest / 'filestore.tar.gz')
    # Parse the entire dump TOC before considering the snapshot usable.
    with (dest / 'database.dump').open('rb') as f:
        run(['docker', 'exec', '-i', DB, 'pg_restore', '--list'], stdin=f, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if restore:
        restore_check(dest, expected, metadata)
    save(dest / 'rows.json', expected)
    for rel in ('compose.yaml', 'compose.reports-qa.yaml', '.env', 'config/odoo.local.conf'):
        if (ROOT / rel).is_file():
            shutil.copy2(ROOT / rel, dest / Path(rel).name)
    candidate = ROOT / '.local-backups/procurement-production-20260912/candidate-source.tar.gz'
    if database == MAIN:
        shutil.copy2(candidate, dest / candidate.name)
    evidence = {'database': database, 'directory': str(dest), 'utc': datetime.now(timezone.utc).isoformat(), 'coherent_no_clients': True, 'table_count': len(expected), 'database_restore_verified': restore, 'attachment_references_verified': references, 'files': {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in dest.iterdir() if p.is_file()}}
    save(dest / 'manifest.json', evidence)
    print('BACKUP_VERIFIED', database, references, flush=True)
    return evidence

def backup_main(restore=False):
    runtime = inspect(MAIN_CONTAINER)
    mount = next(m for m in runtime['Mounts'] if m['Destination'] == '/mnt/baseer-addons')
    candidate = ROOT / '.local-backups/procurement-production-20260912/candidate-source.tar.gz'
    expected_sha256 = '7bb95424379485062db60bc776de364020829febcd80417230ee412b50116588'
    assert not mount['RW'] and mount['Source'].replace('\\', '/').endswith('/.local-backups/procurement-production-20260912/candidate-v1/custom_addons'), 'Update backup source mapping after a new release'
    assert runtime['Config']['Image'] == 'odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd'
    assert sha(candidate) == expected_sha256
    was_running = runtime['State']['Running']
    try:
        if was_running:
            run(['docker', 'stop', '--time', '60', MAIN_CONTAINER], capture_output=True)
        evidence = backup(MAIN, restore)
    finally:
        if was_running:
            run(['docker', 'start', MAIN_CONTAINER], capture_output=True)
            for attempt in range(30):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18069/web/login', timeout=3) as response:
                        if response.status == 200: break
                except OSError:
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('Backup finished but MAIN health check failed after restart')
    save(OUT / 'latest-main-backup.json', evidence)

def prepare_cleanup():
    assert all(not inspect(c)['State']['Running'] for c in RETIRED)
    evidence = [backup(db, restore=True) for db in OLD]
    save(OUT / 'retired-backups.json', evidence)

def cleanup():
    evidence = json.loads((OUT / 'retired-backups.json').read_text(encoding='utf8'))
    assert [e['database'] for e in evidence] == list(OLD)
    assert all(not inspect(c)['State']['Running'] for c in RETIRED)
    for e in evidence:
        db = e['database']; dest = Path(e['directory']).resolve()
        assert dest.is_relative_to(BACK.resolve()) and e['database_restore_verified']
        assert all(sha(dest / name) == meta['sha256'] for name, meta in e['files'].items())
        assert sql('postgres', "SELECT count(*) FROM pg_stat_activity WHERE datname='" + db + "'") == '0'
        assert signatures(db) == json.loads((dest / 'rows.json').read_text(encoding='utf8'))
        assert verify_archive(db, dest / 'filestore.tar.gz') == e['attachment_references_verified']
    for c in RETIRED:
        state = inspect(c)
        assert state['Config']['Labels']['com.docker.compose.project'] == 'baseer_odoo_dev'
        assert not state['State']['Running']
        run(['docker', 'rm', c], capture_output=True)  # No volume removal.
    for db in OLD:
        run(['docker', 'exec', DB, 'dropdb', '-U', 'odoo', db], capture_output=True)  # No FORCE.
        # Exact allowlist inside one Linux process, never a computed host deletion.
        script = "import pathlib,shutil,sys; allowed=" + repr(OLD) + "; name=sys.argv[1]; assert name in allowed; root=pathlib.Path('/var/lib/odoo/filestore').resolve(); p=root/name; assert not p.is_symlink() and p.resolve().parent==root; shutil.rmtree(p)"
        run(['docker', 'exec', MAIN_CONTAINER, 'python3', '-c', script, db], capture_output=True)
    databases = sql('postgres', "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY datname").splitlines()
    assert databases == sorted([MAIN, QA])
    save(OUT / 'cleanup-result.json', {'removed_databases': list(OLD), 'removed_containers': list(RETIRED), 'remaining_odoo_databases': databases, 'volumes_removed': False, 'utc': datetime.now(timezone.utc).isoformat()})
    print('CLEANUP_VERIFIED: original and QA only', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup-main', 'prepare-cleanup', 'cleanup'])
    parser.add_argument('--restore-test', action='store_true')
    args = parser.parse_args()
    BACK.mkdir(parents=True, exist_ok=True)
    lock = BACK / 'maintenance.lock'
    with lock.open('x') as f:
        f.write(datetime.now(timezone.utc).isoformat())
    try:
        if args.action == 'backup-main': backup_main(args.restore_test)
        elif args.action == 'prepare-cleanup': prepare_cleanup()
        else: cleanup()
    finally:
        lock.unlink()
