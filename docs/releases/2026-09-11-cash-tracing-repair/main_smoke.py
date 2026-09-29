"""Read-only report/ledger smoke on original data; no synthetic records created."""
import calendar
import hashlib
import importlib
import json
from pathlib import Path
from decimal import Decimal
from odoo import api, fields
from odoo.fields import Domain

assert env.cr.dbname in ('baseer_dev','baseer_cash_repair_main_20260911')
env.cr.rollback();env.cr.execute('SET TRANSACTION READ ONLY')
checks=[];companies=[];months=[]
owner=env['res.users'].search([('baseer_access_role','=','owner'),('active','=',True)],limit=1)
if not owner:
    owner=env.ref('base.user_admin')
assert owner.active and owner.id!=1
for module, version in CANDIDATE['versions'].items():
    folder=Path(importlib.import_module('odoo.addons.'+module).__file__).parent
    assert str(folder)=='/mnt/baseer-addons/'+module
    actual={'custom_addons/'+module+'/'+p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    expected={p:h for p,h in CANDIDATE['files'].items() if p.startswith('custom_addons/'+module+'/')}
    assert actual==expected
    assert env['ir.module.module'].search([('name','=',module)]).latest_version==version
    checks.append(module+':live-source-and-version')

for company in owner.company_ids:
    E=api.Environment(env.cr,owner.id,{'allowed_company_ids':[company.id],'lang':'en_US'},su=False)
    assert not E.su
    moves=E['account.move'];data=moves.baseer_financial_register_kpis([])
    sections=next(g for g in data['currency_groups'] if g['currency_id']==company.currency_id.id)['sections']
    for section in sections:
        for card in section['cards']:
            rows=moves.search(Domain([('state','=','posted')]) & Domain(card['domain']))
            if card['key']=='overdue': continue
            if card['key']=='partial': value=Decimal(len(rows))
            else:
                field={'total':'baseer_register_amount','settled':'baseer_register_settled','outstanding':'baseer_register_outstanding'}[card['key']]
                value=sum((Decimal(str(x[field])) for x in rows),Decimal(0))
            assert value==Decimal(card['display'].replace(',',''))
            checks.append(f'{company.id}:all:{section["key"]}:{card["key"]}')
    companies.append({'id':company.id,'currency':company.currency_id.name,'sections':sections})
    if company.currency_id.name!='SAR': continue
    first=moves.search([('state','=','posted')],order='date,id',limit=1)
    selected={fields.Date.context_today(E['account.move']).strftime('%Y-%m')}
    if first: selected.add(first.date.strftime('%Y-%m'))
    for month in sorted(selected):
        year,number=map(int,month.split('-'));end=f'{month}-{calendar.monthrange(year,number)[1]}'
        cash=E['eh.account.dynamic.report.handler.baseer_cash_categories'].compute({'company_ids':[company.id],'posted_only':True,'baseer_include_tax':True,'baseer_months':[month],'date':{'mode':'range','date_from':month+'-01','date_to':end}})
        native=E['account.move.line'].search([('company_id','=',company.id),('parent_state','=','posted'),('account_id.account_type','=','asset_cash'),('date','>=',month+'-01'),('date','<=',end)])
        net=sum((Decimal(str(x.balance)) for x in native),Decimal(0)).quantize(Decimal('.01'))
        assert Decimal(cash['meta']['exact_totals']['actual_net_movement'])==net
        assert Decimal(cash['meta']['exact_totals']['balance_check'])==0
        checks.append(f'{company.id}:{month}:cash-native-ledger')
        scoped=moves.with_context(baseer_register_cash_month=month)
        incoming=scoped.baseer_financial_register_cash_kpis([])
        cards=incoming['currency_groups'][0]['sections'][0]['cards']
        for card in cards:
            rows=scoped.search(Domain([('state','=','posted'),('baseer_register_cash_visible','=',True)]) & Domain(card['domain']))
            field={'receipts':'baseer_register_cash_receipts','payments':'baseer_register_cash_payments','net':'baseer_register_cash_net'}[card['key']]
            value=sum((Decimal(str(x[field])) for x in rows),Decimal(0))
            assert value==Decimal(card['display'].replace(',',''))
            checks.append(f'{company.id}:{month}:inout:{card["key"]}')
        months.append({'company':company.id,'month':month,'cash_totals':cash['meta']['exact_totals'],'inout':{c['key']:c['display'] for c in cards}})
env.cr.rollback()
print('MAIN_REPAIR_SMOKE_JSON '+json.dumps({'status':'PASS','candidate':CANDIDATE['commit'],'candidate_sha256':CANDIDATE['candidate_sha256'],'database':env.cr.dbname,'actor_user_id':owner.id,'actor_role':owner.baseer_access_role,'su':False,'read_only':True,'rollback':True,'checks':checks,'companies':companies,'months':months}))
