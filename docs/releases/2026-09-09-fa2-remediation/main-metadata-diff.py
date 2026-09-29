"""Describe rehearsal master-data changes; no names, wages or contact values emitted."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
baseline=json.loads((f.OUT/'main-column-baseline.json').read_text())
diff=[]
for table in ('res_company','res_partner','hr_employee','hr_version'):
 if table in baseline:
  cols=baseline[table]['columns'];ids=baseline[table]['ids']
 else:
  if not f.o.sql('baseer_dev',"SELECT to_regclass('public."+table+"')"):continue
  cols=f.o.sql('baseer_dev',"SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' AND table_name='"+table+"'")
  ids=json.loads(f.o.sql('baseer_dev','SELECT coalesce(json_agg(id),\'[]\'::json) FROM '+table))
 predicate='id IN ('+','.join(str(int(i)) for i in ids)+')' if ids else 'false'
 def rows(database):
  return {r['id']:r for r in json.loads(f.o.sql(database,"SELECT coalesce(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT "+cols+' FROM '+table+' WHERE '+predicate+')t'))}
 original=rows('baseer_dev');rehearsal=rows(f.db('main'))
 for rid in sorted(set(original)|set(rehearsal)):
  a,b=original.get(rid,{}),rehearsal.get(rid,{})
  if a!=b:diff.append({'table':table,'id':rid,'changed_columns':sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k))})
f.save('main-metadata-diff.json',{'comparison':'Current read-only main versus rehearsal, original columns and rows only. No sensitive values emitted.','differences':diff})
print(json.dumps(diff,ensure_ascii=False,indent=2))
