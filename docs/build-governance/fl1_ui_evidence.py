"""Record completed, human-visible FL1 browser observations; never drives a browser."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
folder = root / 'docs/build-governance/fl1-ui'
required = ['partial-ar.txt', 'partial-ar.png', 'filter-preserved-ar.txt', 'source-ar.txt',
            'mobile-ar.txt', 'mobile-ar.png', 'desktop-en.txt', 'desktop-en.png', 'empty-en.txt']
assert all((folder / item).is_file() for item in required)
partial = (folder / 'partial-ar.txt').read_text(encoding='utf8')
filtered = (folder / 'filter-preserved-ar.txt').read_text(encoding='utf8')
mobile = (folder / 'mobile-ar.txt').read_text(encoding='utf8')
empty = (folder / 'empty-en.txt').read_text(encoding='utf8')
assert '200.10' in partial and '35.05' in partial and '165.05' in partial
assert 'INV/2026/00001' in filtered and 'العملاء: مدفوع جزئيًا (SAR)' not in filtered
assert 'link "INV/2026/00001' in mobile and 'المبلغ المسوّى' in mobile
assert '0 documents' in empty and '0.00SAR' in empty
addon = root / 'custom_addons/baseer_financial_register'
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
result = {
    'status': 'PASS', 'database': 'baseer_ar1_roles_20260910',
    'checks': [
        'Native Invoicing menu opens financial register, paginated list and ten invoice cards',
        'Arabic labels, source names, Western figures and native payment badges render',
        'Partial customer card shows two matching rows: total200.10, settled35.05, outstanding165.05',
        'Native number/reference query remains after toggling off the owned KPI facet',
        'Source button opens the existing partially settled native invoice',
        '480px fresh navigation selects native kanban with two KPI columns and document width480',
        'English labels, amounts and source types render; existing native view-switch labels may retain Arabic',
        'No-match search shows zero invoice indicators and no operations',
    ],
    'mobile_measurement': {'viewport_width': 480, 'document_width': 480,
                           'native_kanban': True, 'grid_columns': '216.5px 216.5px'},
    'viewport_restored': True, 'language_restored': 'ar_001',
    'limitations': ['UI uses the existing isolated QA database and synthetic fixtures left by an earlier test-only localization install; this is not financial preservation evidence.',
                    'Authoritative accounting/rollback evidence uses separate clean MAIN clone baseer_ar1_fl1_clean_20260910.',
                    'Access denial, native installment arithmetic and source-summary navigation are covered in backend integration evidence; no claim of browser execution of those cases.'],
    'source_files': {p.relative_to(addon).as_posix(): digest(p) for p in sorted(addon.rglob('*'))
                     if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'},
    'evidence_files': {name: digest(folder / name) for name in required},
}
(root / 'docs/build-governance/fl1-ui-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print('FL1_UI_PASS', len(result['checks']))
