"""Freeze the QA-only PB1 source candidate and verify the existing reports."""
import ast
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / 'docs/releases/2026-09-07-purchase-batch-qa4'
ARCHIVE = ROOT / '.local-backups/releases/2026-09-07-purchase-batch-qa4/baseer-purchase-batch-qa4.zip'
RELEASE.mkdir(parents=True, exist_ok=True)
ARCHIVE.parent.mkdir(parents=True, exist_ok=True)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

baseline = json.loads((ROOT / 'docs/releases/2026-09-07-reports-r1/manifest.json').read_text(encoding='utf-8-sig'))
patch = json.loads((ROOT / 'docs/build-governance/cash_print_candidate_hashes.json').read_text(encoding='utf-8-sig'))
overrides = {Path(item['Path']).relative_to(ROOT).as_posix(): item['Hash'].lower() for item in patch}
for item in baseline['files']:
    assert sha(ROOT / item['path']) == overrides.get(item['path'], item['sha256']), item['path']

addon = ROOT / 'custom_addons/baseer_purchase_batch'
files = sorted(p for base in (addon, ROOT / 'custom_addons/baseer_category_display') for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
module = ast.literal_eval((addon / '__manifest__.py').read_text(encoding='utf-8-sig'))
items = [{'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in files]
with ZipFile(ARCHIVE, 'w', ZIP_DEFLATED) as archive:
    for p in files:
        archive.write(p, p.relative_to(addon.parent).as_posix())
with ZipFile(ARCHIVE) as archive:
    assert len(archive.namelist()) == len(items)
    for item in items:
        name = item['path'].removeprefix('custom_addons/')
        assert hashlib.sha256(archive.read(name)).hexdigest() == item['sha256']

evidence_names = ['purchase_batch_qa4_checks.json', 'purchase_batch_qa4_regression_checks.json', 'purchase_batch_qa4_ui_checks.json', 'qa4_table.png', 'qa4_supplier.png', 'qa4_row_form.png', 'qa4_credit_validation.png', 'qa4_financial_before.txt', 'qa4_financial_after.txt', 'qa4_legacy_before.json', 'qa4_main_readonly.txt', 'qa4_upgrade.log', 'qa4_final_upgrade.log']

evidence = []
for name in evidence_names:
    p = ROOT / 'docs/build-governance' / name
    evidence.append({'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)})
manifest = {
    'candidate': 'BASEER-ODOO-PB1/v1 QA4', 'date': '2026-09-07',
    'scope': 'QA preview only; not installed on main',
    'identity': 'SHA256 source manifest and verified zip; workspace has no release commit',
    'module': 'baseer_purchase_batch', 'version': module['version'], 'dependencies': module['depends'],
    'qa_database': 'baseer_reports_qa_20260907',
    'runtime_image_id': 'sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd',
    'installed_dependency_versions': {'baseer_category_display': '19.0.1.0.0', 'account': '19.0.1.4', 'baseer_report_layout': '19.0.1.1.0'},
    'existing_report_files_verified': len(baseline['files']),
    'baseline': 'Reports R1 with previously accepted cash print 19.0.1.3.1 two-file patch',
    'main_readonly_check': {'moves': 0, 'move_lines': 0, 'purchase_batch_installed': 0, 'category_display_installed': 0},
    'archive': {'path': ARCHIVE.relative_to(ROOT).as_posix(), 'sha256': sha(ARCHIVE), 'entries_verified': len(items)},
    'files': items, 'evidence': evidence,
}
(RELEASE / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps({'source_files': len(items), 'reports_unchanged': len(baseline['files']), 'archive_sha256': sha(ARCHIVE)}))
