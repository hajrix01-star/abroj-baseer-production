"""QA-only additive accounting initialization, preservation and frozen delivery."""
import hashlib, json, sys, zipfile
from pathlib import Path
import om_payroll_ops as o

o.OUT = o.ROOT / 'docs/releases/2026-09-08-company-accounting-seed'
BACK = o.ROOT / '.local-backups/company-accounting-seed-20260908'
ADDONS = '/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19'
FIELDS = ['baseer_salary_expense_id','baseer_salary_payable_id','baseer_deduction_account_id','baseer_loan_account_id','baseer_payroll_journal_id','baseer_eos_expense_id','baseer_eos_journal_id']
TABLES = ['account_move','account_move_line','account_payment','hr_employee','hr_version','baseer_hr_eos','hr_payslip','hr_payslip_run','baseer_hr_loan','res_company','account_account','account_journal','account_payment_method_line','account_tax','resource_calendar','resource_calendar_attendance']

def snapshot(db):
    result={}
    for table in TABLES:
        columns=o.sql(db,"SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='"+table+"'")
        if columns:
            result[table]=json.loads(o.sql(db,f"SELECT coalesce(json_agg(t ORDER BY id),'[]') FROM (SELECT {columns} FROM {table})t"))
    return result

def shell(script, db=o.QA):
    r=o.run(['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+db,'--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/company_accounting_seed_shell.log'],input=script,text=True,capture_output=True)
    print(r.stdout[-5500:]);print(r.stderr[-1300:])

def install(update=False):
    o.run(['docker','stop',o.CONTAINER],capture_output=True)
    try:
        if not update:
            BACK.mkdir(parents=True,exist_ok=False)
            o.write('qa-before.json',snapshot(o.QA));o.write('main-before.json',snapshot('baseer_dev'))
            o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/company-accounting-seed-before.dump'])
            dump=BACK/'database.dump'
            o.run(['docker','cp',o.DB+':/tmp/company-accounting-seed-before.dump',str(dump)],capture_output=True)
            o.write('backup.json',{'path':str(dump.relative_to(o.ROOT)),'sha256':hashlib.sha256(dump.read_bytes()).hexdigest()})
        r=o.run(['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','run','--rm','--no-deps','reports_qa','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,'--database='+o.QA,('--update=' if update else '--init=')+'baseer_company_setup','--without-demo=all','--stop-after-init','--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/company_accounting_seed_install.log'],capture_output=True,text=True)
        print(r.stdout[-1100:]);print(r.stderr[-1100:])
    finally: o.run(['docker','start',o.CONTAINER],capture_output=True)

def preservation():
    before=json.loads((o.OUT/'qa-before.json').read_text(encoding='utf-8'));after=snapshot(o.QA)
    changes={};added={};bad=[]
    for table,rows in before.items():
        old={r['id']:r for r in rows};new={r['id']:r for r in after[table]}
        added[table]=sorted(new.keys()-old.keys())
        if added[table] and table not in ('account_account','account_journal','account_payment_method_line'):
            bad.append(table+': unexpected additions')
        for rid,record in old.items():
            if rid not in new: bad.append(table+': removed '+str(rid));continue
            delta={k:[v,new[rid].get(k)] for k,v in record.items() if v!=new[rid].get(k)}
            if not delta: continue
            changes.setdefault(table,{})[rid]=delta
            permitted=(FIELDS+['write_date','write_uid']) if table=='res_company' else (['payment_account_id','write_date','write_uid'] if table=='account_payment_method_line' else [])
            if set(delta)-set(permitted): bad.append(table+': fields changed '+str(rid))
            if table=='res_company' and any(record.get(f) and record[f]!=new[rid].get(f) for f in FIELDS): bad.append('configured company setting overwritten')
            if table=='account_payment_method_line':
                jid=record['journal_id'];journals={r['id']:r for r in before['account_journal']}
                used=any(r.get('journal_id')==jid for t in ('account_move','account_payment') for r in before[t])
                if used or record.get('payment_account_id') or new[rid].get('payment_account_id')!=journals[jid]['default_account_id']:
                    bad.append('unsafe existing payment default change '+str(rid))
    main=snapshot('baseer_dev')==json.loads((o.OUT/'main-before.json').read_text(encoding='utf-8'))
    result={'main_unchanged':main,'qa_preserved':not bad,'issues':bad,'changes':changes,'added_ids':added}
    o.write('preservation.json',result)
    assert main and not bad,result
    print('Preserved; allowed configuration deltas:',{k:len(v) for k,v in changes.items()},'new:',{k:len(v) for k,v in added.items() if v})

def package():
    module=o.ROOT/'custom_addons/baseer_company_setup'
    files=sorted(p for p in module.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    archive=o.OUT/'baseer_company_setup-19.0.1.0.0.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,p.relative_to(module.parent))
    o.write('candidate.json',{'version':'19.0.1.0.0','target':o.QA,'zip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':{str(p.relative_to(o.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
    print('Packaged',len(files),'files')

if __name__=='__main__':
    mode=sys.argv[1]
    if mode=='install':install()
    elif mode=='update':install(True)
    elif mode=='checks':
        shell("exec(compile(open('/mnt/qa-evidence/company_accounting_seed_checks.py').read(),'company_seed','exec'))\n")
        result=json.loads((o.ROOT/'docs/build-governance/company_accounting_seed_checks.json').read_text(encoding='utf-8'))
        assert 'traceback' not in result and result.get('rolled_back') and all(c['passed'] for c in result['checks']), 'Workflow checks failed; inspect JSON evidence'
    elif mode=='preservation':preservation()
    elif mode=='package':package()
    elif mode=='race-prepare':
        assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='baseer_company_seed_race'")=='0'
        o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/company-seed-race.dump'])
        o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" baseer_company_seed_race'])
        o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" -d baseer_company_seed_race --no-owner /tmp/company-seed-race.dump'])
        print('Isolated race clone ready')
    elif mode=='race':
        shell("exec(compile(open('/mnt/qa-evidence/company_accounting_seed_concurrency.py').read(),'company_seed_race','exec'))\n",'baseer_company_seed_race')
        result=json.loads((o.ROOT/'docs/build-governance/company_accounting_seed_concurrency.json').read_text(encoding='utf-8'))
        assert 'traceback' not in result and all(c['passed'] for c in result['checks']), 'Race checks failed'
    elif mode=='race-remove':
        assert o.sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='baseer_company_seed_race'")=='0'
        o.run(['docker','exec',o.DB,'sh','-c','dropdb -U "$POSTGRES_USER" baseer_company_seed_race'])
        print('Isolated race clone removed')
