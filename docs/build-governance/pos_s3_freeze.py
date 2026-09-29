from pathlib import Path
import ast, hashlib, json, zipfile
root=Path.cwd()
release=root/'docs/releases/2026-09-07-pos-summary-qa3'
archive_dir=root/'.local-backups/releases/2026-09-07-pos-summary-qa3'
archive_dir.mkdir(parents=True,exist_ok=True)
archive=archive_dir/'baseer-pos-summary-qa3.zip'
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
files=[]
for path in sorted((root/'custom_addons/baseer_pos_summary').rglob('*')):
    if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.pyc','.pyo'):continue
    if path.suffix=='.py':ast.parse(path.read_text(encoding='utf-8-sig'))
    files.append({'path':path.relative_to(root).as_posix(),'sha256':digest(path)})
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
    for row in files:output.write(root/row['path'],row['path'].removeprefix('custom_addons/'))
old=json.loads((root/'docs/releases/2026-09-07-pos-summary-qa1/manifest.json').read_text(encoding='utf-8-sig'))
unchanged=[]
for row in old['files']:
    if row['path'].startswith('custom_addons/baseer_pos_summary/'):continue
    assert digest(root/row['path'])==row['sha256'],row['path']
    unchanged.append(row['path'])
evidence=[]
for pattern in ('pos_s3_*.json','pos_s3_*.png','pos_s3_main_readonly.txt','pos_s3_whatsapp_ui_message.txt'):
    for path in sorted((root/'docs/build-governance').glob(pattern)):
        evidence.append({'path':path.relative_to(root).as_posix(),'sha256':digest(path)})
result={'reference':'POS-S3','module_version':'19.0.1.2.0','environment':'QA only','files':files,
        'archive':archive.relative_to(root).as_posix(),'archive_sha256':digest(archive),
        'unchanged_shared_sources':unchanged,'evidence':evidence}
(release/'manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'files':len(files),'evidence':len(evidence),'unchanged_shared':len(unchanged),'sha256':result['archive_sha256']}))

