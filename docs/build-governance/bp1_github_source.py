"""Prepare clean accepted BP1 source update; never stage the workspace root."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from live1_export import known_secrets

root = Path(__file__).resolve().parents[2]
repo = root / '.local-backups/live1-20260909/repository'
candidate = json.loads((root / 'docs/releases/2026-09-09-browser-print/candidate.json').read_text())
source = Path(candidate['source_directory'])
old = json.loads((repo / 'release-source.json').read_text())
assert old['source_commit'] == candidate['parent']
assert not subprocess.check_output(['git','-C',str(repo),'status','--porcelain']).strip()
assert subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip() == '5ba4857f69c389fc81ecbd1e5559e2758622eb9d'
secrets = known_secrets()
for rel, digest in candidate['files'].items():
    data = (source / rel).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    if rel in old['files']:
        assert old['files'][rel] == digest
        assert hashlib.sha256((repo / rel).read_bytes()).hexdigest() == digest
    else:
        assert rel.startswith('custom_addons/baseer_browser_print/')
        assert not any(secret in data for secret in secrets)
        assert b'PRIVATE KEY-----' not in data
        (repo / rel).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source / rel,repo / rel)
(repo / 'release-source.json').write_text(json.dumps(dict(source_commit=candidate['commit'],
    odoo_image=candidate['image'],odoo_major=19,files=candidate['files']),indent=2)+'\n',encoding='utf8')
print('BP1 clean source ready; no database, attachments or private evidence included')
