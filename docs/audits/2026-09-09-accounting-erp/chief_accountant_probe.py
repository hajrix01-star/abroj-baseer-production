"""Read-only SQL accounting inventory. No writes to Odoo or configuration."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
def sql(query):
    command = ['docker', 'exec', '-i', 'baseer_odoo_dev-db-1', 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', 'odoo', '-d', 'baseer_dev', '-Atq']
    completed = subprocess.run(command, input='BEGIN READ ONLY;\n' + query + '\nROLLBACK;\n', text=True, encoding='utf8', capture_output=True, check=True)
    return json.loads(completed.stdout.strip())

queries = {
'companies': """SELECT coalesce(json_agg(x),'[]') FROM (SELECT id,name,partner_id,currency_id,chart_template,parent_id,account_fiscal_country_id,account_sale_tax_id,account_purchase_tax_id,tax_calculation_rounding_method,account_price_include,fiscalyear_lock_date,tax_lock_date,sale_lock_date,purchase_lock_date,hard_lock_date,account_opening_move_id,account_opening_date,inventory_valuation,cost_method FROM res_company ORDER BY id)x;""",
'accounts': """SELECT coalesce(json_agg(x),'[]') FROM (SELECT a.id,c.res_company_id company_id,a.code_store->>c.res_company_id::text code,a.name,a.account_type,a.active,a.reconcile,a.currency_id FROM account_account a LEFT JOIN account_account_res_company_rel c ON c.account_account_id=a.id ORDER BY c.res_company_id,a.code_store->>c.res_company_id::text,a.id)x;""",
'journals': """SELECT coalesce(json_agg(x),'[]') FROM (SELECT id,company_id,name,code,type,active,currency_id,default_account_id,suspense_account_id,profit_account_id,loss_account_id,non_deductible_account_id,restrict_mode_hash_table FROM account_journal ORDER BY company_id,id)x;""",
'payment_method_lines': """SELECT coalesce(json_agg(x),'[]') FROM (SELECT l.id,l.name,l.journal_id,j.company_id,j.type journal_type,l.payment_account_id,m.code,m.payment_type FROM account_payment_method_line l JOIN account_journal j ON j.id=l.journal_id JOIN account_payment_method m ON m.id=l.payment_method_id ORDER BY j.company_id,l.id)x;""",
'taxes': """SELECT coalesce(json_agg(x),'[]') FROM (SELECT id,company_id,name,type_tax_use,tax_scope,amount_type,amount,price_include_override,tax_exigibility,active,tax_group_id,cash_basis_transition_account_id,country_id,include_base_amount,is_base_affected,ubl_cii_tax_category_code,ubl_cii_tax_exemption_reason_code FROM account_tax ORDER BY company_id,id)x;""",
'tax_repartition': """SELECT coalesce(json_agg(x),'[]') FROM (SELECT id,tax_id,company_id,document_type,repartition_type,factor_percent,account_id FROM account_tax_repartition_line ORDER BY company_id,tax_id,document_type,id)x;""",
'pos_methods': """SELECT coalesce(json_agg(x),'[]') FROM (SELECT m.id,m.name,m.company_id,m.journal_id,m.outstanding_account_id,m.receivable_account_id,m.active,m.is_cash_count,m.split_transactions,m.payment_method_type,c.kind FROM pos_payment_method m LEFT JOIN baseer_pos_payment_category c ON c.id=m.baseer_category_id ORDER BY m.company_id,m.id)x;""",
'foreign_keys': """SELECT coalesce(json_agg(x),'[]') FROM (SELECT c.conrelid::regclass::text source_table,att.attname field,c.confrelid::regclass::text target_table FROM pg_constraint c JOIN pg_attribute att ON att.attrelid=c.conrelid AND att.attnum=c.conkey[1] WHERE c.contype='f' AND c.confrelid IN ('account_account'::regclass,'account_journal'::regclass) ORDER BY c.conrelid::regclass::text,att.attname)x;""",
'schema': """SELECT coalesce(json_object_agg(table_name,cols),'{}') FROM (SELECT table_name,json_agg(column_name ORDER BY ordinal_position) cols FROM information_schema.columns WHERE table_schema='public' AND (table_name IN ('account_move','account_move_line','account_payment','account_partial_reconcile','account_tax_group','account_group','product_template','product_category','res_partner','baseer_purchase_category_map') OR table_name LIKE 'account_fiscal_position%') GROUP BY table_name)x;""",
'transaction_counts': """SELECT coalesce(json_object_agg(t,n),'{}') FROM (SELECT 'account_move' t,count(*) n FROM account_move UNION ALL SELECT 'account_move_line',count(*) FROM account_move_line UNION ALL SELECT 'account_payment',count(*) FROM account_payment UNION ALL SELECT 'account_partial_reconcile',count(*) FROM account_partial_reconcile UNION ALL SELECT 'account_full_reconcile',count(*) FROM account_full_reconcile UNION ALL SELECT 'account_bank_statement',count(*) FROM account_bank_statement UNION ALL SELECT 'account_bank_statement_line',count(*) FROM account_bank_statement_line UNION ALL SELECT 'pos_order',count(*) FROM pos_order UNION ALL SELECT 'pos_session',count(*) FROM pos_session UNION ALL SELECT 'baseer_pos_summary',count(*) FROM baseer_pos_summary)x;""",
'xmlids': """SELECT coalesce(json_agg(x),'[]') FROM (SELECT module,name,model,res_id FROM ir_model_data WHERE model IN ('account.account','account.journal','account.tax') AND module IN ('account','baseer_company_setup','baseer_service_seed','baseer_pos_summary') ORDER BY module,model,name)x;""",
}
data = {'at_utc': datetime.now(timezone.utc).isoformat(), 'database': 'baseer_dev', 'mode': 'BEGIN READ ONLY / ROLLBACK', 'queries': queries}
for key, query in queries.items():
    data[key] = sql(query)
company_fields = [r['field'] for r in data['foreign_keys'] if r['source_table']=='res_company']
data['company_account_journal_defaults'] = sql('SELECT json_agg(x) FROM (SELECT id,' + ','.join('"'+c+'"' for c in company_fields) + ' FROM res_company ORDER BY id)x;')
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'chief-accountant-inventory.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'companies':len(data['companies']),'accounts':len(data['accounts']),'journals':len(data['journals']),'taxes':len(data['taxes']),'transactions':data['transaction_counts']},ensure_ascii=False))
