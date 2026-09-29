from pathlib import Path
import ast, hashlib, json, zipfile
root=Path.cwd()
release=root/'docs/releases/2026-09-08-pos-summary-qa5'
release.mkdir(parents=True,exist_ok=True)
archive=root/'.local-backups/pos-summary-s5/baseer-pos-summary-qa5.zip'
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
files=[]
for p in sorted((root/'custom_addons/baseer_pos_summary').rglob('*')):
    if not p.is_file() or '__pycache__' in p.parts or p.suffix in ('.pyc','.pyo'):continue
    if p.suffix=='.py':ast.parse(p.read_text(encoding='utf-8-sig'))
    files.append({'path':p.relative_to(root).as_posix(),'sha256':digest(p)})
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as out:
    for row in files:out.write(root/row['path'],row['path'].removeprefix('custom_addons/'))
evidence=[]
for pattern in ('pos_s5_lifecycle_checks.*','pos_s5_regression_checks.*','pos_s5_*.png','pos_s5_ui_fixture.json','pos_s5_upgrade.log'):
    for p in sorted((root/'docs/build-governance').glob(pattern)):
        evidence.append({'path':p.relative_to(root).as_posix(),'sha256':digest(p)})
old=json.loads((root/'docs/releases/2026-09-08-pos-summary-qa4/manifest.json').read_text())
unchanged=[r['path'] for r in old['files'] if digest(root/r['path'])==r['sha256']]
result={'reference':'POS-S5 lifecycle only','module_version':'19.0.1.3.0','environment':'QA only','files':files,'evidence':evidence,'unchanged_from_qa4':unchanged,'archive':archive.relative_to(root).as_posix(),'archive_sha256':digest(archive),'backup_sha256':digest(root/'.local-backups/pos-summary-s5/database.dump'),'pending_user_scope':['inclusive tax pricing new versus existing amounts','closed record meaning and deletion scope']}
(release/'manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'files':len(files),'evidence':len(evidence),'sha256':result['archive_sha256']}))
