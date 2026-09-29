"""Reproducible QA-only installation operations; no credentials in evidence."""
import ast, hashlib, json, re, shutil, subprocess, sys, urllib.request, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/releases/2026-09-08-om-payroll'
BACK = ROOT / '.local-backups/om-payroll-20260908'
SHA = 'bf4b5867315da40466c2a830a087986427c61b9a'
DB = 'baseer_odoo_dev-db-1'
QA = 'baseer_reports_qa_20260907'
CONTAINER = 'baseer_odoo_dev-reports_qa-1'
ADDONS = ['om_hr_payroll', 'om_hr_payroll_account']
def run(args, **kw):
    if kw.get('text'): kw.setdefault('encoding','utf-8')
    return subprocess.run(args, cwd=ROOT, check=True, **kw)
def sql(db, query):
    return run(['docker','exec','-i',DB,'sh','-c','psql -U "$POSTGRES_USER" -d '+db+' -At -v ON_ERROR_STOP=1'],input=query,text=True,capture_output=True).stdout.strip()
def write(name, data):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def source():
    BACK.mkdir(parents=True,exist_ok=True)
    archive=BACK/'upstream.zip'
    urllib.request.urlretrieve('https://codeload.github.com/odoomates/odooapps/zip/'+SHA,archive)
    target=ROOT/'third_party_addons/odoomates_19'
    assert not target.exists(), 'source directory already exists'
    target.mkdir()
    files=[]
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            parts=Path(entry.filename).parts
            if len(parts)<3 or parts[1] not in ADDONS or entry.is_dir(): continue
            dest=target.joinpath(*parts[1:]).resolve()
            assert dest.is_relative_to(target.resolve())
            dest.parent.mkdir(parents=True,exist_ok=True)
            data=z.read(entry)
            dest.write_bytes(data)
            files.append({'path':dest.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(data).hexdigest()})
    manifests={name:ast.literal_eval((target/name/'__manifest__.py').read_text(encoding='utf-8')) for name in ADDONS}
    write('source.json',{'commit':SHA,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'manifests':manifests,'files':files})
    print('Pinned source', SHA, len(files), 'files', {k:v['depends'] for k,v in manifests.items()})
def snapshot(db,label):
    result={}
    for table in ['account_move','account_move_line','account_payment','res_company','res_partner','res_users','res_groups_users_rel','res_company_users_rel']:
        cols=sql(db,"SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='"+table+"' AND column_name NOT IN ('password','totp_secret');")
        result[table]=json.loads(sql(db,"SELECT json_build_object('count',count(*),'hash',md5(coalesce(string_agg(j,',' ORDER BY j),''))) FROM (SELECT row_to_json(t)::text j FROM (SELECT "+cols+" FROM "+table+")t)s;"))
    result['modules']=json.loads(sql(db,"SELECT json_agg(t) FROM (SELECT name,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)t;"))
    write(label+'.json',result)
    print(label,{k:v for k,v in result.items() if k!='modules'},'installed',len(result['modules']))
def backup():
    dest=BACK/'preinstall'
    dest.mkdir(parents=True,exist_ok=False)
    run(['docker','stop',CONTAINER],capture_output=True)
    assert sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='"+QA+"';")=='0'
    snapshot(QA,'qa-before')
    run(['docker','exec',DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+QA+' -f /tmp/om-payroll-before.dump'])
    run(['docker','cp',DB+':/tmp/om-payroll-before.dump',str(dest/'database.dump')],capture_output=True)
    # Helper mounts existing volume read-only; QA is stopped for coherent snapshot.
    with (dest/'filestore.tar.gz').open('wb') as f:
        run(['docker','run','--rm','--volumes-from',CONTAINER+':ro','--entrypoint','tar','odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd','-czf','-','-C','/var/lib/odoo/filestore',QA],stdout=f)
    shutil.copy2(ROOT/'compose.reports-qa.yaml',dest/'compose.reports-qa.yaml')
    shutil.copy2(ROOT/'config/odoo.local.conf',dest/'odoo.local.conf')
    write('backup.json',[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in dest.iterdir()])
    print('QA stopped; coherent backup complete')
if __name__=='__main__':
    if sys.argv[1]=='source': source()
    elif sys.argv[1]=='snapshot': snapshot(sys.argv[2],sys.argv[3])
    elif sys.argv[1]=='backup': backup()
    elif sys.argv[1]=='checks':
        result=run(['docker','exec','-i',CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--database='+QA,'--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/om_payroll_checks.log'],input="exec(compile(open('/mnt/qa-evidence/om_payroll_checks.py').read(), 'om_payroll_checks.py', 'exec'))\n",text=True,capture_output=True)
        print(result.stdout)
    elif sys.argv[1]=='preservation':
        result={}
        for table in ['res_partner','res_groups_users_rel']:
            dump=run(['docker','exec',DB,'pg_restore','--data-only','--table='+table,'-f','-','/tmp/om-payroll-before.dump'],capture_output=True,text=True).stdout
            match=re.search(r'COPY public\.'+table+r' \((.*?)\) FROM stdin;\n(.*?)\n\\\.',dump,re.S)
            assert match,table
            cols,values=match.groups()
            query='BEGIN; CREATE TEMP TABLE om_before (LIKE '+table+'); COPY om_before ('+cols+') FROM stdin;\n'+values+'\n\\.\nSELECT json_build_object(\'before\',(SELECT json_agg(t) FROM (SELECT '+cols+' FROM om_before)t),\'after\',(SELECT json_agg(t) FROM (SELECT '+cols+' FROM '+table+')t)); ROLLBACK;'
            payload=sql(QA,query)
            data=json.loads(payload[payload.index('{'):payload.rindex('}')+1])
            if table=='res_partner':
                before={x['id']:x for x in data['before']}; after={x['id']:x for x in data['after']}
                result[table]={'same_original_columns':before==after,'changed_fields':{str(k):[c for c in before[k] if before[k][c]!=after[k][c]] for k in before if before[k]!=after.get(k)},'added_ids':list(after.keys()-before.keys())}
            else:
                before={tuple(sorted(x.items())) for x in data['before']}; after={tuple(sorted(x.items())) for x in data['after']}
                result[table]={'added':[dict(x) for x in after-before],'removed':[dict(x) for x in before-after]}
        result['main_exact']=json.loads((OUT/'main-before.json').read_text())==json.loads((OUT/'main-after.json').read_text())
        result['persistent_slips']=int(sql(QA,'SELECT count(*) FROM hr_payslip;'))
        result['persistent_batches']=int(sql(QA,'SELECT count(*) FROM hr_payslip_run;'))
        result['group_added_xmlid']=sql(QA,"SELECT module||'.'||name FROM ir_model_data WHERE model='res.groups' AND res_id=71;")
        result['partner_identity']=json.loads(sql(QA,"SELECT json_agg(t) FROM (SELECT u.id user_id,u.partner_id FROM res_users u WHERE u.partner_id IN (2,3))t;"))
        write('preservation.json',result)
        print(json.dumps(result,indent=2))
