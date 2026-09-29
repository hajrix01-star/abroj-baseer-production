"""Freeze the BP-S3 QA candidate and immutable evidence."""
import json,hashlib,zipfile,ast
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'docs/releases/2026-09-08-baseer-payroll-month';ADDON=ROOT/'custom_addons/baseer_payroll'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def identity(p):return {'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
assert all(read(OUT/'preservation.json').values())
checks=read(ROOT/'docs/build-governance/baseer_payroll_month_checks.json');assert checks['status']=='passed' and checks['rolled_back']
previous=read(ROOT/'docs/releases/2026-09-08-baseer-payroll-flow/candidate.json')
assert identity(ROOT/'docs/releases/2026-09-08-baseer-payroll-flow'/previous['archive'])['sha256']==previous['archive_sha256']
upstream=read(ROOT/'docs/releases/2026-09-08-om-payroll/source.json');assert all(identity(ROOT/f['path'])['sha256']==f['sha256'] for f in upstream['files'])
files=[p for p in sorted(ADDON.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
version=ast.literal_eval((ADDON/'__manifest__.py').read_text())['version'];assert version=='19.0.1.1.1'
archive=OUT/f'baseer_payroll-{version}.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,p.relative_to(ADDON.parent))
evidence=[ROOT/('docs/build-governance/baseer_payroll_month_'+s) for s in ['checks.json','picker_desktop.png','picker_mobile.png','payment_default.png','loans_desktop.png','loans_mobile.png','loan_history.png','salary_setup.png','upgrade_final.log']]+[OUT/'preservation.json',OUT/'HANDOFF.md',ROOT/'docs/build-governance/BASEER-PAYROLL-MONTH.md']
R={'version':version,'target':'QA only','archive':archive.name,'archive_sha256':identity(archive)['sha256'],'files':[identity(p) for p in files],'evidence':[identity(p) for p in evidence],'backup':read(OUT/'backup.json'),'predecessor_archive_sha256':previous['archive_sha256'],'upstream_files_unchanged':len(upstream['files']),'checks':len(checks['checks']),'main_exact':True,'git_commit':None}
(OUT/'candidate.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'version':version,'files':len(files),'evidence':len(evidence),'sha256':R['archive_sha256']}))
