"""Preserve pre-install columns/rows while allowing additive module schema and seed rows."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
database=f.db('main')
tables=['account_move','account_move_line','account_payment','account_partial_reconcile','res_company','res_partner','hr_employee','hr_payslip','hr_payslip_run']
def rowhash(table,cols,ids):
 predicate='id IN ('+','.join(str(int(i)) for i in ids)+')' if ids else 'false'
 return f.o.sql(database,"SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM (SELECT "+cols+' FROM '+table+' WHERE '+predicate+')t')
path=f.OUT/'main-column-baseline.json'
if len(sys.argv)==1:
 assert not path.exists()
 records={}
 for table in tables:
  if not f.o.sql(database,"SELECT to_regclass('public."+table+"')"):continue
  cols=f.o.sql(database,"SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' AND table_name='"+table+"'")
  ids=json.loads(f.o.sql(database,'SELECT coalesce(json_agg(id ORDER BY id),\'[]\'::json) FROM '+table))
  records[table]={'columns':cols,'ids':ids,'row_hash':rowhash(table,cols,ids)}
 f.save('main-column-baseline.json',records)
 print('Captured pre-install projections',len(records))
else:
 records=json.loads(path.read_text());changed=[]
 for table,record in records.items():
  if rowhash(table,record['columns'],record['ids'])!=record['row_hash']:changed.append(table)
 f.save('main-projection-result.json',{'database':database,'compared_tables':list(records),'changed_preexisting_rows':changed,
  'financial_preexisting_rows_unchanged':not any(t.startswith('account_') for t in changed),
  'comparison':'Original columns and original row IDs; additive fields/seed records explicitly excluded.'})
 print('Changed pre-existing rows:',changed)
 assert not any(t.startswith('account_') for t in changed)
