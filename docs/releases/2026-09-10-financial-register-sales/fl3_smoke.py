"""Read-only register reconciliation on an explicitly selected existing database."""
import json
from datetime import date
from decimal import Decimal
from odoo import api
from odoo.fields import Domain

assert env.cr.dbname in ('baseer_ic1_20260910', 'baseer_dev')
env.cr.rollback()
env.cr.execute('SET TRANSACTION READ ONLY')
env.cr.execute('SHOW transaction_read_only')
assert env.cr.fetchone()[0] == 'on'
checks, companies, incoming_outgoing = [], [], []
owner = env['res.users'].search([('baseer_access_role', '=', 'owner'), ('active', '=', True)], limit=1)
assert owner
for company in owner.company_ids:
    actor = api.Environment(env.cr, owner.id, {'allowed_company_ids': [company.id], 'lang': 'en_US'}, su=False)
    moves = actor['account.move']
    data = moves.baseer_financial_register_kpis([])
    sections = next(g for g in data['currency_groups'] if g['currency_id'] == company.currency_id.id)['sections']
    for section in sections:
        for card in section['cards']:
            rows = moves.search(Domain([('state', '=', 'posted')]) & Domain(card['domain']))
            key = card['key']
            if key == 'partial': amount = Decimal(len(rows))
            elif key == 'overdue':
                # Overdue is installment-based; invoice Outstanding can also include future terms.
                continue
            else:
                field = {'total': 'baseer_register_amount', 'settled': 'baseer_register_settled',
                         'outstanding': 'baseer_register_outstanding'}[key]
                amount = sum((Decimal(str(row[field])) for row in rows), Decimal(0))
            assert amount == Decimal(card['display'].replace(',', '')), (company.id, section['key'], key)
            checks.append(f'{company.id}:{section["key"]}:{key}:row-card-parity')
    companies.append({'id': company.id, 'currency': company.currency_id.name,
                      'sections': [{'key': s['key'], 'values': {c['key']: c['display'] for c in s['cards']}} for s in sections]})
    if company.currency_id.name == 'SAR':
        first = moves.search([('state', '=', 'posted')], order='date,id', limit=1)
        months = {date.today().strftime('%Y-%m')}
        if first:
            months.add(first.date.strftime('%Y-%m'))
        for month in sorted(months):
            scoped = moves.with_context(baseer_register_cash_month=month)
            cash_data = scoped.baseer_financial_register_cash_kpis([])
            cards = cash_data['currency_groups'][0]['sections'][0]['cards']
            visible_domain = Domain([('state', '=', 'posted'), ('baseer_register_cash_visible', '=', True)])
            for card in cards:
                rows = scoped.search(visible_domain & Domain(card['domain']))
                field = {'receipts': 'baseer_register_cash_receipts',
                         'payments': 'baseer_register_cash_payments',
                         'net': 'baseer_register_cash_net'}[card['key']]
                amount = sum((Decimal(str(row[field])) for row in rows), Decimal(0))
                assert amount == Decimal(card['display'].replace(',', '')), (company.id, month, card['key'])
                checks.append(f'{company.id}:{month}:incoming-outgoing:{card["key"]}:row-card-parity')
            incoming_outgoing.append({'company': company.id, 'month': month,
                                      'values': {c['key']: c['display'] for c in cards}})
env.cr.rollback()
print('FL3_SMOKE_JSON ' + json.dumps({'status': 'PASS', 'database': env.cr.dbname,
    'checks': checks, 'companies': companies, 'incoming_outgoing': incoming_outgoing,
    'database_enforced_read_only': True, 'rollback': True}))
