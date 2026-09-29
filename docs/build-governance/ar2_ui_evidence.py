import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
out = root / 'docs/releases/2026-09-10-access-roles-user-form'
saved = (out / 'accountant-saved-ar.txt').read_text(encoding='utf-8')
prefs = (out / 'accountant-inbox-ar.txt').read_text(encoding='utf-8')
assert 'AR2 Fixed Accountant' in saved and 'text: المحاسب' in saved
assert all(s in saved for s in ('generic "ARZ"', 'generic "المعلم الشامي"', 'generic "دوحة المستهلك"'))
assert 'button "الحفظ يدوياً"' not in saved and '- dialog:' not in saved
assert 'radio "في أودو" [checked]' in prefs and '- dialog:' not in prefs
assert '/placeholder: الفوترة' in saved and '/placeholder: المدير' in saved
assert 'radio "المدير" [disabled]' in saved
paths = ('__manifest__.py', 'models/res_users.py', 'views/res_users_views.xml')
source = {p: hashlib.sha256((root / 'custom_addons/baseer_access_roles' / p).read_bytes()).hexdigest() for p in paths}
result = dict(status='PASS', database='baseer_ar1_roles_20260910',
              checks=['Native new accountant form saves with inbox preference',
                      'All three selected companies retained after reload',
                      'Accountant preset and permitted application selections retained',
                      'Native administrator radio disabled while preset applies',
                      'In Odoo preference retained after reload'], source_files=source,
              evidence_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.suffix in ('.txt','.png')})
(root / 'docs/build-governance/ar2-ui-checks.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print('AR2 UI PASS', len(result['checks']))
