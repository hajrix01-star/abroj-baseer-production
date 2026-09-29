import json
from odoo.addons.baseer_work_schedule.models.time_math import daily_average_label
assert env.cr.dbname == 'baseer_dev'
m=env['ir.module.module'].search([('name','=','baseer_work_schedule')])
assert m.state=='installed' and m.latest_version=='19.0.1.0.2'
assert daily_average_label({0:630,1:630})=='10:30'
assert not env['resource.calendar']._fields['baseer_average_label'].store
for name in ['view_baseer_schedule_template_form','view_baseer_schedule_template_list']:
    assert 'baseer_average_label' in env.ref('baseer_work_schedule.'+name).arch_db
assert 'متوسط الدوام اليومي' in env.ref('baseer_work_schedule.view_baseer_schedule_wizard_form').with_context(lang='ar_001').arch_db
print('WS3_MAIN_VERIFY '+json.dumps({'installed':m.latest_version,'average630minutes':'10:30','saved_views_use_display_label':True,'nonstored':True,'Arabic_label':True}))
env.cr.rollback()
