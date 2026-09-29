"""Explicitly persistent IC2 browser/race fixtures in the isolated QA database only."""
import json
from datetime import timedelta
from pathlib import Path
from odoo import Command, fields

assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
config = env['pos.config'].search([('baseer_summary_only', '=', True), ('company_id', '=', 2)]).filtered(
    lambda c: {'cash', 'bank', 'platform'}.issubset(set(c.payment_method_ids.filtered('active').mapped('baseer_category_id.kind'))))[:1]
assert config
company = config.company_id
owner = env['res.users'].search([('baseer_access_role', '=', 'owner'), ('company_ids', 'in', company.ids)], limit=1)
assert owner
actor = env(user=owner.id, su=False, context={'allowed_company_ids': company.ids, 'lang': 'ar_001'})
methods = [config.payment_method_ids.filtered(lambda m: m.active and m.baseer_category_id.kind == kind)[:1]
           for kind in ('cash', 'bank', 'platform')]
day = fields.Date.context_today(actor['baseer.pos.summary']) - timedelta(days=45)
items = {}
for key, reference in (('summary_ui', 'IC2 QA UI SUMMARY'), ('summary_race', 'IC2 QA RACE SUMMARY')):
    record = actor['baseer.pos.summary'].search([('external_reference', '=', reference)], limit=1)
    if not record:
        while actor['baseer.pos.summary'].search_count([('company_id', '=', company.id), ('business_date', '=', day)]):
            day += timedelta(days=1)
        record = actor['baseer.pos.summary'].create({'company_id': company.id, 'config_id': config.id,
            'business_date': day, 'day_schedule': 'all', 'period_scope': 'all', 'customer_count': 12,
            'external_reference': reference, 'allocation_ids': [Command.create({'payment_method_id': method.id, 'amount': value})
                for method, value in zip(methods, (115, 230, 345))]})
        record.action_approve()
        day += timedelta(days=1)
    items[key] = {'id': record.id, 'name': record.name, 'date': str(record.business_date),
                  'gross': record.amount_gross, 'moves': record._native_moves().ids}
items.update(database=env.cr.dbname, company_id=company.id, owner_id=owner.id,
             method_ids=[m.id for m in methods], qa_fixture_committed=True, main_untouched=True)
env.cr.commit()
Path('/mnt/qa-evidence/ic2-ui-fixtures-summary.json').write_text(json.dumps(items, indent=2), encoding='utf8')
print(json.dumps(items))
