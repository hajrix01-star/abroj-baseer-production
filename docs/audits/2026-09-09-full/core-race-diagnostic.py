from odoo import api
import json
assert env.cr.dbname=='baseer_audit_core_20260909'
e=api.Environment(env.cr,env.ref('base.user_admin').id,{'allowed_company_ids':[10]})
b=e['baseer.purchase.batch'].search([('line_ids.supplier_ref','like','FA1 FINAL%'),('state','=','approved')])
print(json.dumps({'batches':b.ids,'billcounts':b.mapped('bill_count'),'paycounts':b.mapped('payment_count'),'bills':b.move_ids.ids,'pays':b.line_ids.payment_id.ids,'billamounts':b.move_ids.mapped('amount_total'),'taxes':b.move_ids.mapped('amount_tax'),'paylines':b.line_ids.payment_id.move_id.line_ids.read(['account_id','balance']),'billlines':b.move_ids.line_ids.read(['account_id','balance','reconciled'])},default=str))
env.cr.rollback()
