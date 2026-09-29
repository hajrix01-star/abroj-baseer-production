"""Synthetic read-query load in a rollback-only isolated database; not posting capacity."""
import json
import statistics
import time
from pathlib import Path
from odoo import fields, Command
from odoo.tools import SQL
assert env.cr.dbname == 'baseer_partner_priority_qa_20260909'
try:
    company = env['res.company'].search([], order='id', limit=1)
    P = env['res.partner'].with_company(company).with_context(res_partner_search_mode='supplier')
    seed = P.create({'name':'PP1 capacity seed','is_company':True})
    env.flush_all()
    env.cr.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='res_partner' AND column_name <> 'id' ORDER BY ordinal_position")
    partner_columns = [r[0] for r in env.cr.fetchall()]
    partner_values = [SQL("'PP1 CAP ' || n") if col in ('name','complete_name') else SQL.identifier('source',col) for col in partner_columns]
    env.cr.execute(SQL('INSERT INTO res_partner (%s) SELECT %s FROM res_partner source CROSS JOIN generate_series(1,10000)n WHERE source.id=%s RETURNING id',
        SQL(',').join(map(SQL.identifier, partner_columns)),SQL(',').join(partner_values),seed.id))
    partner_ids = [r[0] for r in env.cr.fetchall()]
    env.cr.execute('UPDATE res_partner SET commercial_partner_id=id WHERE id=ANY(%s)', [partner_ids])
    favorite = P.browse(partner_ids[-1])
    favorite.baseer_is_favorite = True
    account = env['account.account'].with_company(company).search([('company_ids', 'in', company.ids), ('account_type', '=', 'expense')], limit=1)
    journal = env['account.journal'].with_company(company).search([('company_id', '=', company.id), ('type', '=', 'purchase')], limit=1)
    move = env['account.move'].with_company(company).create({
        'move_type': 'in_invoice', 'partner_id': partner_ids[0], 'company_id': company.id,
        'journal_id': journal.id, 'invoice_date': fields.Date.today(),
        'invoice_line_ids': [Command.create({'name': 'capacity fixture', 'quantity': 1, 'price_unit': 1,
            'account_id': account.id, 'tax_ids': [Command.clear()]})],
    })
    move.action_post()
    env.flush_all()
    env.cr.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='account_move' AND column_name <> 'id' ORDER BY ordinal_position")
    columns = [r[0] for r in env.cr.fetchall()]
    expressions = []
    for col in columns:
        if col == 'name':
            expressions.append(SQL("'PP1/CAP/' || n"))
        elif col == 'partner_id' or col == 'commercial_partner_id':
            expressions.append(SQL('(%s::int[])[1 + ((n-1) %% 10000)]', partner_ids))
        else:
            expressions.append(SQL.identifier('source', col))
    env.cr.execute(SQL('INSERT INTO account_move (%s) SELECT %s FROM account_move source CROSS JOIN generate_series(1,100000)n WHERE source.id=%s',
        SQL(',').join(map(SQL.identifier, columns)), SQL(',').join(expressions), move.id))
    env.cr.execute('ANALYZE res_partner')
    env.cr.execute('ANALYZE account_move')
    timings = []
    for _ in range(6):
        start = time.perf_counter()
        found = P.name_search('PP1 CAP', limit=8)
        timings.append(round((time.perf_counter()-start)*1000, 2))
        assert found[0][0] == favorite.id
    output = {'contacts':10000, 'synthetic_recent_bills':100000, 'readers_measured':1,
              'lookup_ms':timings, 'warm_median_ms':statistics.median(timings[1:]),
              'limit':8, 'favorite_before_limit':True, 'rolled_back':True,
              'limits':'Synthetic query load only; no 20-user or financial posting capacity claim.'}
    Path('/mnt/pp1-evidence/capacity.json').write_text(json.dumps(output,indent=2))
    print('PP1 CAPACITY', json.dumps(output))
finally:
    env.cr.rollback()
    env.cr.execute('ANALYZE res_partner')
    env.cr.execute('ANALYZE account_move')
