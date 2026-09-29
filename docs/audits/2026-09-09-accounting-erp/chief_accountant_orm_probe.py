"""Run company-aware, read-only ORM checks on MAIN; never invoke seeds/posting."""
import json
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent
script = r'''
import json
env.cr.rollback()
env.cr.execute('SET TRANSACTION READ ONLY')
result={'mode':'SET TRANSACTION READ ONLY / ROLLBACK','companies':[]}
def account_info(account, company):
    if not account:
        return None
    return {'id':account.id,'code':account.with_company(company).code,'type':account.account_type,
            'active':account.active,'reconcile':account.reconcile,'owned':company in account.company_ids}
try:
    for company in env['res.company'].search([],order='id'):
        co=company.with_company(company).with_context(allowed_company_ids=company.ids)
        row={'id':co.id,'name':co.name,'partner_property_issues':[],'product_account_issues':[],'service_mappings':[],'pos':[]}
        partners=co.env['res.partner'].with_context(active_test=False).search(['|',('company_id','=',False),('company_id','=',co.id)])
        row['partners_checked']=len(partners)
        for p in partners:
            for field,kind in [('property_account_receivable_id','asset_receivable'),('property_account_payable_id','liability_payable')]:
                account=p[field]
                if not account or not account.active or co not in account.company_ids or account.account_type!=kind or not account.reconcile:
                    row['partner_property_issues'].append({'partner_id':p.id,'field':field,'account':account_info(account,co)})
        products=co.env['product.template'].search(['|',('company_id','=',False),('company_id','=',co.id)])
        row['products_checked']=len(products)
        for p in products:
            accounts=p._get_product_accounts()
            for use,key,types in [(p.sale_ok,'income',('income','income_other')),(p.purchase_ok,'expense',('expense','expense_direct_cost','expense_depreciation'))]:
                if use:
                    a=accounts.get(key)
                    if not a or not a.active or co not in a.company_ids or a.account_type not in types:
                        row['product_account_issues'].append({'product_template_id':p.id,'type':p.type,'key':key,'account':account_info(a,co)})
        for mapping in co.env['baseer.purchase.category.map'].search([('company_id','=',co.id)]):
            p=mapping.product_id
            a=p._get_product_accounts()['expense']
            row['service_mappings'].append({'map_id':mapping.id,'product_id':p.id,'category':mapping.category_id.display_name,'account':account_info(a,co)})
        for config in co.env['pos.config'].search([('company_id','=',co.id),('baseer_summary_only','=',True)]):
            try:
                config._validate_baseer_setup()
                status='valid'
            except Exception as error:
                status=type(error).__name__+': '+str(error)
            row['pos'].append({'config_id':config.id,'status':status,'product_id':config.baseer_summary_product_id.id,'tax_id':config.baseer_summary_tax_id.id,'method_ids':config.payment_method_ids.ids})
        row['payment_invoice_state']=co.env['account.move']._get_invoice_in_payment_state()
        row['payment_fallbacks']={}
        for ptype,key in [('inbound','account_journal_payment_debit_account_id'),('outbound','account_journal_payment_credit_account_id')]:
            a=co.env['account.chart.template'].ref(key,raise_if_not_found=False) or co.transfer_account_id
            row['payment_fallbacks'][ptype]=account_info(a,co)
        row['payroll_accounts']={key:account_info(co[key],co) for key in ['baseer_salary_expense_id','baseer_salary_payable_id','baseer_deduction_account_id','baseer_loan_account_id','baseer_eos_expense_id']}
        result['companies'].append(row)
    env.flush_all()
    print('CHIEF_ACCOUNTANT='+json.dumps(result,ensure_ascii=False))
finally:
    env.cr.rollback()
'''
args=['docker','exec','-i','baseer_odoo_dev-odoo-1','/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf',
'--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
'--database=baseer_dev','--no-http','--max-cron-threads=0','--log-level=critical']
done=subprocess.run(args,input=script,text=True,encoding='utf8',capture_output=True)
(OUT/'chief-accountant-orm.log').write_text(done.stdout+'\n'+done.stderr,encoding='utf8')
done.check_returncode()
result=json.loads(next(line.split('=',1)[1] for line in done.stdout.splitlines() if line.startswith('CHIEF_ACCOUNTANT=')))
(OUT/'chief-accountant-orm.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps([{'company':c['id'],'partners':c['partners_checked'],'partner_issues':len(c['partner_property_issues']),'products':c['products_checked'],'product_issues':len(c['product_account_issues']),'mappings':len(c['service_mappings']),'pos':c['pos'],'fallback':c['payment_fallbacks']} for c in result['companies']],ensure_ascii=False))
