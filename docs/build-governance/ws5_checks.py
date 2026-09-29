"""WS5 native raw-time contract checks, rollback-only QA."""
import json
from odoo import Command
assert env.cr.dbname == 'baseer_reports_qa_20260907'
E = env(context=dict(env.context, allowed_company_ids=[6], lang='en_US'))
checks = []
def check(label, condition):
    assert condition, label
    checks.append(label)
try:
    days = E['baseer.schedule.day'].search([('weekday', 'in', list(range(6)))])
    check('Six work days fixture', len(days) == 6)
    for start, end, daily, weekly in [('09:07','15:43','06:36','39:36'), ('21:00','03:00','06:00','36:00'), ('21:00','24:00','03:00','18:00')]:
        w = E['baseer.schedule.wizard'].create({'name':'WS5 rollback only', 'company_id':6,
            'day_ids':[Command.set(days.ids)], 'period_ids':[Command.create({'time_from':start,'time_to':end})]})
        check(start+'-'+end+' server duration', w.average_label == daily and w.total_label == weekly and not w.validation_message)
        w.unlink()
    split = E['baseer.schedule.wizard'].create({'name':'WS5 split', 'company_id':6,
        'day_ids':[Command.set(days.ids)], 'period_ids':[
            Command.create({'time_from':'09:30','time_to':'15:30'}),
            Command.create({'time_from':'20:00','time_to':'00:30'})]})
    check('Two shifts remain10:30 daily and63:00 weekly', split.average_label == '10:30' and split.total_label == '63:00' and not split.validation_message)
    invalid = E['baseer.schedule.wizard'].create({'name':'WS5 invalid', 'company_id':6,
        'day_ids':[Command.set(days.ids)], 'period_ids':[Command.create({'time_from':'24:00','time_to':'03:00'})]})
    check('Server rejects24 as start', bool(invalid.validation_message))
    check('All wizard entrypoints remain modal', E['baseer.schedule.wizard']._action()['target'] == 'new'
        and E.ref('baseer_work_schedule.action_baseer_schedule_wizard').target == 'new')
    check('Raw inputs remain native char fields', all(E['baseer.schedule.period']._fields[f].type == 'char' for f in ['time_from','time_to']))
    print('WS5_CHECKS='+json.dumps({'passed':len(checks),'checks':checks,'fixtures':'rolled back'}))
finally:
    env.cr.rollback()
