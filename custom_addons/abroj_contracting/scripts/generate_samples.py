"""Run through odoo-bin shell on the designated throwaway database only."""
import base64
from pathlib import Path

assert env.cr.dbname == 'abroj_contracting_544_run9', 'Samples must only run in the throwaway test database'
out = Path('/workspace/abroj-contract-samples')
out.mkdir(exist_ok=True)
company_values = {
    'name': 'Abroj Contracting — شركة أبروج للمقاولات (عينة)',
    'contracting_name_ar': 'مؤسسة ابرج للمقاولات',
    'contracting_name_en': 'ABROJ',
    'company_registry': '1010000000', 'vat': '300000000000003',
    'street': 'طريق الملك فهد / King Fahd Road', 'city': 'الرياض / Riyadh',
    'country_id': env.ref('base.sa').id,
    'phone': '+966 11 000 0000', 'email': 'contracts@example.com',
    'website': 'https://example.com', 'currency_id': env.ref('base.SAR').id,
}
company = env['res.company'].search([('name', '=', company_values['name'])], limit=1)
if not company:
    company = env['res.company'].with_context(install_mode=True, install_demo=True).create(company_values)
else:
    company.write(company_values)
company.contracting_white_logo = base64.b64encode(Path('/workspace/abroj-baseer-production/custom_addons/abroj_contracting/static/img/abroj-logo-core-white-20261004.svg').read_bytes())
logo = Path('/workspace/abroj-baseer-production/custom_addons/abroj_contracting/static/img/abroj-logo-core-primary-20261004.png')
if logo.exists():
    company.logo = base64.b64encode(logo.read_bytes())
env = env(context=dict(env.context, allowed_company_ids=[company.id]))
client = env['res.partner'].create({'name': 'عميل تجريبي / Sample Client', 'vat': '310000000000003', 'country_id': env.ref('base.sa').id})
subparty = env['res.partner'].create({'name': 'مقاول تجريبي / Sample Subcontractor', 'vat': '320000000000003', 'country_id': env.ref('base.sa').id})
project = env['project.project'].create({
    'name': 'تشطيب مكتب تجريبي / Sample Office Fit-out', 'partner_id': client.id,
    'company_id': company.id, 'contract_value': 100000, 'contract_vat_percent': 15,
    'contract_retention_percent': 5, 'contracting_start': '2026-11-01', 'contracting_end': '2027-01-30',
    'contracting_goal': 'أعمال التشطيب والكهرباء والتكييف وفق المخططات المعتمدة.\nFit-out, electrical and HVAC works under approved drawings.',
    'contracting_goal_en': 'Fit-out, electrical and HVAC works under approved drawings.',
    'contracting_goal_ar': 'أعمال التشطيب والكهرباء والتكييف وفق المخططات المعتمدة.',
    'contract_payment_schedule_en': '30% advance\n40% after main works\n30% on handover',
    'contract_payment_schedule_ar': '30% مقدم\n40% بعد إنجاز الأعمال الرئيسية\n30% عند التسليم',
    'contract_payment_schedule': '30% مقدم / Advance\n40% بعد إنجاز الأعمال الرئيسية / Main works\n30% عند التسليم / Handover',
})
sub = env['abroj.contracting.subcontractor'].create({
    'project_id': project.id, 'partner_id': subparty.id, 'agreed_amount': 60000,
    'contract_type': 'materials', 'retention_percent': 5, 'duration_days': 90,
    'start_date': '2026-11-01', 'end_date': '2027-01-30',
    'scope_en': 'Execute fit-out per approved drawings',
    'scope_ar': 'تنفيذ التشطيبات وفق المخططات',
    'payment_terms_en': '20% advance, 60% progress, 20% handover',
    'payment_terms_ar': '20% مقدم، 60% حسب الإنجاز، 20% عند التسليم',
    'penalties_en': 'SAR 500 per day of delay, capped at 10% of contract value',
    'penalties_ar': '500 ريال عن كل يوم تأخير بحد أقصى 10% من قيمة العقد',
    'scope': 'تنفيذ التشطيبات وفق المخططات / Execute fit-out per approved drawings',
    'payment_terms': '20% مقدم، 60% حسب الإنجاز، 20% عند التسليم\n20% advance, 60% progress, 20% handover',
    'penalties': '500 ريال عن كل يوم تأخير بحد أقصى 10% من قيمة العقد\nSAR 500 per day of delay, capped at 10% of contract value',
})
env['abroj.contracting.invoice'].create({
    'project_id': project.id, 'subcontractor_id': sub.id, 'number': 'SAMPLE-MAT-001',
    'amount': 10000, 'invoice_kind': 'materials_company', 'buyer_vat': company.vat,
}).action_confirm()
def voucher(kind, amount, date):
    v = env['abroj.contracting.voucher'].create({
        'project_id': project.id, 'partner_id': client.id if kind == 'receipt' else subparty.id,
        'subcontractor_id': sub.id if kind == 'payment' else False,
        'kind': kind, 'amount': amount, 'date': date, 'method': 'bank',
        'memo': 'دفعة وفق العقد / Payment under contract',
    })
    v.action_issue()
    return v
voucher('receipt', 20000, '2026-11-01')
voucher('receipt', 10000, '2026-11-15')
receipt = voucher('receipt', 15000, '2026-12-01')
voucher('payment', 5000, '2026-11-01')
voucher('payment', 10000, '2026-11-15')
payment = voucher('payment', 8000, '2026-12-01')
for report, record, filename in [
    ('agreement', project, 'client_contract_sample.pdf'),
    ('subcontract', sub, 'subcontractor_contract_sample.pdf'),
    ('voucher', receipt, 'receipt_voucher_sample.pdf'),
    ('voucher', payment, 'payment_voucher_sample.pdf'),
]:
    pdf, kind = env['ir.actions.report'].with_context(force_report_rendering=True)._render_qweb_pdf('abroj_contracting.' + report, record.ids)
    assert kind == 'pdf' and pdf.startswith(b'%PDF-')
    (out / filename).write_bytes(pdf)
    print(filename, len(pdf))
print('Receipt remaining:', receipt.balance_remaining, 'Payment remaining:', payment.balance_remaining)
# No commit: demo records are rolled back when the shell closes.
env.cr.rollback()
