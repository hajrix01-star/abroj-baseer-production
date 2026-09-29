"""Verify final register rows/cards with PostgreSQL-enforced read-only access."""
import json
import subprocess

import fl3_release as r

b = r.b
runtime = r.read_json(r.OUT / 'runtime.json')
assert runtime['http'] == 200 and runtime['installed'] == 'installed|' + r.VERSION
assert b.MAIN == 'baseer_dev'
script = b.ROOT / 'docs/build-governance/fl3_smoke.py'
result = subprocess.run(['docker', 'exec', '-i', b.MAIN_CONTAINER, '/entrypoint.sh', 'odoo', 'shell',
    '--config=/etc/odoo/odoo.local.conf',
    '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
    '--database=' + b.MAIN, '--no-http', '--max-cron-threads=0'], input=script.read_bytes(), capture_output=True)
(r.OUT / 'main-smoke.log').write_bytes(result.stdout + result.stderr)
result.check_returncode()
line = next(line for line in result.stdout.decode().splitlines() if line.startswith('FL3_SMOKE_JSON '))
report = json.loads(line.removeprefix('FL3_SMOKE_JSON '))
assert report['status'] == 'PASS' and report['database_enforced_read_only'] and report['rollback']
b.save(r.OUT / 'main-smoke.json', report)
print('MAIN read-only register smoke:', len(report['checks']), 'PASS')
