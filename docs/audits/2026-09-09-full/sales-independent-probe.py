"""Current-clone-only sales accounting probes; no commits, final rollback.

Run through the audit container Odoo shell with BASEER_AUDIT_DB matching its
actual database name. Names beginning baseer_audit_ are the only accepted DBs.
"""
import os, json, traceback
from pathlib import Path
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs
from odoo import Command
from odoo.exceptions import UserError, ValidationError, AccessError

assert env.cr.dbname == 'baseer_audit_sales_20260909'
assert env.cr.dbname.startswith('baseer_audit_')
output = {'database': env.cr.dbname, 'checks': [], 'observations': []}
def D(x): return Decimal(str(x or 0)).quantize(Decimal('.01'))
def check(name, actual, expected):
    output['checks'].append({'name':name,'actual':str(actual),'expected':str(expected),'passed':actual==expected})
    assert actual == expected, output['checks'][-1]
def denied(name, fn):
    try:
        with env.cr.savepoint(): fn()
    except (UserError, ValidationError, AccessError) as exc:
        output['checks'].append({'name':name,'passed':True,'error':str(exc)})
    else: raise AssertionError(name+' unexpectedly allowed')
class Undo(Exception): pass

try:
    admin=env.ref('base.user_admin')
    configs=env['pos.config'].search([('baseer_summary_only','=',True)])
    assert configs, 'No dedicated POS installed/configured in actual clone'
    config=configs[:1]
    c=config.company_id
    e=env(user=admin.id,context={'allowed_company_ids':c.ids,'lang':'en_US','tz':'Asia/Riyadh'})
    config=e['pos.config'].browse(config.id)
    if config.baseer_summary_product_id.type != 'service':
        output['fixture_override']={'product_id':config.baseer_summary_product_id.id,'original_type':config.baseer_summary_product_id.type,'test_type':'service','persisted':False}
        config.baseer_summary_product_id.write({'type':'service'})
    config._validate_baseer_setup()
    methods={k:config.payment_method_ids.filtered(lambda m:m.baseer_category_id.kind==k)[:1] for k in ('cash','bank','platform')}
    assert all(methods.values()), 'Current config lacks one of cash/bank/platform'
    output['configuration']={'company_id':c.id,'config_id':config.id,'methods':{k:v.id for k,v in methods.items()}}
    S=e['baseer.pos.summary']; R=e['baseer.pos.daily.report']; Closure=e['baseer.pos.closure']
    def counts():return {n:e[n].search_count([]) for n in ('baseer.pos.summary','pos.order','pos.session','pos.payment','account.move','account.move.line','account.payment')}
    before=counts()
    def make(day, amounts=None, period='all', schedule='all', customers=10, zero=False, approve=True):
        amounts=amounts if amounts is not None else {'cash':115}
        row=S.create({'company_id':c.id,'config_id':config.id,'business_date':day,'period_scope':period,'day_schedule':schedule,
            'customer_count':customers,'zero_sales':zero,'external_reference':'AUDIT-INDEPENDENT-SALES',
            'allocation_ids':[Command.create({'payment_method_id':methods[k].id,'amount':v}) for k,v in amounts.items()]})
        if approve:row.action_approve()
        return row
    def cash(day,tax=True):
        return e['eh.account.dynamic.report.handler.baseer_cash_categories'].compute({'company_ids':c.ids,'posted_only':True,
            'baseer_include_tax':tax,'date':{'mode':'range','date_from':day,'date_to':day}})
    s=make('2026-01-01',{'cash':115,'bank':230,'platform':805},customers=100)
    moves=s._native_moves()
    check('gross 1150',D(s.amount_gross),D(1150));check('net 1000',D(s.amount_net),D(1000));check('tax150',D(s.amount_tax),D(150))
    check('per customer 11.50',D(s.average_per_customer),D('11.50'))
    check('income credit1000',D(-sum(moves.line_ids.filtered(lambda l:l.account_id.account_type in ('income','income_other')).mapped('balance'))),D(1000))
    check('asset cash345',D(sum(moves.line_ids.filtered(lambda l:l.account_id.account_type=='asset_cash').mapped('balance'))),D(345))
    check('platform clearing805',D(sum(moves.line_ids.filtered(lambda l:l.account_id==methods['platform'].outstanding_account_id).mapped('balance'))),D(805))
    check('all moves dated business day',set(moves.mapped('date')),{date(2026,1,1)})
    for tax,expected in ((True,345),(False,300)):
        p=cash('2026-01-01',tax)
        check('cash receipts tax='+str(tax),D(p['totals']['receipts']),D(expected))
        check('cash reconciliation tax='+str(tax),D(p['totals']['balance_check']),D(0))
    prior=counts();s.action_approve();check('idempotent approval',counts(),prior)
    message=parse_qs(urlparse(s.action_share_whatsapp()['url']).query)
    check('WhatsApp preview has only text, no recipient',set(message),{'text'})
    check('WhatsApp preview includes gross', '1,150.00' in message['text'][0],True)
    # Genuine later-date platform settlement; independently expected 115 gross /100 net.
    bank=methods['bank']; platform=methods['platform']
    settlement=e['account.move'].create({'company_id':c.id,'journal_id':bank.journal_id.id,'date':'2026-01-02','ref':'AUDIT-INDEPENDENT-SETTLE',
        'line_ids':[Command.create({'account_id':bank.journal_id.default_account_id.id,'debit':115}),
                    Command.create({'account_id':platform.outstanding_account_id.id,'credit':115})]})
    settlement.action_post()
    original=moves.line_ids.filtered(lambda l:l.account_id==platform.outstanding_account_id)
    (original|settlement.line_ids.filtered(lambda l:l.account_id==platform.outstanding_account_id)).reconcile()
    check('platform residual690',D(sum(original.mapped('amount_residual'))),D(690))
    for tax,expected in ((True,115),(False,100)):
        p=cash('2026-01-02',tax)
        check('later settlement receipts tax='+str(tax),D(p['totals']['receipts']),D(expected))
    # Both shifts together are ONE date; zero work counts; dayoff/missing/incomplete do not.
    make('2026-02-01',period='morning',schedule='split',customers=10)
    make('2026-02-01',{'cash':230},period='evening',schedule='split',customers=20)
    make('2026-02-02',{},customers=0,zero=True)
    cl=Closure.create({'date_from':'2026-02-03','date_to':'2026-02-03','reason':'holiday'});cl.action_confirm()
    make('2026-02-04',period='morning',schedule='split',customers=5)
    data=R._aggregate_days(c,'2026-02-01','2026-02-05')
    t=data['totals']
    for k,v in {'recorded_sales':460,'recorded_customers':35,'complete_sales':345,'complete_customers':30,
                'operating_days':2,'closed_days':1,'incomplete_days':1,'missing_days':1,'average_daily_sales':'172.50','average_daily_customers':15}.items():
        check('daily '+k,D(t[k]),D(v))
    denied('overlapping dayoff denied',lambda:Closure.create({'date_from':'2026-02-01','date_to':'2026-02-01'}).action_confirm())
    # Partial shift closure completes a worked date in report, inspect archive parity.
    close_evening=Closure.create({'date_from':'2026-02-04','date_to':'2026-02-04','period_scope':'evening','reason':'maintenance'})
    close_evening.action_confirm()
    daily=R._aggregate_days(c,'2026-02-04','2026-02-04')['days'][0]
    e.flush_all()
    archive=e['baseer.pos.day.archive'].search([('company_id','=',c.id),('business_date','=','2026-02-04')])
    output['observations'].append({'case':'partial closure archive parity','daily_status':daily['status'],'archive_missing_shift':archive.missing_shift,'archive_state':archive.state})
    # Late failure after native cash/bank side effects must restore every document count.
    draft=make('2026-03-01',{'cash':115,'bank':230,'platform':805},approve=False)
    before_fail=counts(); cls=type(e['pos.session']); orig=cls._create_combine_account_payment; calls=[0]
    def fail(record,*args,**kwargs):
        calls[0]+=1
        if calls[0]==2:raise UserError('AUDIT injected second bank failure')
        return orig(record,*args,**kwargs)
    with patch.object(cls,'_create_combine_account_payment',fail):denied('late posting failure',draft.action_approve)
    check('late failure atomic document counts',counts(),before_fail)
    check('late failure keeps draft',draft.state,'draft')
    # Current authorized native accounting correction probes, each independently rolled back.
    for operation in ('reverse','reset_draft'):
        try:
            with env.cr.savepoint():
                if operation=='reverse':
                    wizard=e['account.move.reversal'].with_context(active_model='account.move',active_ids=s.move_id.ids).create({'date':s.business_date,'reason':'AUDIT reviewed correction','journal_id':s.move_id.journal_id.id})
                    wizard.reverse_moves()
                    reversed_moves=s.move_id.reversal_move_ids
                    evidence={'reversal_ids':reversed_moves.ids,'reversal_states':reversed_moves.mapped('state')}
                else:
                    s.move_id.button_draft();evidence={'move_state':s.move_id.state}
                fresh=R._aggregate_days(c,'2026-01-01','2026-01-01')
                ledger=e['account.move.line'].search([('company_id','=',c.id),('parent_state','=','posted'),('date','=','2026-01-01'),('account_id.account_type','in',['income','income_other'])])
                evidence.update(operation=operation,allowed=True,summary_state=s.state,daily_sales=str(fresh['totals']['recorded_sales']),posted_net_income=str(D(-sum(ledger.mapped('balance')))))
                output['observations'].append(evidence)
                raise Undo()
        except Undo:pass
        except (UserError,ValidationError,AccessError) as exc:output['observations'].append({'operation':operation,'allowed':False,'error':str(exc)})
    output['status']='completed'
except Exception as exc:
    output.update(status='failed',error=str(exc),traceback=traceback.format_exc())
finally:
    env.cr.rollback()
    output['rollback']=True
    Path('/mnt/qa-evidence/sales-independent-result.json').write_text(json.dumps(output,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SALES_AUDIT_RESULT '+json.dumps(output,default=str,ensure_ascii=False))
