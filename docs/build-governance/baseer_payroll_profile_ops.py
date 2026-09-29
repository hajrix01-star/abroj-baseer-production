"""BP-S4 isolated QA operations; no original database upgrades."""
import sys, json, re
import om_payroll_ops as o
o.OUT=o.ROOT/'docs/releases/2026-09-08-baseer-payroll-profile'
o.BACK=o.ROOT/'.local-backups/baseer-payroll-profile-20260908'
mode=sys.argv[1]
if mode=='backup':
    o.snapshot('baseer_dev','main-before')
    try: o.backup()
    finally: o.run(['docker','start',o.CONTAINER],capture_output=True)
elif mode in ('checks','eos-checks'):
    name='baseer_payroll_profile_checks' if mode=='checks' else 'baseer_payroll_eos_checks'
    r=o.run(['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--database='+o.QA,'--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/'+name+'.log'],input="exec(compile(open('/mnt/qa-evidence/"+name+".py').read(),'profile_checks','exec'))\n",text=True,capture_output=True)
    print(r.stdout[-6500:]); print(r.stderr[-1200:])
elif mode=='upgrade':
    o.run(['docker','stop',o.CONTAINER],capture_output=True)
    try:
        r=o.run(['docker','compose','-f','compose.yaml','-f','compose.reports-qa.yaml','run','--rm','--no-deps','reports_qa','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--database='+o.QA,'--update=baseer_payroll','--i18n-overwrite','--stop-after-init','--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/baseer_payroll_profile_upgrade.log'],text=True,capture_output=True)
        print(r.stdout[-1600:]);print(r.stderr[-1600:])
    finally:o.run(['docker','start',o.CONTAINER],capture_output=True)
elif mode=='race-prepare':
    assert o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='baseer_payroll_profile_race';")=='0'
    o.run(['docker','exec',o.DB,'sh','-c','pg_dump -U "$POSTGRES_USER" -Fc '+o.QA+' -f /tmp/baseer-profile-race-seed.dump'])
    o.run(['docker','exec',o.DB,'sh','-c','createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" baseer_payroll_profile_race'])
    o.run(['docker','exec',o.DB,'sh','-c','pg_restore -U "$POSTGRES_USER" -d baseer_payroll_profile_race --no-owner /tmp/baseer-profile-race-seed.dump'])
    print('Disposable concurrency database ready; no HTTP route.')
elif mode=='race':
    r=o.run(['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--database=baseer_payroll_profile_race','--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/baseer_payroll_eos_concurrency.log'],input="exec(compile(open('/mnt/qa-evidence/baseer_payroll_eos_concurrency.py').read(),'eos_race','exec'))\n",text=True,capture_output=True)
    print(r.stdout[-5000:]);print(r.stderr[-1000:])
elif mode=='race-remove':
    assert o.QA!='baseer_payroll_profile_race'
    assert o.sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='baseer_payroll_profile_race';")=='0'
    o.run(['docker','exec',o.DB,'sh','-c','dropdb -U "$POSTGRES_USER" --if-exists baseer_payroll_profile_race'])
    print('Only the disposable concurrency database removed.')
elif mode=='preservation':
    o.snapshot('baseer_dev','main-after');o.snapshot(o.QA,'qa-after')
    before=json.loads((o.OUT/'qa-before.json').read_text());after=json.loads((o.OUT/'qa-after.json').read_text())
    r={}
    # New nullable model columns do not change historical financial values.
    for table in ('account_move','account_move_line','account_payment','res_company','res_partner','res_users','res_groups_users_rel','res_company_users_rel'):
        dump=o.run(['docker','exec',o.DB,'pg_restore','--data-only','--table='+table,'-f','-','/tmp/om-payroll-before.dump'],text=True,capture_output=True).stdout
        match=re.search(r'COPY public\.'+table+r' \((.*?)\) FROM stdin;',dump)
        assert match,table
        cols=','.join(c.strip() for c in match.group(1).split(',') if c.strip() not in ('password','totp_secret'))
        actual=json.loads(o.sql(o.QA,"SELECT json_build_object('count',count(*),'hash',md5(coalesce(string_agg(j,',' ORDER BY j),''))) FROM (SELECT row_to_json(t)::text j FROM (SELECT "+cols+' FROM '+table+")t)s;"))
        r[table]=actual==before[table]
    r['main_exact']=json.loads((o.OUT/'main-before.json').read_text())==json.loads((o.OUT/'main-after.json').read_text())
    o.write('preservation.json',r);assert all(r.values()),r
