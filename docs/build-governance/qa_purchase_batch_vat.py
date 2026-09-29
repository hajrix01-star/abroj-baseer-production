"""QA2 VAT bridge behavior and native lifecycle; all financial writes roll back."""
import json
from decimal import Decimal
from pathlib import Path
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
local = env(user=env.ref('base.user_admin').id, context={'allowed_company_ids': [6], 'lang': 'en_US', 'tz': 'Asia/Riyadh'})
company = local['res.company'].browse(6)
tax = company.account_purchase_tax_id
sample = local['baseer.purchase.batch'].browse(24).line_ids[0]
Batch, Line = local['baseer.purchase.batch'], local['baseer.purchase.batch.line']
checks = []
serial = 0

def check(condition, label):
    assert condition, label
    checks.append(label)

def denied(fn, label):
    try:
        with env.cr.savepoint():
            fn()
    except (UserError, ValidationError, AccessError):
        check(True, label)
    else:
        raise AssertionError(label + ' was allowed')

def cents(value):
    return Decimal(str(value)).quantize(Decimal('.01'))

def counts():
    return {name: local[name].search_count([]) for name in ('account.move', 'account.move.line', 'account.payment')}

def make(**extra):
    global serial
    serial += 1
    row = {'invoice_date': '2026-09-07', 'partner_id': sample.partner_id.id,
           'supplier_ref': 'PB2 VAT TEST/' + str(serial), 'category_map_id': sample.category_map_id.id,
           'gross_amount': 115, 'payment_method_line_id': sample.payment_method_line_id.id}
    row.update(extra)
    return Batch.create({'company_id': company.id, 'entry_date': '2026-09-07', 'line_ids': [Command.create(row)]})

before = counts()
check(bool(tax) and tax.amount == 15, 'QA principal purchase tax is configured15%')
b = make(vat_enabled=True)
line = b.line_ids
check(line.tax_id == tax and line.vat_enabled and not line.vat_is_custom, 'toggle selects exact company principal tax')
check(cents(line.net_amount) == 100 and cents(line.tax_amount) == 15, 'on: gross115/net100/tax15')
line.write({'vat_enabled': False})
check(not line.tax_id and not line.vat_enabled and cents(line.net_amount) == 115 and cents(line.tax_amount) == 0, 'off: gross115/net115/tax0')
line.write({'vat_enabled': True, 'tax_id': tax.id})
check(line.tax_id == tax, 'compatible UI onchange tax_id and toggle accepted')
denied(lambda: line.write({'vat_enabled': False, 'tax_id': tax.id}), 'contradictory off and tax rejected')
denied(lambda: line.write({'vat_enabled': True, 'tax_id': False}), 'contradictory on and no tax rejected')
denied(lambda: make(vat_enabled='false'), 'nonboolean RPC flag rejected')
check(line.tax_id == tax and cents(line.tax_amount) == 15, 'rejected writes preserve draft VAT')
b.action_approve()
check(line.move_id.state == 'posted' and line.move_id.payment_state == 'paid', 'toggle bill natively posted and fully paid')
check(cents(line.move_id.amount_total) == 115 and cents(line.move_id.amount_tax) == 15 and cents(line.move_id.amount_residual) == 0, 'native paid bill matches displayed tax')
denied(lambda: line.write({'vat_enabled': False}), 'approved VAT toggle protected through RPC')
plain = make(vat_enabled=False)
plain.action_approve()
check(plain.line_ids.move_id.payment_state == 'paid' and cents(plain.line_ids.move_id.amount_tax) == 0, 'tax-off bill natively posted and paid115 with zeroVAT')

legacy_tax = tax.copy({'name': 'PB2 legacy5%', 'amount': 5})
legacy = make(tax_id=legacy_tax.id)
old_tax = legacy.line_ids.tax_id
old_amounts = (legacy.line_ids.net_amount, legacy.line_ids.tax_amount)
check(legacy.line_ids.vat_is_custom, 'legacy5% visibly distinguished from principal15')
legacy.line_ids.write({'description': 'description only'})
legacy.line_ids.invalidate_recordset()
check(legacy.line_ids.tax_id == old_tax and (legacy.line_ids.net_amount, legacy.line_ids.tax_amount) == old_amounts, 'legacy tax preserved across unrelated write and reread')
legacy.action_approve()
check(legacy.line_ids.move_id.invoice_line_ids.tax_ids == legacy_tax, 'existing legacytax approved without implicit replacement')

class Restore(Exception):
    pass

def invalid_default(changes, label):
    try:
        with env.cr.savepoint():
            if changes is None:
                company.account_purchase_tax_id = False
            else:
                invalid = tax.copy({'name': 'PB2 invalid default', **changes})
                company.account_purchase_tax_id = invalid
            denied(lambda: make(vat_enabled=True), label)
            # Reading approved rows must not resolve or reject current settings.
            line.invalidate_recordset()
            check(line.tax_id == tax, label + ': historical record remains readable')
            raise Restore()
    except Restore:
        pass

invalid_default(None, 'missing company default rejected')
invalid_default({'amount': 5}, 'non15 company default rejected')
invalid_default({'active': False}, 'archived company default rejected')
invalid_default({'type_tax_use': 'sale'}, 'sale company default rejected')
invalid_default({'include_base_amount': True}, 'compound company default rejected')
foreign_tax = local['account.tax'].with_context(allowed_company_ids=[7]).browse(139)
denied(lambda: make(vat_enabled=True, tax_id=foreign_tax.id), 'crosscompany tax and toggle rejected')

env.cr.rollback()
check(counts() == before, 'all test financial documents rolled back')
result = {'database': env.cr.dbname, 'passed': len(checks), 'checks': checks, 'rollback': True}
Path('/mnt/qa-evidence/purchase_batch_vat_checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print('PURCHASE_BATCH_VAT_OK', len(checks))
