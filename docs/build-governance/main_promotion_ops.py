import sys, subprocess, json, hashlib, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/releases/2026-09-08-main-promotion'
BACK = ROOT / '.local-backups/main-promotion-20260908'
DB = 'baseer_odoo_dev-db-1'
def run(args, **kw):
    return subprocess.run(args, cwd=ROOT, check=True, **kw)
def sql(db, query):
    return run(['docker','exec','-i',DB,'sh','-c','psql -U "$POSTGRES_USER" -d '+db+' -At -v ON_ERROR_STOP=1'], input=query, text=True, capture_output=True).stdout.strip()
def snapshot(db, name):
    result = {}
    baseline_path=OUT/'main-before.json'
    baseline=json.loads(baseline_path.read_text(encoding='utf-8')) if baseline_path.exists() else {}
    for table in ['account_move','account_move_line','account_payment','account_account','account_tax','account_journal','res_partner','res_company','product_template','product_product','product_category','pos_config','pos_payment_method']:
        columns=baseline.get(table,{}).get('columns') or sql(db,"SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='"+table+"';")
        result[table] = json.loads(sql(db, "SELECT json_build_object('count', count(*),'hash',md5(coalesce(string_agg(row_to_json(t)::text,''),''))) FROM (SELECT "+columns+" FROM "+table+" ORDER BY id)t;"))
        result[table]['columns']=columns
    result['users'] = json.loads(sql(db,"SELECT json_agg(t) FROM (SELECT id,login,active,company_id FROM res_users ORDER BY id)t;"))
    result['user_groups']=json.loads(sql(db,'SELECT json_agg(t) FROM (SELECT * FROM res_groups_users_rel ORDER BY uid,gid)t;'))
    result['user_companies']=json.loads(sql(db,'SELECT json_agg(t) FROM (SELECT * FROM res_company_users_rel ORDER BY user_id,cid)t;'))
    result['modules'] = json.loads(sql(db,"SELECT json_agg(t) FROM (SELECT name,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)t;"))
    result['business'] = {}
    for table in ['baseer_purchase_batch','baseer_purchase_batch_line','baseer_pos_summary','baseer_pos_day_entry','baseer_pos_closure','pos_order','pos_session']:
        if sql(db,"SELECT to_regclass('"+table+"') IS NOT NULL;") == 't':
            result['business'][table] = int(sql(db,'SELECT count(*) FROM '+table+';'))
    (OUT/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name, {k:({a:b for a,b in v.items() if a!='columns'} if isinstance(v,dict) else v) for k,v in result.items() if k not in ['modules','users','user_groups','user_companies']})
def backup(label):
    dest=BACK/label
    dest.mkdir(parents=True,exist_ok=False)
    run(['docker','exec',DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc baseer_dev -f /tmp/main-promotion.dump'])
    run(['docker','cp',DB+':/tmp/main-promotion.dump',str(dest/'database.dump')])
    # Separate filestore directory per database; archive only the original.
    run(['docker','exec','baseer_odoo_dev-reports_qa-1','tar','-czf','/tmp/main-filestore.tar.gz','-C','/var/lib/odoo/filestore','baseer_dev'])
    run(['docker','cp','baseer_odoo_dev-reports_qa-1:/tmp/main-filestore.tar.gz',str(dest/'filestore.tar.gz')])
    shutil.copy2(ROOT/'config/odoo.local.conf',dest/'odoo.local.conf')
    shutil.copy2(ROOT/'compose.yaml',dest/'compose.yaml')
    files=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in dest.iterdir()]
    (OUT/(label+'-backup.json')).write_text(json.dumps(files,indent=2),encoding='utf-8')
    print('Backup verified',label,[(p['path'],p['bytes']) for p in files])
if sys.argv[1]=='backup': backup(sys.argv[2])
elif sys.argv[1]=='snapshot': snapshot(sys.argv[2],sys.argv[3])
elif sys.argv[1]=='clone':
    target='baseer_promotion_rehearsal_20260908'
    assert sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+target+"';")=='0'
    run(['docker','exec',DB,'sh','-c','createdb -U "$POSTGRES_USER" '+target])
    run(['docker','exec',DB,'sh','-c','pg_restore -U "$POSTGRES_USER" --no-owner --exit-on-error -d '+target+' /tmp/main-promotion.dump'])
    run(['docker','exec','-u','root','baseer_odoo_dev-reports_qa-1','python3','-c',"import shutil,os; p='/var/lib/odoo/filestore/'; assert not os.path.exists(p+'"+target+"'); shutil.copytree(p+'baseer_dev',p+'"+target+"'); shutil.chown(p+'"+target+"',user='odoo',group='odoo')"])
    # Files retain ownership from source copy only through explicit recursive chown.
    run(['docker','exec','-u','root','baseer_odoo_dev-reports_qa-1','chown','-R','odoo:odoo','/var/lib/odoo/filestore/'+target])
    sql(target,'UPDATE ir_cron SET active=false; UPDATE ir_mail_server SET active=false;')
    print('Isolated clone ready',target)
