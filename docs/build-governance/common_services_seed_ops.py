"""QA-only deployment and evidence for CSS1. Never writes the main database."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path
import om_payroll_ops as o
import company_accounting_seed_ops as prior

OUT = o.ROOT / 'docs/releases/2026-09-08-common-services-seed'
BACK = o.ROOT / '.local-backups/common-services-seed-20260908'
ADDONS = prior.ADDONS
MODULE = 'baseer_service_seed'
TABLES = prior.TABLES + ['res_partner', 'product_template', 'product_product', 'product_category', 'baseer_purchase_category_map']

def snapshot(db):
    prior.TABLES = TABLES
    return prior.snapshot(db)

def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def install(update=False):
    o.run(['docker', 'stop', o.CONTAINER], capture_output=True)
    try:
        if not update:
            BACK.mkdir(parents=True, exist_ok=False)
            save('qa-before.json', snapshot(o.QA))
            save('main-before.json', snapshot('baseer_dev'))
            o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/common-services-seed-before.dump'])
            dump = BACK / 'database.dump'
            o.run(['docker','cp',o.DB+':/tmp/common-services-seed-before.dump',str(dump)],capture_output=True)
            save('backup.json', {'path':str(dump.relative_to(o.ROOT)), 'sha256':hashlib.sha256(dump.read_bytes()).hexdigest()})
        result = o.run(['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','run','--rm','--no-deps','reports_qa','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+o.QA,('--update=' if update else '--init=')+MODULE,'--without-demo=all','--stop-after-init','--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/common_services_seed_install.log'],capture_output=True,text=True)
        print(result.stdout[-1600:]); print(result.stderr[-1600:])
    finally:
        o.run(['docker','start',o.CONTAINER],capture_output=True)

def preservation():
    before = json.loads((OUT / 'qa-before.json').read_text(encoding='utf-8'))
    after = snapshot(o.QA)
    added = {}; changed = {}
    for table, rows in before.items():
        old = {r['id']:r for r in rows}; new = {r['id']:r for r in after[table]}
        added[table] = sorted(new.keys()-old.keys())
        delta = [rid for rid, row in old.items() if new.get(rid) != row]
        if delta: changed[table] = delta
    main = snapshot('baseer_dev') == json.loads((OUT / 'main-before.json').read_text(encoding='utf-8'))
    allowed = {'account_account','res_partner','product_template','product_product','product_category','baseer_purchase_category_map'}
    unexpected = {t:ids for t,ids in added.items() if ids and t not in allowed}
    result = {'main_unchanged':main, 'existing_rows_changed':changed, 'added_ids':added, 'unexpected_additions':unexpected}
    save('preservation.json',result)
    assert main and not changed and not unexpected, result
    print('Preserved all existing rows; main unchanged.', {t:len(v) for t,v in added.items() if v})

def package():
    module = o.ROOT / 'custom_addons' / MODULE
    files = sorted(p for p in module.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    OUT.mkdir(parents=True,exist_ok=True)
    archive = OUT / (MODULE+'-19.0.1.0.0.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p,p.relative_to(module.parent))
    save('candidate.json',{'version':'CSS1 / 19.0.1.0.0','database':o.QA,'zip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':{str(p.relative_to(o.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
    print('Packaged',len(files),'files')

if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'install': install()
    elif mode == 'update': install(True)
    elif mode == 'preservation': preservation()
    elif mode == 'package': package()
    elif mode == 'checks':
        prior.shell("exec(compile(open('/mnt/qa-evidence/common_services_seed_checks.py').read(), 'common_services_seed_checks.py', 'exec'))\n")
        data=json.loads((o.ROOT/'docs/build-governance/common_services_seed_checks.json').read_text(encoding='utf-8'))
        assert data.get('status') == 'passed', data
    elif mode == 'race-prepare':
        assert o.sql('postgres', "SELECT count(*) FROM pg_database WHERE datname='baseer_service_seed_race'") == '0'
        o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/common-service-seed-race.dump'])
        o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" baseer_service_seed_race'])
        o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" -d baseer_service_seed_race --no-owner /tmp/common-service-seed-race.dump'])
        print('Isolated race clone ready')
    elif mode == 'race':
        prior.shell("exec(compile(open('/mnt/qa-evidence/common_services_seed_concurrency.py').read(), 'css1_race', 'exec'))\n", 'baseer_service_seed_race')
    elif mode == 'race-remove':
        assert o.sql('postgres', "SELECT count(*) FROM pg_stat_activity WHERE datname='baseer_service_seed_race'") == '0'
        o.run(['docker','exec',o.DB,'sh','-c','dropdb -U "$POSTGRES_USER" baseer_service_seed_race'])
        print('Isolated test clone removed')
