"""Create/remove a dedicated temporary QA user; never alter existing users."""
import json
import secrets
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
private = root / '.local-backups/browser-print-20260909/qa-user.json'
if sys.argv[-1] == 'create':
    assert not private.exists(), 'QA user record already exists'
    secret = secrets.token_urlsafe(24)
    code = '''
assert env.cr.dbname == 'baseer_reports_qa_20260907'
assert not env['res.users'].with_context(active_test=False).search([('login','=','bp1.print.qa')])
groups = [env.ref(x).id for x in ['base.group_user','account.group_account_manager','om_hr_payroll.group_hr_payroll_manager']]
u = env['res.users'].with_context(no_reset_password=True, tracking_disable=True).create(dict(
    name='BP1 Print QA', login='bp1.print.qa', password=PASSWORD,
    company_id=6, company_ids=[(6,0,[6,10])], group_ids=[(6,0,groups)], lang='ar_001'))
env.cr.commit()
print('BP1_USER', u.id, u.partner_id.id)
'''.replace('PASSWORD', repr(secret))
else:
    info = json.loads(private.read_text())
    code = '''
assert env.cr.dbname == 'baseer_reports_qa_20260907'
u=env['res.users'].with_context(active_test=False).browse(USER_ID).exists()
assert not u or u.login == 'bp1.print.qa'
p=u.partner_id
u.unlink()
if p: p.unlink()
env.cr.commit()
print('BP1_USER_REMOVED')
'''.replace('USER_ID', str(info['id']))
result = subprocess.run(['docker','exec','-i','baseer_odoo_dev-reports_qa-1','/entrypoint.sh','odoo','shell',
    '--config=/etc/odoo/odoo.local.conf',
    '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19,/mnt/sales-dashboard-addons',
    '-d','baseer_reports_qa_20260907','--no-http','--max-cron-threads=0'],
    input=code, text=True, encoding='utf8', capture_output=True, check=True)
if sys.argv[-1] == 'create':
    marker = next(x for x in result.stdout.splitlines() if x.startswith('BP1_USER ')).split()
    private.write_text(json.dumps(dict(id=int(marker[1]),partner_id=int(marker[2]),login='bp1.print.qa',password=secret)),encoding='utf8')
    print('Temporary QA print user created')
else:
    print('Temporary QA print user removed')
