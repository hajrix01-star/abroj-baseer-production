import json
assert env.cr.dbname == 'baseer_dev'
module=env['ir.module.module'].search([('name','=','baseer_work_schedule')])
assert module.state == 'installed' and module.latest_version == '19.0.1.0.1'
assert not env['ir.module.module'].search_count([('state','in',['to install','to upgrade','to remove'])])
arch=env['baseer.schedule.wizard'].get_view(view_id=env.ref('baseer_work_schedule.view_baseer_schedule_wizard_form').id,view_type='form')['arch']
assert arch.count('widget="baseer_schedule_time"') == 4
assert env['baseer.schedule.period']._fields['time_from'].type == 'char'
assert env['baseer.schedule.period']._fields['time_to'].type == 'char'
print('WS2_MAIN_VERIFY '+json.dumps({'installed':module.latest_version,'four_time_widgets':True,'HHMM_char_contract_unchanged':True,'no_pending_modules':True}))
env.cr.rollback()
