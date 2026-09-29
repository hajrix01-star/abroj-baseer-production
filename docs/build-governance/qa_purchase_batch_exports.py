"""Read-only export and final narrow edge checks against QA preview fixtures."""
import json
from pathlib import Path
from odoo import Command
from odoo.exceptions import UserError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
local = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids': [6], 'lang': 'ar_001'})
out = Path('/mnt/qa-evidence')
draft = local['baseer.purchase.batch'].browse(24)
ui = local['baseer.purchase.batch'].search([('line_ids.supplier_ref', '=', 'PB1 UI/001')])
assert len(ui) == 1 and ui.state == 'approved' and ui.line_ids.move_id.payment_state == 'paid'
assert ui.line_ids.move_id.amount_total == 115 and ui.line_ids.move_id.amount_tax == 15
counts = [env[m].search_count([]) for m in ('account.move', 'account.move.line', 'account.payment')]
checks = ['UI-created batch is posted and paid, gross115/net100/tax15']
maps = local['baseer.purchase.category.map'].name_search('مياه', [('company_id', '=', 6)])
assert len(maps) == 1, maps
checks.append('category search uses category text and returns only matching map')
for lang in ('ar_001', 'en_US'):
    for label, batch in [('draft', draft), ('approved', ui)]:
        scoped = batch.with_context(lang=lang)
        data = scoped._get_print_data()
        assert not any(ch in json.dumps(data, ensure_ascii=False) for ch in '٠١٢٣٤٥٦٧٨٩'), 'non-Western numeric print data'
        pdf, _ = local['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf('baseer_purchase_batch.action_report_purchase_batch', res_ids=batch.ids)
        assert pdf.startswith(b'%PDF-')
        (out / f'purchase_batch_{label}_{lang}.pdf').write_bytes(pdf)
        checks.append(f'native PDF {label}/{lang}: {len(pdf)} bytes')
        if label == 'draft':
            assert data['totals'] == {'gross': '402.50', 'net': '350.00', 'tax': '52.50'}
        else:
            assert data['totals'] == {'gross': '115.00', 'net': '100.00', 'tax': '15.00'}
            assert data['rows'][0]['invoice'] == ui.line_ids.move_id.name
try:
    with env.cr.savepoint():
        usd = local.ref('base.USD')
        usd.active = True
        j = local['account.journal'].create({'name': 'PB1 foreign currency probe', 'code': 'PBF', 'type': 'bank', 'company_id': 6, 'currency_id': usd.id})
        method = j.outbound_payment_method_line_ids[:1]
        method.payment_account_id = j.default_account_id
        vals = ui.line_ids.copy_data()[0]
        for field in ('batch_id', 'company_id', 'currency_id', 'net_amount', 'tax_amount', 'batch_state', 'bill_payment_state'):
            vals.pop(field, None)
        vals.update(supplier_ref='PB1 foreign currency probe', payment_method_line_id=method.id)
        local['baseer.purchase.batch'].create({'company_id': 6, 'line_ids': [Command.create(vals)]})
except UserError as exc:
    assert 'عملة' in str(exc), str(exc)
    checks.append('foreign-currency payment journal rejected with Arabic message')
else:
    raise AssertionError('Foreign currency journal accepted')
assert counts == [env[m].search_count([]) for m in ('account.move', 'account.move.line', 'account.payment')]
env.cr.rollback()
(out / 'purchase_batch_export_checks.json').write_text(json.dumps({'checks': checks, 'passed': len(checks),
    'draft_id': draft.id, 'ui_approved_id': ui.id, 'ui_invoice_id': ui.line_ids.move_id.id}, ensure_ascii=False, indent=2), encoding='utf-8')
print('PB1_EXPORTS_OK', checks)
