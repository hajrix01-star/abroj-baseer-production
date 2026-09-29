"""Freeze BP-S2 source and exercised evidence; no database changes."""
import ast,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/releases/2026-09-08-baseer-payroll-flow'
ADDON=ROOT/'custom_addons/baseer_payroll'
def identity(p): return {'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
assert read(OUT/'preservation.json')['status']=='passed'
for name in ['checks','concurrency','bank_trial','bank_commit','cash','pdf']:
    assert read(ROOT/f'docs/build-governance/baseer_payroll_flow_{name}.json')['status']=='passed'
upstream=read(ROOT/'docs/releases/2026-09-08-om-payroll/source.json')
assert all(identity(ROOT/f['path'])['sha256']==f['sha256'] for f in upstream['files'])
files=[p for p in sorted(ADDON.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
assert ast.literal_eval((ADDON/'__manifest__.py').read_text())['version']=='19.0.1.1.0'
archive=OUT/'baseer_payroll-19.0.1.1.0.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,p.relative_to(ADDON.parent))
selected=['checks.json','concurrency.json','bank_trial.json','bank_commit.json','cash.json','pdf.json','partial.png','paid.png','employee.png','employee_detail.png','employee_payments.png','employee_mobile.png','detail_mobile.png','dialog_mobile_final.png','mobile_amount.png','statement_ar_001.pdf','statement_en_US.pdf','payslips_ar_001.pdf','payslips_en_US.pdf','statement_ar.png','statement_en.png','payslip_ar.png','upgrade_final.log']
evidence=[ROOT/('docs/build-governance/baseer_payroll_flow_'+name) for name in selected]
evidence += [OUT/'preservation.json',OUT/'HANDOFF.md',ROOT/'docs/build-governance/BASEER-PAYROLL-FLOW.md']
R={'version':'19.0.1.1.0','target':'baseer_reports_qa_20260907 only','git_commit':None,'git_note':'No committed baseline; exact source and artifact hashes identify candidate.','archive':archive.name,'archive_sha256':identity(archive)['sha256'],'files':[identity(p) for p in files],'evidence':[identity(p) for p in evidence],'upstream_commit':upstream['commit'],'upstream_files_unchanged':len(upstream['files']),'backup':read(OUT/'backup.json'),'preview_run':107,'check_count':92,'main_unchanged':True}
(OUT/'candidate.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'version':R['version'],'files':len(files),'evidence':len(evidence),'archive_sha256':R['archive_sha256']}))
