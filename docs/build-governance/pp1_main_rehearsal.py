"""Rehearse the exact composite installation against a fresh, isolated MAIN dump."""
import json
import pp1_main_release as r

b = r.b
database = 'baseer_pp1_main_rehearsal_20260910'
candidate = r.verify_candidate()
assert b.sql('postgres', "SELECT count(*) FROM pg_database WHERE datname='" + database + "'") == '0'
dump = r.BACK / 'rehearsal.dump'
assert not dump.exists()
with dump.open('wb') as out:
    b.run(['docker', 'exec', b.DB, 'pg_dump', '-U', 'odoo', '-Fc', b.MAIN], stdout=out)
b.run(['docker', 'exec', b.DB, 'createdb', '-U', 'odoo', '-O', 'odoo', '--template=template0', database], capture_output=True)
with dump.open('rb') as inp:
    b.run(['docker', 'exec', '-i', b.DB, 'pg_restore', '-U', 'odoo', '--no-owner', '--exit-on-error', '-d', database], stdin=inp, capture_output=True)
b.MAIN = database
cols = r.columns()
before = r.projection(cols)
overlay = r.BACK / 'compose.rehearsal.yaml'
overlay.write_text('''services:
  pp1_rehearsal:
    image: ''' + candidate['image'] + '''
    environment:
      HOST: db
      USER: ${POSTGRES_USER}
      PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - ./config/odoo.local.conf:/etc/odoo/odoo.local.conf:ro
      - ./.local-backups/partner-priority-main-20260910/candidate/custom_addons:/mnt/baseer-addons:ro
      - ./.local-backups/partner-priority-main-20260910/candidate/third_party_addons:/mnt/third-party-addons:ro
    restart: 'no'
''', encoding='utf8')
base = ['docker', 'compose', '-p', 'baseer_odoo_dev', '-f', 'compose.yaml', '-f', str(overlay), 'run', '--rm', '--no-deps', '-T', 'pp1_rehearsal', 'odoo']
options = ['--config=/etc/odoo/odoo.local.conf', '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19', '--database=' + database, '--no-http', '--max-cron-threads=0']
with (r.OUT / 'rehearsal-install.log').open('wb') as log:
    b.run(base + options + ['--init=' + r.MODULE, '--stop-after-init'], cwd=b.ROOT, stdout=log, stderr=log)
assert before == r.projection(cols), 'Rehearsal changed original business data'
script = '''import json
assert env.cr.dbname == 'baseer_pp1_main_rehearsal_20260910'
assert env['ir.module.module'].search([('name', '=', 'baseer_browser_print')]).state == 'installed'
assert env['ir.module.module'].search([('name', '=', 'baseer_partner_priority')]).state == 'installed'
results = []
for company in env['res.company'].search([]):
    partners = env['res.partner'].with_context(allowed_company_ids=[company.id], res_partner_search_mode='supplier')
    names = partners.name_search(domain=[('supplier_rank', '>', 0)], limit=8)
    records = partners.browse([row[0] for row in names])
    assert not any(records.mapped('baseer_is_favorite'))
    counts = records.mapped('baseer_recent_bill_count')
    assert counts == sorted(counts, reverse=True)
    results.append({'company':company.id,'returned':len(names),'frequency_sorted':True})
env.cr.rollback()
print('PP1_SMOKE ' + json.dumps(results))
'''
result = b.run(base + ['shell'] + options, input=script, capture_output=True, text=True, encoding='utf8', cwd=b.ROOT)
(r.OUT / 'rehearsal-smoke.log').write_text(result.stdout + result.stderr, encoding='utf8')
assert 'PP1_SMOKE ' in result.stdout
assert before == r.projection(cols), 'Smoke changed original business data'
b.save(r.OUT / 'rehearsal.json', dict(candidate=candidate['commit'], fresh_main_clone=True,
    installed=True, browser_print_installed=True, protected_tables=len(cols), existing_rows_and_columns_exact=True,
    company_smoke=json.loads(result.stdout.split('PP1_SMOKE ', 1)[1].splitlines()[0]),
    no_http=True, cron_disabled=True, no_main_filestore_mount=True))
b.run(['docker', 'exec', b.DB, 'dropdb', '-U', 'odoo', database], capture_output=True)
print('REHEARSAL_PASS', candidate['commit'], len(cols), flush=True)
