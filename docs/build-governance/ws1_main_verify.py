"""Read-only post-install checks against frozen MAIN module."""
import json
assert env.cr.dbname == 'baseer_dev'
module = env['ir.module.module'].search([('name', '=', 'baseer_work_schedule')])
assert module.state == 'installed' and module.latest_version == '19.0.1.0.0'
assert not env['ir.module.module'].search_count([('state', 'in', ['to install', 'to upgrade', 'to remove'])])
view = env['hr.employee'].with_context(lang='ar_001').get_view(view_id=env.ref('hr.view_employee_form').id, view_type='form')
assert 'action_baseer_set_schedule' in view['arch']
action = env.ref('baseer_work_schedule.action_baseer_schedule_templates')
form = env.ref('baseer_work_schedule.view_baseer_schedule_template_form')
assert form.model == 'resource.calendar'
assert env['baseer.schedule.day'].search_count([]) == 7
assert not env['resource.calendar'].search_count([('baseer_simple', '=', True)])
assert not env['hr.version'].with_context(active_test=False).search_count([('baseer_schedule_version', '=', True)])
print('WS1_MAIN_VERIFY ' + json.dumps(dict(installed=module.latest_version, employee_button=True, weekdays=7,
    no_new_employee_assignments=True, no_pending_modules=True, template_action=action.id, template_form=form.id)))
env.cr.rollback()
