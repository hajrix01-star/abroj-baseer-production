"""Snapshot completed source, parse it, and archive immutable review/deployment inputs."""
import ast,hashlib,json,shutil,sys,zipfile
from pathlib import Path
from lxml import etree
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
target=f.BACK/'candidate';target.mkdir(exist_ok=True)
old=json.loads((f.OUT/'candidate.json').read_text(encoding='utf-8'))['files'] if (f.OUT/'candidate.json').exists() else {}
files={};parsers={'python':0,'xml':0};mods={}
for folder in ('custom_addons','third_party_addons'):
 for p in sorted((f.o.ROOT/folder).rglob('*')):
  if not p.is_file() or '__pycache__' in p.parts or '.git' in p.parts or p.suffix=='.pyc':continue
  relative=p.relative_to(f.o.ROOT).as_posix();data=p.read_bytes()
  if p.suffix=='.py':ast.parse(data.decode('utf-8-sig'),filename=relative);parsers['python']+=1
  if p.suffix=='.xml':etree.fromstring(data);parsers['xml']+=1
  if p.name=='__manifest__.py':mods[p.parent.name]=ast.literal_eval(data.decode('utf-8-sig'))
  files[relative]=hashlib.sha256(data).hexdigest();dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
for removed in set(old)-set(files):
 p=(target/removed).resolve();assert p.is_relative_to(target.resolve())
 if p.is_file():p.unlink()
archive=f.OUT/'candidate-source.zip'
if archive.exists():
 previous=hashlib.sha256(archive.read_bytes()).hexdigest()[:12]
 shutil.copy2(archive,f.BACK/('candidate-'+previous+'.zip'))
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for relative in files:z.write(target/relative,relative)
baseline=json.loads((f.audit.OUT/'candidate.json').read_text(encoding='utf-8'))['custom_and_vendor_files']
changed=[p for p,h in files.items() if baseline.get(p)!=h]
record={'files':files,'changed_from_fa1':changed,'deleted_from_fa1':sorted(set(baseline)-set(files)),
 'parse_counts':parsers,'module_versions':{m:v.get('version') for m,v in mods.items()},
 'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'source_directory':str(target),
 'engine':'odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd'}
f.save('candidate.json',record)
print('Frozen',len(files),'files;',len(changed),'changed;',parsers,'archive',record['archive_sha256'])
