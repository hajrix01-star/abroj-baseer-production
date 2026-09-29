import json
from odoo import Command
qa = env(context=dict(env.context, allowed_company_ids=[6]))
Summary = qa['baseer.pos.summary']
day = '2026-02-13'
assert not Summary.search_count([('company_id','=',6),('business_date','=',day)])
config = Summary._default_config()
method = config.payment_method_ids.filtered(lambda m: m.journal_id.type == 'cash')[:1]
sources = Summary.create([{'business_date':day,'day_schedule':'split','period_scope':period,'customer_count':1,
                          'notes':'S5 UI lifecycle fixture — delete after verification',
                          'allocation_ids':[Command.create({'payment_method_id':method.id,'amount':115})]}
                         for period in ('morning','evening')])
qa.flush_all()
record = qa['baseer.pos.day.archive'].search([('company_id','=',6),('business_date','=',day)])
entry = record.action_open()
result = {'summary_ids':sources.ids,'day_id':record.id,'entry_id':entry['res_id'],'company_id':6,'date':day}
with open('/mnt/qa-evidence/pos_s5_ui_fixture.json','w') as output: json.dump(result,output)
env.cr.commit()
print('S5_UI_FIXTURE',json.dumps(result))
