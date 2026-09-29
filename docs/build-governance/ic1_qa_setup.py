"""Restore a verified MAIN snapshot to a new, isolated database; never overwrite."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = 'baseer_ic1_20260910'
PG = 'baseer_odoo_dev-db-1'
meta = json.loads((ROOT / 'docs/releases/2026-09-10-financial-register-cash/post-release-backup.json').read_text())
dump = Path(meta['directory']) / 'database.dump'
assert hashlib.sha256(dump.read_bytes()).hexdigest() == meta['files']['database.dump']['sha256']
def run(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, **kw)
exists = run(['docker','exec',PG,'psql','-U','odoo','-d','postgres','-Atc',
              "SELECT 1 FROM pg_database WHERE datname='" + DB + "'"]).stdout.strip()
assert not exists, 'QA database exists; refusing to overwrite'
run(['docker','exec',PG,'createdb','-U','odoo',DB])
run(['docker','exec','-i',PG,'pg_restore','-U','odoo','--no-owner','--no-privileges','--exit-on-error','-d',DB],input=dump.read_bytes())
run(['docker','exec',PG,'psql','-U','odoo','-d',DB,'-v','ON_ERROR_STOP=1','-c',
     "UPDATE ir_cron SET active=false; UPDATE ir_mail_server SET active=false;"])
print(json.dumps({'database':DB,'restored_from_sha256':meta['files']['database.dump']['sha256'],
                  'main_untouched':True,'cron_and_mail_disabled':True}))
