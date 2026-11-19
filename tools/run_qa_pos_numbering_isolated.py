"""Bounded isolated QA runner: never mounts production or deployed QA data."""
import datetime
import json
import os
import pathlib
import secrets
import subprocess
import tarfile

BASE = pathlib.Path('/srv/baseer-qa/test-runs/posnum1-20261120')
NET = 'posnum1-20261120-internal'
PG = 'posnum1-20261120-db'
IMAGE = 'sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd'
PGIMAGE = 'sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94'

def call(args):
    return subprocess.check_output(args, text=True).strip()

assert BASE.is_dir() and (BASE/'candidate.tar').is_file()
resume = (BASE/'PREPARED.json').exists()
if resume:
    active = call(['docker','ps','--filter','label=baseer.scope=posnum1-qa','--format','{{.Names}}']).splitlines()
    assert active == [PG], 'Previous owned Odoo test must finish before reusing database'
label = 'r2' if resume else 'r1'
source = BASE/('candidate-' + label)
source.mkdir(mode=0o755)
with tarfile.open(BASE/'candidate.tar') as archive:
    for member in archive.getmembers():
        path = pathlib.PurePosixPath(member.name)
        assert not path.is_absolute() and '..' not in path.parts
        assert path.parts[0] == 'custom_addons' and not member.issym() and not member.islnk()
    archive.extractall(source, filter='data')
data = BASE/'odoo-data'
if not resume:
    password = secrets.token_urlsafe(32)
    for filename, content in (
        ('postgres.env', f'POSTGRES_USER=posnum1\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=postgres\n'),
        ('runtime.env', f'HOST={PG}\nUSER=posnum1\nPASSWORD={password}\n'),
    ):
        path = BASE/filename
        path.write_text(content)
        path.chmod(0o600)
    data.mkdir(mode=0o755)
    os.chown(data, 100, 101)
    call(['docker','network','create','--internal','--label','baseer.scope=posnum1-qa',NET])
    call(['docker','run','-d','--name',PG,'--network',NET,'--memory','256m','--cpus','0.25',
          '--pids-limit','128','--label','baseer.scope=posnum1-qa','--env-file',str(BASE/'postgres.env'),PGIMAGE])
import time
for _ in range(30):
    if subprocess.run(['docker','exec',PG,'pg_isready','-U','posnum1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0:
        break
    time.sleep(1)
else:
    raise RuntimeError('Owned PostgreSQL not ready')
assert json.loads(call(['docker','network','inspect',NET]))[0]['Internal']
(BASE/('PREPARED-' + label + '.json')).write_text(json.dumps({'image':IMAGE,'network':NET,'postgres':PG,
    'database':'baseer_qa_posnum1','production_mounts':False,'ports':False,'source':(BASE/'CANDIDATE_COMMIT').read_text().strip()}))
if not resume:
    (BASE/'PREPARED.json').write_text((BASE/'PREPARED-r1.json').read_text())
common = ['docker','run','--rm','--network',NET,'--memory','1280m','--cpus','0.65','--pids-limit','256',
    '--cap-drop','ALL','--security-opt','no-new-privileges','--label','baseer.scope=posnum1-qa',
    '--env-file',str(BASE/'runtime.env'),'--mount',f'type=bind,src={data},dst=/var/lib/odoo',
    '--mount',f'type=bind,src={source / "custom_addons"},dst=/mnt/candidate,readonly']
odoo = ['--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/candidate',
        '-d','baseer_qa_posnum1','--max-cron-threads=0','--workers=0','--without-demo=all']
test_log = BASE/('odoo-tests-' + label + '.log')
with test_log.open('w') as log:
    result = subprocess.run(common+['--name','posnum1-20261120-tests',IMAGE,'odoo']+odoo+
        ['-u' if resume else '-i','baseer_pos_cache_resilience','--test-enable','--test-tags=/baseer_pos_cache_resilience',
         '--stop-after-init','--log-level=test'],stdout=log,stderr=subprocess.STDOUT)
assert result.returncode == 0, 'Odoo test process failed; inspect retained log'
text = test_log.read_text()
assert '0 failed, 0 error(s)' in text and 'test_receipt_recovery_named_alias_compiles' in text, 'Odoo tests failed or absent'
with (BASE/'asset-acceptance.log').open('w') as log:
    result = subprocess.run(common+['-i','--name','posnum1-20261120-assets',IMAGE,'odoo','shell']+odoo+
        ['--no-http','--log-level=warn'],input=(BASE/'qa_pos_numbering_acceptance.py').read_text(),
        text=True,stdout=log,stderr=subprocess.STDOUT)
assert result.returncode == 0, 'Asset acceptance failed; inspect log'
line = next(line for line in (BASE/'asset-acceptance.log').read_text().splitlines() if line.startswith('POS_NUM1_QA_ACCEPTANCE='))
acceptance = json.loads(line.split('=',1)[1])
(BASE/'ACCEPTANCE.json').write_text(json.dumps(acceptance,indent=2))
node = subprocess.run(['node','--test',str(source/'custom_addons/baseer_pos_cache_resilience/static/tests/receipt_numbering.test.mjs'),
    str(source/'custom_addons/baseer_pos_cache_resilience/static/tests/cache_resilience.test.mjs')],capture_output=True,text=True)
(BASE/'node-tests.log').write_text(node.stdout+node.stderr)
assert node.returncode == 0
modules = subprocess.run(['node',str(BASE/'qa_pos_numbering_modules.mjs'),str(BASE/'ACCEPTANCE.json'),str(source)],capture_output=True,text=True)
(BASE/'compiled-modules.log').write_text(modules.stdout+modules.stderr)
assert modules.returncode == 0, 'Compiled module execution failed'
call(['docker','stop',PG])
summary = {key:value for key,value in acceptance.items() if key!='compiled'}
summary.update({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'node_tests':27,
    'compiled_module_execution':True,'isolated_database_only':True,'postgres_stopped':True})
(BASE/'SUMMARY.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary),flush=True)
