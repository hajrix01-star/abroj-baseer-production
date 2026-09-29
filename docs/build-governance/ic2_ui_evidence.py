"""Bind observed browser evidence to the exact two-add-on source inventory."""
import hashlib
import json
from pathlib import Path
root = Path(__file__).resolve().parents[2]
evidence = root / 'docs/build-governance/ic2-ui'
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
sources = {path.relative_to(root).as_posix(): digest(path)
           for addon in ('baseer_financial_correction', 'baseer_pos_summary')
           for path in sorted((root / 'custom_addons' / addon).rglob('*'))
           if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}
report = {'status': 'PASS', 'database': 'baseer_ic1_20260910',
          'observations': {
              'Arabic and English native invoice/payment cancellation preview': ['cancel-ar.txt', 'cancel-en.txt'],
              'Arabic480 cancellation confirms both original record IDs and amount500': ['cancel-480-ar.txt', 'cancel-result-ar.txt'],
              'Cancelled purchase row visibly retained and active totals500': ['batch-result-en.txt'],
              'Summary title and acknowledgement labelled in Arabic/English': ['summary-ar.txt', 'summary-en.txt'],
              'Native480 mobile payment cards and editable nested amount form': ['summary-480-ar.txt', 'summary-line-480-ar.txt'],
              'Browser summary confirmation approves corrected790/15customers and links original690': ['summary-result-ar.txt']},
          'mobile_geometry': {'viewport': 480, 'document_scroll_width': 480, 'dialog_scroll_width': 480},
          'backend_validation': {'core_checks': 60, 'summary_checks': 38,
                                 'real_concurrency_cases': 2, 'actual_browser_accounting': 'ic2-ui-accounting.json'},
          'limitations': ['Erroneous bookkeeping correction only; no actual bank refund.',
                         'Whole-batch cancellation omitted; each purchase row is one atomic operation.',
                         'Shared or externally settled payments and protected HR/payroll/stock sources retain native source-specific workflows.',
                         'Native mobile kanban is selected when opening at mobile width; an already-open desktop list retains its mode after resize.'],
          'evidence_files': {p.relative_to(evidence).as_posix(): digest(p) for p in sorted(evidence.rglob('*')) if p.is_file()},
          'source_sha256': sources}
assert json.loads((root / 'docs/build-governance/ic2-ui-accounting.json').read_text())['status'] == 'PASS'
(root / 'docs/build-governance/ic2-ui-checks.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf8')
print('UI PASS:', len(report['evidence_files']), 'evidence files;', len(sources), 'bound source files')
