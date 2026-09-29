"""Promote the already accepted QA source to MAIN; preserve native business data."""
import ast
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'docs/build-governance'))
import environment_backups as b
from ic2_release import review_go, verify_mounts

OUT = Path(__file__).resolve().parent
BACK = ROOT / '.local-backups/cash-tracing-repair-20260911'
SOURCE = BACK / 'candidate'
QA_EVIDENCE = ROOT / 'docs/audits/2026-09-10-90day-simulation/repair'
PARENT = 'f38e4c4934c377dac69cd563c2ed3ca30b61bf9e'
OLD_RELEASE = '2026-09-10-financial-register-sales'
NEW_RELEASE = '2026-09-11-cash-tracing-repair'
OLD_FOLDER = 'financial-register-sales-20260910'
NEW_FOLDER = 'cash-tracing-repair-20260911'
QA = 'baseer_odoo_dev-ic1_qa-1'
CLONE = 'baseer_cash_repair_main_20260911'
ADDONS = '/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19'
MODULES = ('baseer_cash_categories', 'baseer_pos_summary', 'baseer_financial_register')
META_TABLES = ('res_partner', 'res_groups', 'res_groups_privilege', 'ir_rule', 'ir_model_access')

def read(path):
    return json.loads(path.read_text(encoding='utf8'))

def sql(database, query):
    assert database in (b.MAIN, CLONE, 'baseer_ic1_20260910', 'postgres')
    return b.sql(database, 'BEGIN READ ONLY; ' + query + '; COMMIT;').replace('BEGIN\n', '').removesuffix('\nCOMMIT')

def inventory(folder):
    return {p.relative_to(folder).as_posix(): b.sha(p) for p in sorted(folder.rglob('*')) if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts and p.suffix != '.pyc'}

def freeze():
    accepted = read(QA_EVIDENCE / 'candidate.json')
    prior = read(ROOT / 'docs/releases' / OLD_RELEASE / 'candidate.json')
    assert accepted['parent'] == prior['commit'] == PARENT
    assert inventory(Path(accepted['source_directory'])) == accepted['files']
    assert read(QA_EVIDENCE / 'verification-final.json')['independent_status'] == 'PASS'
    assert read(QA_EVIDENCE / 'qa-smoke.json')['status'] == 'PASS'
    assert len(accepted['files']) == 1183 and len(accepted['changed_files']) == 6
    assert sorted(p for p in accepted['files'] if accepted['files'][p] != prior['files'].get(p)) == accepted['changed_files']
    assert not SOURCE.exists() and not (OUT / 'candidate.json').exists()
    for name, sha in accepted['files'].items():
        assert name.split('/')[0] in ('custom_addons', 'third_party_addons') and '..' not in Path(name).parts
        target = SOURCE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(accepted['source_directory']) / name, target)
        assert b.sha(target) == sha
    for command in (['git','init','--initial-branch=codex/cash-tracing-repair'], ['git','config','core.autocrlf','false'], ['git','add','--','custom_addons','third_party_addons'], ['git','-c','user.name=Codex Release','-c','user.email=codex-release@localhost','commit','-m','Fix payroll and POS cash source tracing']):
        b.run(command, cwd=SOURCE, capture_output=True)
    commit = b.run(['git','rev-parse','HEAD'], cwd=SOURCE, capture_output=True, text=True).stdout.strip()
    archive = OUT / 'candidate-source.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as stream:
        for name in sorted(accepted['files']): stream.write(SOURCE / name, name)
    evidence = ('verification-final.json','qa-smoke.json','PREDEPLOY-GO.md','COMPARISON.md','UI-REVIEW.md','closeout.json')
    result = dict(accepted, commit=commit, source_directory=str(SOURCE), archive_sha256=b.sha(archive), qa_evidence_directory=str(QA_EVIDENCE), evidence_sha256={name:b.sha(QA_EVIDENCE/name) for name in evidence})
    b.save(OUT / 'candidate.json', result)
    print('FROZEN', commit, len(result['files']), len(result['changed_files']), flush=True)

def verify_candidate():
    candidate = read(OUT / 'candidate.json')
    assert candidate['parent'] == PARENT and inventory(SOURCE) == candidate['files']
    assert b.sha(OUT / 'candidate-source.zip') == candidate['archive_sha256']
    assert b.run(['git','rev-parse','HEAD'], cwd=SOURCE, capture_output=True, text=True).stdout.strip() == candidate['commit']
    assert not b.run(['git','status','--porcelain'], cwd=SOURCE, capture_output=True, text=True).stdout.strip()
    assert all(b.sha(QA_EVIDENCE / name) == sha for name, sha in candidate['evidence_sha256'].items())
    return candidate

def snapshot(database):
    cols = json.loads(sql(database, """SELECT json_object_agg(table_name,cols) FROM (SELECT c.table_name,array_agg(c.column_name ORDER BY c.ordinal_position) cols FROM information_schema.columns c JOIN information_schema.tables t ON t.table_schema=c.table_schema AND t.table_name=c.table_name WHERE c.table_schema='public' AND t.table_type='BASE TABLE' AND (c.table_name ~ '^(account|baseer|hr|pos|resource|stock|sale|purchase|product)_' OR c.table_name IN ('res_company','res_partner','res_users','res_company_users_rel','ir_rule','ir_model_access') OR c.table_name LIKE 'res_groups%' OR c.table_name LIKE 'res_users%' OR c.table_name LIKE 'ir_rule%' OR c.table_name LIKE '%group%rel') GROUP BY c.table_name)t"""))
    parts = []
    for table in sorted(cols):
        parts.append("SELECT '"+table+"' name,count(*) rows,md5(coalesce(string_agg(h,'' ORDER BY h),'')) hash FROM (SELECT md5(row_to_json(t)::text) h FROM \""+table+'\" t)s')
    hashes = sorted(json.loads(sql(database, 'SELECT json_agg(t ORDER BY name) FROM ('+' UNION ALL '.join(parts)+')t')), key=lambda row:row['name'])
    meta = {table: json.loads(sql(database, 'SELECT json_agg(t ORDER BY id) FROM '+table+' t')) for table in META_TABLES}
    versions = json.loads(sql(database, "SELECT json_object_agg(name,latest_version) FROM ir_module_module WHERE state='installed'"))
    return {'columns':cols,'hashes':hashes,'metadata_rows':meta,'versions':versions}

def compare(before, after, expected_metadata=None):
    assert before['columns'] == after['columns'], 'Schema changed'
    old = {x['name']:x for x in before['hashes']}
    changed = [x['name'] for x in after['hashes'] if old[x['name']] != x]
    assert set(changed).issubset(META_TABLES), 'Business/security rows changed: '+str(changed)
    metadata = {}
    for table in changed:
        left = {x['id']:x for x in before['metadata_rows'][table]}
        right = {x['id']:x for x in after['metadata_rows'][table]}
        assert left.keys() == right.keys()
        rows = {}
        for ident in left:
            delta = {k:{'before':left[ident].get(k),'after':right[ident].get(k)} for k in set(left[ident])|set(right[ident]) if left[ident].get(k)!=right[ident].get(k)}
            if delta:
                assert set(delta).issubset({'write_date','write_uid'}), (table,ident,delta)
                if expected_metadata is not None:
                    allowed = expected_metadata.get(table,{}).get(str(ident),{})
                    assert set(delta).issubset(allowed), (table,ident,delta)
                    if 'write_uid' in delta: assert delta['write_uid']['after'] == allowed['write_uid']['after']
                rows[str(ident)] = delta
        metadata[table] = rows
    candidate = verify_candidate()
    assert after['versions'] == dict(before['versions'], **candidate['versions']), 'Unexpected module version changes'
    return {'candidate':candidate['commit'],'all_business_exact':True,'security_exact':True,'schema_exact':True,'module_versions_exact':True,'protected_tables':len(old),'all_rows_exact':not changed,'technical_metadata_only':metadata}

def run_upgrade(container, database, label):
    assert (container,database) in ((QA,CLONE),)
    verify_qa_source()
    with (OUT / (label+'.log')).open('wb') as log:
        b.run(['docker','exec',container,'/entrypoint.sh','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+database,'--update='+','.join(MODULES),'--stop-after-init','--no-http','--max-cron-threads=0'], stdout=log, stderr=log)

def verify_qa_source():
    candidate=verify_candidate();runtime=b.inspect(QA)
    assert runtime['Config']['Image']==candidate['image']
    files={}
    for destination, prefix in (('/mnt/baseer-addons','custom_addons/'),('/mnt/third-party-addons','third_party_addons/')):
        mount=next(m for m in runtime['Mounts'] if m['Destination']==destination)
        assert not mount['RW']
        files.update({prefix+p:sha for p,sha in inventory(Path(mount['Source'])).items()})
    assert files==candidate['files']
    b.save(OUT/'clone-runtime-source.json',{'candidate':candidate['commit'],'image':runtime['Config']['Image'],'source_tree_exact':True,'files':len(files)})

def rehearsal():
    candidate = verify_candidate()
    verify_mounts(b.inspect(b.MAIN_CONTAINER), OLD_FOLDER, candidate['image'])
    dump = BACK/'rehearsal-main.dump'
    if sql('postgres', "SELECT count(*) FROM pg_database WHERE datname='"+CLONE+"'") == '0':
        before = snapshot(b.MAIN)
        b.save(OUT/'main-live-before-rehearsal.json', before)
        with dump.open('wb') as handle: b.run(['docker','exec',b.DB,'pg_dump','-U','odoo','-Fc',b.MAIN], stdout=handle, stderr=subprocess.PIPE)
        b.run(['docker','exec',b.DB,'createdb','-U','odoo','-O','odoo','--template=template0',CLONE], capture_output=True)
        with dump.open('rb') as handle: b.run(['docker','exec','-i',b.DB,'pg_restore','-U','odoo','-d',CLONE,'--exit-on-error'], stdin=handle, capture_output=True)
    else:
        assert (OUT/'main-live-before-rehearsal.json').is_file() and not (OUT/'clone-before.json').exists(), 'Only an unmodified snapshot may resume'
        before=read(OUT/'main-live-before-rehearsal.json');before['hashes']=sorted(before['hashes'],key=lambda row:row['name'])
        b.save(OUT/'main-live-before-rehearsal.json',before)
    copied = snapshot(CLONE)
    assert before == copied and snapshot(b.MAIN) == before, 'MAIN changed during rehearsal snapshot'
    archive = BACK/'rehearsal-main-filestore.tar.gz'
    b.archive_filestore(b.MAIN, archive)
    b.run(['docker','cp',str(archive),QA+':/tmp/main-repair-filestore.tar.gz'], capture_output=True)
    code = "import tarfile; from pathlib import Path; root=Path('/var/lib/odoo/filestore').resolve(); target=root/'"+CLONE+"'; assert not target.exists() and target.resolve().parent==root; target.mkdir(); archive=tarfile.open('/tmp/main-repair-filestore.tar.gz');\nfor m in archive:\n p=Path(m.name); assert p.parts[0]=='baseer_dev' and '..' not in p.parts and not p.is_absolute() and (m.isdir() or m.isfile()); dest=target.joinpath(*p.parts[1:]); assert dest.resolve().is_relative_to(target);\n if m.isdir(): dest.mkdir(parents=True,exist_ok=True)\n else: dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(archive.extractfile(m).read())"
    b.run(['docker','exec',QA,'python3','-c',code], capture_output=True)
    # Verify immutable file references from the restored DB, not a moving live query.
    refs=json.loads(sql(CLONE,"SELECT coalesce(json_agg(t),'[]') FROM (SELECT store_fname,checksum,file_size FROM ir_attachment WHERE store_fname IS NOT NULL)t"))
    import tarfile
    required={b.MAIN+'/'+x['store_fname']:x for x in refs};found=set()
    with tarfile.open(archive,'r:gz') as stream:
        for member in stream:
            if member.name in required:
                ref=required[member.name];assert member.size==ref['file_size'] and hashlib.sha1(stream.extractfile(member).read()).hexdigest()==ref['checksum'];found.add(member.name)
    assert found==set(required)
    b.save(OUT/'clone-before.json', copied)
    b.save(OUT/'clone-backup.json', {'dump_sha256':b.sha(dump),'filestore_sha256':b.sha(archive),'attachment_references_verified':len(refs),'business_snapshot_consistent':True})
    run_upgrade(QA, CLONE, 'clone-upgrade')
    after=snapshot(CLONE);b.save(OUT/'clone-after.json',after)
    b.save(OUT/'clone-preservation.json',compare(copied,after))
    assert snapshot(b.MAIN)==before, 'MAIN changed during rehearsal'
    print('REHEARSAL_PASS',len(copied['hashes']),flush=True)

def publish():
    candidate=verify_candidate();review_go(OUT/'PREDEPLOY-GO.md',candidate['commit'])
    rehearsal_proof=read(OUT/'clone-preservation.json')
    assert rehearsal_proof['candidate']==candidate['commit'] and rehearsal_proof['all_business_exact']
    assert read(OUT/'clone-smoke.json')['status']=='PASS'
    assert not (OUT/'main-backup.json').exists(), 'Publish already started; inspect before resuming'
    verify_mounts(b.inspect(b.MAIN_CONTAINER),OLD_FOLDER,candidate['image'])
    assert sql(b.MAIN,"SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')")=='0'
    old_prefix='./.local-backups/'+OLD_FOLDER+'/candidate/'
    new_prefix='./.local-backups/'+NEW_FOLDER+'/candidate/'
    configs={name:(ROOT/name).read_text(encoding='utf8') for name in ('compose.yaml','compose.main-release.yaml')}
    assert all(content.count(old_prefix)==3 for content in configs.values())
    lock=b.BACK/'maintenance.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('x') as handle: handle.write('Cash repair '+candidate['commit'])
    completed=False
    try:
        b.run(['docker','stop','--time','30',b.MAIN_CONTAINER],capture_output=True)
        b.save(OUT/'main-backup.json',b.backup(b.MAIN))
        before=snapshot(b.MAIN);b.save(OUT/'main-before.json',before)
        for name, content in configs.items():
            shutil.copy2(ROOT/name,BACK/(name+'.before'));(ROOT/name).write_text(content.replace(old_prefix,new_prefix),encoding='utf8')
        with (OUT/'main-upgrade.log').open('wb') as log:
            b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','run','--rm','--no-deps','-T','odoo','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+b.MAIN,'--update='+','.join(MODULES),'--stop-after-init','--no-http','--max-cron-threads=0'],cwd=ROOT,stdout=log,stderr=log)
        after=snapshot(b.MAIN);b.save(OUT/'main-after.json',after)
        b.save(OUT/'main-preservation.json',compare(before,after,rehearsal_proof['technical_metadata_only']))
        helper=ROOT/'docs/build-governance/environment_backups.py';content=helper.read_text(encoding='utf8')
        assert OLD_RELEASE in content and OLD_FOLDER in content
        shutil.copy2(helper,BACK/'environment_backups.py.before')
        helper.write_text(content.replace(OLD_RELEASE,NEW_RELEASE).replace(OLD_FOLDER,NEW_FOLDER),encoding='utf8')
        b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','up','-d','--no-deps','odoo'],cwd=ROOT,capture_output=True)
        for attempt in range(20):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18069/web/login',timeout=3) as response:
                    if response.status==200: break
            except OSError: pass
            time.sleep(1)
        else: raise RuntimeError('MAIN health check failed')
        verify_runtime()
        completed=True
    finally:
        if completed: lock.unlink()

def verify_runtime():
    candidate=verify_candidate();runtime=b.inspect(b.MAIN_CONTAINER)
    verify_mounts(runtime,NEW_FOLDER,candidate['image'])
    assert '--database='+b.MAIN in runtime['Config']['Cmd']
    assert runtime['HostConfig']['PortBindings']['8069/tcp'][0]['HostPort']=='18069'
    assert sql(b.MAIN,"SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')")=='0'
    versions=json.loads(sql(b.MAIN,"SELECT json_object_agg(name,latest_version) FROM ir_module_module WHERE name IN ('"+"','".join(MODULES)+"')"))
    assert versions==candidate['versions']
    with urllib.request.urlopen('http://127.0.0.1:18069/web/login',timeout=5) as response: assert response.status==200
    b.save(OUT/'runtime.json',{'candidate':candidate['commit'],'http':200,'source_tree_exact':True,'no_pending_modules':True,'versions':versions,'mounts':runtime['Mounts'],'image':candidate['image']})
    print('MAIN_RUNTIME_PASS',candidate['commit'],flush=True)

def smoke(database):
    assert database in (CLONE,b.MAIN)
    candidate=verify_candidate();container=QA if database==CLONE else b.MAIN_CONTAINER
    script=(OUT/'main_smoke.py').read_bytes()
    payload=('CANDIDATE = '+repr(candidate)+'\nexec(compile('+repr(script)+',"main_smoke.py","exec"))\n').encode()
    process=subprocess.run(['docker','exec','-i',container,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+database,'--no-http','--max-cron-threads=0'],input=payload,capture_output=True)
    label='clone' if database==CLONE else 'main'
    (OUT/(label+'-smoke.log')).write_bytes(process.stdout+process.stderr);process.check_returncode()
    line=next(x for x in process.stdout.decode().splitlines() if x.startswith('MAIN_REPAIR_SMOKE_JSON '))
    result=json.loads(line.removeprefix('MAIN_REPAIR_SMOKE_JSON '));b.save(OUT/(label+'-smoke.json'),result)
    print(label.upper()+'_SMOKE_PASS',len(result['checks']),flush=True)

if __name__=='__main__':
    {'freeze':freeze,'rehearsal':rehearsal,'publish':publish,'verify-runtime':verify_runtime,'verify-qa-source':verify_qa_source,'clone-smoke':lambda:smoke(CLONE),'main-smoke':lambda:smoke(b.MAIN)}[sys.argv[1]]()
