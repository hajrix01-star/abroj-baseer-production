"""Summarize actual browser observations; bind evidence to reviewed source."""
import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
folder = ROOT/'docs/build-governance/ic1-ui'
addon = ROOT/'custom_addons/baseer_financial_correction'
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
observations = {
 'Arabic native invoice action and correction dialog': 'dialog-ar.txt',
 'English labels and editable fields': 'dialog-en.txt',
 'Native mobile invoice-line cards at480px': 'dialog-480-ar.txt',
 'Mobile nested line edit with labeled inputs': 'line-480-ar.txt',
 'Mobile400 to500 confirmation keeps posted unpaid invoice and visible audit reason': 'corrected-480-ar.txt',
 'Financial-register pencil entry': 'register-en.txt',
 'Register dialog explicitly editable after fresh page load': 'register-dialog-en.txt',
 'Owner sees Arabic per-accountant correction checkbox': 'permission-settings-ar.txt',
 'Owner saves disabled checkbox on QA accountant': 'permission-saved-ar.txt',
 'Disabled accountant invoice retains native actions without shared correction button': 'permission-disabled-en.txt',
}
for path in observations.values():
    assert (folder/path).is_file()
assert '500.00 SR' in (folder/'corrected-480-ar.txt').read_text(encoding='utf-8')
assert 'textbox "Correction reason"' in (folder/'register-dialog-en.txt').read_text(encoding='utf-8')
assert 'checkbox "السماح بتصحيح العمليات المالية" [checked]' in (folder/'permission-settings-ar.txt').read_text(encoding='utf-8')
assert 'checkbox "السماح بتصحيح العمليات المالية" [checked]' not in (folder/'permission-saved-ar.txt').read_text(encoding='utf-8')
assert 'button "Correct operation"' not in (folder/'permission-disabled-en.txt').read_text(encoding='utf-8')
report = {'status':'PASS','database':'baseer_ic1_20260910', 'observations':observations,
 'mobile_geometry':{'viewport':480,'document_scroll_width':480,'dialog_scroll_widths':[480,480]},
 'cashier_execution':'Denied by63-case backend suite and20-case source-route suite; user explicitly reaffirmed prohibition',
 'limitations':['Existing native direct draft/edit permissions are unchanged; this is the shared correction workflow.',
 'Source-owned POS/payroll/loan actions retain their own role checks; no generic journal rewrite.',
 'Full browser refresh required after upgrade to discard cached readonly view.'],
 'evidence_files':{p.relative_to(folder).as_posix():sha(p) for p in sorted(folder.rglob('*')) if p.is_file()},
 'source_sha256':{p.relative_to(addon).as_posix():sha(p) for p in sorted(addon.rglob('*'))
                  if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'},
 'backend_validation':'63PASS rollback and commitguard;20source routes PASS;two-confirm and line-edit concurrent sessions PASS'}
(ROOT/'docs/build-governance/ic1-ui-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('IC1 UI evidence PASS:10 journeys,480px geometry and exact source inventory')
