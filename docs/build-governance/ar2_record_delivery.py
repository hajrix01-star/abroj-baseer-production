import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
out = root / 'docs/releases/2026-09-10-access-roles-user-form'
repo = root / '.local-backups/live1-20260909/repository'
candidate = json.loads((out / 'candidate.json').read_text(encoding='utf-8'))
runtime = json.loads((out / 'runtime.json').read_text(encoding='utf-8'))
assert runtime['candidate'] == candidate['commit'] and runtime['http'] == 200
github = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
runs = json.loads(subprocess.check_output(['gh','run','list','--repo','hajrix01-star/Odoo-Baseer','--limit','5','--json','databaseId,headSha,status,conclusion,url'],text=True))
run = next(r for r in runs if r['headSha'] == github)
assert run['conclusion'] == 'success'
data = dict(source_commit=candidate['commit'], github_commit=github, files=1156, source_only=True, workflow=run)
(out / 'github.json').write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
index = root / 'docs/architecture/registry/INDEX.md'
old = index.read_text(encoding='utf-8-sig')
assert not old.startswith('AR2 current MAIN release')
header = (f"AR2 current MAIN release (2026-09-10): `{candidate['commit']}`, roles19.0.1.0.1. "
          "Fixes accountant/cashier saves with native In Odoo notifications; preserves preference across role changes and previews role grants immediately. "
          "55 focused rollback checks +5 Arabic UI checks PASS.368 business tables and current memberships/presets unchanged. "
          f"1156files/3changes/1153preserved; GitHub `{github}`;CI{run['databaseId']}success. "
          "[Handoff](../../releases/2026-09-10-access-roles-user-form/HANDOFF.md). Earlier entries historical.\n\n")
index.write_text(header+old,encoding='utf-8')
handoff=out/'HANDOFF.md'
handoff.write_text(handoff.read_text(encoding='utf-8')+f"\nDeployed original source `{candidate['commit']}`; HTTP200,368 protected tables and current security assignments exactly preserved. GitHub `{github}` matches accepted source; CI{run['databaseId']} succeeded.\n",encoding='utf-8')
print('AR2 delivery recorded',github)
