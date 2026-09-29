"""Create a paid two-row purchase batch for isolated IC2 UI checks."""
import json
from pathlib import Path
from odoo import Command, fields

assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
meta = json.loads(Path('/mnt/qa-evidence/ic1-ui-fixtures.json').read_text())
actor = env(user=meta['user_ids']['owner'], su=False,
            context={'allowed_company_ids': [meta['company_id']], 'lang': 'ar_001'})
company = actor['res.company'].browse(meta['company_id'])
invoice = actor['account.move'].browse(meta['move_id'])
mapping = actor['baseer.purchase.category.map'].search([('company_id', '=', company.id)], limit=1)
journal = actor['account.journal'].search([('company_id', '=', company.id), ('type', 'in', ['cash', 'bank'])]).filtered(
    lambda item: item.default_account_id.account_type == 'asset_cash')[:1]
method = journal.outbound_payment_method_line_ids.filtered(
    lambda item: item.code == 'manual' and item.payment_account_id == journal.default_account_id)[:1]
assert mapping and method
batch = actor['baseer.purchase.batch.line'].search([('supplier_ref', '=', 'IC2-UI-BATCH-0')], limit=1).batch_id
if not batch:
    batch = actor['baseer.purchase.batch'].create({'company_id': company.id, 'line_ids': [Command.create({
        'invoice_date': fields.Date.context_today(invoice), 'partner_id': invoice.partner_id.id,
        'supplier_ref': 'IC2-UI-BATCH-' + str(i), 'category_map_id': mapping.id,
        'description': 'IC2 isolated UI purchase', 'gross_amount': 500, 'tax_id': False,
        'payment_method_line_id': method.id, 'is_credit': False}) for i in range(2)]})
    batch.action_approve()
result = {'database': env.cr.dbname, 'batch_id': batch.id, 'company_id': company.id,
          'rows': [{'id': row.id, 'invoice_id': row.move_id.id, 'payment_id': row.payment_id.id}
                   for row in batch.line_ids.sorted('id')], 'qa_fixture_committed': True, 'main_untouched': True}
env.cr.commit()
Path('/mnt/qa-evidence/ic2-ui-fixtures-batch.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
