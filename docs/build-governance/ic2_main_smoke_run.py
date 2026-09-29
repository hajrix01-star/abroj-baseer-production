"""Run the read-only installed-view check against the original after R2 recovery."""
import json
import subprocess
from pathlib import Path
import ic2_recovery as recovery

r, b = recovery.r, recovery.b
assert r.read_json(r.OUT / 'runtime.json')['http'] == 200
script = b.ROOT / 'docs/build-governance/ic2_main_smoke.py'
result = subprocess.run(['docker', 'exec', '-i', b.MAIN_CONTAINER, '/entrypoint.sh', 'odoo', 'shell',
    '--config=/etc/odoo/odoo.local.conf',
    '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
    '--database=' + b.MAIN, '--no-http', '--max-cron-threads=0'], input=script.read_bytes(), capture_output=True)
(r.OUT / 'main-smoke.log').write_bytes(result.stdout + result.stderr)
if result.returncode:
    print(result.stderr.decode(errors='replace')[-4000:])
result.check_returncode()
report = next(json.loads(line) for line in result.stdout.decode().splitlines() if line.startswith('{"status"'))
assert report['status'] == 'PASS'
b.save(r.OUT / 'main-smoke.json', report)
print(json.dumps(report))
