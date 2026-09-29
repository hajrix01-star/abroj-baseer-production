"""Final business-row fingerprints and exact-name disposable clone cleanup."""
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import full_audit_ops as a
baseline=json.loads((a.OUT/'qa-before.json').read_text(encoding='utf-8'))
if len(sys.argv)>1 and sys.argv[1]=='cleanup':
    results=[]
    for scope in a.SCOPES:
        database=a.db(scope)
        assert database in tuple('baseer_audit_'+s+'_20260909' for s in a.SCOPES)
        assert database not in (a.o.QA,'baseer_dev')
        active=int(a.o.sql('postgres',"SELECT count(*) FROM pg_stat_activity WHERE datname='"+database+"'"))
        assert active==0, (database,'still in use')
        a.o.run(['docker','exec',a.o.DB,'sh','-c','dropdb -U "$POSTGRES_USER" '+database],capture_output=True)
        absent=a.o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='"+database+"'")=='0'
        results.append({'database':database,'removed':absent})
    a.save('clone-cleanup.json',results)
    print(json.dumps(results,indent=2))
else:
    restored=a.snapshot(a.db('security'))
    a.save('core-restoration-result.json',{'database':a.db('security'),
      'method':'pg_dump -Fc and pg_restore, then read-only/rollback security probes',
      'compared_tables':list(baseline),'differences':[t for t in baseline if baseline[t]!=restored[t]],
      'business_rows_match_qa_baseline':baseline==restored,
      'filestore_restored':False,'full_disaster_recovery_claimed':False})
    a.preserve()
    print((a.OUT/'core-restoration-result.json').read_text(encoding='utf-8'))
