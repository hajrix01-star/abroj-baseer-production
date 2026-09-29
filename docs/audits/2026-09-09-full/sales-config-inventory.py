assert env.cr.dbname=='baseer_audit_sales_20260909'
import json
from pathlib import Path
results=[]
for config in env['pos.config'].search([('baseer_summary_only','=',True)]):
    row={'id':config.id,'company':config.company_id.id,'name':config.name,'active':config.active,
         'product':config.baseer_summary_product_id.read(['name','active','type','company_id']),
         'tax':config.baseer_summary_tax_id.read(['name','amount','price_include','active']),
         'methods':config.payment_method_ids.read(['name','active','baseer_category_id','journal_id','outstanding_account_id'])}
    try:config.with_company(config.company_id)._validate_baseer_setup();row['valid']=True
    except Exception as exc:row.update(valid=False,error=str(exc))
    results.append(row)
Path('/mnt/qa-evidence/sales-config-inventory.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
