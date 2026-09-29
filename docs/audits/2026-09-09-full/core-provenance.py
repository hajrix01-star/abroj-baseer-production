"""Read-only provenance, parsers and native/runtime comparison."""
import ast,hashlib,json,subprocess,sys,difflib
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'docs/build-governance'))
import om_payroll_ops as o
OUT=Path(__file__).parent
c=json.loads((OUT/'candidate.json').read_text(encoding='utf-8'))
issues=[];parsed={'python':0,'xml':0}
for path in c['custom_and_vendor_files']:
    p=ROOT/path
    try:
        if p.suffix=='.py':ast.parse(p.read_text(encoding='utf-8-sig'));parsed['python']+=1
        elif p.suffix=='.xml':ET.parse(p);parsed['xml']+=1
    except Exception as exc:issues.append({'file':path,'error':str(exc)})
remote="""import sys,json,pathlib,hashlib
d=json.load(sys.stdin)
errors=[]
for p,h in d.items():
 q=p.replace('custom_addons/','/mnt/baseer-addons/',1).replace('third_party_addons/','/mnt/third-party-addons/',1)
 if hashlib.sha256(pathlib.Path(q).read_bytes()).hexdigest()!=h:errors.append(p)
print(json.dumps(errors))
"""
r=o.run(['docker','exec','-i',o.CONTAINER,'python3','-c',remote],input=json.dumps(c['custom_and_vendor_files']),capture_output=True,text=True)
mounted=json.loads(r.stdout)
vendor=[]
for file in ('docs/releases/2026-09-08-om-payroll/source.json','docs/releases/2026-09-08-legion-theme-qa1/manifest.json'):
    d=json.loads((ROOT/file).read_text(encoding='utf-8'));entries=d['files']
    changed=[v['path'] for v in entries if not (ROOT/v['path']).exists() or hashlib.sha256((ROOT/v['path']).read_bytes()).hexdigest()!=v['sha256']]
    vendor.append({'baseline':file,'files':len(entries),'changed':changed})
native=['orm/models.py','orm/environments.py','service/model.py','addons/account/models/account_move.py','addons/account/models/account_payment.py','addons/account/wizard/account_payment_register.py','addons/web/static/src/webclient/actions/action_service.js']
local={}
for f in native:
    p=ROOT/'odoo'/('odoo' if not f.startswith('addons/') else '')/f
    if p.exists():local[f]=hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
remote="""import sys,json,pathlib,hashlib
d=json.load(sys.stdin);r={}
for p,h in d.items():
 q=pathlib.Path('/usr/lib/python3/dist-packages/odoo')/p
 r[p]={'same_normalized_line_endings':q.exists() and hashlib.sha256(q.read_bytes().replace(bytes([13,10]),bytes([10]))).hexdigest()==h}
print(json.dumps(r))
"""
r=o.run(['docker','exec','-i',o.CONTAINER,'python3','-c',remote],input=json.dumps(local),capture_output=True,text=True)
out={'source_file_count':len(c['custom_and_vendor_files']),'parsers':parsed,'parse_errors':issues,'mounted_differences':mounted,'recorded_vendor_baselines':vendor,'native_critical_source_runtime_comparison':json.loads(r.stdout)}
diffs=[]
for f,v in out['native_critical_source_runtime_comparison'].items():
    if v['same_normalized_line_endings']:continue
    localpath=ROOT/'odoo'/('odoo' if not f.startswith('addons/') else '')/f
    runtime=o.run(['docker','exec',o.CONTAINER,'cat','/usr/lib/python3/dist-packages/odoo/'+f],capture_output=True,text=True).stdout
    diffs.extend(difflib.unified_diff(localpath.read_text(encoding='utf-8').splitlines(True),runtime.splitlines(True),fromfile='local/'+f,tofile='runtime/'+f))
(OUT/'core-native-runtime.diff').write_text(''.join(diffs),encoding='utf-8')
(OUT/'core-provenance.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
