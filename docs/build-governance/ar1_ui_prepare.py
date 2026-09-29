"""Persistent, explicitly isolated browser fixtures. Never run on MAIN."""
from odoo import Command, fields
import json
from pathlib import Path

assert env.cr.dbname == 'baseer_ar1_roles_20260910'
assert env.su
mapping = env['baseer.purchase.category.map'].search([('active', '=', True)], limit=1)
company = mapping.company_id
actors = {}
for role in ('cashier', 'accountant', 'owner'):
    actor = env['res.users'].with_context(no_reset_password=True).create({
        'name': 'AR1 UI ' + role, 'login': 'ar1-ui-' + role,
        'password': 'AR1-isolated-ui-2026!', 'lang': 'ar_001',
        'company_id': company.id, 'company_ids': [Command.set(company.ids)],
        'baseer_access_role': role,
    })
    actors[role] = actor.id
local = env(context={'allowed_company_ids': company.ids})
supplier = local['res.partner'].create({'name': 'AR1 UI Supplier', 'company_id': company.id})
cash = env(user=actors['cashier'], su=False, context={'allowed_company_ids': company.ids})
batch = cash['baseer.purchase.batch'].create({'company_id': company.id, 'line_ids': [Command.create({
    'partner_id': supplier.id, 'invoice_date': fields.Date.today(), 'supplier_ref': 'AR1-UI-001',
    'category_map_id': mapping.id, 'gross_amount': 115, 'vat_enabled': True, 'is_credit': True,
})]})
Path('/mnt/qa-evidence/ar1-ui-fixtures.json').write_text(json.dumps({
    'users': actors, 'batch': batch.id, 'action': env.ref('baseer_purchase_batch.action_purchase_batches').id,
    'company': company.id, 'supplier': supplier.id,
}, indent=2))
env.cr.commit()
print('AR1_UI_READY')
