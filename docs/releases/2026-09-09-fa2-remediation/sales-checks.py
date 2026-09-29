assert env.cr.dbname == 'baseer_fix_sales_20260909'
import json,traceback
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
from odoo import Command
from odoo.exceptions import AccessError,UserError,ValidationError
from odoo.tools.safe_eval import safe_eval
e=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[6],'lang':'en_US','tz':'Asia/Riyadh'})
out={'checks':[]}
def D(x):return Decimal(str(x or 0)).quantize(Decimal('.01'))
def check(name,actual,expected=True):
    out['checks'].append({'name':name,'actual':str(actual),'expected':str(expected),'passed':actual==expected});assert actual==expected,out['checks'][-1]
def denied(name,fn):
    try:
        with env.cr.savepoint():fn()
    except (AccessError,UserError,ValidationError) as exc:out['checks'].append({'name':name,'passed':True,'error':str(exc)})
    else:raise AssertionError(name+' allowed')
def count():return {name:e[name].search_count([]) for name in ('baseer.pos.summary','pos.order','pos.session','account.move','account.move.line','account.payment','account.partial.reconcile')}
try:
    cfg=e['pos.config'].browse(1);cfg._validate_baseer_setup()
    check('upgrade assigns valid service',cfg.baseer_summary_product_id.type,'service')
    check('original stock product29 unchanged',e['product.product'].browse(29).type,'consu')
    check('replacement is separate product',cfg.baseer_summary_product_id.id!=29)
    out['upgrade_product']={'original':29,'replacement':cfg.baseer_summary_product_id.id}
    pcount=e['product.product'].search_count([]);e['pos.config']._repair_summary_service_products()
    check('repair idempotent product count',e['product.product'].search_count([]),pcount)
    denied('dedicated product type cannot drift',lambda:cfg.baseer_summary_product_id.write({'type':'consu'}))
    originals=e['baseer.pos.summary'].search([('state','=','approved'),('order_id','!=',False)])
    check('legacy original entries have protected ownership',all(m.baseer_pos_summary_id==s for s in originals for m in s._native_moves()))
    methods={k:cfg.payment_method_ids.filtered(lambda m:m.baseer_category_id.kind==k)[:1] for k in ('cash','bank','platform')}
    S=e['baseer.pos.summary']
    def make(day,amounts=None,period='all',schedule='all'):
        amounts=amounts or {'cash':115}
        s=S.create({'business_date':day,'config_id':cfg.id,'period_scope':period,'day_schedule':schedule,'customer_count':10,
            'allocation_ids':[Command.create({'payment_method_id':methods[k].id,'amount':v}) for k,v in amounts.items()]})
        s.action_approve();return s
    def correct(s,reason='Wrong external report amount'):
        w=e['baseer.pos.summary.correction'].create({'summary_id':s.id,'reason':reason})
        action=w.action_correct();return S.browse(action['res_id'])
    def daily(day):return e['baseer.pos.daily.report']._aggregate_days(e.company,day,day)['totals']
    def native_sales(day):
        env.flush_all()
        return D(sum(e['report.pos.order'].search([('company_id','=',6),('date','>=',day+' 00:00:00'),('date','<=',day+' 23:59:59'),('state','!=','cancel')]).mapped('price_total')))
    def cash(day):return e['eh.account.dynamic.report.handler.baseer_cash_categories'].compute({'company_ids':[6], 'posted_only':True,
        'date':{'date_from':day,'date_to':day},'baseer_include_tax':True})['totals']
    source=make('2026-01-01',{'cash':115,'bank':230,'platform':805})
    check('native POS action defaults to excluding cancelled',safe_eval(e.ref('point_of_sale.action_report_pos_order_all').context)['search_default_not_cancelled'],1)
    check('native POS report before correction1150',native_sales('2026-01-01'),D(1150))
    check('source posted ownership',all(m.baseer_pos_summary_id==source for m in source._native_moves()))
    native_before=count()
    denied('native-shaped forged summary order rejected by Baseer',lambda:e['pos.order'].with_context(_baseer_pos_summary_token=True).create({
        'session_id':source.session_id.id,'company_id':6,'baseer_summary_id':source.id,'source':'baseer_summary',
        'amount_total':0,'amount_tax':0,'amount_paid':0,'amount_return':0}))
    check('native-shaped forged order leaves no side effects',count(),native_before)
    restricted=e['res.users'].create({'name':'FA2 POS manager only','login':'fa2_sales_restricted','company_id':6,
        'company_ids':[Command.set([6])],'group_ids':[Command.set([e.ref('base.group_user').id,e.ref('point_of_sale.group_pos_manager').id,e.ref('account.group_account_invoice').id])]})
    check('restricted fixture lacks accounting manager',restricted.has_group('account.group_account_manager'),False)
    denied('POS manager without accounting manager cannot correct',lambda:source.with_user(restricted).action_open_correction())
    denied('owned session move reset denied',source.move_id.button_draft)
    denied('owned journal line edit denied',lambda:source.move_id.line_ids[:1].write({'name':'bad'}))
    denied('owned move forged context denied',lambda:source.move_id.with_context(_baseer_pos_summary_token=True).button_draft())
    def native_reverse(move):
        return e['account.move.reversal'].with_context(active_model='account.move',active_ids=move.ids).create({'date':move.date,'journal_id':move.journal_id.id,'reason':'Reviewed receipt correction'}).reverse_moves()
    denied('native income reversal denied',lambda:native_reverse(source.move_id))
    denied('forged reversed source create denied',lambda:e['account.move'].create({'journal_id':source.move_id.journal_id.id,'reversed_entry_id':source.move_id.id}))
    denied('blank correction denied',lambda:correct(source,' '))
    denied('foreign active company correction denied',lambda:source.with_context(allowed_company_ids=[9,6])._correct_summary('bad company'))
    denied('RPC boolean cannot cancel native order',lambda:source.order_id.with_context(_baseer_pos_summary_token=True)._mark_summary_corrected())
    receipts=e['account.payment'].search([('pos_session_id','=',source.session_id.id)])
    denied('owned payment link cannot be cleared',lambda:receipts.write({'pos_session_id':False}))
    denied('owned payment move cannot be cleared',lambda:receipts.write({'move_id':False}))
    denied('owned cash statement link cannot be cleared',lambda:source.session_id.statement_line_ids.write({'pos_session_id':False}))
    denied('owned cash statement move cannot be cleared',lambda:source.session_id.statement_line_ids.write({'move_id':False}))
    denied('forged new receipt session link denied',lambda:e['account.payment'].create({'pos_session_id':source.session_id.id,'amount':1}))
    # Late failure must revert earlier native reversals and every source link.
    before=count();cls=type(e['account.move']);native=cls._reverse_moves
    def fail_after(*args,**kwargs):native(*args,**kwargs);raise UserError('Injected post-reversal failure')
    with patch.object(cls,'_reverse_moves',fail_after):denied('late correction failure denied',lambda:correct(source))
    check('late correction rolls back all accounting counts',count(),before)
    check('late correction leaves source approved',source.state,'approved')
    def fail_replacement(*args,**kwargs):
        check('injected late failure sees cancelled source and native order',source.state=='cancelled' and source.order_id.state=='cancel')
        raise UserError('Injected replacement creation failure after state transition')
    with patch.object(type(S),'create',fail_replacement):denied('failure after source state transition denied',lambda:correct(source))
    check('post-state failure rolls back all accounting counts',count(),before)
    check('post-state failure restores source and native order',source.state=='approved' and source.order_id.state=='done' and not source._native_moves().reversal_move_ids)
    replacement=correct(source)
    denied('replacement original date retained',lambda:replacement.write({'business_date':'2026-01-03'}))
    denied('replacement original shift retained',lambda:replacement.write({'period_scope':'morning','day_schedule':'morning'}))
    denied('replacement correction chain cannot be deleted',replacement.unlink)
    check('source cancelled',source.state,'cancelled');check('order cancelled',source.order_id.state,'cancel')
    check('replacement remains reviewable draft',replacement.state,'draft')
    check('linked chain',source.replacement_id==replacement and replacement.replaces_id==source)
    check('one reversal for each original',len(source.reversal_move_ids),len(source._native_moves()))
    denied('native correction reversal remains protected',source.reversal_move_ids.button_draft)
    check('replacement draft excluded from sales',D(daily('2026-01-01')['recorded_sales']),D(0))
    check('native POS report after correction0',native_sales('2026-01-01'),D(0))
    check('historical source gross retained1150',D(source.amount_gross),D(1150))
    check('historical source customers retained10',source.customer_count,10)
    check('reversal cash net0',D(cash('2026-01-01')['actual_net_movement']),D(0))
    again=correct(source);check('repeated correction same replacement',again,replacement)
    replacement.write({'customer_count':20,'allocation_ids':[Command.clear(),Command.create({'payment_method_id':methods['cash'].id,'amount':230})]})
    replacement.action_approve()
    check('replacement daily gross230',D(daily('2026-01-01')['recorded_sales']),D(230))
    check('native POS report replacement230',native_sales('2026-01-01'),D(230))
    check('replacement daily customers20',daily('2026-01-01')['recorded_customers'],20)
    check('replacement daily one day',daily('2026-01-01')['operating_days'],1)
    check('replacement average230',D(daily('2026-01-01')['average_daily_sales']),D(230))
    posted=e['account.move.line'].search([('company_id','=',6),('date','=','2026-01-01'),('parent_state','=','posted')])
    check('net ledger income200',D(-sum(posted.filtered(lambda l:l.account_id.account_type in ('income','income_other')).mapped('balance'))),D(200))
    check('net ledger VAT30',D(-sum(posted.filtered('tax_line_id').mapped('balance'))),D(30))
    check('replacement cash230',D(cash('2026-01-01')['actual_net_movement']),D(230))
    env.flush_all();day=e['baseer.pos.day.archive'].search([('company_id','=',6),('business_date','=','2026-01-01')])
    check('archive counts replacement only',D(day.amount_total),D(230))
    check('archive customers count replacement only',day.customer_total,20)
    denied('cancelled source sharing denied',source.action_share_whatsapp)
    check('replacement WhatsApp gross230','230.00' in replacement.action_share_whatsapp()['url'])
    receipt_source=make('2026-01-02')
    receipt=receipt_source._native_moves()-receipt_source.move_id
    native_reverse(receipt)
    check('receipt-only reversal keeps approved sale',receipt_source.state,'approved')
    check('receipt-only reversal daily115',D(daily('2026-01-02')['recorded_sales']),D(115))
    check('receipt-only reversal cash0',D(cash('2026-01-02')['actual_net_movement']),D(0))
    denied('full correction after receipt reversal explains rejection',lambda:correct(receipt_source))
    morning=make('2026-02-01',period='morning',schedule='split')
    closure=e['baseer.pos.closure'].create({'date_from':'2026-02-01','date_to':'2026-02-01','period_scope':'evening','reason':'maintenance'});closure.action_confirm()
    env.flush_all();archive=e['baseer.pos.day.archive'].search([('company_id','=',6),('business_date','=','2026-02-01')])
    check('half closure daily complete',daily('2026-02-01')['operating_days'],1)
    check('half closure archive no missing shift',archive.missing_shift,False)
    action=archive.action_view_closures();check('half closure source accessible',closure.id in action['domain'][0][2])
    # Native partial reconciliation to a platform settlement outside the source.
    external_source=make('2026-02-02',{'platform':115})
    clearing=external_source._native_moves().line_ids.filtered(lambda l:l.account_id==methods['platform'].outstanding_account_id)
    bank=methods['bank'].journal_id.default_account_id
    settlement=e['account.move'].create({'journal_id':cfg.journal_id.id,'date':'2026-02-02','line_ids':[
        Command.create({'name':'partial external settlement','account_id':bank.id,'debit':50}),
        Command.create({'name':'partial platform settlement','account_id':clearing.account_id.id,'credit':50})]})
    settlement.action_post();(clearing|settlement.line_ids.filtered(lambda l:l.account_id==clearing.account_id)).reconcile()
    matches=clearing.matched_credit_ids|clearing.matched_debit_ids;before=count()
    denied('external partial settlement blocks full correction',lambda:correct(external_source))
    check('external partial match retained',bool(matches.exists()) and clearing.amount_residual==65)
    check('external rejection creates no accounting documents',count(),before)
    # Changing a soft lock inside a rollback savepoint exercises the real date guard.
    class RollbackLock(Exception):pass
    try:
        with env.cr.savepoint():
            e.company.write({'fiscalyear_lock_date':'2026-02-02'})
            denied('locked business date correction rejected',lambda:correct(morning))
            raise RollbackLock()
    except RollbackLock:pass
    zero=S.create({'config_id':cfg.id,'business_date':'2026-02-03','zero_sales':True});zero.action_approve();before=count()
    zero_replacement=correct(zero)
    check('zero sales correction uses no financial moves',not zero.reversal_move_ids and count()['account.move']==before['account.move'])
    check('zero sales correction day removed until approval',daily('2026-02-03')['operating_days'],0)
    zero_replacement.action_approve();check('zero replacement restores operating denominator',daily('2026-02-03')['operating_days'],1)
    ar=e(context=dict(e.context,lang='ar_001'))
    check('Arabic correction label loaded',ar['baseer.pos.summary'].fields_get(['correction_reason'])['correction_reason']['string'],'سبب التصحيح')
    check('Arabic corrected state loaded',dict(ar['baseer.pos.summary'].fields_get(['state'])['state']['selection'])['cancelled'],'ملغى للتصحيح')
    out['status']='passed'
except Exception as exc:out.update(status='failed',error=str(exc),traceback=traceback.format_exc())
finally:env.cr.rollback()
Path('/mnt/qa-evidence/sales-checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
