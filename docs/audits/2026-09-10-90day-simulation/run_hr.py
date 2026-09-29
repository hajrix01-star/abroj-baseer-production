import json
import traceback
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from odoo import api

assert env.cr.dbname == 'baseer_sim90_20260910'
root = Path('/tmp/sim90')
info = json.loads((root / 'context.json').read_text(encoding='utf8'))
local = api.Environment(env.cr, info['user_id'], {'allowed_company_ids': [info['company_id']],
    'lang': 'en_US', 'tz': 'Asia/Riyadh', 'tracking_disable': True, 'mail_create_nolog': True,
    'mail_create_nosubscribe': True, 'mail_notify_force_send': False}, su=False)
ctx = dict(info, company=local['res.company'].browse(info['company_id']),
    cash_journal=local['account.journal'].browse(info['cash_journal_id']),
    bank_journal=local['account.journal'].browse(info['bank_journal_id']))
scope = {}
exec(compile((root / 'seed_hr.py').read_bytes(), 'seed_hr.py', 'exec'), scope)
try:
    result = scope['seed_hr'](local, ctx)
    local.flush_all()
    checks = []
    for row in result['manifest']:
        record = local[row['model']].with_context(active_test=False).browse(row['id'])
        for field, expected in row['expected'].items():
            actual = record[field]
            if isinstance(expected, str) and record._fields[field].type in ('float', 'monetary'):
                actual = str(Decimal(str(actual)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
                expected = str(Decimal(expected).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
            checks.append({'model': row['model'], 'id': row['id'], 'field': field,
                           'expected': expected, 'actual': actual, 'passed': expected == actual})
    result['seed_checks'] = checks
    result['failed_checks'] = [c for c in checks if not c['passed']]
    (root / 'hr-manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    assert not result['failed_checks'], result['failed_checks'][:20]
    env.cr.commit()
    print('SIM90_HR_COMPLETE', result['counts'], 'checks', len(checks), flush=True)
except Exception:
    env.cr.rollback()
    (root / 'hr-error.txt').write_text(traceback.format_exc(), encoding='utf8')
    raise
