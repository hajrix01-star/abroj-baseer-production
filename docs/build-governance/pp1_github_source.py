"""Publish preparation for accepted PP1: code only, no data or operational files."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from live1_export import known_secrets

root = Path(__file__).resolve().parents[2]
repo = root / '.local-backups/live1-20260909/repository'
release = root / 'docs/releases/2026-09-10-partner-priority-main'
candidate = json.loads((release / 'candidate.json').read_text(encoding='utf-8-sig'))
assert candidate['commit'] == 'a8d533d67ee4ca3e4a7ce06fc44bc5e459fc192c'
source = Path(candidate['source_directory'])
old = json.loads((repo / 'release-source.json').read_text(encoding='utf8'))
assert old['source_commit'] == '80ab864153b9e337090d5a1286150e7a64ad6319'
assert not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain']).strip()
assert subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() == '216c0a04091ed3bc367317f8967ab5a3ac22c8ce'
assert len(candidate['files']) == 1135 and len(old['files']) == 1126
assert set(old['files']).issubset(candidate['files'])
secrets = known_secrets()
additions = []
for rel, digest in candidate['files'].items():
    path = source / rel
    assert path.resolve().is_relative_to(source.resolve()) and not path.is_symlink()
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    if rel in old['files']:
        assert old['files'][rel] == digest
        assert hashlib.sha256((repo / rel).read_bytes()).hexdigest() == digest
    else:
        assert rel.startswith('custom_addons/baseer_partner_priority/')
        assert not any(secret in data for secret in secrets)
        assert b'PRIVATE KEY-----' not in data
        additions.append(rel)
assert len(additions) == 9
# All checks finish before preparing the clean source checkout.
for rel in additions:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / rel, repo / rel)
(repo / 'release-source.json').write_bytes((json.dumps(dict(source_commit=candidate['commit'],
    odoo_image=candidate['image'], odoo_major=19, files=candidate['files']), indent=2) + '\n').encode('utf8'))
print('Prepared9 approved addon files;1126 baseline files unchanged;source inventory1135')
