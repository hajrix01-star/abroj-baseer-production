"""Use the original's existing native administrator when no owner preset is assigned."""
import json
import hashlib
import shutil
import subprocess

import fl3_release as r

b = r.b
r.verify_runtime()
assert b.MAIN == 'baseer_dev'
script = (r.OUT / 'fl3_smoke.py').read_text(encoding='utf8')
needle = "owner = env['res.users'].search([('baseer_access_role', '=', 'owner'), ('active', '=', True)], limit=1)"
assert script.count(needle) == 1
script = script.replace(needle, needle + "\nif not owner and env.cr.dbname == 'baseer_dev':\n    owner = env.ref('base.user_admin')\nassert owner.active\nprint('FL3_ACTOR_JSON ' + json.dumps({'id': owner.id, 'role': owner.baseer_access_role, 'native_xmlid': 'base.user_admin' if owner == env.ref('base.user_admin') else None, 'company_ids': owner.company_ids.ids, 'superuser': False}))")
failed = r.OUT / 'main-smoke.log'
if failed.exists() and not (r.OUT / 'main-smoke.owner-preset-missing.log').exists():
    shutil.copy2(failed, r.OUT / 'main-smoke.owner-preset-missing.log')
result = subprocess.run(['docker', 'exec', '-i', b.MAIN_CONTAINER, '/entrypoint.sh', 'odoo', 'shell',
    '--config=/etc/odoo/odoo.local.conf',
    '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
    '--database=' + b.MAIN, '--no-http', '--max-cron-threads=0'], input=script.encode(), capture_output=True)
(r.OUT / 'main-smoke.log').write_bytes(result.stdout + result.stderr)
if result.returncode:
    print(result.stderr.decode(errors='replace')[-1800:])
result.check_returncode()
lines = result.stdout.decode().splitlines()
report = json.loads(next(x.removeprefix('FL3_SMOKE_JSON ') for x in lines if x.startswith('FL3_SMOKE_JSON ')))
actor = json.loads(next(x.removeprefix('FL3_ACTOR_JSON ') for x in lines if x.startswith('FL3_ACTOR_JSON ')))
assert report['status'] == 'PASS' and report['database_enforced_read_only'] and report['rollback']
report['actor'] = actor
report['selector_note'] = 'Existing native administrator used because MAIN has no owner preset; no roles assigned.'
report['runner_sha256'] = b.sha(b.ROOT / 'docs/build-governance/fl3_main_readonly.py')
report['executed_script_sha256'] = hashlib.sha256(script.encode()).hexdigest()
b.save(r.OUT / 'main-smoke.json', report)
shutil.copy2(b.ROOT / 'docs/build-governance/fl3_main_readonly.py', r.OUT / 'fl3_main_readonly.py')
print('MAIN read-only register smoke:', len(report['checks']), 'PASS; actor', actor['id'])
