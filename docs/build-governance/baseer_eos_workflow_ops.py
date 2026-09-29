"""QA-only BP-S6 operations; separate immutable backup/evidence from BP-S4."""
import json, sys, hashlib, zipfile
import om_payroll_ops as o

o.OUT = o.ROOT / 'docs/releases/2026-09-08-baseer-eos-workflow'
BACK = o.ROOT / '.local-backups/baseer-eos-workflow-20260908'
ADDONS = '/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19'
TABLES = ('account_move', 'account_move_line', 'account_payment', 'hr_employee', 'hr_version', 'res_company', 'resource_calendar', 'resource_calendar_attendance', 'baseer_hr_eos')

def snap(db, before=None):
    result = {}
    for table in TABLES:
        cols=before[table]['columns'] if before else o.sql(db,"SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='"+table+"'")
        if not cols:
            result[table]={'ids':[], 'columns':'', 'hash':''}
            continue
        ids = before[table]['ids'] if before else json.loads(o.sql(db, f"SELECT coalesce(json_agg(id ORDER BY id),'[]') FROM {table}"))
        where = 'WHERE id IN (' + ','.join(map(str, ids)) + ')' if ids else 'WHERE false'
        result[table] = {'ids': ids, 'columns':cols, 'hash': o.sql(db, f"SELECT md5(coalesce(string_agg(row_to_json(t)::text,',' ORDER BY id),'')) FROM (SELECT {cols} FROM {table} {where}) t")}
    return result

mode = sys.argv[1]
if mode == 'upgrade':
    BACK.mkdir(parents=True, exist_ok=False)
    o.run(['docker', 'stop', o.CONTAINER], capture_output=True)
    try:
        o.write('qa-before.json', snap(o.QA))
        o.write('main-before.json', snap('baseer_dev'))
        o.run(['docker', 'exec', o.DB, 'sh', '-c', 'pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/baseer-eos-workflow-before.dump'])
        dump = BACK / 'database.dump'
        o.run(['docker', 'cp', o.DB+':/tmp/baseer-eos-workflow-before.dump', str(dump)], capture_output=True)
        o.write('backup.json', {'path':str(dump.relative_to(o.ROOT)), 'sha256':hashlib.sha256(dump.read_bytes()).hexdigest()})
        r = o.run(['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','run','--rm','--no-deps','reports_qa','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+o.QA,'--update=baseer_payroll','--stop-after-init','--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/baseer_eos_workflow_upgrade.log'], capture_output=True, text=True)
        print(r.stdout[-1200:]); print(r.stderr[-1200:])
    finally:
        o.run(['docker','start',o.CONTAINER],capture_output=True)
elif mode == 'reupgrade':
    o.run(['docker','stop',o.CONTAINER],capture_output=True)
    try:
        r=o.run(['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','run','--rm','--no-deps','reports_qa','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+o.QA,'--update=baseer_payroll','--stop-after-init','--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/baseer_eos_workflow_upgrade.log'],capture_output=True,text=True)
        print(r.stdout[-800:]);print(r.stderr[-800:])
    finally: o.run(['docker','start',o.CONTAINER],capture_output=True)
elif mode in ('checks','translate','regression'):
    name='baseer_eos_workflow_'+mode
    r=o.run(['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+o.QA,'--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/'+name+'.log'],input="exec(compile(open('/mnt/qa-evidence/"+name+".py').read(),'eos_workflow','exec'))\n",text=True,capture_output=True)
    print(r.stdout[-5500:]);print(r.stderr[-1800:])
elif mode == 'race-prepare':
    assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='baseer_eos_workflow_race'")=='0'
    o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/eos-workflow-race.dump'])
    o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" baseer_eos_workflow_race'])
    o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" -d baseer_eos_workflow_race --no-owner /tmp/eos-workflow-race.dump'])
    print('Disposable clone ready')
elif mode == 'race':
    r=o.run(['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database=baseer_eos_workflow_race','--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/baseer_eos_workflow_concurrency.log'],input="exec(compile(open('/mnt/qa-evidence/baseer_eos_workflow_concurrency.py').read(),'eos_workflow_race','exec'))\n",text=True,capture_output=True)
    print(r.stdout[-4500:]);print(r.stderr[-1500:])
elif mode == 'race-remove':
    assert o.sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='baseer_eos_workflow_race'")=='0'
    o.run(['docker','exec',o.DB,'sh','-c','dropdb -U "$POSTGRES_USER" baseer_eos_workflow_race'])
    print('Disposable clone removed')
elif mode == 'preservation':
    results={}
    for db,label in ((o.QA,'qa'),('baseer_dev','main')):
        before=json.loads((o.OUT/(label+'-before.json')).read_text())
        results[label] = snap(db,before)==before
    o.write('preservation.json',results)
    assert all(results.values()),results
    print(results)
elif mode == 'package':
    module=o.ROOT/'custom_addons/baseer_payroll'
    files=[p for p in module.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    archive=o.OUT/'baseer_payroll-19.0.1.3.0.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files): z.write(p,p.relative_to(module.parent))
    o.write('candidate.json',{'version':'19.0.1.3.0','target':o.QA,'zip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(), 'files':{str(p.relative_to(o.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
    print('Packaged', len(files), 'files')
