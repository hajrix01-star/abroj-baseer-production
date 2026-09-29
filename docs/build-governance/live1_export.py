"""Export only the accepted release source for the user-selected GitHub repo.

No remote operations, database access, cleanup, or changes to running services.
Never stage the working root: its private operational evidence is out of scope.
"""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / 'docs/releases/2026-09-09-sales-dashboard-application-share/candidate.json'
OUT = ROOT / '.local-backups/live1-20260909/repository'
EXPECTED = '1108f2a8fc0edee2f61d728135feee02590a8f46'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def known_secrets():
    # Local values are comparison-only: never exported or printed.
    found = set()
    for path in (ROOT / '.env', ROOT / 'config/odoo.local.conf'):
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if '=' not in line or line.lstrip().startswith('#'):
                    continue
                key, value = line.split('=', 1)
                value = value.strip().strip('\"\'')
                if re.search(r'pass|secret|token|private_key', key, re.I) and len(value) >= 8:
                    found.add(value.encode())
    return found


def main():
    manifest = json.loads(RELEASE.read_text(encoding='utf-8-sig'))
    assert manifest['commit'] == EXPECTED and len(manifest['files']) == 1118
    source = Path(manifest['source_directory']).resolve()
    assert not OUT.exists(), 'Export already exists; do not overwrite or delete it'
    payload = {}
    secrets = known_secrets()
    for rel, digest in manifest['files'].items():
        p = PurePosixPath(rel)
        assert not p.is_absolute() and '..' not in p.parts and '\\' not in rel
        assert p.parts[0] in ('custom_addons', 'third_party_addons')
        target = source.joinpath(*p.parts)
        assert target.resolve().is_relative_to(source) and not target.is_symlink()
        assert p.name != '.env' and not any(x in p.parts for x in ('.git', '__pycache__'))
        data = target.read_bytes()
        assert sha(data) == digest, 'Source differs: ' + rel
        assert not any(secret in data for secret in secrets), 'Local credential found in: ' + rel
        assert not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data), 'Private key in: ' + rel
        payload[rel] = data
    clean_manifest = {'source_commit': EXPECTED, 'odoo_image': manifest['image'],
                      'odoo_major': 19, 'files': manifest['files']}
    payload['release-source.json'] = (json.dumps(clean_manifest, indent=2) + '\n').encode()
    payload['.gitignore'] = b'''# Source-only repository: private runtime and business data never belong here.
.env
.env.*
!.env.example
*.pem
*.key
*.dump
*.sql
*.backup
*.log
__pycache__/
*.pyc
.local-backups/
filestore/
backups/
odoo-data/
postgres-data/
'''
    payload['README.md'] = '''# بصير — Odoo Baseer

كود التخصيصات المعتمد لنظام بصير على **Odoo 19 Community**.
يشمل14موديولًا مخصصًا والاعتماديات الخارجية الموجودة في الإصدار المعتمد.
المستودع مخصص للكود؛ بيانات الموظفين والرواتب والعمليات والمرفقات وكلمات المرور ليست ضمنه.

## الإصدار الحالي

- أصل المصدر: `1108f2a8fc0edee2f61d728135feee02590a8f46`.
- ملف `release-source.json` يثبت1118ملفًا ببصمات SHA256 وصورة Odoo المعتمدة.
- الإضافات المخصصة: `custom_addons`.
- الاعتماديات المستخدمة: `third_party_addons/erp_heritage_19` و`third_party_addons/odoomates_19`.
- التراخيص محفوظة في ملفات كل موديول. الإضافات الخارجية تبقى ملكًا لأصحابها وفق تراخيصها.

## التحقق

```sh
python ops/verify_source.py
```

GitHub Actions يشغّل فحص المصدر عند رفع الكود. هذا فحص سلامة ملفات وصياغة؛ لا يدّعي اختبار تثبيت أودو أو جاهزية السيرفر.

## النقل إلى السيرفر

يلزم نقل قاعدة البيانات الأصلية وملفات filestore بقناة خاصة منفصلة، ثم مطابقتها قبل فتح النظام.
السيرفر والدومين لم يحددا بعد، والنشر الحي التلقائي **غير مفعّل** في هذه النسخة.
راجع [خطة النشر والتحديثات](ops/DEPLOYMENT.md).

The repository contains accepted source only. A fresh install does not reproduce private database configuration or business records. Production migration and deployment require the target-specific setup and checks described in the runbook.
'''.encode('utf8')
    payload['ops/DEPLOYMENT.md'] = '''# Live migration and future updates

Status: source preparation only; no live server or automatic deployment is configured.

## First migration

1. Identify host, SSH access, domain, resources and an empty target database. Do not overwrite an existing database.
2. Prepare the accepted Odoo19 image and compatible PostgreSQL16. Use a restricted Odoo database owner, separate from bootstrap credentials. Keep secrets outside Git.
3. Configure HTTPS, proxy_mode, exact dbfilter, disabled database listing, private database ports and websocket forwarding. Choose workers only after measuring host resources.
4. Freeze local original writes briefly; take a fresh coherent database and filestore backup. Transfer privately with hashes. Never send backup archives or environment files to GitHub.
5. Restore into an isolated target; validate employees, companies, payroll configuration, all business-table projections, attachments and application flows. Configure server URL and external integrations intentionally.
6. Enable traffic only after successful checks. The live database then becomes authoritative. The old local original is retained as a backup and must not accept divergent business entries.

## Future code updates

Develop locally -> validate in QA -> freeze accepted release -> update code and release-source.json together -> push to GitHub -> CI -> serialized deployment to the identified server.

Each deployment must use the exact passing commit, take a coherent LIVE backup, upgrade affected modules and verify health and critical flows. Normal code updates must never restore a local database over live data. Database migrations are versioned and reviewed. No blind automatic code downgrade after a schema migration; recover using compatible source and its corresponding backup when appropriate.

Production workflow remains absent until host/domain, trusted SSH host key, deployment identity, secrets and target paths are known. Configure private off-host scheduled backups, retention, restore verification and failure notifications before launch. Do not publish edits on every filesystem save.

Official references:
- https://www.odoo.com/documentation/19.0/administration/on_premise/deploy.html
- https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments
'''.encode()
    payload['ops/verify_source.py'] = '''"""Verify accepted source integrity; no imports of Odoo or business data."""
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'release-source.json').read_text(encoding='utf8'))
expected = manifest['files']
assert expected and manifest['odoo_major'] == 19
actual = {p.relative_to(root).as_posix() for folder in ('custom_addons', 'third_party_addons')
          for p in (root / folder).rglob('*') if p.is_file()
          and '__pycache__' not in p.parts and p.suffix != '.pyc'}
assert actual == set(expected), 'Source file inventory differs'
for rel, digest in expected.items():
    parts = PurePosixPath(rel)
    assert not parts.is_absolute() and '..' not in parts.parts and parts.parts[0] in ('custom_addons', 'third_party_addons')
    path = root.joinpath(*parts.parts)
    assert not path.is_symlink() and path.resolve().is_relative_to(root)
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest, 'Hash differs: ' + rel
    if path.suffix == '.py':
        ast.parse(data.decode('utf-8-sig'), filename=rel)
    elif path.suffix == '.xml':
        ET.fromstring(data)
print('PASS: %s accepted source files; Python/XML syntax valid' % len(expected))
'''.encode()
    payload['.github/workflows/source-check.yml'] = b'''name: Verify accepted source
on:
  push:
  pull_request:
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          persist-credentials: false
      - name: Verify checksums and syntax
        run: python3 ops/verify_source.py
'''
    # Write only after every selected source file passes its checks.
    OUT.mkdir(parents=True)
    for rel, data in payload.items():
        path = OUT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    evidence = {'status': 'PASS', 'source_commit': EXPECTED, 'source_files': len(manifest['files']),
                'total_files': len(payload), 'known_local_credentials_absent': True,
                'private_key_markers_absent': True, 'source_hashes_exact': True,
                'files': {rel: sha(data) for rel, data in payload.items()}}
    evidence_path = ROOT / 'docs/build-governance/live1-export.json'
    evidence_path.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf8')
    print('EXPORTED', len(payload), 'files to', OUT)


if __name__ == '__main__':
    main()
