"""Seal existing audit artifacts and validate final report local references."""
import hashlib,json,re
from pathlib import Path
out=Path(__file__).resolve().parent
root=out.parents[2]
candidate=json.loads((out/'candidate.json').read_text(encoding='utf-8'))
actual={}
for name in ('custom_addons','third_party_addons'):
    for p in (root/name).rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts and p.suffix!='.pyc':
            actual[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
assert actual==candidate['custom_and_vendor_files'],'Candidate source changed'
missing=[]
for label,url in re.findall(r'\[([^\]]+)\]\(([^)]+)\)',(out/'FINAL-AUDIT.md').read_text(encoding='utf-8')):
    if url!='evidence-index.json' and not url.startswith(('http:','https:')) and not (out/url).exists():missing.append(url)
assert not missing,missing
files={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
       for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence-index.json' and '__pycache__' not in p.parts}
result={'decision':'NO-GO','frozen_source_files':len(actual),'source_exactly_unchanged':True,
        'local_report_links_valid':True,'artifact_count':len(files),'sha256':files}
(out/'evidence-index.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='sha256'},indent=2))
