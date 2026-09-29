"""Bind observed Arabic browser acceptance artifacts to tested source hashes."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
out = root / 'docs/releases/2026-09-10-access-roles'
checks = []
def observed(file, required=(), absent=()):
    text = (out / file).read_text(encoding='utf-8')
    assert all(s in text for s in required), file
    assert all(s not in text for s in absent), file
    checks.append(file)

observed('cashier-draft-ar.txt', ('AR1-UI-SAVED',), ('button "حفظ واعتماد"',))
observed('accountant-draft-ar.txt', ('حفظ واعتماد',))
observed('accountant-posted-ar.txt', ('BILL/2026/09/0001',))
observed('cashier-app-menu.txt', ('نقطة البيع',), ('menuitem "الموظفون"', 'menuitem "الفوترة"'))
observed('accountant-app-menu.txt', ('المبيعات', 'نقطة البيع', 'الفوترة', 'الشراء'), ('menuitem "الموظفون"',))
observed('owner-app-menu.txt', ('الموظفون', 'المرتبات', 'الإعدادات'))
observed('owner-role-selector-ar.txt', ('الصلاحية الجاهزة',))
observed('owner-role-options-ar.txt', ('الكاشير', 'المحاسب', 'المالك'))
observed('cashier-advance-posted-ar.txt', ('radio "قائمة" [checked]', '100.01 SR', 'AR1 UI Employee', 'عدد الأقساط'), ('button "اعتماد وصرف"', 'الراتب', 'Payroll'))
life = json.loads((root / 'docs/build-governance/ar1-lifecycle-checks.json').read_text(encoding='utf-8'))
files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.suffix in ('.txt', '.png')}
result = dict(status='PASS', database='baseer_ar1_roles_20260910', checks=checks,
              source_files=life['source_files'], evidence_files=files,
              limitations=['Arabic native desktop forms verified; no separate narrow viewport assertion.',
                            'Both-role advance disbursement covered by 83 backend checks; actual browser disbursement performed as cashier.'])
(root / 'docs/build-governance/ar1-ui-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print('UI PASS', len(checks))
