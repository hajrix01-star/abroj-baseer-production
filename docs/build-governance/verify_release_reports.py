"""Read/render verification only; never create financial fixtures. Run inside live Odoo container."""
import hashlib
import json
from pathlib import Path
from odoo.tools import config

assert env.cr.dbname in ('baseer_dev', 'baseer_release_rehearsal_20260907')
prefix = 'release_main' if env.cr.dbname == 'baseer_dev' else 'release_rehearsal'
out = Path('/tmp/baseer-release-evidence') if env.cr.dbname == 'baseer_dev' else Path('/mnt/qa-evidence')
out.mkdir(exist_ok=True)
checks = []
admin = env.ref('base.user_admin')
versions = {'eh_account_base': '19.0.1.8.0', 'eh_account_dynamic_reports': '19.0.1.8.1',
            'baseer_report_layout': '19.0.1.1.0', 'baseer_cash_categories': '19.0.1.3.0'}
for name, version in versions.items():
    mod = env['ir.module.module'].search([('name', '=', name)])
    assert mod.state == 'installed' and mod.installed_version == version, (name, mod.state, mod.installed_version)
checks.append({'check': 'installed versions', 'passed': True, 'versions': versions})
companies = env['res.company'].search([])
assert sorted(companies.ids) == [1, 2, 3], companies.ids
assert all(c.currency_id.name == 'SAR' and not c.parent_id for c in companies)
assert set(companies.ids).issubset(admin.company_ids.ids)
checks.append({'check': 'three independent SAR companies and admin access', 'passed': True})
before_moves = env['account.move'].search_count([])
before_lines = env['account.move.line'].search_count([])
stored = env['ir.attachment'].search([('store_fname', '!=', False)])
verified = 0
for attachment in stored:
    path = Path(config['data_dir']) / 'filestore' / env.cr.dbname / attachment.store_fname
    assert path.is_file(), ('missing attachment', attachment.id)
    if attachment.checksum:
        assert hashlib.sha1(path.read_bytes()).hexdigest() == attachment.checksum, ('attachment checksum', attachment.id)
    verified += 1
checks.append({'check': 'filestore attachment integrity', 'passed': True, 'verified': verified})
for company in companies:
    reports = env['eh.account.dynamic.report'].with_user(admin).with_company(company).with_context(
        allowed_company_ids=[company.id], lang='ar_001')
    for code in ('profit_and_loss', 'cash_flow', 'baseer_cash_categories'):
        report = reports.search([('code', '=', code)])
        assert len(report) == 1
        opts = {'date': {'mode': 'range', 'date_from': '2026-09-01', 'date_to': '2026-09-30'},
                'company_ids': [company.id], 'posted_only': True}
        if code == 'baseer_cash_categories':
            opts.update(baseer_months=['2026-07', '2026-08', '2026-09'], baseer_include_tax=True)
        payload = report.render(opts, use_cache=False)
        assert payload.get('columns') and isinstance(payload.get('lines'), list), code
        checks.append({'check': 'report render', 'company': company.id, 'code': code,
                       'passed': True, 'totals': payload.get('totals')})
        if company.id == 1:
            pdf = report.render_pdf(opts, use_cache=False)
            xlsx = report.render_xlsx(opts, use_cache=False)
            assert pdf.startswith(b'%PDF-') and xlsx.startswith(b'PK')
            (out / f'{prefix}_{code}.pdf').write_bytes(pdf)
            (out / f'{prefix}_{code}.xlsx').write_bytes(xlsx)
            checks.append({'check': 'native PDF and XLSX', 'code': code, 'passed': True,
                           'pdf_bytes': len(pdf), 'xlsx_bytes': len(xlsx)})
assert env['account.move'].search_count([]) == before_moves
assert env['account.move.line'].search_count([]) == before_lines
checks.append({'check': 'no financial records changed', 'passed': True, 'moves': before_moves, 'lines': before_lines})
action = env.ref('baseer_cash_categories.action_cash_categories')
result = {'database': env.cr.dbname, 'checks': checks, 'cash_action_id': action.id}
env.cr.rollback()
(out / f'{prefix}_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print('RELEASE_REPORTS_OK', env.cr.dbname, len(checks), 'action', action.id)
