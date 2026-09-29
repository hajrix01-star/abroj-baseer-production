"""Isolated synthetic rehearsal. Never mutates MAIN or published source."""
import json, subprocess, sys, hashlib, tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BACK = ROOT / '.local-backups/90day-simulation-20260910'
DB = 'baseer_odoo_dev-db-1'
QA = 'baseer_odoo_dev-ic1_qa-1'
OLD = 'baseer_ic1_20260910'
NEW = 'baseer_sim90_20260910'
ADDONS = '/usr/lib/python3/dist-packages/odoo/addons,/mnt/ic1-addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19'

def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def sql(db, query):
    assert db in (OLD, NEW, 'postgres', 'baseer_dev')
    if db == 'baseer_dev':
        query = 'BEGIN READ ONLY; ' + query + '; COMMIT;'
    return run(['docker','exec','-i',DB,'psql','-U','odoo','-d',db,'-qAt','-v','ON_ERROR_STOP=1'],input=query,text=True,encoding='utf8',capture_output=True).stdout.strip()

def signatures(db):
    tables=sql(db,"SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'account_%' OR tablename LIKE 'baseer_%' OR tablename LIKE 'hr_%' OR tablename IN ('res_company','res_users','res_partner','res_groups','res_groups_users_rel')) ORDER BY tablename").splitlines()
    parts=[]
    for table in tables:
        quoted='"'+table.replace('"','""')+'"'
        parts.append("SELECT '"+table+"' AS name,count(*) AS rows,md5(coalesce(string_agg(h,'' ORDER BY h),'')) AS hash FROM (SELECT md5(row_to_json(t)::text) h FROM "+quoted+' t)s')
    return json.loads(sql(db,'SELECT json_agg(x ORDER BY name) FROM ('+' UNION ALL '.join(parts)+')x'))

def evidence_before():
    save(OUT/'main-before.json',signatures('baseer_dev'))
    refs=json.loads(sql(OLD,"SELECT coalesce(json_agg(t),'[]') FROM (SELECT store_fname,checksum,file_size FROM ir_attachment WHERE store_fname IS NOT NULL)t"))
    required={OLD+'/'+r['store_fname']:r for r in refs}; found=set()
    with tarfile.open(BACK/'qa-filestore.tar.gz','r:gz') as archive:
        for item in archive:
            if item.name in required:
                ref=required[item.name]
                assert item.isfile() and item.size==ref['file_size']
                assert hashlib.sha1(archive.extractfile(item).read()).hexdigest()==ref['checksum']
                found.add(item.name)
    assert found==set(required),'Old QA attachment coverage incomplete'
    save(OUT/'backup-attachments.json',{'references':len(refs),'unique_files':len(found),'all_checksums_verified':True})
    print('PRESERVATION_BASELINE_AND_ATTACHMENTS_VERIFIED',len(refs),flush=True)

def cutover():
    retained='baseer_ic1_before_sim90_20260910'
    assert sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+retained+"'")=='0'
    for filename in ('hr.json','sales.json','purchases.json'):
        assert (OUT/'runtime'/filename).is_file(),filename
    with (BACK/'simulation-ready.dump').open('wb') as handle:
        run(['docker','exec',DB,'pg_dump','-U','odoo','-Fc',NEW],stdout=handle,stderr=subprocess.PIPE)
    run(['docker','exec',QA,'tar','-czf','/tmp/sim90-ready-filestore.tar.gz','-C','/var/lib/odoo/filestore',NEW],capture_output=True)
    run(['docker','cp',QA+':/tmp/sim90-ready-filestore.tar.gz',str(BACK/'simulation-ready-filestore.tar.gz')],capture_output=True)
    save(OUT/'simulation-backup.json',{'database':NEW,'path':str(BACK),'dump_sha256':hashlib.sha256((BACK/'simulation-ready.dump').read_bytes()).hexdigest(),'filestore_sha256':hashlib.sha256((BACK/'simulation-ready-filestore.tar.gz').read_bytes()).hexdigest()})
    run(['docker','stop','--time','30',QA],capture_output=True)
    try:
        assert sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname IN ('"+OLD+"','"+NEW+"')")=='0','Data writers still active'
        sql('postgres','ALTER DATABASE "'+OLD+'" RENAME TO "'+retained+'"; ALTER DATABASE "'+NEW+'" RENAME TO "'+OLD+'";')
        image=json.loads(run(['docker','inspect',QA],capture_output=True,text=True).stdout)[0]['Config']['Image']
        code="from pathlib import Path; root=Path('/var/lib/odoo/filestore').resolve(); old=root/'"+OLD+"'; new=root/'"+NEW+"'; kept=root/'"+retained+"'; assert all(p.resolve().parent==root for p in (old,new,kept)); assert old.is_dir() and new.is_dir() and not kept.exists(); old.rename(kept); new.rename(old)"
        run(['docker','run','--rm','--network','none','--volumes-from',QA,'--entrypoint','python3',image,'-c',code],capture_output=True)
    finally:
        run(['docker','start',QA],capture_output=True)
    after=signatures('baseer_dev')
    before=sorted(json.loads((OUT/'main-before.json').read_text(encoding='utf8')), key=lambda row: row['name'])
    save(OUT/'main-after.json',after)
    save(OUT/'cutover.json',{'active_database':OLD,'retained_database':retained,'port':18075,'main_tables_unchanged':before==after,'main_tables_checked':len(after),'source_code_changed':False,'github_changed':False})
    print('QA_CUTOVER_COMPLETE',len(after),'MAIN_TABLES_IDENTICAL',before==after,flush=True)

def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def shell(script, database=NEW):
    assert database==NEW or (database==OLD and (OUT/'cutover.json').is_file())
    run(['docker','exec',QA,'mkdir','-p','/tmp/sim90'],capture_output=True)
    run(['docker','cp',str(OUT/script),QA+':/tmp/sim90/'+script],capture_output=True)
    payload="exec(compile(open('/tmp/sim90/"+script+"','rb').read(),'/tmp/sim90/"+script+"','exec'))\n"
    with (OUT/(script+'.log')).open('wb') as log:
        run(['docker','exec','-i',QA,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+database,'--no-http','--max-cron-threads=0'],input=payload.encode(),stdout=log,stderr=subprocess.STDOUT)
    run(['docker','cp',QA+':/tmp/sim90/.',str(OUT/'runtime')],capture_output=True)
    print('SHELL_COMPLETE',script,flush=True)

def prepare():
    BACK.mkdir(parents=True,exist_ok=True)
    runtime=json.loads(run(['docker','inspect',QA],capture_output=True,text=True).stdout)[0]
    assert runtime['HostConfig']['PortBindings']['8069/tcp'][0]['HostPort']=='18075'
    assert '--database='+OLD in runtime['Config']['Cmd']
    modules=json.loads(sql(OLD,"SELECT json_agg(x) FROM (SELECT name,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)x"))
    save(OUT/'environment-before.json',{'qa_database':OLD,'staging_database':NEW,'modules':modules,'runtime_command':runtime['Config']['Cmd'],'main_policy':'no mutation; source remains frozen'})
    dump=BACK/'qa-before.dump'
    if not dump.exists():
        with dump.open('wb') as f:
            run(['docker','exec',DB,'pg_dump','-U','odoo','-Fc',OLD],stdout=f,stderr=subprocess.PIPE)
        with dump.open('rb') as f:
            run(['docker','exec','-i',DB,'pg_restore','--list'],stdin=f,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        run(['docker','exec',QA,'tar','-czf','/tmp/sim90-qa-filestore.tar.gz','-C','/var/lib/odoo/filestore',OLD],capture_output=True)
        run(['docker','cp',QA+':/tmp/sim90-qa-filestore.tar.gz',str(BACK/'qa-filestore.tar.gz')],capture_output=True)
    save(OUT/'backup.json',{'database':OLD,'path':str(BACK),'dump_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'filestore_bytes':(BACK/'qa-filestore.tar.gz').stat().st_size,'dump_toc_verified':True,'old_database_retained_at_cutover':True})
    if sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+NEW+"'")=='0':
        run(['docker','exec',DB,'createdb','-U','odoo','-O','odoo','--template=template0',NEW],capture_output=True)
    else:
        assert sql(NEW,"SELECT count(*) FROM pg_tables WHERE schemaname='public'")=='0','Only empty failed initialization may resume.'
    names=','.join(m['name'] for m in modules)
    with (OUT/'initialize.log').open('wb') as log:
        run(['docker','exec',QA,'/entrypoint.sh','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+NEW,'--init='+names,'--without-demo=all','--stop-after-init','--no-http','--max-cron-threads=0'],stdout=log,stderr=subprocess.STDOUT)
    print('STAGING_INITIALIZED',NEW,len(modules),flush=True)

if __name__=='__main__':
    if sys.argv[1]=='prepare': prepare()
    elif sys.argv[1]=='shell': shell(sys.argv[2],sys.argv[3] if len(sys.argv)>3 else NEW)
    elif sys.argv[1]=='evidence-before': evidence_before()
    elif sys.argv[1]=='cutover': cutover()
