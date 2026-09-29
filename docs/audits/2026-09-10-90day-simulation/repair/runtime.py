"""Isolated same-ledger repair runner; never writes to MAIN."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent
ROOT = HERE.parents[3]
BACK = ROOT / '.local-backups/90day-repair-20260910'
DB = 'baseer_odoo_dev-db-1'
QA = 'baseer_odoo_dev-ic1_qa-1'
ACTIVE = 'baseer_ic1_20260910'
CLONE = 'baseer_sim90_fix_20260911'
ADDONS = '/usr/lib/python3/dist-packages/odoo/addons,/tmp/repair-addons,/mnt/ic1-addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19'
MODULES = ('baseer_cash_categories', 'baseer_pos_summary', 'baseer_financial_register')

def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def sql(db, query, readonly=True):
    assert db in (ACTIVE, CLONE, 'baseer_dev', 'postgres')
    assert readonly or db in (CLONE, 'postgres')
    if readonly:
        query = 'BEGIN READ ONLY; ' + query + '; COMMIT;'
    return run(['docker', 'exec', '-i', DB, 'psql', '-U', 'odoo', '-d', db, '-qAt', '-v', 'ON_ERROR_STOP=1'], input=query, text=True, encoding='utf8', capture_output=True).stdout.strip()

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')

def signatures(db):
    tables = sql(db, "SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'account_%' OR tablename LIKE 'baseer_%' OR tablename LIKE 'hr_%' OR tablename LIKE 'pos_%' OR tablename LIKE 'purchase_%' OR tablename LIKE 'stock_%' OR tablename IN ('res_company','res_users','res_partner','res_groups','res_groups_users_rel')) ORDER BY tablename").splitlines()
    parts = []
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        parts.append("SELECT '" + table + "' AS name,count(*) AS rows,md5(coalesce(string_agg(h,'' ORDER BY h),'')) AS hash FROM (SELECT md5(row_to_json(t)::text) h FROM " + quoted + ' t)s')
    return json.loads(sql(db, 'SELECT json_agg(x ORDER BY name) FROM (' + ' UNION ALL '.join(parts) + ')x'))

def prepare():
    BACK.mkdir(parents=True, exist_ok=True)
    for database, filename in ((ACTIVE, 'qa-before.json'), ('baseer_dev', 'main-before.json')):
        path = HERE / filename
        if not path.exists():
            save(path, signatures(database))
    dump = BACK / 'same-data-before.dump'
    if not dump.exists():
        with dump.open('wb') as handle:
            run(['docker', 'exec', DB, 'pg_dump', '-U', 'odoo', '-Fc', ACTIVE], stdout=handle, stderr=subprocess.PIPE)
    assert sql('postgres', "SELECT count(*) FROM pg_database WHERE datname='" + CLONE + "'") == '0', 'Clone already exists; do not overwrite'
    run(['docker', 'exec', DB, 'createdb', '-U', 'odoo', '-O', 'odoo', '--template=template0', CLONE], capture_output=True)
    with dump.open('rb') as handle:
        run(['docker', 'exec', '-i', DB, 'pg_restore', '-U', 'odoo', '-d', CLONE, '--exit-on-error'], stdin=handle, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    code = "from pathlib import Path; import shutil; root=Path('/var/lib/odoo/filestore').resolve(); src=root/'" + ACTIVE + "'; dst=root/'" + CLONE + "'; assert src.is_dir() and not dst.exists() and src.resolve().parent==root and dst.resolve().parent==root; shutil.copytree(src,dst)"
    run(['docker', 'exec', QA, 'python3', '-c', code], capture_output=True)
    clone = signatures(CLONE)
    assert clone == json.loads((HERE / 'qa-before.json').read_text(encoding='utf8'))
    save(HERE / 'clone.json', {'database': CLONE, 'source': ACTIVE, 'tables_identical': len(clone), 'dump_sha256': hashlib.sha256(dump.read_bytes()).hexdigest()})
    print('CLONE_READY', CLONE, len(clone), flush=True)

def stage(frozen=False):
    run(['docker', 'exec', QA, 'mkdir', '-p', '/tmp/repair-addons', '/tmp/sim90/repair'], capture_output=True)
    source = ROOT
    if frozen:
        candidate = json.loads((HERE / 'candidate.json').read_text(encoding='utf8'))
        source = Path(candidate['source_directory'])
        for name, sha in candidate['files'].items():
            assert hashlib.sha256((source / name).read_bytes()).hexdigest() == sha
    for module in MODULES:
        run(['docker', 'cp', str(source / 'custom_addons' / module), QA + ':/tmp/repair-addons/'], capture_output=True)
    if frozen:
        code = "import hashlib,json; from pathlib import Path; root=Path('/tmp/repair-addons'); print(json.dumps({p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}))"
        observed = json.loads(run(['docker', 'exec', QA, 'python3', '-c', code], capture_output=True, text=True).stdout)
        expected = {name.removeprefix('custom_addons/'): sha for name, sha in candidate['files'].items() if any(name.startswith('custom_addons/' + module + '/') for module in MODULES)}
        assert observed == expected
        save(HERE / 'staged-source.json', {'candidate_sha256': candidate['candidate_sha256'], 'files': observed, 'all_exact': True})
    for script in HERE.glob('*.py'):
        run(['docker', 'cp', str(script), QA + ':/tmp/sim90/repair/' + script.name], capture_output=True)
    print('CODE_AND_TESTS_STAGED', flush=True)

def shell(script, database=CLONE, phase='targeted', live=False):
    assert database in (CLONE, ACTIVE)
    assert Path(script).name == script and script.endswith('.py')
    run(['docker', 'exec', QA, 'mkdir', '-p', '/tmp/sim90/repair'], capture_output=True)
    run(['docker', 'cp', str(HERE / script), QA + ':/tmp/sim90/repair/' + script], capture_output=True)
    if live:
        assert database == ACTIVE
        run(['docker', 'cp', str(HERE / 'candidate.json'), QA + ':/tmp/sim90/repair/candidate.json'], capture_output=True)
    payload = "exec(compile(open('/tmp/sim90/repair/" + script + "','rb').read(),'/tmp/sim90/repair/" + script + "','exec'))\n"
    with (HERE / (script + '.' + database + '.log')).open('wb') as log:
        assert phase in ('targeted', 'coupling')
        addons = ADDONS.replace('/tmp/repair-addons,', '').replace('/mnt/ic1-addons,', '') if live else ADDONS
        process = subprocess.run(['docker', 'exec', '-i', '-e', 'REPAIR_PHASE=' + phase, QA, '/entrypoint.sh', 'odoo', 'shell', '--config=/etc/odoo/odoo.local.conf', '--addons-path=' + addons, '--database=' + database, '--no-http', '--max-cron-threads=0'], input=payload.encode(), stdout=log, stderr=subprocess.STDOUT)
    outputs = run(['docker', 'exec', QA, 'python3', '-c', "from pathlib import Path; print('\\n'.join(p.name for p in Path('/tmp/sim90/repair').glob('*.json')))"], capture_output=True, text=True).stdout.splitlines()
    for name in outputs:
        assert Path(name).name == name
        run(['docker', 'cp', QA + ':/tmp/sim90/repair/' + name, str(HERE / name)], capture_output=True)
    process.check_returncode()
    print('SHELL_COMPLETE', script, database, flush=True)

if __name__ == '__main__':
    if sys.argv[1] == 'prepare': prepare()
    elif sys.argv[1] == 'stage': stage()
    elif sys.argv[1] == 'stage-frozen': stage(frozen=True)
    elif sys.argv[1] == 'shell-live': shell(sys.argv[2], ACTIVE, live=True)
    elif sys.argv[1] == 'shell': shell(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else CLONE, sys.argv[4] if len(sys.argv) > 4 else 'targeted')
