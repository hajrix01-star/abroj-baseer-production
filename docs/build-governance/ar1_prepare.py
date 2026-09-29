"""Create an isolated MAIN clone for role installation/testing; no MAIN writes."""
from pathlib import Path
import environment_backups as b

database = 'baseer_ar1_roles_20260910'
back = b.ROOT / '.local-backups/access-roles-20260910'
out = b.ROOT / 'docs/releases/2026-09-10-access-roles'
back.mkdir(parents=True, exist_ok=True)
out.mkdir(parents=True, exist_ok=True)
assert b.sql('postgres', "SELECT count(*) FROM pg_database WHERE datname='" + database + "'") == '0'
dump = back / 'qa-source.dump'
assert not dump.exists()
with dump.open('wb') as stream:
    b.run(['docker', 'exec', b.DB, 'pg_dump', '-U', 'odoo', '-Fc', b.MAIN], stdout=stream)
b.run(['docker', 'exec', b.DB, 'createdb', '-U', 'odoo', '-O', 'odoo', '--template=template0', database], capture_output=True)
with dump.open('rb') as stream:
    b.run(['docker', 'exec', '-i', b.DB, 'pg_restore', '-U', 'odoo', '--no-owner', '--exit-on-error', '-d', database], stdin=stream, capture_output=True)
overlay = '''services:
  roles_qa:
    image: odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd
    environment:
      HOST: db
      USER: ${POSTGRES_USER}
      PASSWORD: ${POSTGRES_PASSWORD}
    command: ["odoo", "--config=/etc/odoo/odoo.local.conf", "--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/role-addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19", "--database=baseer_ar1_roles_20260910", "--db-filter=^baseer_ar1_roles_20260910$", "--no-database-list", "--max-cron-threads=0"]
    ports: ["127.0.0.1:18074:8069"]
    volumes:
      - ./config/odoo.local.conf:/etc/odoo/odoo.local.conf:ro
      - ./.local-backups/sales-dashboard-preview-20260910/candidate/custom_addons:/mnt/baseer-addons:ro
      - ./.local-backups/sales-dashboard-preview-20260910/candidate/third_party_addons:/mnt/third-party-addons:ro
      - ./custom_addons/baseer_access_roles:/mnt/role-addons/baseer_access_roles:ro
      - ./docs/build-governance:/mnt/qa-evidence
    restart: 'no'
'''
(b.ROOT / 'compose.roles-qa.yaml').write_text(overlay, encoding='utf8')
print('AR1_CLONE_READY', database)
