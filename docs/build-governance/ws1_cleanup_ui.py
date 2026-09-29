"""Remove only the root browser's unassigned QA template."""
import json
assert env.cr.dbname == 'baseer_reports_qa_20260907'
calendar = env['resource.calendar'].browse(262).exists()
if calendar:
    assert calendar.name == 'WS1 UI دوام فترتين'
    assert calendar.baseer_simple and calendar.baseer_is_template
    assert not env['hr.version'].with_context(active_test=False).search_count([('resource_calendar_id', '=', calendar.id)])
    calendar.unlink()
env.cr.commit()
print(json.dumps({'qa_template_262_removed': True, 'employee_assignments_changed': False}))
