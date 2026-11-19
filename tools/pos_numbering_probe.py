"""Read-only runtime/source identity probe; no Odoo ORM or database writes."""
import datetime
import hashlib
import json
import pathlib
import subprocess

def run(args):
    return subprocess.check_output(args, text=True).strip()

result = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'environments': {}}
for label, container, root in (
    ('production', 'baseer-odoo-prod-odoo-1', '/srv/abroj-baseer-production/current'),
    ('qa', 'baseer-qa-refresh-20261023-odoo-1', '/srv/baseer-qa/current'),
):
    info = json.loads(run(['docker', 'inspect', container]))[0]
    entry = {'container': container, 'id': info['Id'], 'image': info['Image'],
             'started_at': info['State']['StartedAt'], 'restart_count': info['RestartCount'],
             'release': str(pathlib.Path(root).resolve()),
             'commit': (pathlib.Path(root) / 'RELEASE_COMMIT').read_text().strip(), 'files': {}}
    entry['version'] = run(['docker', 'exec', container, 'odoo', '--version'])
    for relative in ('static/src/app/utils/devices_identifier_sequence.js',
                     'static/src/app/services/pos_store.js'):
        path = '/usr/lib/python3/dist-packages/odoo/addons/point_of_sale/' + relative
        source = run(['docker', 'exec', container, 'cat', path])
        entry['files'][relative] = {'sha256_text': hashlib.sha256(source.encode()).hexdigest(), 'source': source}
    entry['mounts'] = [{'source': m['Source'], 'destination': m['Destination'], 'rw': m['RW']} for m in info['Mounts']]
    result['environments'][label] = entry
print(json.dumps(result, ensure_ascii=False, indent=2))
