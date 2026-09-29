"""Small isolated-QA shell runner; never selects MAIN."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = 'baseer_odoo_dev-ic1_qa-1'
ADDONS = '/usr/lib/python3/dist-packages/odoo/addons,/mnt/ic1-addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19'

def shell(code, name):
    result = subprocess.run(['docker','exec','-i',CONTAINER,'/entrypoint.sh','odoo','shell',
        '--config=/etc/odoo/odoo.local.conf','--addons-path='+ADDONS,
        '--database=baseer_ic1_20260910','--no-http','--max-cron-threads=0'],
        input=code.encode(), capture_output=True)
    (ROOT/'docs/build-governance'/('ic1-'+name+'.log')).write_bytes(result.stdout+result.stderr)
    print(result.stdout.decode(errors='replace')[-3000:])
    if result.returncode:
        print(result.stderr.decode(errors='replace')[-5000:])
    result.check_returncode()

if __name__ == '__main__':
    shell(Path(sys.argv[1]).read_text(encoding='utf-8'), Path(sys.argv[1]).stem)
