from pathlib import Path
import json
assert env.cr.dbname == 'baseer_ar1_roles_20260910'
assert env.su
company = env['res.company'].browse(2)
local = env(context={'allowed_company_ids': company.ids})
contact = local['res.partner'].create({'name': 'AR1 UI Employee', 'company_id': company.id})
employee = local['hr.employee'].create({'name': 'AR1 UI Employee', 'company_id': company.id, 'work_contact_id': contact.id})
journal = local['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'cash'), ('active', '=', True)], limit=1)
assert journal and company.baseer_loan_account_id
Path('/mnt/qa-evidence/ar1-advance-ui-fixtures.json').write_text(json.dumps({'employee': employee.id, 'journal': journal.id, 'journal_name': journal.name, 'action':env.ref('baseer_access_roles.action_advance_entries').id},ensure_ascii=False,indent=2),encoding='utf8')
env.cr.commit()
print('AR1_ADVANCE_UI_READY')
