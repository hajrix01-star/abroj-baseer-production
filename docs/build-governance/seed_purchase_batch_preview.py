"""Clearly labeled, persistent QA-only demo and concurrency fixtures."""
import json
from pathlib import Path
from odoo import Command

assert env.cr.dbname == 'baseer_reports_qa_20260907'
admin = env.ref('base.user_admin')
company = env['res.company'].browse(6)
local = env(user=admin.id, context=dict(env.context, allowed_company_ids=company.ids, tracking_disable=True, mail_create_nolog=True, lang='ar_001'))
assert not local.su
marker = 'PB1 Preview'
check = local['baseer.purchase.batch'].search([('line_ids.supplier_ref', 'like', marker + '%')], limit=1)
assert not check, 'Preview already seeded; use existing evidence IDs, do not duplicate fixtures.'
acct = lambda kind: local['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', kind)], limit=1)
tax = local['account.tax'].search([('company_id', '=', company.id), ('type_tax_use', '=', 'purchase'), ('amount_type', '=', 'percent'), ('amount', '=', 15)], limit=1)
assert tax
partners = [local['res.partner'].create({'name': name, 'company_id': company.id,
    'property_account_payable_id': acct('liability_payable').id, 'property_account_receivable_id': acct('asset_receivable').id})
    for name in ('مورد تجريبي — مواد استهلاكية', 'مورد تجريبي — اتصالات')]
parent = local['product.category'].create({'name': 'تجربة الإدخال الجماعي'})
maps = []
for index, name in enumerate(('مياه ومشروبات', 'اتصالات وإنترنت')):
    cat = local['product.category'].create({'name': name, 'parent_id': parent.id})
    expense = acct('expense_direct_cost') if index == 0 else local['account.account'].search([
        ('company_ids', 'in', company.ids), ('name', 'ilike', 'هاتف'), ('account_type', '=', 'expense')], limit=1)
    assert expense
    product = local['product.product'].create({'name': 'ملخص تجريبي — ' + name, 'type': 'service', 'purchase_ok': True,
        'sale_ok': False, 'company_id': company.id, 'categ_id': cat.id,
        'property_account_expense_id': expense.id, 'supplier_taxes_id': [Command.set(tax.ids)]})
    maps.append(local['baseer.purchase.category.map'].create({'company_id': company.id, 'category_id': cat.id, 'product_id': product.id}))
methods = []
for kind, code, name in [('cash', 'P1C', 'كاش تجريبي — الإدخال الجماعي'), ('bank', 'P1B', 'بنك تجريبي — الإدخال الجماعي')]:
    journal = local['account.journal'].create({'name': name, 'code': code, 'type': kind, 'company_id': company.id})
    method = journal.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'manual')[:1]
    method.payment_account_id = journal.default_account_id
    methods.append(method)

def line(ref, amount=115, paid=True, i=0, day='06'):
    return {'invoice_date': '2026-09-' + day, 'partner_id': partners[i].id, 'supplier_ref': ref,
        'entry_type': 'purchase' if i == 0 else 'expense', 'category_map_id': maps[i].id,
        'description': 'بيانات تجريبية للمعاينة فقط', 'gross_amount': amount, 'tax_id': tax.id,
        'payment_method_line_id': methods[i].id if paid else False}

def batch(rows):
    return local['baseer.purchase.batch'].create({'company_id': company.id, 'entry_date': '2026-09-07',
        'line_ids': [Command.create(vals) for vals in rows]})

preview = batch([line(marker + '/001'), line(marker + '/002', 230, i=1, day='05'), line(marker + '/003', 57.5, paid=False)])
same = batch([line('PB1 Concurrent Same')])
dup_a = batch([line('PB1 Concurrent Duplicate')])
dup_b = batch([line('pb1 concurrent duplicate')])
separate = [batch([line('PB1 Concurrent Separate ' + str(i))]) for i in range(2)]
evidence = {'company_id': company.id, 'preview_id': preview.id, 'same_batch_id': same.id,
    'duplicate_batch_ids': [dup_a.id, dup_b.id], 'separate_batch_ids': [b.id for b in separate],
    'mapping_ids': [m.id for m in maps], 'partner_ids': [p.id for p in partners], 'payment_method_ids': [m.id for m in methods]}
env.cr.commit()
Path('/mnt/qa-evidence/purchase_batch_preview_ids.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
print('PB1_PREVIEW_CREATED', evidence)
