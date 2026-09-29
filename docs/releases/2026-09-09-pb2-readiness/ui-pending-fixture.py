from odoo import api
assert env.cr.dbname=='baseer_pb2_test_20260909'
ui=env['res.users'].search([('login','=','pb2.review.local')])
assert len(ui)==1
E=api.Environment(env.cr,ui.id,dict(env.context,allowed_company_ids=[6],lang='ar_001',tracking_disable=True,mail_create_nolog=True))
employee=E['hr.employee'].create({'name':'PB2 — موظف يحتاج تاريخ العقد','company_id':6,'wage':2000})
assert employee.baseer_payroll_enabled and not employee.contract_date_start
run=E['hr.payslip.run'].browse(147)
assert run.state=='draft' and run.company_id.id==6
run.action_load_employees()
slip=run.slip_ids.filtered(lambda s:s.employee_id==employee)
assert len(slip)==1 and slip.baseer_readiness=='pending' and slip.baseer_net==0
env.cr.commit()
print('UI_PENDING',employee.id,slip.id)
