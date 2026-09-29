"""QA-only BP-S2 operations; failures propagate to the shell."""
import sys,json
from pathlib import Path
import om_payroll_ops as o
sys.stdout.reconfigure(encoding='utf-8')
mode=sys.argv[1]
script={'trial':'bank','commit':'bank','checks':'checks','concurrency':'concurrency','cash':'cash','pdf':'pdf'}[mode]
path='baseer_payroll_flow_'+script
prefix='BP_FLOW_COMMIT=True\n' if mode=='commit' else ''
result=o.run(['docker','exec','-i',o.CONTAINER,'/entrypoint.sh','odoo','shell',
    '--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
    '--database='+o.QA,'--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/'+path+'.log'],
    input=prefix+"exec(compile(open('/mnt/qa-evidence/"+path+".py').read(), '"+path+".py', 'exec'))\n",text=True,capture_output=True)
print(result.stdout)
if result.stderr: print(result.stderr[-1200:])
json_name=path+('_'+mode if mode in ('trial','commit') else '')+'.json'
p=json.loads((o.ROOT/'docs/build-governance'/json_name).read_text(encoding='utf-8'))
if p['status']!='passed': raise SystemExit(1)
