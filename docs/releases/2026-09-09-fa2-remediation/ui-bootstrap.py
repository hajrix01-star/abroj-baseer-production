"""Create an isolated review identity; never read or reset a live user's password."""
import json,secrets,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
password=secrets.token_urlsafe(28)
credentials={'login':'fa2.review.local','password':password}
(f.BACK/'ui-credentials.json').write_text(json.dumps(credentials),encoding='utf-8')
script="""
from odoo import Command
assert env.cr.dbname=='baseer_fix_core_20260909'
env['ir.mail_server'].search([]).write({'active':False})
env['ir.cron'].search([]).write({'active':False})
groups=[env.ref(x).id for x in ['base.group_system','om_hr_payroll.group_hr_payroll_manager','point_of_sale.group_pos_manager','account.group_account_manager','hr.group_hr_manager']]
u=env['res.users'].with_context(no_reset_password=True,mail_create_nolog=True,mail_create_nosubscribe=True).create({
 'name':'FA2 Review','login':'fa2.review.local','password':PASSWORD_VALUE,'company_id':10,'company_ids':[Command.set([10])],
 'group_ids':[Command.set(groups)],'lang':'ar_001','tz':'Asia/Riyadh'})
env.cr.commit()
print('Created isolated UI reviewer',u.id)
""".replace('PASSWORD_VALUE',repr(password))
f.capture('core','ui-bootstrap',['docker','exec','-i',f.o.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf',
 '--addons-path='+f.addons('core'),'--database='+f.db('core'),'--no-http','--max-cron-threads=0','--logfile=/tmp/fa2-evidence-core/ui-bootstrap.log'],script)
