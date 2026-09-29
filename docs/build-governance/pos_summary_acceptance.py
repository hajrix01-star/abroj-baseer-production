"""QA integration acceptance. All cases roll back; preview setup is separate."""
import json
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from psycopg2 import IntegrityError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
fixture = json.loads(Path('/mnt/qa-evidence/pos_summary_fixture.json').read_text())
qa = env(context=dict(env.context, allowed_company_ids=[fixture['company_id']], lang='en_US'))
config = qa['pos.config'].browse(fixture['config_id'])
Summary = qa['baseer.pos.summary']
methods = config.payment_method_ids
cash = methods.filtered(lambda m: m.baseer_category_id.kind == 'cash')[:1]
bank = methods.filtered(lambda m: m.baseer_category_id.kind == 'bank')[:1]
platform = methods.filtered(lambda m: m.baseer_category_id.kind == 'platform')[:1]
checks = []

def check(name, result):
    assert result, name
    checks.append(name)

def reject(name, fn):
    try:
        with qa.cr.savepoint():
            fn()
    except (AccessError, UserError, ValidationError, IntegrityError):
        checks.append(name)
    else:
        raise AssertionError('Not rejected: ' + name)

def vals(day=date(2026, 8, 17), **changes):
    data = {'business_date': day, 'external_reference': 'QA external <1800> & Arabic تقرير', 'customer_count': 60,
            'allocation_ids': [Command.create({'payment_method_id': m.id, 'amount': amount}) for m, amount in [(cash,500),(bank,700),(platform,600)]]}
    data.update(changes)
    return data

try:
    before = {m: qa[m].search_count([]) for m in ['baseer.pos.summary','pos.order','pos.session','account.move','stock.picking']}
    reject('empty summary rejected', lambda: Summary.create(vals(allocation_ids=[])))
    for value in [-1, 1.1, True, 10000001]:
        reject('customer invalid ' + str(value), lambda value=value: Summary.create(vals(customer_count=value)))
    for value in [-1, 0, 1.001, 1000000000, True]:
        reject('amount invalid ' + str(value), lambda value=value: Summary.create(vals(allocation_ids=[Command.create({'payment_method_id':cash.id,'amount':value})])))
    reject('protected status rejected', lambda: Summary.create(vals(state='approved')))
    reject('foreign company rejected', lambda: Summary.create(vals(company_id=7)))
    reject('ordinary cashier blocked on summary config', config.open_ui)
    reject('direct dedicated session blocked', lambda: qa['pos.session'].create({'config_id': config.id}))
    summary = Summary.create(vals())
    check('draft total1800', round(summary.amount_gross,2)==1800)
    check('draft average30', summary.average_per_customer==30)
    check('draft net1565.22 tax234.78', round(summary.amount_net,2)==1565.22 and round(summary.amount_tax,2)==234.78)
    reject('same day duplicate rejected', lambda: Summary.create(vals()))
    reject('all day overlaps morning', lambda: Summary.create(vals(period_scope='morning')))
    reject('last allocation removal rejected', lambda: summary.write({'allocation_ids':[Command.clear()]}))
    check('failed removal preserves3',len(summary.allocation_ids)==3)
    started=time.monotonic()
    summary.action_approve()
    elapsed=time.monotonic()-started
    check('approved summary',summary.state=='approved')
    order=summary.order_id; session=summary.session_id
    check('one paid closed order',order.state=='done' and session.state=='closed' and len(session.order_ids)==1)
    check('one service line no stock',len(order.lines)==1 and order.lines.product_id.type=='service' and not order.picking_ids)
    check('three native payments gross1800',len(order.payment_ids)==3 and round(sum(order.payment_ids.mapped('amount')),2)==1800)
    check('posted dates match business day',all(m.state=='posted' and m.date==summary.business_date for m in summary._native_moves()))
    check('journal balance zero',all(round(sum(m.line_ids.mapped('balance')),2)==0 for m in summary._native_moves()))
    check('native revenue1565.22',round(-sum(session.move_id.line_ids.filtered(lambda l:l.account_id.account_type in ('income','income_other')).mapped('balance')),2)==1565.22)
    check('native VAT234.78',round(-sum(session.move_id.line_ids.filtered('tax_line_id').mapped('balance')),2)==234.78)
    check('platform clearing600',round(sum(summary._native_moves().line_ids.filtered(lambda l:l.account_id==platform.outstanding_account_id).mapped('balance')),2)==600)
    after_approve={m:qa[m].search_count([]) for m in before}
    summary.action_approve()
    check('repeat approval idempotent',after_approve=={m:qa[m].search_count([]) for m in before})
    reject('approved header immutable',lambda:summary.write({'customer_count':61}))
    reject('approved allocation immutable',lambda:summary.allocation_ids[:1].write({'amount':501}))
    reject('approved cannot delete',summary.unlink)
    action=summary.action_share_whatsapp()
    link=urlparse(action['url']); message=parse_qs(link.query).get('text',[''])[0]
    check('WhatsApp Web compose only',link.scheme=='https' and link.netloc=='web.whatsapp.com' and bool(message))
    check('WhatsApp preserves company and totals',summary.company_id.name in message and '1,800' in message and '60' in message)
    check('sharing does not repost',after_approve=={m:qa[m].search_count([]) for m in before})
    groups=Summary._read_group([('id','=',summary.id)],['company_id'],['amount_gross:sum','customer_count:sum'])
    check('summary analytics counts60 once',groups[0][1:]==(1800,60))
    alloc_groups=qa['baseer.pos.summary.allocation']._read_group([('summary_id','=',summary.id)],['category_id'],['amount:sum'])
    check('method categories sum1800',sum(g[1] for g in alloc_groups)==1800)
    morning=Summary.create(vals(day=date(2026,8,18),period_scope='morning'))
    evening=Summary.create(vals(day=date(2026,8,18),period_scope='evening'))
    check('morning evening allowed',bool(morning and evening))
    reject('all conflicts separate shifts',lambda:Summary.create(vals(day=date(2026,8,18))))
    report_path=Path('/mnt/qa-evidence/pos_summary_cash_checks.py')
    if report_path.exists():
        report_globals={}; exec(compile(report_path.read_text(),str(report_path),'exec'),report_globals)
        cash_results=report_globals['run_pos_cash_checks'](qa,summary)
    else:
        cash_results={'pending':True}
    result={'status':'PASS','checks':checks,'count':len(checks),'approval_seconds':elapsed,'summary_id':summary.id,'native_order_id':order.id,'native_session_id':session.id,'moves':summary._native_moves().ids,'cash_report':cash_results}
    Path('/mnt/qa-evidence/pos_summary_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    print('POS_SUMMARY_ACCEPTANCE_OK',json.dumps(result,ensure_ascii=False,default=str))
finally:
    env.cr.rollback()
