"""Read-only release/runtime inventory for the accounting audit; writes evidence only."""
import datetime
import hashlib
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent
manifest = json.loads((ROOT / 'docs/releases/2026-09-09-pos-payment-seed/candidate.json').read_text(encoding='utf-8-sig'))
candidate = ROOT / '.local-backups/pos-payment-seed-20260909/candidate'
differences = []
for name, expected in manifest['files'].items():
    path = candidate / name
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    if actual != expected:
        differences.append({'path': name, 'expected': expected, 'actual': actual})

def command(args):
    return subprocess.check_output(args, text=True, encoding='utf-8').strip()

runtime = json.loads(command(['docker', 'inspect', 'baseer_odoo_dev-odoo-1']))[0]
sql = """BEGIN READ ONLY;
SELECT json_build_object(
 'database',current_database(),
 'companies',(SELECT json_agg(json_build_object('id',id,'name',name,'currency_id',currency_id,'chart_template',chart_template)) FROM res_company),
 'installed_modules',(SELECT json_agg(json_build_object('name',name,'version',latest_version) ORDER BY name) FROM ir_module_module WHERE state='installed'),
 'pending_modules',(SELECT json_agg(json_build_object('name',name,'state',state)) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')),
 'moves',(SELECT count(*) FROM account_move),
 'move_lines',(SELECT count(*) FROM account_move_line),
 'payments',(SELECT count(*) FROM account_payment));
ROLLBACK;"""
rows = command(['docker', 'exec', 'baseer_odoo_dev-db-1', 'psql', '-U', 'odoo', '-d', 'baseer_dev', '-At', '-c', sql]).splitlines()
db = json.loads(next(row for row in rows if row.startswith('{')))
evidence = {
    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'commit': manifest['commit'],
    'candidate_path': str(candidate),
    'files_checked': len(manifest['files']),
    'hash_differences': differences,
    'runtime': {'image': runtime['Config']['Image'], 'state': runtime['State']['Status'],
        'source_mounts': [dict(destination=m['Destination'], source=m['Source'], writable=m['RW']) for m in runtime['Mounts'] if m['Destination'].startswith('/mnt/')]},
    'database': db,
    'mode': 'Read-only source inspection and BEGIN READ ONLY SQL; no operational writes or tests.'
}
(OUT / 'provenance.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'files_checked':len(manifest['files']), 'hash_differences':differences,'installed_modules':len(db['installed_modules']),'pending_modules':db['pending_modules'],'moves':db['moves'],'move_lines':db['move_lines'],'payments':db['payments']},ensure_ascii=False))
