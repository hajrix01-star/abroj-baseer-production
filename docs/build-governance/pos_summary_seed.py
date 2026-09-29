"""Explicit QA-only setup: new isolated journals and methods, no main data."""
import json
from pathlib import Path
from odoo import Command

assert env.cr.dbname == 'baseer_reports_qa_20260907'
company = env['res.company'].browse(6)
qa = env(context=dict(env.context, allowed_company_ids=[company.id], lang='en_US'))
config = qa['pos.config'].search([('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
if not config:
    receivable = company.account_default_pos_receivable_account_id
    sale_journal = qa['account.journal'].browse(30)
    tax = qa['account.tax'].browse(83)
    income = qa['account.account'].browse(595)
    assert sale_journal.company_id == company and tax.company_id == company and company in income.company_ids
    product = qa['product.product'].create({
        'name': 'QA — ملخص المبيعات الخارجية', 'type': 'service', 'company_id': company.id,
        'available_in_pos': True, 'sale_ok': True, 'purchase_ok': False,
        'property_account_income_id': income.id, 'taxes_id': [Command.set(tax.ids)],
    })
    categories = {}
    for kind, name in [('cash', 'النقد'), ('bank', 'البنوك'), ('platform', 'تطبيقات التوصيل')]:
        categories[kind] = qa['baseer.pos.payment.category'].create({'name': name, 'kind': kind, 'company_id': company.id})
    methods = qa['pos.payment.method']
    for kind, name, code in [('cash', 'كاش', 'PSC'), ('bank', 'بنك', 'PSB'), ('platform', 'هنقرستيشن', 'PSH'), ('platform', 'جاهز', 'PSJ'), ('platform', 'كيتا', 'PSK')]:
        journal = qa['account.journal'].create({'name': 'QA ملخصات — ' + name, 'code': code, 'type': 'cash' if kind == 'cash' else 'bank', 'company_id': company.id})
        vals = {'name': name, 'company_id': company.id, 'journal_id': journal.id, 'receivable_account_id': receivable.id, 'payment_method_type': 'none', 'baseer_category_id': categories[kind].id}
        if kind == 'bank':
            journal.default_account_id.reconcile = True
            vals['outstanding_account_id'] = journal.default_account_id.id
        elif kind == 'platform':
            clearing = qa['account.account'].create({'name': 'QA تسوية — ' + name, 'code': '129' + code[-1] + '01', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [Command.set(company.ids)]})
            vals['outstanding_account_id'] = clearing.id
        methods |= qa['pos.payment.method'].create(vals)
    config = qa['pos.config'].create({
        'name': 'QA ARZ — ملخصات المبيعات', 'company_id': company.id,
        'baseer_summary_only': True, 'baseer_summary_product_id': product.id, 'baseer_summary_tax_id': tax.id,
        'journal_id': sale_journal.id, 'invoice_journal_id': sale_journal.id,
        'payment_method_ids': [Command.set(methods.ids)], 'cash_control': True, 'use_presets': False,
    })
config._validate_baseer_setup()
data = {'company_id': company.id, 'config_id': config.id, 'product_id': config.baseer_summary_product_id.id, 'tax_id': config.baseer_summary_tax_id.id, 'methods': config.payment_method_ids.read(['name', 'journal_id', 'outstanding_account_id', 'baseer_category_id'])}
env.cr.commit()
Path('/mnt/qa-evidence/pos_summary_fixture.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('POS_SUMMARY_SEED_OK', json.dumps(data, ensure_ascii=False))
