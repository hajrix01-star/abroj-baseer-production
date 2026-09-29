"""Correct our synthetic fixture account selection, never a business correction journey.

Authorized exclusively for the not-yet-published SIM90 staging dataset. The
Python lifecycle capability is bounded to verified synthetic invoice IDs.
Balances, reconciliations, payments, dates and all HR accounting stay unchanged.
Recovery point: before-purchase-account-repair.dump, verified before invocation.
"""
import hashlib
import json
import traceback
from decimal import Decimal
from pathlib import Path
from odoo import api, Command
from odoo.addons.baseer_financial_correction.models.lifecycle import lifecycle_scope

assert env.cr.dbname == 'baseer_sim90_20260910'
OUT = Path('/tmp/sim90')
info = json.loads((OUT / 'context.json').read_text(encoding='utf8'))
assert info['company_id'] == 2 and info['user_id'] == 5
source = (OUT / 'purchases.json').read_bytes()
manifest = json.loads(source)
E = api.Environment(env.cr, 5, {'allowed_company_ids': [2], 'lang': 'en_US',
    'tracking_disable': True, 'mail_create_nolog': True, 'mail_create_nosubscribe': True}, su=False)
company = E['res.company'].browse(2)
assert company.name == 'بصير التجريبية — محاكاة 90 يوماً'
assert company.baseer_salary_expense_id.id == 143 and company.expense_account_id.id == 141
assert company.expense_account_id.account_type == 'expense_direct_cost'
assert not E['account.account'].search_count([('company_ids', 'in', [2]), ('code', '=', 'SIMOPEX')])
products = E['product.product'].browse(range(85, 96)).exists()
assert len(products) == 11 and all(p.company_id.id == 2 and 'SIM90' in p.name
    and p.property_account_expense_id.id == 143 for p in products)
document_ids = {int(r['id']) for r in manifest['documents'] if r.get('model', 'account.move') == 'account.move'}
moves = E['account.move'].browse(sorted(document_ids)).exists()
assert len(moves) == len(document_ids) and all(m.company_id.id == 2 and m.state == 'posted'
    and m.move_type in ('in_invoice', 'in_refund') for m in moves)
affected = moves.line_ids.filtered(lambda line: line.account_id.id == 143)
assert len(affected) == 936 and len(affected.move_id) == 936
assert all(line.company_id.id == 2 and line.product_id.id in products.ids
           and line.display_type == 'product' for line in affected)
target_moves = affected.move_id
for field in ('baseer_payslip_id', 'baseer_correction_payslip_id', 'baseer_loan_id', 'baseer_hr_service_id', 'baseer_eos_id'):
    assert not target_moves.filtered(field), field
env.cr.execute('SELECT id FROM account_move WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(target_moves.ids)])
env.cr.execute('SELECT id FROM account_move_line WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(affected.ids)])
affected.invalidate_recordset()
assert all(l.account_id.id == 143 and l.move_id.id in document_ids for l in affected)
affected_ids = set(affected.ids)
result = {'status': 'STARTED', 'database': env.cr.dbname, 'company_id': 2,
    'classification': 'Synthetic fixture setup repair; not a business correction journey or permission change',
    'backup': {'path': '.local-backups/90day-simulation-20260910/before-purchase-account-repair.dump',
               'bytes': 10350337, 'sha256': 'eb1d0e1776359822b8bf8fe3c678222fb8dcb626aef8c32b18299cf7f699f12d'},
    'affected_invoice_ids': sorted(target_moves.ids), 'affected_line_ids': sorted(affected.ids),
    'purchase_documents': len(document_ids), 'affected_invoices': len(target_moves),
    'affected_expense_lines': len(affected), 'products': products.ids, 'checks': [], 'committed': False}


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def financial_snapshot():
    """Normalize only the authorized account_id delta; every other source field is compared."""
    all_moves = E['account.move'].search([('company_id', '=', 2)], order='id')
    move_fields = ['state', 'move_type', 'date', 'invoice_date', 'invoice_date_due', 'partner_id',
        'journal_id', 'currency_id', 'company_id', 'amount_total', 'amount_tax', 'amount_untaxed',
        'amount_residual', 'payment_state', 'ref', 'payment_reference', 'reversed_entry_id',
        'origin_payment_id', 'matched_payment_ids', 'line_ids']
    move_fields += [f for f in all_moves._fields if f.startswith('baseer_') and
        all_moves._fields[f].store and all_moves._fields[f].type in ('many2one', 'one2many', 'many2many')]
    lines = all_moves.line_ids.sorted('id')
    line_fields = ['move_id', 'account_id', 'partner_id', 'company_id', 'currency_id', 'date',
        'debit', 'credit', 'balance', 'amount_currency', 'amount_residual', 'amount_residual_currency',
        'reconciled', 'full_reconcile_id', 'matched_debit_ids', 'matched_credit_ids', 'product_id',
        'quantity', 'price_unit', 'discount', 'tax_ids', 'tax_repartition_line_id', 'tax_tag_ids',
        'tax_line_id', 'display_type', 'name']
    rows = lines.read(line_fields)
    for row in rows:
        if row['id'] in affected_ids:
            row['account_id'] = 'AUTHORIZED_FIXTURE_ACCOUNT_RECLASSIFICATION'
    payments = E['account.payment'].search([('company_id', '=', 2)], order='id')
    partials = E['account.partial.reconcile'].search([('company_id', '=', 2)], order='id')
    hr_lines = lines.filtered(lambda l: bool(l.move_id.baseer_payslip_id or l.move_id.baseer_loan_id
        or l.move_id.baseer_hr_service_id or l.move_id.baseer_eos_id or l.move_id.baseer_correction_payslip_id))
    stock = {}
    for model in ('stock.move', 'stock.move.line', 'stock.quant', 'stock.valuation.layer'):
        if model not in E:
            continue
        records = E[model].search([('company_id', '=', 2)], order='id')
        fields = [f for f in ('product_id', 'state', 'date', 'quantity', 'product_uom_qty',
            'value', 'remaining_value', 'unit_cost', 'account_move_id', 'remaining_qty',
            'reserved_quantity', 'location_id', 'location_dest_id', 'lot_id', 'write_date') if f in records._fields]
        stock[model] = digest(records.read(fields))
    return {'all_move_business_fields': digest(all_moves.read(move_fields)),
        'all_line_business_fields_except_authorized_account': digest(rows),
        'payments': digest(payments.read(['state', 'amount', 'date', 'journal_id', 'move_id',
            'partner_id', 'payment_type', 'partner_type', 'destination_account_id', 'invoice_ids'])),
        'reconciliations': digest(partials.read(['debit_move_id', 'credit_move_id', 'amount',
            'debit_amount_currency', 'credit_amount_currency', 'full_reconcile_id'])),
        'hr_lines': digest(hr_lines.read(line_fields)),
        'stock_quantities_valuation_and_movements': stock,
        'roles': digest(E['res.users'].browse([5, 6, 7]).read(['baseer_access_role',
            'baseer_allow_financial_correction', 'group_ids', 'company_ids'])),
        'counts': {'moves': len(all_moves), 'lines': len(lines), 'payments': len(payments),
                   'reconciliations': len(partials), 'hr_lines': len(hr_lines)}}


before = financial_snapshot()
try:
    expense = E['account.account'].create({'name': 'SIM90 مصروفات تشغيلية تجريبية',
        'code': 'SIMOPEX', 'account_type': 'expense', 'company_ids': [Command.set([2])]})
    private = company.baseer_salary_expense_id | company.baseer_salary_payable_id | company.baseer_deduction_account_id | company.baseer_loan_account_id
    assert expense not in private and company.expense_account_id not in private
    group_products = {141: products.filtered(lambda p: p.id in [85, 86, 87, 88, 89, 95]),
                      expense.id: products.filtered(lambda p: p.id in [90, 91, 92, 93, 94])}
    stock_product = products.filtered(lambda p: p.id == 95)
    packaging_category = products.filtered(lambda p: p.id == 89).categ_id
    assert packaging_category
    result['stock_product_category'] = {'product_id': 95, 'old_category_id': stock_product.categ_id.id,
        'old_oracle_category_id': False, 'new_category_id': packaging_category.id}
    stock_product.write({'categ_id': packaging_category.id})
    mapping = []
    for account_id, group in group_products.items():
        group.write({'property_account_expense_id': account_id})
        lines = affected.filtered(lambda l: l.product_id in group)
        lifecycle_scope(lines, target_moves, E['account.payment']).write({'account_id': account_id})
        mapping.append({'old_account_id': 143, 'new_account_id': account_id,
            'product_ids': group.ids, 'line_ids': sorted(lines.ids), 'invoice_ids': sorted(lines.move_id.ids),
            'line_count': len(lines), 'net_balance': str(sum((Decimal(str(l.balance)) for l in lines), Decimal(0)))})
    E.flush_all()
    E.invalidate_all()
    after = financial_snapshot()
    assert before == after, {'before': before, 'after': after}
    assert not moves.line_ids.filtered(lambda line: line.account_id.id == 143)
    assert all(q == 0 for q in [sum((Decimal(str(l.balance)) for l in m.line_ids), Decimal(0)) for m in target_moves])
    assert all(p.property_account_expense_id.id in (141, expense.id) for p in products)
    result.update(status='PASS', before=before, after=after, mapping=mapping,
        new_operating_expense_account_id=expense.id,
        checks=['All amounts, dates, states and source links unchanged', 'All payment and reconciliation business fields unchanged',
                'All actual HR accounting unchanged', 'All actor roles and company permissions unchanged',
                'Exactly 936 verified synthetic expense lines reclassified', 'All affected entries remain balanced'])
    manifest['fixture_account_setup_repair'] = {'classification': result['classification'],
        'old_expense_account_id': 143, 'product_expense_account_ids': {
            str(p.id): p.property_account_expense_id.id for p in products}, 'affected_invoice_ids': sorted(target_moves.ids)}
    account_by_product = {p.id: account_id for account_id, group in group_products.items() for p in group}
    for collection in ('documents', 'manifest'):
        for document in manifest[collection]:
            product_id = document.get('product_id')
            if product_id in account_by_product:
                document['expense_account_id'] = account_by_product[product_id]
            if product_id == 95:
                document['category_id'] = packaging_category.id
                for allocation in document.get('category_allocations', []):
                    allocation['category_id'] = packaging_category.id
    for event in manifest['events']:
        if event.get('product_id') == 95:
            event['category_id'] = packaging_category.id
    # No monetary oracle is rewritten; the stock category is the only event metadata delta.
    def event_money(rows):
        return [{k: v for k, v in row.items() if k != 'category_id'} for row in rows]
    assert digest(event_money(manifest['events'])) == digest(event_money(json.loads(source)['events']))
    result['monetary_events_unchanged'] = True
    print('SIM90_REPAIR_COMMIT_START', len(affected), flush=True)
    env.cr.commit()
    result['committed'] = True
    if not (OUT / 'purchases-before-account-repair.json').exists():
        (OUT / 'purchases-before-account-repair.json').write_bytes(source)
    (OUT / 'purchases.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding='utf8')
except Exception:
    env.cr.rollback()
    result.update(status='FAIL', error=traceback.format_exc())
finally:
    (OUT / 'purchase-account-repair.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    print('SIM90_PURCHASE_ACCOUNT_REPAIR', result['status'], 'COMMITTED', result['committed'], flush=True)
assert result['status'] == 'PASS' and result['committed'], result.get('error', 'Repair failed')
