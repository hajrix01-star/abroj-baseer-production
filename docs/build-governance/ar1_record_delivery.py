import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
out = root / 'docs/releases/2026-09-10-access-roles'
commit = '98f9d4dced9f7a844d3d44e63f89d8d0d8218664'
github = 'c021ceac3a7ce2c980687e1fd46f073a2ab21426'
data = dict(source_commit=commit, github_commit=github, files=1156,
            workflow_run=34482110786, conclusion='success', source_only=True)
(out / 'github.json').write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
index = root / 'docs/architecture/registry/INDEX.md'
header = ('AR1 current MAIN release (2026-09-10): `' + commit + '`, new baseer_access_roles19.0.1.0.0, payroll19.0.1.5.1. '
          'Owner/accountant/cashier presets; cashier own purchase drafts, accountant approval; both approve employee advances through a private screen without salary access. '
          '300 integration checks +12 lifecycle checks +9 Arabic UI evidence groups PASS;367 original business tables and existing user memberships unchanged, no presets assigned automatically. '
          '1156 files/23 changes/1133 preserved. GitHub `' + github + '`;CI34482110786success. '
          '[Handoff](../../releases/2026-09-10-access-roles/HANDOFF.md). Earlier entries historical.\n\n')
old = index.read_text(encoding='utf-8-sig')
assert not old.startswith('AR1 current MAIN release')
index.write_text(header + old, encoding='utf-8')
handoff = out / 'HANDOFF.md'
handoff.write_text(handoff.read_text(encoding='utf-8') + '\nDeployment completed: source `' + commit + '`, MAIN HTTP200 and all preservation checks passed. GitHub `' + github + '` matches all 1,156 source files; workflow34482110786 succeeded. Original users must be assigned the desired preset explicitly by an administrator.\n', encoding='utf-8')
# Clarify schema description only; measured preservation results are unchanged.
p = out / 'main-preservation.json'
preservation = json.loads(p.read_text(encoding='utf-8'))
preservation['added_schema'] = 'Role selector/security metadata, dedicated advance-entry model and private HR payment marker; no existing user assignment or business transaction migration'
p.write_text(json.dumps(preservation, indent=2)+'\n', encoding='utf-8')
print('AR1 delivery recorded')
