"""S2 raw RPC boundaries and native posting regression; rollback only."""
import json
from datetime import date
from pathlib import Path
from odoo import Command
from odoo.exceptions import AccessError, ValidationError, UserError

assert env.cr.dbname == 'baseer_reports_qa_20260907'
fixture = json.loads(Path('/mnt/qa-evidence/pos_summary_fixture.json').read_text())
qa = env(context=dict(env.context, allowed_company_ids=[fixture['company_id']], lang='en_US'))
Summary = qa['baseer.pos.summary']
config = qa['pos.config'].browse(fixture['config_id'])
cash = config.payment_method_ids.filtered(lambda m: m.baseer_category_id.kind == 'cash')[:1]
checks = []
def check(label, value):
    assert value, label
    checks.append(label)
def reject(label, fn):
    try:
        with qa.cr.savepoint(): fn()
    except (AccessError, ValidationError, UserError): checks.append(label)
    else: raise AssertionError(label)
def values(day, **kw):
    result = {'business_date': day, 'customer_count': 10,
              'allocation_ids': [Command.create({'payment_method_id': cash.id, 'amount': 115})]}
    result.update(kw)
    return result
try:
    defaults = Summary.default_get(['config_id','allocation_ids','period_scope','day_schedule'])
    check('all active configured methods prefilled', len(defaults['allocation_ids']) == 5)
    check('prefilled amounts zero', all(cmd[2]['amount'] == 0 for cmd in defaults['allocation_ids']))
    reject('empty auto-default amounts cannot silently save', lambda: Summary.create({'business_date':'2026-06-01'}))
    summary = Summary.create(values('2026-06-01'))
    check('reference optional stable internal name', not summary.external_reference and summary.name.startswith('POS-S/'))
    reject('negative slot rejected', lambda: summary.allocation_ids.write({'amount':-1}))
    reject('excess precision rejected', lambda: summary.allocation_ids.write({'amount':1.001}))
    reject('false amount rejected', lambda: summary.allocation_ids.write({'amount':False}))
    zeros = config.payment_method_ids - cash
    summary.write({'allocation_ids':[Command.create({'payment_method_id':m.id,'amount':0}) for m in zeros]})
    summary.action_approve()
    check('zero slots do not create native payments', len(summary.order_id.payment_ids)==1)
    check('native gross115 tax15 unchanged', summary.amount_gross==115 and summary.amount_tax==15)
    check('native payment dates match', all(m.date==date(2026,6,1) for m in summary._native_moves()))
    check('native moves balanced', all(round(sum(m.line_ids.mapped('balance')),2)==0 for m in summary._native_moves()))
    reject('approved day metadata immutable', lambda: summary.write({'day_schedule':'split'}))
    reject('approved zero flag immutable', lambda: summary.write({'zero_sales':True}))
    before = {model:qa[model].search_count([]) for model in ['account.move','pos.order','pos.session']}
    zero = Summary.create(values('2026-06-02',zero_sales=True,customer_count=0,allocation_ids=[]))
    zero.action_approve()
    zero.action_approve()
    check('zero approval explicit and audited',zero.state=='approved' and zero.approved_by_id and zero.approved_at)
    check('zero repeated approval no finance',all(qa[m].search_count([])==n for m,n in before.items()))
    check('zero no fictitious source',not zero.order_id and not zero.session_id)
    check('zero whatsapp prepared manually',zero.action_share_whatsapp()['url'].startswith('https://web.whatsapp.com/send?'))
    reject('zero must not contain amounts',lambda:Summary.create(values('2026-06-03',zero_sales=True,customer_count=0)))
    reject('zero must not contain customers',lambda:Summary.create(values('2026-06-03',zero_sales=True,allocation_ids=[])))
    reject('fake boolean declaration',lambda:Summary.create(values('2026-06-03',zero_sales='yes')))
    morning = Summary.create(values('2026-06-03',period_scope='morning',day_schedule='split'))
    evening = Summary.create(values('2026-06-03',period_scope='evening',day_schedule='split'))
    check('two independent customer counts',morning.customer_count==10 and evening.customer_count==10)
    reject('mismatched day schedule',lambda:evening.write({'day_schedule':'evening'}))
    reject('all day cannot combine shifts',lambda:Summary.create(values('2026-06-03')))
    reject('wrong period for single-shift schedule',lambda:Summary.create(values('2026-06-04',period_scope='evening',day_schedule='morning')))
    single=Summary.create(values('2026-06-04',period_scope='morning',day_schedule='morning'))
    check('explicit single shift permitted',single.day_schedule=='morning')
    result={'status':'PASS','count':len(checks),'checks':checks}
    Path('/mnt/qa-evidence/pos_s2_summary_checks.json').write_text(json.dumps(result,indent=2))
    print('S2_SUMMARY_PASS', len(checks))
finally:
    qa.cr.rollback()
