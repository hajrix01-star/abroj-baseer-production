assert env.cr.dbname=='baseer_audit_sales_20260909'
import json,traceback
from pathlib import Path
from decimal import Decimal
from odoo import Command
e=env(user=env.ref('base.user_admin').id,context={'allowed_company_ids':[6],'lang':'en_US'})
out={'checks':[],'reports':{}}
def D(x):return Decimal(str(x or 0)).quantize(Decimal('.01'))
def check(name,actual,expected):
    out['checks'].append({'name':name,'actual':str(actual),'expected':str(expected),'passed':actual==expected})
    assert actual==expected,out['checks'][-1]
try:
    s=e['baseer.pos.summary'].create({'config_id':1,'business_date':'2026-06-18','customer_count':10,
        'allocation_ids':[Command.create({'payment_method_id':1,'amount':115})]})
    s.action_approve()
    assert len(s)==1 and s.amount_gross==115
    options={'company_ids':[6],'posted_only':True,'unfold_all':True,'lazy_expand':False,
        'date':{'date_from':'2026-06-18','date_to':'2026-06-18'}}
    aml=e['account.move.line'].search([('company_id','=',6),('date','=','2026-06-18'),('parent_state','=','posted')])
    check('source gross115',D(s.amount_gross),D(115))
    for code in ('profit_and_loss','trial_balance','general_ledger','baseer_cash_categories'):
        report=e['eh.account.dynamic.report'].search([('code','=',code)],limit=1)
        assert report,code
        payload=report.render(options,use_cache=False)
        out['reports'][code]=payload
    pnl=out['reports']['profit_and_loss'];check('ERP Heritage P&L income100',D(pnl['totals']['income']),D(100))
    check('ERP Heritage P&L net profit100',D(pnl['totals']['net_profit']),D(100))
    check('ERP Heritage cash receipts115',D(out['reports']['baseer_cash_categories']['totals']['receipts']),D(115))
    # Every source account must agree with trial balance period movement.
    tb=out['reports']['trial_balance']
    for account in aml.account_id:
        source=aml.filtered(lambda line:line.account_id==account)
        rows=[row for row in tb['lines'] if row['id']=='account-'+str(account.id)]
        assert len(rows)==1,(account.id,[r['id'] for r in tb['lines']])
        values={col['expression_label']:col['value'] for col in rows[0]['columns']}
        check('trial balance debit '+str(account.id),D(values['period_debit']),D(sum(source.mapped('debit'))))
        check('trial balance credit '+str(account.id),D(values['period_credit']),D(sum(source.mapped('credit'))))
        out.setdefault('trial_balance_accounts',[]).append({'account':account.id,'expected_debit':str(D(sum(source.mapped('debit')))),'expected_credit':str(D(sum(source.mapped('credit')))),'values':values})
    gl_rows=[row for row in out['reports']['general_ledger']['lines'] if row.get('meta',{}).get('kind')=='aml']
    check('general ledger exact source AML ids',{row['meta']['aml_id'] for row in gl_rows},set(aml.ids))
    for row in gl_rows:
        original=e['account.move.line'].browse(row['meta']['aml_id'])
        values={col['expression_label']:col['value'] for col in row['columns']}
        check('general ledger debit '+str(original.id),D(values['debit']),D(original.debit))
        check('general ledger credit '+str(original.id),D(values['credit']),D(original.credit))
    # Partial cash reversal leaves sales intact; only cash collections reverse.
    cash_moves=s._native_moves().filtered(lambda move:any(l.account_id.account_type=='asset_cash' for l in move.line_ids))
    wizard=e['account.move.reversal'].with_context(active_model='account.move',active_ids=cash_moves.ids).create({'date':'2026-06-18','reason':'AUDIT partial financial reversal','journal_id':cash_moves.journal_id.id})
    wizard.reverse_moves()
    after=e['eh.account.dynamic.report'].search([('code','=','baseer_cash_categories')],limit=1).render(options,use_cache=False)
    check('cash-only reversal cash net0',D(after['totals']['actual_net_movement']),D(0))
    check('cash-only reversal daily sales retained115',D(e['baseer.pos.daily.report']._aggregate_days(e.company,'2026-06-18','2026-06-18')['totals']['recorded_sales']),D(115))
    out['cash_only_reversal']={'totals':after['totals'],'diagnostics':after['meta']['diagnostics'],'summary_state':s.state}
    source=e['baseer.pos.summary'].create({'config_id':1,'business_date':'2026-06-19','customer_count':10,
        'allocation_ids':[Command.create({'payment_method_id':1,'amount':1150})]});source.action_approve()
    action=e['baseer.pos.summary.correction'].create({'summary_id':source.id,'reason':'Independent ERP report correction'}).action_correct()
    replacement=e['baseer.pos.summary'].browse(action['res_id']);replacement.allocation_ids.write({'amount':230});replacement.write({'customer_count':20});replacement.action_approve()
    corrected_options=dict(options,date={'date_from':'2026-06-19','date_to':'2026-06-19'})
    out['corrected_reports']={}
    for code in ('profit_and_loss','trial_balance','general_ledger','baseer_cash_categories'):
        out['corrected_reports'][code]=e['eh.account.dynamic.report'].search([('code','=',code)],limit=1).render(corrected_options,use_cache=False)
    check('corrected ERP Heritage P&L income200',D(out['corrected_reports']['profit_and_loss']['totals']['income']),D(200))
    check('corrected ERP Heritage P&L net profit200',D(out['corrected_reports']['profit_and_loss']['totals']['net_profit']),D(200))
    check('corrected ERP Heritage cash230',D(out['corrected_reports']['baseer_cash_categories']['totals']['actual_net_movement']),D(230))
    corrected_aml=e['account.move.line'].search([('company_id','=',6),('date','=','2026-06-19'),('parent_state','=','posted')])
    gl_rows=[row for row in out['corrected_reports']['general_ledger']['lines'] if row.get('meta',{}).get('kind')=='aml']
    check('corrected general ledger retains exact original reversal replacement AML ids',{row['meta']['aml_id'] for row in gl_rows},set(corrected_aml.ids))
    income=corrected_aml.filtered(lambda line:line.account_id.account_type in ('income','income_other')).account_id
    tb_rows=[row for row in out['corrected_reports']['trial_balance']['lines'] if row['id']=='account-'+str(income.id)]
    values={col['expression_label']:col['value'] for col in tb_rows[0]['columns']}
    check('corrected trial balance gross income debit1000',D(values['period_debit']),D(1000))
    check('corrected trial balance gross income credit1200',D(values['period_credit']),D(1200))
    out['status']='completed'
except Exception as exc:out.update(status='failed',error=str(exc),traceback=traceback.format_exc())
finally:env.cr.rollback()
Path('/mnt/qa-evidence/sales-vendor-parity-result.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k!='reports'},ensure_ascii=False,default=str))
