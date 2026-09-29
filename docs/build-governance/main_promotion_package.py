"""Freeze vetted addons, checking prior independent-release source manifests."""
from pathlib import Path
import ast
import hashlib
import json
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.local-backups/main-promotion-20260908'
RELEASE = ROOT / 'docs/releases/2026-09-08-main-promotion'
approved = {}
references = [
    'docs/releases/2026-09-07-reports-r1/manifest.json',
    'docs/releases/2026-09-07-purchase-batch-qa5/manifest.json',
    'docs/releases/2026-09-07-pos-summary-qa1/manifest.json',
    'docs/releases/2026-09-08-pos-summary-qa6/manifest.json',
    'docs/build-governance/nav1_manifest.json',
    'docs/releases/2026-09-08-legion-theme-qa1/manifest.json',
]
for ref in references:
    for entry in json.loads((ROOT / ref).read_text(encoding='utf-8-sig'))['files']:
        approved[entry['path'].replace('\\', '/')] = (entry['sha256'], ref)
approved['custom_addons/baseer_cash_categories/models/cash_pdf.py'] = ('53364c5c69afc7d819aac8d499c202fe11721dd9ff23e4a632492d73e85cf525', 'docs/build-governance/CASH-PRINT-CLEAN-REVIEW.md')
approved['custom_addons/baseer_cash_categories/__manifest__.py'] = ('8cd25f75e0878071faf42196f2de863b9e54501c3ef4f37d18680ce6673bb56b', 'docs/build-governance/CASH-PRINT-CLEAN-REVIEW.md')
modules = [
    *['custom_addons/' + name for name in (
        'baseer_core', 'baseer_cash_categories', 'baseer_report_layout',
        'baseer_purchase_batch', 'baseer_category_display', 'baseer_pos_summary',
        'baseer_web_navigation', 'baseer_legion_compat')],
    *['third_party_addons/erp_heritage_19/' + name for name in (
        'eh_account_base', 'eh_account_dynamic_reports', 'legion_enterprise_theme')],
]
files, versions, problems = [], {}, []
for module in modules:
    manifest = ast.literal_eval((ROOT / module / '__manifest__.py').read_text(encoding='utf-8-sig'))
    versions[Path(module).name] = manifest['version']
    for path in sorted((ROOT / module).rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        rel = path.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        prior = approved.get(rel)
        if prior and prior[0] != digest:
            problems.append({'path': rel, 'reason': 'changed since reviewed candidate', 'reference': prior[1]})
        elif not prior and Path(module).name != 'baseer_core':
            problems.append({'path': rel, 'reason': 'no prior source approval'})
        files.append({'path': rel, 'sha256': digest, 'reference': prior[1] if prior else 'unchanged installed foundation'})
RELEASE.mkdir(parents=True, exist_ok=True)
(RELEASE / 'source-audit.json').write_text(json.dumps({'files': len(files), 'problems': problems}, indent=2), encoding='utf8')
if problems:
    print(json.dumps(problems, indent=2)); raise SystemExit(1)
OUT.mkdir(parents=True, exist_ok=True)
for entry in files:
    target = OUT / 'candidate' / entry['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / entry['path'], target)
with ZipFile(OUT / 'addons.zip', 'w', ZIP_DEFLATED) as archive:
    for entry in files:
        archive.write(ROOT / entry['path'], entry['path'])
result = {'candidate': 'MAIN-PROMOTION M1', 'modules': versions, 'files': files,
          'archive': {'path': str((OUT / 'addons.zip').relative_to(ROOT)), 'sha256': hashlib.sha256((OUT / 'addons.zip').read_bytes()).hexdigest()},
          'image': 'odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd',
          'excluded': ['payroll/OpenHRMS', 'QA data', 'unfinished tax/permission policies']}
(RELEASE / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf8')
print(json.dumps({'files': len(files), 'modules': versions, 'archive': result['archive']}))
