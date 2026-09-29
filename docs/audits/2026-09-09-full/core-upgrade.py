"""Rehearse the frozen installed custom modules on the disposable core clone."""
import json, subprocess, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import full_audit_ops as a
database=a.db('core')
assert database=='baseer_audit_core_20260909'
candidate=json.loads((a.OUT/'candidate.json').read_text(encoding='utf-8'))
modules=[m['name'] for m in candidate['qa_installed'] if m['name'].startswith('baseer_')]
before=a.snapshot(database)
a.save('core-upgrade-before.json',before)
started=time.monotonic()
result=subprocess.run(['docker','exec',a.o.CONTAINER,'/entrypoint.sh','odoo',
 '--config=/etc/odoo/odoo.local.conf','--addons-path='+a.ADDONS,
 '--database='+database,'--update='+','.join(modules),'--stop-after-init',
 '--no-http','--max-cron-threads=0','--logfile=/tmp/full-audit-core/upgrade.log'],
 capture_output=True,text=True,encoding='utf-8',cwd=a.o.ROOT)
(a.OUT/'core-upgrade-stdout.txt').write_text(result.stdout+'\nSTDERR:\n'+result.stderr,encoding='utf-8')
after=a.snapshot(database)
a.save('core-upgrade-after.json',after)
changed=[t for t in before if before[t]!=after[t]]
financial=['account_move','account_move_line','account_payment','account_partial_reconcile']
states=json.loads(a.o.sql(database,"SELECT json_agg(t) FROM (SELECT name,state,latest_version FROM ir_module_module WHERE name LIKE 'baseer_%' ORDER BY name)t"))
out={'database':database,'modules':modules,'exit_code':result.returncode,
 'elapsed_seconds':round(time.monotonic()-started,2),'changed_tables':changed,
 'financial_rows_unchanged':not any(t in changed for t in financial),'module_states':states}
a.save('core-upgrade-result.json',out)
a.o.run(['docker','cp',a.o.CONTAINER+':/tmp/full-audit-core/upgrade.log',str(a.OUT/'core-upgrade.log')],capture_output=True)
print(json.dumps(out,ensure_ascii=False,indent=2))
assert result.returncode==0
assert out['financial_rows_unchanged']
