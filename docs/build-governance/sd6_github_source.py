"""Prepare the accepted dashboard background source delta for GitHub."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from live1_export import known_secrets

root = Path(__file__).resolve().parents[2]
repo = root / '.local-backups/live1-20260909/repository'
release = root / 'docs/releases/2026-09-10-sales-dashboard-background'
candidate = json.loads((release / 'candidate.json').read_text(encoding='utf-8-sig'))
runtime = json.loads((release / 'runtime.json').read_text(encoding='utf-8-sig'))
assert runtime['candidate'] == candidate['commit']
source = Path(candidate['source_directory'])
old = json.loads((repo / 'release-source.json').read_text(encoding='utf8'))
assert old['source_commit'] == candidate['parent'] == 'de89a85675cb7d36a503618a4fa5fb9faf6ad696'
assert not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain']).strip()
assert subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() == '4f40d7249b477c981d1cc61f637b9c639d0f977f'
assert len(candidate['files']) == 1135 and set(old['files']) == set(candidate['files'])
changed = {rel for rel, digest in candidate['files'].items() if old['files'][rel] != digest}
assert changed == {'custom_addons/baseer_sales_dashboard/__manifest__.py', 'custom_addons/baseer_sales_dashboard/static/src/sales_dashboard.scss'}
secrets = known_secrets()
for rel, digest in candidate['files'].items():
    path = source / rel
    assert path.resolve().is_relative_to(source.resolve()) and not path.is_symlink()
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    assert hashlib.sha256((repo / rel).read_bytes()).hexdigest() == old['files'][rel]
    if rel in changed:
        assert not any(secret in data for secret in secrets)
        assert b'PRIVATE KEY-----' not in data
for rel in changed:
    shutil.copy2(source / rel, repo / rel)
(repo / 'release-source.json').write_bytes((json.dumps(dict(source_commit=candidate['commit'],
    odoo_image=candidate['image'], odoo_major=19, files=candidate['files']), indent=2) + '\n').encode('utf8'))
print('Prepared2 reviewed source changes;1133 baseline files unchanged')
