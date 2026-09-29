"""Run with odoo shell on isolated PP1 QA only. All business fixtures roll back."""
import json
import time
from datetime import timedelta
from pathlib import Path
from odoo import Command, fields
from odoo.exceptions import AccessError

assert env.cr.dbname == 'baseer_partner_priority_qa_20260909'
results = []
def check(label, condition):
    assert condition, label
    results.append(label)

def denied(label, fn):
    try:
        with env.cr.savepoint():
            fn()
    except AccessError:
        results.append(label)
    else:
        raise AssertionError(label)

try:
    companies = env['res.company'].search([], order='id', limit=3)
    a, b, c = companies
    P = env['res.partner'].with_context(allowed_company_ids=[a.id, b.id], res_partner_search_mode='supplier')
    peers = P.create([{'name': 'PP1 TEST ' + name, 'supplier_rank': 1} for name in ['Alpha', 'Busy', 'Favorite', 'Zulu']])
    alpha, busy, favorite, zulu = peers
    domain = [('id', 'in', peers.ids)]
    favorite.baseer_is_favorite = True
    check('A favorite true / B default false', favorite.baseer_is_favorite and not favorite.with_company(b).baseer_is_favorite)
    busy.with_company(b).baseer_is_favorite = True
    check('B independent favorite', busy.with_company(b).baseer_is_favorite and not busy.baseer_is_favorite)
    check('C independent default', not favorite.with_company(c).baseer_is_favorite)
    favorite.baseer_is_favorite = False
    check('Unfavorite affects only A', not favorite.baseer_is_favorite and busy.with_company(b).baseer_is_favorite)
    favorite.baseer_is_favorite = True
    check('Company favorite domain', P.search(domain + [('baseer_is_favorite', '=', True)]).ids == favorite.ids)
    today = fields.Date.context_today(P)

    def bill(partner, company=a, age=0, state='posted', kind='in_invoice'):
        M = env['account.move'].with_company(company)
        account = env['account.account'].with_company(company).search([
            ('company_ids', 'in', company.ids), ('account_type', '=', 'expense'),
        ], limit=1)
        journal = env['account.journal'].with_company(company).search([
            ('company_id', '=', company.id), ('type', '=', 'purchase'),
        ], limit=1)
        move = M.create({
            'move_type': kind, 'company_id': company.id, 'journal_id': journal.id,
            'partner_id': partner.id, 'invoice_date': today - timedelta(days=age),
            'date': today - timedelta(days=age),
            'invoice_line_ids': [Command.create({'name': 'PP1 test only', 'account_id': account.id,
                'quantity': 1, 'price_unit': 1, 'tax_ids': [Command.clear()]})],
        })
        if state == 'posted':
            move.action_post()
        elif state == 'cancel':
            move.button_cancel()
        return move

    busy_bills = [bill(busy), bill(busy, age=89)]
    bill(alpha)
    bill(zulu, age=90)
    bill(zulu, age=-1)
    bill(zulu, state='draft')
    bill(zulu, state='cancel')
    bill(zulu, kind='in_refund')
    bill(zulu, company=b)
    check('Exact posted bill window and exclusions', {p.id: p.baseer_recent_bill_count for p in peers} == {
        alpha.id: 1, busy.id: 2, favorite.id: 0, zulu.id: 0,
    })
    expected = [favorite.id, busy.id, alpha.id, zulu.id]
    check('Favorite then usage then alphabet', P.search(domain).ids == expected)
    check('Rank before LIMIT', P.search(domain, limit=1).ids == [favorite.id])
    check('Stable paginated continuation', P.search(domain, offset=1, limit=2).ids == [busy.id, alpha.id])
    check('name_search native matching', [x[0] for x in P.name_search('Busy', domain=domain)] == [busy.id])
    check('name_search ranked limit', [x[0] for x in P.name_search('PP1 TEST', domain=domain, limit=2)] == expected[:2])
    check('B ranks and counts independently', P.with_company(b).search(domain).ids == [busy.id, zulu.id, alpha.id, favorite.id])
    generic = P.with_context(res_partner_search_mode=False, baseer_partner_priority=False)
    check('Unrelated native order unchanged', generic._order == env['res.partner']._order and generic.search(domain).ids == [alpha.id, busy.id, favorite.id, zulu.id])
    check('Sales selector uses same favorites', P.with_context(res_partner_search_mode='customer').search(domain).ids == expected)
    check('Batch context works', generic.with_context(baseer_partner_priority=True).search(domain).ids == expected)
    names = P.web_name_search('PP1 TEST', {'display_name': {}, 'baseer_is_favorite': {}}, domain=domain, limit=2)
    check('Favorite metadata and formatted names', names[0]['baseer_is_favorite'] and '__formatted_display_name' in names[0])
    check('Names never decorated', all('★' not in p.name and '★' not in p.display_name for p in peers))
    raw = P.web_search_read(domain, {'display_name': {}, 'baseer_is_favorite': {}}, limit=2, offset=1)
    check('Search More server pagination', [r['id'] for r in raw['records']] == expected[1:3])

    private = generic.create({'name': 'PP1 TEST private B', 'company_id': b.id})
    check('Ranked partner isolation with A+B allowed', not P.name_search(domain=[('id', '=', private.id)]))
    denied('Cannot star other-company private contact', lambda: private.write({'baseer_is_favorite': True}))
    denied('Cannot move and star to other company', lambda: alpha.write({'company_id': b.id, 'baseer_is_favorite': True}))
    other = peers.with_company(b).filtered(lambda p: p == busy)
    other.baseer_is_favorite = False
    check('Removing B star preserves A star', favorite.baseer_is_favorite and not busy.with_company(b).baseer_is_favorite)

    basic = env['res.users'].with_context(no_reset_password=True).create({
        'name': 'PP1 no invoice access', 'login': 'pp1.no.invoice', 'company_id': a.id,
        'company_ids': [Command.set([a.id, b.id])],
        'group_ids': [Command.set([env.ref('base.group_user').id])],
    })
    PB = P.with_user(basic)
    check('No bill read ACL fixture', not PB.env['account.move'].has_access('read'))
    check('No bill access fallback', PB.search(domain).ids == [favorite.id, alpha.id, busy.id, zulu.id])
    denied('Forged unauthorized current company rejected', lambda: PB.with_context(allowed_company_ids=[c.id]).search(domain))

    reader = env['res.users'].with_context(no_reset_password=True).create({
        'name': 'PP1 invoice reader', 'login': 'pp1.invoice.reader', 'company_id': a.id,
        'company_ids': [Command.set([a.id, b.id])],
        'group_ids': [Command.set([env.ref('account.group_account_invoice').id, env.ref('base.group_partner_manager').id])],
    })
    env['ir.rule'].create({'name': 'PP1 restrict Busy bills', 'model_id': env.ref('account.model_account_move').id,
        'domain_force': "[('partner_id', '!=', %s)]" % busy.id})
    PR = P.with_user(reader)
    check('Bill read rule limits ranking', PR.search(domain).ids == [favorite.id, alpha.id, busy.id, zulu.id])
    denied('Restricted company favorite write', lambda: favorite.with_user(reader).with_context(allowed_company_ids=[c.id]).write({'baseer_is_favorite': True}))
    busy_bills[0].button_draft()
    busy_bills[0].button_cancel()
    busy_bills[1].button_draft()
    busy_bills[1].button_cancel()
    check('Cancelled source reflected immediately', P.search(domain).ids == [favorite.id, alpha.id, busy.id, zulu.id])
    Path('/mnt/pp1-evidence/checks.json').write_text(json.dumps({'passed': len(results), 'checks': results}, indent=2))
    print('PP1 PASS', len(results))
finally:
    env.cr.rollback()
