"""Local evidence only: bind the owned delta, immutable baseline and test results."""
import difflib, hashlib, json, zipfile
from pathlib import Path
from pypdf import PdfReader

out = Path(__file__).resolve().parent
root = out.parents[2]
paths = [
    'custom_addons/baseer_payroll/security/security.xml',
    'custom_addons/baseer_service_seed/models/purchase_batch.py',
    'third_party_addons/odoomates_19/om_hr_payroll/wizard/hr_payroll_contribution_register_report.py',
    'third_party_addons/odoomates_19/om_hr_payroll/report/report_contribution_register.py',
]
manifest = {'owned_files': {}, 'results': {}, 'pdfs': {}}
patches = []
with zipfile.ZipFile(root / 'docs/audits/2026-09-09-full/candidate-source.zip') as archive:
    for path in paths:
        before = archive.read(path)
        after = (root / path).read_bytes()
        manifest['owned_files'][path] = {'fa1_sha256': hashlib.sha256(before).hexdigest(), 'fa2_sha256': hashlib.sha256(after).hexdigest()}
        patches.extend(difflib.unified_diff(before.decode('utf-8-sig').splitlines(keepends=True), after.decode('utf-8-sig').splitlines(keepends=True), fromfile='a/' + path, tofile='b/' + path))
(out / 'security-source.patch').write_text(''.join(patches), encoding='utf-8')
for name in ('security-result.json', 'security-boundaries-result.json', 'security-report-render-result.json'):
    data = json.loads((out / 'security-runtime' / name).read_text(encoding='utf-8'))
    manifest['results'][name] = {'status': data['status'], 'checks': len(data['checks']), 'passed': sum(bool(x['passed']) for x in data['checks']), 'failed': data['failed_checks']}
for lang in ('en_US', 'ar_001'):
    path = out / 'security-runtime' / ('security-contribution-' + lang + '.pdf')
    reader = PdfReader(path)
    manifest['pdfs'][path.name] = {'pages': len(reader.pages), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'amount_239_70_in_text': '239.70' in ''.join(page.extract_text() or '' for page in reader.pages)}
(out / 'security-validation.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'checks': sum(x['checks'] for x in manifest['results'].values()), 'passed': sum(x['passed'] for x in manifest['results'].values()), 'pdfs': manifest['pdfs']}, ensure_ascii=False))
