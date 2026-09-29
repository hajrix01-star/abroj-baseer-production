"""Install/restart the isolated existing QA using the accepted base plus SD1 only."""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACK = ROOT / '.local-backups/sales-dashboard-compact-20260909'
OUT = ROOT / 'docs/releases/2026-09-09-sales-dashboard-compact'
BACK.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
CONFIG = BACK / 'compose.qa.yaml'
ADDONS = '/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19,/mnt/sales-dashboard-addons'
DB = 'baseer_reports_qa_20260907'
CONFIG.write_text('''services:
  reports_qa:
    volumes:
      - ./.local-backups/pos-payment-seed-20260909/candidate/custom_addons:/mnt/baseer-addons:ro
      - ./.local-backups/pos-payment-seed-20260909/candidate/third_party_addons:/mnt/third-party-addons:ro
      - ./custom_addons/baseer_sales_dashboard:/mnt/sales-dashboard-addons/baseer_sales_dashboard:ro
    command:
      - odoo
      - --config=/etc/odoo/odoo.local.conf
      - --addons-path=''' + ADDONS + '''
      - --database=''' + DB + '''
      - --db-filter=^''' + DB + '''$
      - --no-database-list
      - --max-cron-threads=0
''', encoding='utf-8')
compose = ['docker', 'compose', '-p', 'baseer_odoo_dev', '-f', 'compose.yaml', '-f', 'compose.reports-qa.yaml', '-f', str(CONFIG)]
if sys.argv[-1] in ('install', 'update'):
    with (OUT / 'qa-install.log').open('wb') as stream:
        subprocess.run(compose + ['run', '--rm', '--no-deps', '-T', 'reports_qa', 'odoo',
            '--config=/etc/odoo/odoo.local.conf', '--addons-path=' + ADDONS, '--database=' + DB,
            ('--init=' if sys.argv[-1] == 'install' else '--update=') + 'baseer_sales_dashboard',
            '--stop-after-init', '--no-http', '--max-cron-threads=0'], cwd=ROOT, stdout=stream, stderr=stream, check=True)
    print('QA module installed/updated')
elif sys.argv[-1] == 'start':
    subprocess.run(compose + ['up', '-d', '--no-deps', 'reports_qa'], cwd=ROOT, check=True)
elif sys.argv[-1] == 'restart':
    subprocess.run(compose + ['restart', 'reports_qa'], cwd=ROOT, check=True)
else:
    raise SystemExit('Choose install, update, start or restart')
