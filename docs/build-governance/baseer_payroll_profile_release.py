"""Freeze BP-S4 source and acceptance evidence without changing any database."""
import ast,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'docs/releases/2026-09-08-baseer-payroll-profile';ADDON=ROOT/'custom_addons/baseer_payroll'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def identity(p):return {'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
assert all(read(OUT/'preservation.json').values())
names=['baseer_payroll_profile_checks','baseer_payroll_eos_checks','baseer_payroll_eos_concurrency']
results={n:read(ROOT/'docs/build-governance'/f'{n}.json') for n in names}
assert all(r['status']=='passed' for r in results.values())
assert all(results[n]['rolled_back'] for n in names[:2])
assert read(ROOT/'docs/build-governance/baseer_payroll_profile_ui_checks.json')['test_estimates_removed']
previous=read(ROOT/'docs/releases/2026-09-08-baseer-payroll-month/candidate.json')
assert identity(ROOT/'docs/releases/2026-09-08-baseer-payroll-month'/previous['archive'])['sha256']==previous['archive_sha256']
upstream=read(ROOT/'docs/releases/2026-09-08-om-payroll/source.json')
assert all(identity(ROOT/f['path'])['sha256']==f['sha256'] for f in upstream['files'])
files=[p for p in sorted(ADDON.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
version=ast.literal_eval((ADDON/'__manifest__.py').read_text())['version'];assert version=='19.0.1.2.0'
archive=OUT/f'baseer_payroll-{version}.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,p.relative_to(ADDON.parent))
evidence=[ROOT/'docs/build-governance'/f'{n}.json' for n in names]+[ROOT/'docs/build-governance'/n for n in ['baseer_payroll_profile_ui_checks.json','baseer_payroll_profile_desktop.png','baseer_payroll_profile_mobile.png','baseer_payroll_eos_desktop.png','baseer_payroll_eos_mobile.png','baseer_payroll_profile_upgrade.log','BASEER-PAYROLL-PROFILE.md']]+[OUT/'preservation.json',OUT/'HANDOFF.md']
data={'version':version,'target':'QA only','archive':archive.name,'archive_sha256':identity(archive)['sha256'],'files':[identity(p) for p in files],'evidence':[identity(p) for p in evidence],'backup':read(OUT/'backup.json'),'predecessor_archive_sha256':previous['archive_sha256'],'upstream_files_unchanged':len(upstream['files']),'checks':{n:len(r['checks']) for n,r in results.items()},'main_exact':True,'git_commit':None}
(OUT/'candidate.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'version':version,'files':len(files),'sha256':data['archive_sha256'],'checks':data['checks']}))
