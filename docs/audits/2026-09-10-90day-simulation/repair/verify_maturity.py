"""Read-only timezone correction: independent native supplier-maturity sum."""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo
from odoo import api

assert env.cr.dbname in ('baseer_sim90_fix_20260911', 'baseer_ic1_20260910')
env.cr.rollback()
env.cr.execute('SET TRANSACTION READ ONLY')
actor = api.Environment(env.cr, 5, {'allowed_company_ids': [2], 'lang': 'en_US', 'tz': 'Asia/Riyadh'}, su=False)
assert not actor.su
day = datetime.now(ZoneInfo('Asia/Riyadh')).date()
def q(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
moves = actor['account.move']
facets = [('company_id', '=', 2), ('state', '=', 'posted'), ('date', '>=', '2026-01-01'), ('date', '<=', '2026-03-31')]
payload = moves.baseer_financial_register_kpis(facets)
cards = next(section['cards'] for group in payload['currency_groups'] for section in group['sections'] if section['key'] == 'supplier')
actual = q(next(card['display'] for card in cards if card['key'] == 'overdue').replace(',', ''))
lines = actor['account.move.line'].search([
    ('company_id', '=', 2), ('parent_state', '=', 'posted'),
    ('move_id.date', '>=', '2026-01-01'), ('move_id.date', '<=', '2026-03-31'),
    ('move_id.move_type', 'in', ['in_invoice', 'in_refund']),
    ('account_id.account_type', '=', 'liability_payable'),
    ('date_maturity', '<', day)])
expected = -sum((q(line.amount_residual) for line in lines), Decimal('0.00'))
checks = [{'key': 'all-quarter|2026-01-01:all:supplier:overdue:native-maturity',
           'status': 'PASS' if actual == expected else 'FAIL', 'actual': str(actual), 'expected': str(expected)}]
env.cr.execute('SHOW transaction_read_only')
assert env.cr.fetchone()[0] == 'on'
env.cr.rollback()
result = {'status': checks[0]['status'], 'database': env.cr.dbname, 'su': False,
    'read_only': True, 'rollback': True, 'date_utc': str(date.today()), 'actor_date': str(day),
    'timezone': 'Asia/Riyadh', 'checks': checks,
    'note': 'Native invoice maturity filtered independently; report domain/as_of is not used as expected.',
    'script_sha256': hashlib.sha256(Path('/tmp/sim90/repair/verify_maturity.py').read_bytes()).hexdigest()}
out = Path('/tmp/sim90/repair/verification-maturity.json')
assert not out.exists(), 'Preserve earlier evidence'
out.write_text(json.dumps(result, indent=2))
print('MATURITY_VERIFY', result['status'], actual, expected, day, flush=True)
