"""SP1 QA-only backup, update, explicit consolidation and acceptance packaging."""
import ast, hashlib, json, sys, zipfile
import om_payroll_ops as o
import common_services_seed_ops as s

OUT=o.ROOT/'docs/releases/2026-09-09-shared-partners'
BACK=o.ROOT/'.local-backups/shared-partners-20260909'
MODULES=['baseer_purchase_batch','baseer_service_seed','baseer_hr_services','baseer_web_navigation']
COMPOSE=['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','run','--rm','--no-deps']
def save(name,data):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def update(backup=False):
    o.run(['docker','stop',o.CONTAINER],capture_output=True)
    try:
        if backup:
            BACK.mkdir(parents=True,exist_ok=False)
            save('qa-before.json',s.snapshot(o.QA));save('main-before.json',s.snapshot('baseer_dev'))
            o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/sp1-before.dump'])
            o.run(['docker','cp',o.DB+':/tmp/sp1-before.dump',str(BACK/'database.dump')],capture_output=True)
            o.run(COMPOSE+['--entrypoint','tar','reports_qa','-czf','/mnt/qa-evidence/sp1-filestore.tar.gz','-C','/var/lib/odoo/filestore',o.QA],capture_output=True)
            (o.ROOT/'docs/build-governance/sp1-filestore.tar.gz').replace(BACK/'filestore.tar.gz')
            save('backup.json',{p.name:{'path':str(p.relative_to(o.ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in BACK.iterdir() if p.is_file()})
        o.run(COMPOSE+['reports_qa','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+s.ADDONS,'--database='+o.QA,'--update='+','.join(MODULES),'--without-demo=all','--stop-after-init','--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/shared_partners_install.log'],capture_output=True,text=True)
    finally: o.run(['docker','start',o.CONTAINER],capture_output=True)
    print('QA update complete')
def preservation():
    before=json.loads((OUT/'qa-before.json').read_text(encoding='utf-8'));after=s.snapshot(o.QA)
    oldseed={r['id'] for r in json.loads((o.ROOT/'docs/build-governance/shared_partners_inventory.json').read_text(encoding='utf-8'))['seed']}
    issues=[];changes={};preference_changes={}
    for table,rows in before.items():
        old={r['id']:r for r in rows};new={r['id']:r for r in after[table]}
        removed=old.keys()-new.keys()
        if removed and (table!='res_partner' or not removed<=oldseed):issues.append(table+': unapproved original rows deleted')
        for rid,row in old.items():
            if table=='res_partner' and rid in removed and rid in oldseed:
                changes[str(rid)]=['deleted_by_user_authorization'];continue
            now=new.get(rid,{})
            delta=[k for k,v in row.items() if now.get(k)!=v]
            if not delta:continue
            if table=='res_partner' and rid==3 and set(delta)<= {'write_date'}:
                preference_changes[str(rid)]={'fields':delta,'reason':'Native current-user language menu acceptance test; original language restored','before':{k:row[k] for k in delta},'after':{k:now[k] for k in delta}}
            else: issues.append(f'{table}:{rid}:{delta}')
        if table!='res_partner' and new.keys()-old.keys():issues.append(table+': unexpected new rows')
    main=s.snapshot('baseer_dev')==json.loads((OUT/'main-before.json').read_text(encoding='utf-8'))
    save('preservation.json',{'original_financial_rows_unchanged':not issues,'no_unapproved_changes':not issues,'main_unchanged':main,'deleted_seed_sources':len(changes),'authorized_current_user_preference_metadata':preference_changes,'issues':issues})
    assert not issues and main,issues
    print('Preservation passed; deleted seed sources:',len(changes))
def package():
    files=sorted(p for m in MODULES for p in (o.ROOT/'custom_addons'/m).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    OUT.mkdir(parents=True,exist_ok=True);archive=OUT/'baseer-shared-partners-SP1.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,p.relative_to(o.ROOT/'custom_addons'))
    save('candidate.json',{'database':o.QA,'modules':{m:ast.literal_eval((o.ROOT/'custom_addons'/m/'__manifest__.py').read_text(encoding='utf-8'))['version'] for m in MODULES},'zip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':{p.relative_to(o.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
    print('Packaged files:',len(files))
if __name__=='__main__':
    mode=sys.argv[1]
    if mode=='update-first':update(True)
    elif mode=='update':update()
    elif mode=='checks':
        s.prior.shell("exec(compile(open('/mnt/qa-evidence/shared_partners_checks.py').read(),'shared_partners_checks.py','exec'))\n")
        d=json.loads((o.ROOT/'docs/build-governance/shared_partners_checks.json').read_text(encoding='utf-8'))
        assert d['status']=='passed',d
    elif mode in ('consolidate','dry-run'):
        s.prior.shell('SP1_COMMIT='+str(mode=='consolidate')+"\nexec(compile(open('/mnt/qa-evidence/shared_partners_consolidate.py').read(),'shared_partners_consolidate.py','exec'))\n")
        suffix='_applied' if mode=='consolidate' else '_dryrun'
        d=json.loads((o.ROOT/('docs/build-governance/shared_partners_consolidate'+suffix+'.json')).read_text(encoding='utf-8'))
        assert d['status']=='passed',d
    elif mode=='preservation':preservation()
    elif mode=='package':package()
    elif mode=='verify':
        from xml.etree import ElementTree
        d=json.loads((OUT/'candidate.json').read_text(encoding='utf-8'))
        archive=OUT/'baseer-shared-partners-SP1.zip'
        assert hashlib.sha256(archive.read_bytes()).hexdigest()==d['zip_sha256']
        with zipfile.ZipFile(archive) as z:
            assert len(z.namelist())==len(d['files'])
            for path,digest in d['files'].items():
                p=o.ROOT/path
                assert hashlib.sha256(p.read_bytes()).hexdigest()==digest,path
                assert hashlib.sha256(z.read(path.removeprefix('custom_addons/'))).hexdigest()==digest,path
                if p.suffix=='.py':ast.parse(p.read_text(encoding='utf-8'))
                elif p.suffix=='.xml':ElementTree.parse(p)
        remote="import hashlib,json,pathlib; d=json.load(open('/mnt/qa-evidence/../qa-evidence/sp1-candidate.json')); errors=[p for p,h in d['files'].items() if hashlib.sha256(pathlib.Path(p.replace('custom_addons/','/mnt/baseer-addons/',1)).read_bytes()).hexdigest()!=h]; assert not errors,errors; print('Mounted files match:',len(d['files']))"
        temp=o.ROOT/'docs/build-governance/sp1-candidate.json'
        temp.write_text(json.dumps(d),encoding='utf-8')
        r=o.run(['docker','exec',o.CONTAINER,'python3','-c',remote],capture_output=True,text=True)
        save('candidate-verification.json',{'status':'passed','zip_sha256':d['zip_sha256'],'file_count':len(d['files']),'source_zip_mounted_files_match':True,'python_ast_xml_parse':True})
        print(r.stdout)
    elif mode=='guards':
        s.prior.shell("exec(compile(open('/mnt/qa-evidence/shared_partners_guards.py').read(),'sp1_guards','exec'))\n")
        d=json.loads((o.ROOT/'docs/build-governance/shared_partners_guards.json').read_text(encoding='utf-8'))
        assert d['status']=='passed',d
    elif mode=='race-prepare':
        assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='baseer_shared_partners_race'")=='0'
        o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/sp1-race.dump'])
        o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" baseer_shared_partners_race'])
        o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" -d baseer_shared_partners_race --no-owner /tmp/sp1-race.dump'])
        print('Race clone ready')
    elif mode=='race':
        s.prior.shell("exec(compile(open('/mnt/qa-evidence/shared_partners_concurrency.py').read(),'sp1_race','exec'))\n",'baseer_shared_partners_race')
        d=json.loads((o.ROOT/'docs/build-governance/shared_partners_concurrency.json').read_text(encoding='utf-8'))
        assert d['status']=='passed',d
    elif mode=='race-remove':
        assert o.sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='baseer_shared_partners_race'")=='0'
        o.run(['docker','exec',o.DB,'sh','-c','dropdb -U "$POSTGRES_USER" baseer_shared_partners_race'])
        print('Race clone removed')
