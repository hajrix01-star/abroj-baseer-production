"""Focused PDF presentation checks; real reports only, no financial fixtures."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from openpyxl import load_workbook

assert env.cr.dbname in ('baseer_reports_qa_20260907', 'baseer_dev')
qa = env.cr.dbname != 'baseer_dev'
out = Path('/mnt/qa-evidence') if qa else Path('/tmp/baseer-print-evidence')
out.mkdir(exist_ok=True)
prefix = 'cash_print_qa' if qa else 'cash_print_main'
company = env['res.company'].browse(9 if qa else 1)
base = env.ref('baseer_cash_categories.report_cash_categories').with_company(company).with_context(allowed_company_ids=company.ids)
helper = base.env['report.eh_account_dynamic_reports.report_dynamic_pdf_template'].with_context(baseer_cash_pdf=True)
before = (env['account.move'].search_count([]), env['account.move.line'].search_count([]))
checks = []

def check(condition, label):
    assert condition, label
    checks.append(label)

check(env['ir.module.module'].search([('name', '=', 'baseer_cash_categories')]).installed_version == '19.0.1.3.1', 'patch installed')
for count in (1, 3, 12):
    months = ['2026-09'] if count == 1 else (['2026-07', '2026-08', '2026-09'] if count == 3 else ['2026-%02d' % m for m in range(1, 13)])
    for inclusive in (True, False):
        for language in ('ar_001', 'en_US'):
            report = base.with_context(lang=language)
            opts = {'date': {'mode': 'range', 'date_from': '2026-09-01', 'date_to': '2026-09-30'},
                    'company_ids': company.ids, 'posted_only': True,
                    'baseer_months': months, 'baseer_include_tax': inclusive}
            payload = report.render(opts, use_cache=False)
            snapshot = deepcopy(payload)
            full = helper.with_context(baseer_cash_pdf=False)._render_lines(payload)
            clean = helper._render_lines(payload)
            wanted = [row for row in payload['lines'] if row['id'] != 'baseer-reconciliation'
                      and row.get('parent_id') != 'baseer-reconciliation']
            label = '%s/%s/%s' % (count, inclusive, language)
            check([r['id'] for r in clean] == [r['id'] for r in wanted], label + ' appendix removed, category rows preserved')
            check(len(full) == len(payload['lines']) and any(r['id'] == 'baseer-reconciliation' for r in full), label + ' normal rendering retains details')
            check(payload == snapshot, label + ' input payload unchanged')
            for source, rendered in zip(wanted, clean):
                check([c['value'] for c in rendered['cells']] == [c['value'] for c in source['columns']], label + ' values ' + source['id'])
                check(rendered['cells'][-1]['display'] == (source['columns'][-1].get('display_value') or ''), label + ' percentage ' + source['id'])
            panels = helper._build_pdf_table_chunks(payload['columns'], clean)
            check(all(len(p['columns']) <= 6 for p in panels), label + ' compact panels')
            for index, row in enumerate(clean):
                check([c for p in panels for c in p['lines'][index]['cells']] == row['cells'], label + ' panel cells ' + row['id'])
            if (language == 'ar_001' and (count in (1, 12) and inclusive or count == 3 and not inclusive)) or (count == 1 and inclusive and language == 'en_US'):
                pdf = report.render_pdf(opts, use_cache=False)
                check(pdf.startswith(b'%PDF-'), label + ' native PDF')
                (out / f'{prefix}_{count}_{inclusive}_{language}.pdf').write_bytes(pdf)
            if count == 1 and inclusive and language == 'en_US':
                xlsx = report.render_xlsx(opts, use_cache=False)
                rows = list(load_workbook(BytesIO(xlsx), data_only=True).active.values)
                text = '\n'.join(str(c) for row in rows for c in row if c is not None)
                check('Balance reconciliation details' in text and 'partial payments' in text, 'XLSX still retains appendix')

synthetic = deepcopy(payload)
balance = next(r for r in synthetic['lines'] if r['id'] == 'baseer-total-balance_check')
for cell in balance['columns']:
    cell['value'] = 0
balance['columns'][0]['value'] = 0.004
check(not any(r['id'] == balance['id'] for r in helper._render_lines(synthetic)), 'sub-cent discrepancy rounds to zero')
for value in (0.005, -0.005, 1, -1):
    balance['columns'][0]['value'] = value
    balance['columns'][1]['value'] = -value
    warning = next(r for r in helper._render_lines(synthetic) if r['id'] == balance['id'])
    check(warning['level'] == 0 and warning['cells'][0]['value'] == value, 'offsetting monthly discrepancy remains visible ' + str(value))
other = deepcopy(payload)
other['meta']['report_code'] = 'profit_and_loss'
check(len(helper._render_lines(other)) == len(other['lines']), 'other report with same IDs is not filtered')
old = base.search([('code', '=', 'profit_and_loss')]).with_context(lang='en_US', baseer_cash_pdf=True, baseer_cash_pdf_report_id=base.id)
pdf = old.render_pdf(opts, use_cache=False)
check(pdf.startswith(b'%PDF-'), 'native P&L export with injected context works')
(out / f'{prefix}_pnl.pdf').write_bytes(pdf)
check(before == (env['account.move'].search_count([]), env['account.move.line'].search_count([])), 'no financial rows created')
env.cr.rollback()
(out / f'{prefix}_checks.json').write_text(json.dumps({'database': env.cr.dbname, 'passed': len(checks), 'checks': checks, 'financial_counts': before}, ensure_ascii=False, indent=2), encoding='utf-8')
print('CASH_PRINT_OK', env.cr.dbname, len(checks))
