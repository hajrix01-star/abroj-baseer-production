"""FA1 frozen inventory and isolated test databases; no QA/main mutations."""
import ast,hashlib,json,subprocess,sys,time,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import om_payroll_ops as o

OUT=o.ROOT/'docs/audits/2026-09-09-full'
SCOPES=('core','payroll','sales','security')
ADDONS='/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19'
def db(scope):
    assert scope in SCOPES
    return 'baseer_audit_'+scope+'_20260909'
def save(name,value):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def snapshot(database):
    tables=['account_move','account_move_line','account_payment','account_partial_reconcile','res_company','res_partner','hr_employee','hr_payslip','hr_payslip_run','baseer_hr_service','baseer_pos_summary','baseer_purchase_batch']
    out={}
    for t in tables:
        if o.sql(database,"SELECT to_regclass('public."+t+"')"):
            out[t]=json.loads(o.sql(database,"SELECT json_build_object('count',count(*),'hash',md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),''))) FROM "+t+' t'))
    return out
def inventory():
    files={};mods={}
    for root in ('custom_addons','third_party_addons'):
        for p in sorted((o.ROOT/root).rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts or '.git' in p.parts or p.suffix=='.pyc':continue
            rel=p.relative_to(o.ROOT).as_posix();files[rel]=hashlib.sha256(p.read_bytes()).hexdigest()
            if p.name=='__manifest__.py':
                m=ast.literal_eval(p.read_text(encoding='utf-8-sig'))
                mods[p.parent.name]={'path':p.parent.relative_to(o.ROOT).as_posix(),'version':m.get('version'),'depends':m.get('depends',[]),'license':m.get('license')}
    installed=json.loads(o.sql(o.QA,"SELECT json_agg(t) FROM (SELECT name,state,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)t"))
    save('candidate.json',{'custom_and_vendor_files':files,'source_modules':mods,'qa_installed':installed,'local_odoo_commit':o.run(['git','-C','odoo','rev-parse','HEAD'],capture_output=True,text=True).stdout.strip(),'local_odoo_dirty':o.run(['git','-C','odoo','status','--porcelain'],capture_output=True,text=True).stdout.strip(),'qa_image':o.run(['docker','inspect','--format','{{.Image}}',o.CONTAINER],capture_output=True,text=True).stdout.strip()})
    with zipfile.ZipFile(OUT/'candidate-source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for path in files:z.write(o.ROOT/path,path)
    save('candidate-archive.json',{'sha256':hashlib.sha256((OUT/'candidate-source.zip').read_bytes()).hexdigest(),'files':len(files)})
    save('qa-before.json',snapshot(o.QA));save('main-before.json',snapshot('baseer_dev'))
    print('Frozen files',len(files),'source modules',len(mods),'installed',len(installed))
def prepare():
    for scope in SCOPES:assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+db(scope)+"'")=='0'
    o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/full-audit-20260909.dump'])
    def restore(scope):
        o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" '+db(scope)])
        o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" --no-owner -d '+db(scope)+' /tmp/full-audit-20260909.dump'],capture_output=True,text=True)
        o.run(['docker','exec',o.CONTAINER,'mkdir','-p','/tmp/full-audit-'+scope])
        return db(scope)
    with ThreadPoolExecutor(max_workers=4) as ex:results=list(ex.map(restore,SCOPES))
    save('clones.json',{'source':o.QA,'databases':results,'snapshot':'/tmp/full-audit-20260909.dump','status':'ready','no_http_no_cron':True})
    print('Clones ready:',','.join(results))
def run_script(scope,path):
    database=db(scope);p=(o.ROOT/path).resolve();assert p.is_relative_to(o.ROOT/'docs')
    script=p.read_text(encoding='utf-8-sig').replace(o.QA,database)
    script=script.replace('/mnt/qa-evidence','/tmp/full-audit-'+scope)
    script="assert env.cr.dbname=="+repr(database)+"\n"+script
    started=time.monotonic()
    r=subprocess.run(['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+database,'--no-http','--max-cron-threads=0','--logfile=/tmp/full-audit-'+scope+'/'+p.stem+'.log'],input=script,text=True,encoding='utf-8',capture_output=True,cwd=o.ROOT)
    (OUT/(scope+'-'+p.stem+'-stdout.txt')).write_text(r.stdout+'\nSTDERR:\n'+r.stderr,encoding='utf-8')
    dest=OUT/(scope+'-runtime');dest.mkdir(exist_ok=True)
    o.run(['docker','cp',o.CONTAINER+':/tmp/full-audit-'+scope+'/.',str(dest)],capture_output=True)
    print(r.stdout[-12000:]);print(r.stderr[-2500:]);print('Script elapsed',round(time.monotonic()-started,2),'seconds')
    assert r.returncode==0,'Odoo shell failed; see captured stderr'
def preserve():
    d=json.loads((OUT/'candidate.json').read_text(encoding='utf-8'))
    differences=[p for p,h in d['custom_and_vendor_files'].items() if hashlib.sha256((o.ROOT/p).read_bytes()).hexdigest()!=h]
    qa=snapshot(o.QA)==json.loads((OUT/'qa-before.json').read_text(encoding='utf-8'))
    main=snapshot('baseer_dev')==json.loads((OUT/'main-before.json').read_text(encoding='utf-8'))
    save('preservation.json',{'source_unchanged':not differences,'source_differences':differences,'qa_business_unchanged':qa,'main_business_unchanged':main})
    print('source',not differences,'QA',qa,'main',main)
if __name__=='__main__':
    mode=sys.argv[1]
    if mode=='inventory':inventory()
    elif mode=='prepare':prepare()
    elif mode=='run':run_script(sys.argv[2],sys.argv[3])
    elif mode=='preservation':preserve()
