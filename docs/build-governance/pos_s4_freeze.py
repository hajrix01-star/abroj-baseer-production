from pathlib import Path
import ast, hashlib, json, zipfile
root = Path.cwd()
release = root / 'docs/releases/2026-09-08-pos-summary-qa4'
release.mkdir(parents=True, exist_ok=True)
archive = root / '.local-backups/pos-summary-s4/baseer-pos-summary-qa4.zip'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
files = []
for p in sorted((root / 'custom_addons/baseer_pos_summary').rglob('*')):
    if not p.is_file() or '__pycache__' in p.parts or p.suffix in ('.pyc', '.pyo'): continue
    if p.suffix == '.py': ast.parse(p.read_text(encoding='utf-8-sig'))
    files.append({'path':p.relative_to(root).as_posix(), 'sha256':digest(p)})
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
    for row in files: output.write(root / row['path'], row['path'].removeprefix('custom_addons/'))
evidence = [{'path':p.relative_to(root).as_posix(), 'sha256':digest(p)} for pattern in ('pos_s4_checks.*','pos_s4_card_*.png','pos_s4_upgrade_final.log','pos_s4_translate.py') for p in sorted((root/'docs/build-governance').glob(pattern))]
result = {'reference':'POS-S4','module_version':'19.0.1.2.1','environment':'QA only','files':files,'evidence':evidence,'archive':archive.relative_to(root).as_posix(),'archive_sha256':digest(archive),'backup_sha256':digest(root/'.local-backups/pos-summary-s4/database.dump')}
(release/'manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'files':len(files),'evidence':len(evidence),'sha256':result['archive_sha256']}))
