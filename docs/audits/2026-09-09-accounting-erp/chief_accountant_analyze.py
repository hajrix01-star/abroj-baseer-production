"""Analyze read-only inventory and compare with the actual installed SA template."""
import collections
import csv
import io
import json
import subprocess
from pathlib import Path

OUT=Path(__file__).resolve().parent
d=json.loads((OUT/'chief-accountant-inventory.json').read_text(encoding='utf8'))
def native_csv(name):
    source=subprocess.run(['docker','exec','baseer_odoo_dev-odoo-1','cat','/usr/lib/python3/dist-packages/odoo/addons/l10n_sa/data/template/'+name],capture_output=True,text=True,encoding='utf8',check=True).stdout
    (OUT/('chief-native-'+name)).write_text(source,encoding='utf8')
    return list(csv.DictReader(io.StringIO(source)))
chart=native_csv('account.account-sa.csv')
tax_template=native_csv('account.tax-sa.csv')
accounts={a['id']:a for a in d['accounts']}
journals={a['id']:a for a in d['journals']}
xml={(r['model'],r['name']):r['res_id'] for r in d['xmlids'] if r['module']=='account'}
checks={'template_account_mismatches':[],'template_tax_mismatches':[], 'account_duplicate_codes':[],
        'missing_account_ownership_or_code':[],'unreconciled_receivable_payable':[],
        'journal_account_issues':[],'company_default_issues':[],'tax_repartition_issues':[],
        'ordinary_equity_accounts':[],'tax_default_summary':[],'counts':{},'native_chart_accounts_checked':0,'native_taxes_checked':0}
for company in d['companies']:
    cid=company['id']
    owned=[a for a in d['accounts'] if a['company_id']==cid]
    codes=collections.Counter(a['code'] for a in owned)
    checks['account_duplicate_codes'] += [{'company':cid,'code':k,'count':v} for k,v in codes.items() if v>1]
    checks['ordinary_equity_accounts'] += [{'company':cid,'id':a['id'],'code':a['code']} for a in owned if a['account_type']=='equity']
    checks['counts'][str(cid)]={'accounts':len(owned),'active_accounts':sum(a['active'] for a in owned),'journals':sum(j['company_id']==cid for j in d['journals']),'taxes':sum(t['company_id']==cid for t in d['taxes']),'active_taxes':sum(t['company_id']==cid and t['active'] for t in d['taxes'])}
    for row in chart:
        actual=accounts.get(xml.get(('account.account',f'{cid}_{row["id"]}')))
        checks['native_chart_accounts_checked']+=1
        expected={'code':row['code'],'account_type':row['account_type'],'reconcile':row['reconcile']=='True'}
        if not actual or any(actual[k]!=v for k,v in expected.items()):
            checks['template_account_mismatches'].append({'company':cid,'xmlid':row['id'],'expected':expected,'actual':actual})
    for row in tax_template:
        if not row['id']: continue
        actual_id=xml.get(('account.tax',f'{cid}_{row["id"]}'))
        actual=next((t for t in d['taxes'] if t['id']==actual_id),None)
        expected={'amount':float(row['amount'] or 0),'amount_type':row['amount_type'] or 'percent','type_tax_use':row['type_tax_use'] or 'sale','active':row['active']!='False','tax_exigibility':row['tax_exigibility'] or 'on_invoice'}
        checks['native_taxes_checked']+=1
        if not actual or any(actual[k]!=v for k,v in expected.items()):
            checks['template_tax_mismatches'].append({'company':cid,'xmlid':row['id'],'expected':expected,'actual':actual})
    for field in ('account_sale_tax_id','account_purchase_tax_id'):
        t=next(t for t in d['taxes'] if t['id']==company[field])
        repart=[r for r in d['tax_repartition'] if r['tax_id']==t['id']]
        checks['tax_default_summary'].append({'company':cid,'field':field,'tax':t,'repartition':repart})
for a in d['accounts']:
    if not a['company_id'] or not a['code']:
        checks['missing_account_ownership_or_code'].append(a)
    if a['account_type'] in ('asset_receivable','liability_payable') and not a['reconcile']:
        checks['unreconciled_receivable_payable'].append(a)
for j in d['journals']:
    for field in ('default_account_id','suspense_account_id','profit_account_id','loss_account_id','non_deductible_account_id'):
        aid=j[field]
        if not aid: continue
        a=accounts.get(aid)
        if not a or a['company_id']!=j['company_id'] or not a['active']:
            checks['journal_account_issues'].append({'journal':j['id'],'field':field,'account':a})
    if j['type'] in ('cash','bank') and (not j['default_account_id'] or accounts[j['default_account_id']]['account_type']!='asset_cash'):
        checks['journal_account_issues'].append({'journal':j['id'],'issue':'missing_or_nonliquidity_default'})
for c in d['company_account_journal_defaults']:
    for field,value in c.items():
        if field=='id' or not value: continue
        fk=next(k for k in d['foreign_keys'] if k['source_table']=='res_company' and k['field']==field)
        record=(accounts if fk['target_table']=='account_account' else journals).get(value)
        if not record or record['company_id']!=c['id'] or not record['active']:
            checks['company_default_issues'].append({'company':c['id'],'field':field,'record':record})
for t in d['taxes']:
    rows=[r for r in d['tax_repartition'] if r['tax_id']==t['id']]
    for r in rows:
        if r['company_id']!=t['company_id'] or (r['account_id'] and (accounts[r['account_id']]['company_id']!=t['company_id'] or not accounts[r['account_id']]['active'])):
            checks['tax_repartition_issues'].append({'tax':t['id'],'repartition':r,'issue':'company_or_inactive_account'})
    for doc in ('invoice','refund'):
        base=[r for r in rows if r['document_type']==doc and r['repartition_type']=='base']
        tax=[r for r in rows if r['document_type']==doc and r['repartition_type']=='tax']
        if len(base)!=1 or not tax:
            checks['tax_repartition_issues'].append({'tax':t['id'],'document':doc,'issue':'missing_base_or_tax_line'})
        # Reverse-charge +100/-100 pairs are legitimate; verify absolute components rather than demanding net100.
        if any(abs(r['factor_percent'])>100 for r in tax):
            checks['tax_repartition_issues'].append({'tax':t['id'],'document':doc,'issue':'factor_abs_over100'})
checks['payment_methods_without_explicit_account']=[m for m in d['payment_method_lines'] if not m['payment_account_id']]
checks['direct_payroll_ready_outbound']=[m for m in d['payment_method_lines'] if m['payment_type']=='outbound' and m['payment_account_id'] and m['payment_account_id']==journals[m['journal_id']]['default_account_id'] and not accounts[m['payment_account_id']]['reconcile']]
(OUT/'chief-accountant-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v if not isinstance(v,list) else len(v) for k,v in checks.items()},ensure_ascii=False,indent=2))
