"""Disposable QA-only browser identity, never used against MAIN."""
import json
import secrets
from pathlib import Path
from odoo import Command

assert env.cr.dbname == 'baseer_reports_qa_20260907'
auth = Path('/mnt/qa-evidence/sales-dashboard-ui-auth.private.json')
login = 'sd1.preview@example.invalid'
assert not env['res.users'].with_context(active_test=False).search([('login', '=', login)])
password = secrets.token_urlsafe(24)
groups = env.ref('point_of_sale.group_pos_manager') | env.ref('spreadsheet_dashboard.group_dashboard_manager')
user = env['res.users'].with_context(no_reset_password=True, tracking_disable=True).create({
    'name': 'SD1 QA preview', 'login': login, 'password': password, 'lang': 'ar_001',
    'company_id': 6, 'company_ids': [Command.set([6, 7])], 'group_ids': [Command.set(groups.ids)],
})
auth.write_text(json.dumps({'login': login, 'password': password, 'user_id': user.id, 'partner_id': user.partner_id.id}), encoding='utf-8')
env.cr.commit()
print('QA browser identity created; credentials retained privately.')
