"""Bind frozen source, isolated Git commit, deployment inputs and live preservation."""
import hashlib,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
candidate=json.loads((f.OUT/'candidate.json').read_text(encoding='utf-8'))
source=f.BACK/'candidate'
def git(*args):return subprocess.check_output(['git','-C',str(source),*args]).decode().strip()
assert not git('status','--porcelain')
tracked=set(git('ls-files').splitlines())
assert tracked==set(candidate['files']), (len(tracked),len(candidate['files']))
for path,sha in candidate['files'].items():
 assert hashlib.sha256((f.o.ROOT/path).read_bytes()).hexdigest()==sha,path
 assert hashlib.sha256((source/path).read_bytes()).hexdigest()==sha,path
assert hashlib.sha256((f.OUT/'candidate-source.zip').read_bytes()).hexdigest()==candidate['archive_sha256']
inputs={}
for path in ['compose.yaml','compose.reports-qa.yaml','docs/build-governance/fa2_ops.py','docs/releases/2026-09-09-fa2-remediation/TRANSFER-RUNBOOK.md','docs/releases/2026-09-09-fa2-remediation/update-qa.py','docs/releases/2026-09-09-fa2-remediation/finish-qa.py','docs/releases/2026-09-09-fa2-remediation/verify-qa.py']:
 p=f.o.ROOT/path
 if p.exists():inputs[path]=hashlib.sha256(p.read_bytes()).hexdigest()
f.save('candidate-deployment.json',{'source_commit':git('rev-parse','HEAD'),'isolated_repository':str(source),
 'source_archive_sha256':candidate['archive_sha256'],'tracked_source_files':len(tracked),'source_matches_working_files':True,
 'engine':candidate['engine'],'deployment_input_sha256':inputs,'main_deployment_executed':False,
 'notes':'Source commit is in an isolated release repository, not the user workspace. Runtime source is separately sealed in engine-proof.json. Environment secrets are excluded.'})
qa=f.audit.snapshot(f.o.QA);main=f.audit.snapshot('baseer_dev')
f.save('live-preservation-after-qa-update.json' if '--after-qa' in sys.argv else 'live-preservation-before-qa-update.json',{'qa_unchanged':qa==json.loads((f.OUT/'qa-before.json').read_text()),
 'main_unchanged':main==json.loads((f.OUT/'main-before.json').read_text()),'qa_current':qa,'main_current':main})
assert main==json.loads((f.OUT/'main-before.json').read_text()),'Main live changed; investigate'
print('Sealed',git('rev-parse','HEAD'),len(tracked),'files; main preserved; QA baseline equal',qa==json.loads((f.OUT/'qa-before.json').read_text()))
