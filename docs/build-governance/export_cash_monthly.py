"""QA-only native monthly PDF/XLSX export and original-report smoke."""
import json
from pathlib import Path

assert env.cr.dbname == 'baseer_reports_qa_20260907'
out = Path('/mnt/qa-evidence')
c = env['res.company'].browse(9)
base = env.ref('baseer_cash_categories.report_cash_categories').with_context(allowed_company_ids=c.ids).with_company(c)
checks = []
for language, inclusive, months, suffix in [
    ('ar_001', True, ['2026-07', '2026-08', '2026-09'], 'ar_gross'),
    ('ar_001', False, ['2026-07', '2026-08', '2026-09'], 'ar_net'),
    ('en_US', True, ['2026-07', '2026-08', '2026-09'], 'en_gross'),
    ('en_US', False, ['2026-07', '2026-08', '2026-09'], 'en_net'),
    ('ar_001', True, ['2026-%02d' % m for m in range(1, 13)], 'ar_year'),
]:
    opts = {'date': {'mode': 'range', 'date_from': '2026-07-01', 'date_to': '2026-09-30'},
            'baseer_months': months, 'company_ids': c.ids, 'posted_only': True, 'baseer_include_tax': inclusive}
    report = base.with_context(lang=language)
    payload = report.render(opts, use_cache=False)
    pdf = report.render_pdf(opts, use_cache=False)
    xlsx = report.render_xlsx(opts, use_cache=False)
    assert pdf.startswith(b'%PDF-') and xlsx.startswith(b'PK')
    prefix = 'cash_monthly_' + suffix
    (out / (prefix+'.pdf')).write_bytes(pdf)
    (out / (prefix+'.xlsx')).write_bytes(xlsx)
    (out / (prefix+'.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    helper = report.env['report.eh_account_dynamic_reports.report_dynamic_pdf_template'].with_context(baseer_cash_pdf=True)
    rendered = helper._render_lines(payload)
    chunks = helper._build_pdf_table_chunks(payload['columns'], rendered)
    assert all(len(panel['columns']) <= 6 for panel in chunks)
    assert [col['expression_label'] for panel in chunks for col in panel['columns'][1:]] == [
        col['expression_label'] for col in payload['columns'][1:]]
    for index, line in enumerate(rendered):
        assert [v for panel in chunks for v in panel['lines'][index]['cells']] == line['cells']
    for original, line in zip(payload['lines'], rendered):
        expected = original['columns'][-1].get('display_value') or ''
        assert line['cells'][-1]['display'] == expected
    checks.append(dict(file=prefix, pdf_bytes=len(pdf), xlsx_bytes=len(xlsx), totals=payload['totals']))
for code in ('profit_and_loss', 'cash_flow'):
    old = env['eh.account.dynamic.report'].with_context(allowed_company_ids=[6]).with_company(env['res.company'].browse(6)).search([('code', '=', code)])
    opts = {'date': {'mode': 'range', 'date_from': '2026-09-01', 'date_to': '2026-09-30'}, 'company_ids': [6], 'posted_only': True}
    result = old.render(opts, use_cache=False)
    checks.append(dict(existing=code, totals=result['totals']))
    if code == 'profit_and_loss':
        (out / 'cash_monthly_original_pnl.pdf').write_bytes(old.with_context(
            lang='en_US', baseer_cash_pdf=True, baseer_cash_pdf_report_id=base.id).render_pdf(opts, use_cache=False))
(out / 'cash_monthly_export_checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
env.cr.rollback()
print('MONTHLY_EXPORT_SUCCESS', len(checks))
