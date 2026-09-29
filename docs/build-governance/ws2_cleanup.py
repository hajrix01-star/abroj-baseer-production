assert env.cr.dbname == 'baseer_reports_qa_20260907'
cal=env['resource.calendar'].browse(388).exists()
if cal:
    assert cal.name == 'WS2 UI time picker' and cal.baseer_simple
    assert not env['hr.version'].with_context(active_test=False).search_count([('resource_calendar_id','=',cal.id)])
    cal.unlink()
env.cr.commit()
print('WS2_QA_UI_TEMPLATE_REMOVED; NO_EMPLOYEE_ASSIGNMENT')
