"""Freeze the QA candidate and verified shared-date compatibility sources."""
from pathlib import Path
import ast
import hashlib
import json
import zipfile

root=Path.cwd()
release=root/'docs/releases/2026-09-07-pos-summary-qa1'
archive_dir=root/'.local-backups/releases/2026-09-07-pos-summary-qa1'
archive_dir.mkdir(parents=True,exist_ok=True)
archive=archive_dir/'baseer-pos-summary-qa1.zip'
modules=['baseer_pos_summary','baseer_report_layout','baseer_purchase_batch']
files=[]
for module in modules:
    for path in sorted((root/'custom_addons'/module).rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.pyc','.pyo'): continue
        if path.suffix=='.py': ast.parse(path.read_text(encoding='utf-8-sig'))
        data=path.read_bytes()
        files.append({'path':path.relative_to(root).as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
    for row in files: output.write(root/row['path'],row['path'].removeprefix('custom_addons/'))
with zipfile.ZipFile(archive) as check:
    for row in files:
        assert hashlib.sha256(check.read(row['path'].removeprefix('custom_addons/'))).hexdigest()==row['sha256']
old=json.loads((root/'docs/releases/2026-09-07-purchase-batch-qa5/manifest.json').read_text(encoding='utf-8-sig'))
purchase_changes=[v['path'] for v in old['files'] if hashlib.sha256((root/v['path']).read_bytes()).hexdigest()!=v['sha256']]
assert set(purchase_changes)=={'custom_addons/baseer_purchase_batch/__manifest__.py','custom_addons/baseer_purchase_batch/static/src/js/latin_date_field.js'},purchase_changes
evidence_names=[
    'pos_summary_acceptance.json','pos_summary_backend_checks.json','pos_summary_concurrency.json','pos_summary_capacity.json',
    'pos_summary_journal_action.json','pos_summary_native_install_preservation.json','pos_summary_source_preservation.json',
    'pos_summary_main_readonly.txt','pos_summary_qa_final_state.txt','pos_summary_ui_evidence.json',
    'pos_summary_ar_desktop_final.png','pos_summary_ar_mobile.png','pos_summary_en_desktop.png','pos_summary_en_mobile.png',
    'pos_summary_mobile_entry.png','pos_summary_purchase_compatibility.png',
    'pos_summary_acceptance.py','qa_pos_summary_backend.py','pos_summary_cash_checks.py','pos_summary_concurrency.py','pos_summary_capacity.py',
]
evidence=[]
for name in evidence_names:
    p=root/'docs/build-governance'/name
    evidence.append({'path':p.relative_to(root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
manifest={
    'candidate':'BASEER-POS-S1 QA1','date':'2026-09-07','scope':'QA only, no new module installation on main',
    'identity':'Source SHA256 and verified ZIP; no release commit in current workspace',
    'modules':{m:ast.literal_eval((root/'custom_addons'/m/'__manifest__.py').read_text(encoding='utf-8-sig'))['version'] for m in modules},
    'required_pos_dependencies':['point_of_sale','baseer_cash_categories'],
    'purchase_module':'Existing shared-date compatibility package, not required to install POS summaries',
    'qa_database':'baseer_reports_qa_20260907',
    'runtime_image_id':'sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd',
    'archive':{'path':archive.relative_to(root).as_posix(),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'verified_entries':len(files)},
    'purchase_baseline_changed_files':purchase_changes,'files':files,'evidence':evidence,
    'preview_url':'http://127.0.0.1:18070/odoo/action-490/82',
}
(release/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(files),'archive':manifest['archive'],'evidence':len(evidence)},ensure_ascii=False))
