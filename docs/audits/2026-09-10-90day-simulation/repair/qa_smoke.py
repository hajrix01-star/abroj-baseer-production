"""Read-only acceptance against the actual QA runtime mounts after deployment."""
import hashlib
import importlib
import json
from pathlib import Path
from decimal import Decimal
from odoo import api

assert env.cr.dbname == 'baseer_ic1_20260910'
env.cr.execute('SET TRANSACTION READ ONLY')
root = Path('/tmp/sim90/repair')
candidate = json.loads((root / 'candidate.json').read_text())
E = api.Environment(env.cr, 5, {'allowed_company_ids': [2], 'lang': 'ar_001'}, su=False)
result = {'database': env.cr.dbname, 'candidate_sha256': candidate['candidate_sha256'], 'read_only': True, 'su': E.su, 'checks': [], 'monthly': {}}
def check(name, actual, expected):
    passed = actual == expected
    result['checks'].append({'name': name, 'actual': actual, 'expected': expected, 'passed': passed})
    assert passed, result['checks'][-1]

for module, version in candidate['versions'].items():
    folder = Path(importlib.import_module('odoo.addons.' + module).__file__).parent
    check(module + ':actual-runtime-mount', str(folder), '/mnt/baseer-addons/' + module)
    files = {'custom_addons/' + module + '/' + p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    check(module + ':source-exact', files, {p: sha for p, sha in candidate['files'].items() if p.startswith('custom_addons/' + module + '/')})
    check(module + ':installed-version', E['ir.module.module'].search([('name', '=', module)]).latest_version, version)

H = E['eh.account.dynamic.report.handler.baseer_cash_categories']
expected = {'2026-01': ('1580370.24', '-242942.27', '375808.50', '-48275.01'), '2026-02': ('390409.18', '-358348.12', '388838.00', '-88935.26'), '2026-03': ('431108.52', '-360254.17', '431704.25', '-89673.70')}
for month, values in expected.items():
    payload = H.compute({'company_ids': [2], 'posted_only': True, 'baseer_include_tax': True, 'baseer_months': [month], 'date': {'mode': 'range', 'date_from': month + '-01', 'date_to': month + ('-28' if month.endswith('02') else '-31')}})
    totals = payload['meta']['exact_totals']
    for key, value in zip(('receipts', 'payments', 'sales_collections'), values[:3]):
        check(month + ':' + key, totals[key], value)
    check(month + ':balanced', totals['balance_check'], '0.00')
    salary = next(row for row in payload['lines'] if row['id'] == 'payments/ledger-143')
    check(month + ':salary-category', format(Decimal(str(salary['columns'][0]['value'])), '.2f'), values[3])
    result['monthly'][month] = {'totals': totals, 'salary': values[3], 'diagnostics': payload['meta']['diagnostics']}

_, _, empty, _ = E['account.move']._register_cash_snapshot('2026-09')
check('empty-month:no-platform-warning', empty['meta']['baseer_platform_warning'], '')
check('posted-moves-preserved', E['account.move'].search_count([('company_id', '=', 2), ('state', '=', 'posted')]), 4999)
env.cr.rollback()
result['status'] = 'PASS'
(root / 'qa-smoke.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print('QA_SMOKE_PASS', len(result['checks']), flush=True)
