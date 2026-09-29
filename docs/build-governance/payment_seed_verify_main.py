"""Read-only MAIN verification of all current company payment defaults."""
import json
import environment_backups as b

script = '''
import json
result=[]
for original in env['res.company'].search([]):
 co=original.with_company(original).with_context(allowed_company_ids=original.ids)
 config=co._baseer_pos_identity('config','pos.config')
 assert config and len(config.payment_method_ids)==5
 config._validate_baseer_setup()
 defaults=co.env['baseer.pos.day.entry'].default_get(['first_allocation_ids','second_allocation_ids'])
 assert len(defaults['first_allocation_ids'])==len(defaults['second_allocation_ids'])==5
 result.append({'company':co.name,'config':config.id,'valid':True,'methods':[{
  'id':m.id,'name_ar':m.with_context(lang='ar_001').name,'name_en':m.with_context(lang='en_US').name,
  'kind':m.baseer_category_id.kind,'journal':m.journal_id.name,
  'account':(m.journal_id.default_account_id if m.is_cash_count else m.outstanding_account_id).code,
  'account_type':(m.journal_id.default_account_id if m.is_cash_count else m.outstanding_account_id).account_type
 } for m in config.payment_method_ids]})
print('POS_SEED_MAIN='+json.dumps(result,ensure_ascii=False))
env.cr.rollback()
'''
args=['docker','exec','-i',b.MAIN_CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf',
 '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
 '--database='+b.MAIN,'--no-http','--max-cron-threads=0','--log-level=critical']
run=b.run(args,input=script,capture_output=True,text=True,encoding='utf8')
data=json.loads(next(line.split('=',1)[1] for line in run.stdout.splitlines() if line.startswith('POS_SEED_MAIN=')))
b.save(b.ROOT/'docs/releases/2026-09-09-pos-payment-seed/main-companies.json',data)
print('MAIN_COMPANIES_VALID',len(data),flush=True)
