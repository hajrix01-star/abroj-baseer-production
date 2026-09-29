"""QA3 short labels, hierarchy, searches and report appearance. Rollback fixtures."""
import json
from pathlib import Path
assert env.cr.dbname == 'baseer_reports_qa_20260907'
local = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids': [6], 'lang': 'ar_001'})
Cat = local['product.category']
Map = local['baseer.purchase.category.map']
checks = []
def check(value, label):
    assert value, label
    checks.append(label)

parents = Cat.create([{'name': 'QA3 food'}, {'name': 'QA3 supplies'}])
leaves = Cat.create([{'name': 'Water', 'parent_id': p.id} for p in parents])
for leaf in leaves:
    full = leaf.complete_name
    check(leaf.display_name == 'Water', 'default short label ' + full)
    check(leaf.with_context(hierarchical_naming=True).display_name == full, 'explicit native full path ' + full)
    check(leaf.with_context(hierarchical_naming=False).display_name == 'Water' and leaf.display_name == 'Water', 'context cache isolation ' + full)
    found = Cat.name_search(full, operator='ilike')
    check([i for i, name in found] == leaf.ids, 'full path search distinguishes duplicate leaves ' + full)
    check(leaf.parent_id in parents and str(leaf.parent_id.id) + '/' in leaf.parent_path, 'hierarchy and parent path retained ' + full)

sample = Map.browse(2)
maps = Map.browse()
for leaf in leaves:
    product = local['product.product'].create({'name': 'QA3 category service', 'type': 'service', 'company_id': 6,
        'categ_id': leaf.id, 'property_account_expense_id': sample._validated_expense_account().id})
    mapping = Map.create({'company_id': 6, 'category_id': leaf.id, 'product_id': product.id})
    maps |= mapping
    check(mapping.display_name == 'Water' and mapping.parent_category_id == leaf.parent_id, 'mapping leaf and explicit parent ' + leaf.complete_name)
    check(mapping.with_context(hierarchical_naming=True).display_name == leaf.complete_name, 'mapping explicit hierarchy context ' + leaf.complete_name)
    found = Map.name_search(leaf.complete_name, [('company_id', '=', 6)])
    check([i for i, name in found] == mapping.ids, 'mapping full path search selects correct identity ' + leaf.complete_name)
leaves[0].name = 'Still water'
check(leaves[0].display_name == 'Still water' and maps[0].display_name == 'Still water', 'rename invalidates category and mapping labels')
parents[0].name = 'QA3 beverages'
check(leaves[0].complete_name == 'QA3 beverages / Still water' and leaves[0].display_name == 'Still water', 'parent rename preserves short label and rebuilds path')

draft = local['baseer.purchase.batch'].browse(24)
for line in draft.line_ids:
    check(line.category_map_id.display_name == line.category_map_id.category_id.name, 'existing entry shows only leaf ' + str(line.id))
    if not line.description:
        prepared = line._prepare_approval()
        check(prepared['bill']['invoice_line_ids'][0][2]['name'] == line.category_map_id.category_id.complete_name,
              'future native bill description retains prior full path fallback')
probe = draft.line_ids[0]
probe.description = False
check(probe._prepare_approval()['bill']['invoice_line_ids'][0][2]['name'] == probe.category_map_id.category_id.complete_name,
      'explicit empty description preserves full audit path')
env.cr.rollback()

draft = local['baseer.purchase.batch'].browse(24)
data = draft._get_print_data()
check(data['totals'] == {'gross': '402.50', 'net': '350.00', 'tax': '52.50'}, 'existing report monetary values unchanged')
check(all(row['category'] == line.category_map_id.category_id.name for row, line in zip(data['rows'], draft.line_ids)), 'print categories use short labels')
pdf, _ = local['ir.actions.report']._render_qweb_pdf('baseer_purchase_batch.action_report_purchase_batch', res_ids=draft.ids)
check(pdf.startswith(b'%PDF-'), 'native Arabic PDF rendered')
Path('/mnt/qa-evidence/category_labels_qa3.pdf').write_bytes(pdf)
env.cr.rollback()
Path('/mnt/qa-evidence/category_labels_checks.json').write_text(json.dumps({'passed': len(checks), 'checks': checks, 'fixtures_rolled_back': True}, indent=2), encoding='utf-8')
print('CATEGORY_LABELS_OK', len(checks))
