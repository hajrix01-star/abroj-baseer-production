"""Root-owned committed QA fixture for actual browser acceptance; never MAIN."""
import json
from pathlib import Path
from datetime import timedelta
from odoo import fields

assert env.cr.dbname == 'baseer_reports_qa_20260907'
E = env(user=env.ref('base.user_admin').id,
        context={'allowed_company_ids': [10], 'tracking_disable': True}, su=False)
tag = 'WS4A UI schedule'
out = Path('/mnt/qa-evidence/ws4a-ui-fixture.json')
if MODE == 'setup':
    assert not E['resource.calendar'].search_count([('name', '=', tag)])
    wizard = E['baseer.schedule.wizard'].create({
        'name': tag, 'company_id': 10,
        'day_ids': [(6, 0, [E.ref('baseer_work_schedule.day_%s' % d).id for d in range(5)])],
        'period_ids': [(0, 0, {'time_from': '09:30', 'time_to': '15:30'}),
                       (0, 0, {'time_from': '20:00', 'time_to': '00:30'})],
    })
    wizard.action_apply()
    source = wizard.applied_calendar_id
    past = fields.Date.today().replace(day=1) - timedelta(days=60)
    employees = E['hr.employee']
    for name in ('WS4A UI employee A', 'WS4A UI employee B'):
        employee = E['hr.employee'].create({'name': name, 'company_id': 10})
        employee.version_id.write({'date_version': past, 'contract_date_start': past,
            'resource_calendar_id': source.id, 'wage': 1000, 'baseer_salary_mode': 'fixed',
            'baseer_work_days': 30, 'baseer_allowance_total': 0})
        employees |= employee
    env.cr.commit()
    info = {'source_id': source.id, 'employee_ids': employees.ids,
            'action_id': E.ref('baseer_work_schedule.action_baseer_schedule_templates').id}
    out.write_text(json.dumps(info, indent=2))
    edit = E['baseer.schedule.wizard'].with_context(source.action_baseer_edit_schedule()['context']).create({})
    edit.period_ids[:1].write({'time_to': '16:00'})
    edit.action_apply()
    info['new_id'] = edit.applied_calendar_id.id
    env.cr.commit()
    out.write_text(json.dumps(info, indent=2))
    print('UI_FIXTURE', json.dumps(info))
elif MODE == 'cleanup':
    info = json.loads(out.read_text())
    employees = E['hr.employee'].with_context(active_test=False).browse(info['employee_ids']).exists()
    assert all(e.name.startswith('WS4A UI employee ') for e in employees)
    version_ids = E['hr.version'].with_context(active_test=False).search([('employee_id', 'in', employees.ids)]).ids
    E['baseer.schedule.wizard'].search([('name', '=', tag)]).unlink()
    employees.unlink()
    E['hr.version'].browse(version_ids).exists().unlink()
    calendars = E['resource.calendar'].with_context(active_test=False).search([('name', '=', tag)], order='id')
    for calendar in calendars:
        calendar.unlink()
    env.cr.commit()
    print('UI_FIXTURE_REMOVED')
else:
    raise AssertionError('Unknown fixture mode')
