"""Record active QA module drift without exposing business data."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import full_audit_ops as a
candidate=json.loads((a.OUT/'candidate.json').read_text(encoding='utf-8'))
current=json.loads(a.o.sql(a.o.QA,"SELECT json_agg(t) FROM (SELECT name,state,latest_version FROM ir_module_module WHERE state='installed' ORDER BY name)t"))
before={m['name']:m for m in candidate['qa_installed']};after={m['name']:m for m in current}
result={'before_count':len(before),'after_count':len(after),'newly_installed':[after[n] for n in sorted(set(after)-set(before))],
 'removed':[before[n] for n in sorted(set(before)-set(after))],
 'version_changed':[{'before':before[n],'after':after[n]} for n in sorted(set(before)&set(after)) if before[n]!=after[n]],
 'audit_scope':'frozen candidate, not newly installed modules','cause':'not attributed by this read-only evidence'}
a.save('qa-module-drift.json',result)
print(json.dumps(result,indent=2))
