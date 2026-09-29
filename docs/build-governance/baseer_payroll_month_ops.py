"""BP-S3 QA backup, focused checks and preservation."""
import sys,json
import om_payroll_ops as o
o.OUT=o.ROOT/'docs/releases/2026-09-08-baseer-payroll-month'
o.BACK=o.ROOT/'.local-backups/baseer-payroll-month-20260908'
mode=sys.argv[1]
if mode=='backup':
    o.snapshot('baseer_dev','main-before');o.backup()
    o.run(['docker','start',o.CONTAINER],capture_output=True)
elif mode=='checks':
    r=o.run(['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--database='+o.QA,'--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/baseer_payroll_month_checks.log'],input="exec(compile(open('/mnt/qa-evidence/baseer_payroll_month_checks.py').read(),'month_checks','exec'))\n",text=True,capture_output=True)
    print(r.stdout[-2500:]);print(r.stderr[-700:])
    assert json.loads((o.ROOT/'docs/build-governance/baseer_payroll_month_checks.json').read_text())['status']=='passed'
elif mode=='preservation':
    o.snapshot('baseer_dev','main-after');o.snapshot(o.QA,'qa-after')
    before=json.loads((o.OUT/'qa-before.json').read_text());after=json.loads((o.OUT/'qa-after.json').read_text())
    R={t:before[t]==after[t] for t in ('account_move','account_move_line','account_payment','res_company','res_partner','res_users','res_groups_users_rel','res_company_users_rel')}
    R['main_exact']=json.loads((o.OUT/'main-before.json').read_text())==json.loads((o.OUT/'main-after.json').read_text())
    o.write('preservation.json',R);assert all(R.values()),R
