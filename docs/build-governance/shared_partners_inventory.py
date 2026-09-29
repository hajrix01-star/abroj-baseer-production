"""SP1 read-only catalog duplicate and reference inventory; no contact writes."""
import json
from pathlib import Path
import om_payroll_ops as o

OUT=o.ROOT/'docs/build-governance/shared_partners_inventory.json'
def rows(q):
    return json.loads(o.sql(o.QA,"SELECT coalesce(json_agg(x),'[]'::json) FROM ("+q+") x"))

seed=rows("SELECT d.name AS xml_name,p.id,p.name,p.company_id,p.active,p.vat,p.parent_id,p.supplier_rank,p.property_account_payable_id,p.property_account_receivable_id,p.baseer_purchase_category_map_id FROM ir_model_data d JOIN res_partner p ON d.res_id=p.id WHERE d.module='baseer_service_seed' AND d.model='res.partner' ORDER BY p.id")
ids=sorted({r['id'] for r in seed})
assert ids
fk=rows("SELECT conrelid::regclass::text AS table_name,a.attname AS column_name,c.confdeltype AS delete_rule FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1] WHERE c.contype='f' AND c.confrelid='res_partner'::regclass AND cardinality(c.conkey)=1 ORDER BY 1,2")
refs=[]
for f in fk:
    table=f['table_name'];col=f['column_name']
    assert all(ch.isalnum() or ch=='_' for ch in table+col)
    found=rows('SELECT "'+col+'" AS partner_id,count(*) AS count FROM "'+table+'" WHERE "'+col+'" IN ('+','.join(map(str,ids))+') GROUP BY "'+col+'"')
    if found: refs.append(dict(f,counts=found))
duplicates=rows("SELECT p.name,p.vat,count(*) AS count,array_agg(p.id ORDER BY p.id) AS ids,array_agg(p.company_id ORDER BY p.id) AS companies FROM res_partner p WHERE p.active AND p.supplier_rank>0 GROUP BY p.name,p.vat HAVING count(*)>1 ORDER BY count(*) DESC,p.name")
result={'database':o.QA,'seed':seed,'foreign_key_references':refs,'active_supplier_duplicates':duplicates}
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'seed_rows':len(seed),'unique_seed_partners':len(ids),'referencing_tables':refs,'duplicate_groups':len(duplicates)},ensure_ascii=False))
