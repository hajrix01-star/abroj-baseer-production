"""QA-only native exports and comparison report smoke checks."""
import json
from pathlib import Path

assert env.cr.dbname == 'baseer_reports_qa_20260907'
out = Path('/mnt/qa-evidence')
admin = env.ref('base.user_admin')
company = env['res.company'].search([('name', '=', 'QA الفئات النقدية')])
assert len(company) == 1
options = json.loads((out / 'cash_categories_checks.json').read_text())['options']
base = env.ref('baseer_cash_categories.report_cash_categories').with_user(admin).with_context(
    allowed_company_ids=company.ids).with_company(company)
checks = []
for language in ['ar_001', 'en_US']:
    report = base.with_context(lang=language)
    for inclusive in [True, False]:
        opts = dict(options, baseer_include_tax=inclusive)
        prefix = 'cash_categories_%s_%s' % (language, 'gross' if inclusive else 'net')
        payload = report.render(opts, use_cache=False)
        assert payload['totals']['actual_net_movement'] == -271
        assert payload['totals']['balance_check'] == 0
        (out / (prefix + '.json')).write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
        pdf = report.render_pdf(opts, use_cache=False)
        xlsx = report.render_xlsx(opts, use_cache=False)
        assert pdf.startswith(b'%PDF-') and xlsx.startswith(b'PK')
        (out / (prefix + '.pdf')).write_bytes(pdf)
        (out / (prefix + '.xlsx')).write_bytes(xlsx)
        checks.append({'language': language, 'inclusive': inclusive, 'pdf_bytes': len(pdf), 'xlsx_bytes': len(xlsx)})
for code in ['profit_and_loss', 'cash_flow']:
    old_company = env['res.company'].search([('name', '=', 'QA ARZ')])
    old = env['eh.account.dynamic.report'].with_user(admin).with_context(allowed_company_ids=old_company.ids).with_company(old_company).search([('code', '=', code)])
    assert len(old) == 1, code
    old_payload = old.render(dict(options, company_ids=old_company.ids), use_cache=False)
    checks.append({'existing_report': code, 'totals': old_payload['totals']})
action = env.ref('baseer_cash_categories.action_cash_categories')
(out / 'cash_categories_export_checks.json').write_text(json.dumps({'checks': checks, 'action_id': action.id, 'company_id': company.id}, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
env.cr.rollback()  # exports above are files only; no persistent ledger changes
print('CASH_EXPORT_SUCCESS', len(checks), 'checks; action', action.id)
