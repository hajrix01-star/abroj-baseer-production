"""Scoped display checks; all ORM writes rolled back in QA."""
import json
from pathlib import Path
from odoo import Command
from odoo.addons.baseer_work_schedule.models.time_math import daily_average_label
assert env.cr.dbname == 'baseer_reports_qa_20260907'
checks=[]
def check(name, condition):
    assert condition, name
    checks.append({'name':name,'passed':True})
def wizard(days, spans):
    ids=env['baseer.schedule.day'].search([('weekday','in',days)]).ids
    vals=[]
    for start,end,custom in spans:
        value={'time_from':start,'time_to':end}
        if custom is not None:
            value.update(custom_days=True,day_ids=[Command.set(env['baseer.schedule.day'].search([('weekday','in',custom)]).ids)])
        vals.append(Command.create(value))
    return env['baseer.schedule.wizard'].create({'name':'WS3 rollback display check','company_id':env.company.id,
        'day_ids':[Command.set(ids)],'period_ids':vals})
try:
    check('630minutes =>10:30',daily_average_label({0:630})=='10:30')
    check('396minutes =>06:36',daily_average_label({0:396})=='06:36')
    check('fraction minute rounds down',daily_average_label({0:630,1:631,2:630})=='10:30')
    check('half minute rounds up',daily_average_label({0:630,1:631})=='10:31')
    check('minute carry to hour',daily_average_label({0:59,1:60})=='01:00')
    w=wizard([0,1,2,3,5,6],[('09:30','15:30',None),('20:00','00:30',None)])
    check('user example wizard average/weekly',w.average_label=='10:30' and w.total_label=='63:00')
    w.action_apply();cal=w.applied_calendar_id
    check('saved overnight template same average',cal.baseer_average_label=='10:30')
    check('native numeric hours unchanged',cal.hours_per_day==10.5 and cal.hours_per_week==63)
    for minutes, expected in [('33','10:30'),('34','10:31')]:
        w=wizard(list(range(7)),[('08:00','18:30',None),('18:30','18:'+minutes,[0])])
        w.action_apply();cal=w.applied_calendar_id
        check('variable days '+minutes+' agree across wizard and calendar',w.average_label==expected and cal.baseer_average_label==expected)
        check('native payroll average '+minutes+' remains10.51',cal.hours_per_day==10.51)
    w=wizard([0],[])
    check('invalid empty schedule keeps dash',w.average_label=='—' and w.total_label=='—')
    views=[env.ref('baseer_work_schedule.'+name).arch_db for name in ['view_baseer_schedule_wizard_form','view_baseer_schedule_template_form','view_baseer_schedule_template_list']]
    check('all own views useHHMMlabel',all('Average working day (HH:MM)' in view for view in views))
    check('saved displays use nonstored formatter',all('baseer_average_label' in view for view in views[1:]))
    check('display field nonstored',not env['resource.calendar']._fields['baseer_average_label'].store)
finally:
    env.cr.rollback()
Path('/mnt/qa-evidence/ws3-checks.json').write_text(json.dumps({'status':'passed','checks':checks,'rolled_back':True},indent=2))
print('WS3_CHECKS_PASSED',len(checks))
