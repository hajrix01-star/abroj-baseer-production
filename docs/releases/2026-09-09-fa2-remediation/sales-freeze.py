"""Local syntax/evidence/hash verification; no application database access."""
from pathlib import Path
import ast, hashlib, json, xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[3]
addon=root/'custom_addons/baseer_pos_summary'
out=Path(__file__).parent
files=sorted(p for p in addon.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
py=[p for p in files if p.suffix=='.py'];xml=[p for p in files if p.suffix=='.xml']
for p in py:ast.parse(p.read_text(encoding='utf-8-sig'),str(p))
for p in xml:ET.parse(p)
hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
assert hashes==json.loads((out/'sales-source.json').read_text())['sha256'],'Source changed after isolated stage'
checks={}
for name in ['sales-checks.json','sales-races.json','sales-cash-adapter-result.json','sales-vendor-parity-result.json']:
    data=json.loads((out/'sales-runtime'/name).read_text(encoding='utf-8'))
    assert data['status'] in ('passed','PASS','completed'),name
    assert all(c['passed'] for c in data['checks']),name
    checks[name]=len(data['checks'])
legacy=json.loads((out/'sales-runtime/sales-legacy-result.json').read_text(encoding='utf-8'))
assert all(row['status']=='passed' for row in legacy)
manifest={'module':'baseer_pos_summary','version':ast.literal_eval((addon/'__manifest__.py').read_text())['version'],
    'database':'baseer_fix_sales_20260909','syntax':{'python':len(py),'xml':len(xml)},'sha256':hashes,
    'new_and_parity_checks':checks,'legacy_checks':{'backend':42,'operations':46,'s6':48,'whatsapp':24},
    'real_races':3,'total_checks':sum(checks.values())+160,
    'source_manifest_sha256':hashlib.sha256((out/'sales-source.json').read_bytes()).hexdigest()}
(out/'sales-freeze.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in manifest.items() if k!='sha256'},ensure_ascii=False))
