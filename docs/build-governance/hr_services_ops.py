"""HRS1 QA-only installation, preservation and immutable packaging."""
import json
import sys
import hashlib
import zipfile
import common_services_seed_ops as s
s.MODULE = 'baseer_hr_services'
s.OUT = s.o.ROOT / 'docs/releases/2026-09-08-hr-services'
s.BACK = s.o.ROOT / '.local-backups/hr-services-20260908'

def preservation():
    before = json.loads((s.OUT / 'qa-before.json').read_text(encoding='utf-8'))
    after = s.snapshot(s.o.QA)
    issues = []
    for table, rows in before.items():
        old={r['id']:r for r in rows}; new={r['id']:r for r in after[table]}
        if set(old)!=set(new): issues.append(table+': changed row identities')
        for rid,row in old.items():
            current=new.get(rid,{})
            if any(current.get(k)!=v for k,v in row.items()): issues.append(f'{table}:{rid}: changed original values')
            if any(v is not None for k,v in current.items() if k not in row): issues.append(f'{table}:{rid}: unexpected populated new field')
    main=s.snapshot('baseer_dev')==json.loads((s.OUT/'main-before.json').read_text(encoding='utf-8'))
    result={'original_qa_rows_unchanged':not issues,'main_unchanged':main,'issues':issues}
    s.save('preservation.json',result)
    assert not issues and main,result
    print(json.dumps(result))

if __name__=='__main__':
    mode=sys.argv[1]
    if mode=='install': s.install()
    elif mode=='retry-install':
        assert (s.BACK/'database.dump').exists()
        s.o.run(['docker','stop',s.o.CONTAINER],capture_output=True)
        try:
            s.o.run(['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','run','--rm','--no-deps','reports_qa','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+s.ADDONS,'--database='+s.o.QA,'--init='+s.MODULE,'--without-demo=all','--stop-after-init','--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/common_services_seed_install.log'],capture_output=True,text=True)
        finally: s.o.run(['docker','start',s.o.CONTAINER],capture_output=True)
    elif mode=='update': s.install(True)
    elif mode=='preservation': preservation()
    elif mode=='package':
        s.package()
        candidate=json.loads((s.OUT/'candidate.json').read_text(encoding='utf-8'))
        candidate['version']='HRS1 / 19.0.1.0.0'
        s.save('candidate.json',candidate)
    elif mode=='verify-package':
        candidate=json.loads((s.OUT/'candidate.json').read_text(encoding='utf-8'))
        archive=s.OUT/(s.MODULE+'-19.0.1.0.0.zip')
        assert hashlib.sha256(archive.read_bytes()).hexdigest()==candidate['zip_sha256']
        with zipfile.ZipFile(archive) as z:
            for path,digest in candidate['files'].items():
                assert hashlib.sha256((s.o.ROOT/path).read_bytes()).hexdigest()==digest,path
                member=path.replace('\\','/').removeprefix('custom_addons/')
                assert hashlib.sha256(z.read(member)).hexdigest()==digest,path
                mounted='/mnt/baseer-addons/'+member
                deployed=s.o.run(['docker','exec',s.o.CONTAINER,'sha256sum',mounted],capture_output=True,text=True).stdout.split()[0]
                assert deployed==digest,path
        state=s.o.sql(s.o.QA,"SELECT state FROM ir_module_module WHERE name='baseer_hr_services'")
        assert state=='installed',state
        s.save('verified-package.json',{'installed':True,'source_zip_deployed_hashes_match':True,'file_count':len(candidate['files']),'zip_sha256':candidate['zip_sha256']})
        print('All source, archive and QA mounted hashes match; module installed')
    elif mode=='checks':
        s.prior.shell("exec(compile(open('/mnt/qa-evidence/hr_services_checks.py').read(),'hr_services_checks.py','exec'))\n")
        d=json.loads((s.o.ROOT/'docs/build-governance/hr_services_checks.json').read_text(encoding='utf-8'))
        assert d['status']=='passed',d
    elif mode=='race-prepare':
        assert s.o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='baseer_hr_services_race'")=='0'
        s.o.run(['docker','exec',s.o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+s.o.QA+' -f /tmp/hr-services-race.dump'])
        s.o.run(['docker','exec',s.o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" baseer_hr_services_race'])
        s.o.run(['docker','exec',s.o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" -d baseer_hr_services_race --no-owner /tmp/hr-services-race.dump'])
        print('Race clone ready')
    elif mode=='race':
        s.prior.shell("exec(compile(open('/mnt/qa-evidence/hr_services_concurrency.py').read(),'hrs_race','exec'))\n",'baseer_hr_services_race')
        d=json.loads((s.o.ROOT/'docs/build-governance/hr_services_concurrency.json').read_text(encoding='utf-8'))
        assert d['status']=='passed',d
    elif mode=='race-remove':
        assert s.o.sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='baseer_hr_services_race'")=='0'
        s.o.run(['docker','exec',s.o.DB,'sh','-c','dropdb -U "$POSTGRES_USER" baseer_hr_services_race'])
        print('Race clone removed')
