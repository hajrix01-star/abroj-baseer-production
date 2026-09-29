"""Compare QA against the restored unchanged baseline; emit field names, not PII."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import full_audit_ops as a
before=json.loads((a.OUT/'qa-before.json').read_text(encoding='utf-8'))
after=a.snapshot(a.o.QA)
a.save('qa-after.json',after)
a.save('main-after.json',a.snapshot('baseer_dev'))
diffs=[]
for table in before:
    if before[table]==after[table]:continue
    def rows(database):
        raw=json.loads(a.o.sql(database,'SELECT coalesce(json_agg(row_to_json(t)),\'[]\'::json) FROM '+table+' t'))
        return {r['id']:r for r in raw}
    old,new=rows(a.db('security')),rows(a.o.QA)
    for rid in sorted(set(old)|set(new)):
        x,y=old.get(rid,{}),new.get(rid,{})
        if x==y:continue
        keys=[k for k in set(x)|set(y) if x.get(k)!=y.get(k)]
        safe={k:{'before':x.get(k),'after':y.get(k)} for k in keys if k in ('lang','write_date','write_uid')}
        diffs.append({'table':table,'id':rid,'change':'update' if x and y else 'insert' if y else 'delete','fields':sorted(keys),'non_sensitive_metadata':safe})
a.save('preservation-differences.json',diffs)
print(json.dumps(diffs,ensure_ascii=False,indent=2))
