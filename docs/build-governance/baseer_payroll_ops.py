import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import om_payroll_ops as ops
ops.OUT=ops.ROOT/'docs/releases/2026-09-08-baseer-payroll'
ops.BACK=ops.ROOT/'.local-backups/baseer-payroll-20260908'
if sys.argv[1]=='backup':
    ops.snapshot('baseer_dev','main-before')
    ops.backup()
elif sys.argv[1]=='snapshot': ops.snapshot(sys.argv[2],sys.argv[3])
elif sys.argv[1] in ('preview','concurrent-payment','focus'):
    script={'preview':'baseer_payroll_preview.py','concurrent-payment':'baseer_payroll_concurrent_payment.py','focus':'baseer_payroll_focused.py'}[sys.argv[1]]
    result=ops.run(['docker','exec','-i',ops.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--database='+ops.QA,'--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/baseer_payroll_preview.log'],input="exec(compile(open('/mnt/qa-evidence/"+script+"').read(), '"+script+"', 'exec'))\n",text=True,capture_output=True)
    print(result.stdout)
    if result.stderr: print(result.stderr[-6000:])
    if sys.argv[1]=='focus':
        import json
        if json.loads((ops.ROOT/'docs/build-governance/baseer_payroll_focused.json').read_text(encoding='utf-8'))['status']!='passed':
            raise SystemExit(1)
elif sys.argv[1]=='checks':
    result=ops.run(['docker','exec','-i',ops.CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--database='+ops.QA,'--no-http','--max-cron-threads=0','--logfile=/mnt/qa-evidence/baseer_payroll_checks.log'],input="exec(compile(open('/mnt/qa-evidence/baseer_payroll_checks.py').read(), 'baseer_payroll_checks.py', 'exec'))\n",text=True,capture_output=True)
    import json
    payload=json.loads((ops.ROOT/'docs/build-governance/baseer_payroll_checks.json').read_text(encoding='utf-8'))
    print(json.dumps({'status':payload['status'],'checks':len(payload['checks']),'months':payload['months'],'error':payload.get('error')},ensure_ascii=False,indent=2))
    if result.stderr: print(result.stderr[-4000:])
    if payload['status']!='passed': raise SystemExit(1)
