"""Freeze and activate QA only. Original source and database are never mutated."""
import ast
import hashlib
import json
import shutil
import sys
from pathlib import Path
import runtime as r

PREVIOUS = r.ROOT / '.local-backups/financial-register-sales-20260910/candidate'
SOURCE = r.BACK / 'candidate-r2'
ALLOWED = {
    'custom_addons/baseer_cash_categories/models/cash_categories.py',
    'custom_addons/baseer_pos_summary/models/cash_report.py',
    'custom_addons/baseer_financial_register/models/platform.py',
    *('custom_addons/' + m + '/__manifest__.py' for m in r.MODULES),
}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inventory(folder):
    return {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts and p.suffix != '.pyc'}

def allowed_upgrade_metadata(before, after, database, original_rows=None):
    assert {x['name'] for x in before} == {x['name'] for x in after}
    old = {x['name']: x for x in before}
    changed = [x['name'] for x in after if x != old[x['name']]]
    assert set(changed).issubset({'res_groups', 'res_partner'}), changed
    differences = {}
    for table in changed:
        a = original_rows[table] if original_rows else json.loads(r.sql(r.ACTIVE, 'SELECT json_agg(t ORDER BY id) FROM ' + table + ' t'))
        b = json.loads(r.sql(database, 'SELECT json_agg(t ORDER BY id) FROM ' + table + ' t'))
        a, b = {x['id']: x for x in a}, {x['id']: x for x in b}
        assert a.keys() == b.keys()
        rows = []
        for ident in a:
            delta = {key: {'before': a[ident].get(key), 'after': b[ident].get(key)} for key in set(a[ident]) | set(b[ident]) if a[ident].get(key) != b[ident].get(key)}
            if delta:
                assert ident in ({92, 93, 94} if table == 'res_groups' else {29, 30, 31})
                assert set(delta).issubset({'write_date', 'write_uid'} if table == 'res_partner' and ident == 29 else {'write_date'})
                if 'write_uid' in delta:
                    assert delta['write_uid'] == {'before': 5, 'after': 1}
                rows.append({'id': ident, 'fields': delta})
        differences[table] = rows
    return {'tables': len(before), 'all_exact': before == after, 'all_business_exact': True, 'changed_tables': changed, 'technical_metadata_only': differences}

def security_projection(database):
    tables = r.sql(database, "SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'res_groups%' OR tablename LIKE 'res_users%' OR tablename LIKE 'ir_rule%' OR tablename='ir_model_access' OR tablename LIKE '%group%rel') ORDER BY tablename").splitlines()
    parts = ["SELECT '" + table + "' AS name,count(*) AS rows,md5(coalesce(string_agg(h,'' ORDER BY h),'')) AS hash FROM (SELECT md5((to_jsonb(t)-'write_date'-'write_uid')::text) h FROM \"" + table + '\" t)s' for table in tables]
    return json.loads(r.sql(database, 'SELECT json_agg(x ORDER BY name) FROM (' + ' UNION ALL '.join(parts) + ')x'))

def freeze():
    old = json.loads((r.ROOT / 'docs/releases/2026-09-10-financial-register-sales/candidate.json').read_text(encoding='utf8'))
    files = inventory(PREVIOUS)
    assert files == old['files']
    observed = json.loads((r.AUDIT / 'runtime/dataset-inventory.json').read_text(encoding='utf8'))['custom_runtime_source']
    for module, entry in observed.items():
        hashes = inventory(PREVIOUS / 'custom_addons' / module)
        assert len(hashes) == entry['files']
        assert hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest() == entry['sha256'], module
    candidate = dict(files)
    for module in r.MODULES:
        for name, sha in inventory(r.ROOT / 'custom_addons' / module).items():
            candidate['custom_addons/' + module + '/' + name] = sha
    changed = sorted(name for name in candidate if candidate[name] != files.get(name))
    assert set(changed) == ALLOWED, changed
    assert not SOURCE.exists(), 'Frozen candidate is immutable; choose a new revision if needed'
    for name, sha in candidate.items():
        path = r.ROOT / name if name in changed else PREVIOUS / name
        target = SOURCE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        assert digest(target) == sha
    versions = {m: ast.literal_eval((SOURCE / 'custom_addons' / m / '__manifest__.py').read_text(encoding='utf8'))['version'] for m in r.MODULES}
    identifier = hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
    r.save(r.HERE / 'candidate.json', {'candidate_sha256': identifier, 'parent': old['commit'], 'image': old['image'], 'source_directory': str(SOURCE), 'files': candidate, 'changed_files': changed, 'versions': versions, 'baseline_19_runtime_modules_identical': True})
    print('FROZEN', identifier, len(candidate), 'files', len(changed), 'changed', flush=True)

def upgrade_clone():
    candidate = json.loads((r.HERE / 'candidate.json').read_text(encoding='utf8'))
    staged = json.loads((r.HERE / 'staged-source.json').read_text(encoding='utf8'))
    assert staged['all_exact'] and staged['candidate_sha256'] == candidate['candidate_sha256']
    before = r.signatures(r.CLONE)
    r.save(r.HERE / 'clone-before-upgrade.json', before)
    with (r.HERE / 'clone-upgrade.log').open('wb') as log:
        r.run(['docker', 'exec', r.QA, '/entrypoint.sh', 'odoo', '--config=/etc/odoo/odoo.local.conf', '--addons-path=' + r.ADDONS, '--database=' + r.CLONE, '--update=' + ','.join(r.MODULES), '--stop-after-init', '--no-http', '--max-cron-threads=0'], stdout=log, stderr=log)
    after = r.signatures(r.CLONE)
    r.save(r.HERE / 'clone-after-upgrade.json', after)
    proof = allowed_upgrade_metadata(before, after, r.CLONE)
    r.save(r.HERE / 'clone-upgrade-preservation.json', proof)
    print('CLONE_UPGRADED', proof['changed_tables'], flush=True)

def deploy():
    candidate = json.loads((r.HERE / 'candidate.json').read_text(encoding='utf8'))
    assert inventory(SOURCE) == candidate['files']
    assert json.loads((r.HERE / 'clone-upgrade-preservation.json').read_text(encoding='utf8'))['all_business_exact']
    review = (r.HERE / 'PREDEPLOY-GO.md').read_text(encoding='utf8')
    lines = {line.strip() for line in review.splitlines()}
    assert 'Decision: GO' in lines and 'Candidate: ' + candidate['candidate_sha256'] in lines
    current = json.loads(r.run(['docker', 'inspect', r.QA], capture_output=True, text=True).stdout)[0]
    assert current['HostConfig']['PortBindings']['8069/tcp'][0]['HostPort'] == '18075'
    assert '--database=' + r.ACTIVE in current['Config']['Cmd']
    data_volume = next(m['Name'] for m in current['Mounts'] if m['Destination'] == '/var/lib/odoo')
    before = r.signatures(r.ACTIVE)
    assert before == json.loads((r.HERE / 'qa-before.json').read_text(encoding='utf8'))
    metadata_before = {table: json.loads(r.sql(r.ACTIVE, 'SELECT json_agg(t ORDER BY id) FROM ' + table + ' t')) for table in ('res_groups', 'res_partner')}
    security_before = security_projection(r.ACTIVE)
    compose = r.ROOT / 'compose.ic1-qa.yaml'
    shutil.copy2(compose, r.BACK / 'compose.ic1-qa.yaml.before')
    r.run(['docker', 'exec', r.QA, 'tar', '-czf', '/tmp/sim90-repair-before-filestore.tar.gz', '-C', '/var/lib/odoo/filestore', r.ACTIVE], capture_output=True)
    r.run(['docker', 'cp', r.QA + ':/tmp/sim90-repair-before-filestore.tar.gz', str(r.BACK / 'same-data-before-filestore.tar.gz')], capture_output=True)
    r.run(['docker', 'stop', '--time', '30', r.QA], capture_output=True)
    assert r.sql('postgres', "SELECT count(*) FROM pg_stat_activity WHERE datname='" + r.ACTIVE + "'") == '0'
    old = compose.read_text(encoding='utf8')
    new = old.replace('/mnt/ic1-addons,', '').replace('financial-register-cash-20260910/candidate/', '90day-repair-20260910/candidate-r2/')
    new = '\n'.join(line for line in new.splitlines() if ':/mnt/ic1-addons/' not in line) + '\n'
    new = new.replace('      - ./docs/build-governance:/mnt/qa-evidence', '      - ./docs/build-governance:/mnt/qa-evidence\n      - qa_repair_data:/var/lib/odoo')
    new += 'volumes:\n  qa_repair_data:\n    external: true\n    name: ' + data_volume + '\n'
    assert '/custom_addons/baseer_' not in new and '/mnt/ic1-addons' not in new
    compose.write_text(new, encoding='utf8')
    addons = r.ADDONS.replace('/tmp/repair-addons,', '').replace('/mnt/ic1-addons,', '')
    command = ['docker', 'compose', '-p', 'baseer_odoo_dev', '-f', 'compose.yaml', '-f', 'compose.ic1-qa.yaml']
    with (r.HERE / 'qa-upgrade.log').open('wb') as log:
        r.run(command + ['run', '--rm', '--no-deps', '-T', 'ic1_qa', 'odoo', '--config=/etc/odoo/odoo.local.conf', '--addons-path=' + addons, '--database=' + r.ACTIVE, '--update=' + ','.join(r.MODULES), '--stop-after-init', '--no-http', '--max-cron-threads=0'], cwd=r.ROOT, stdout=log, stderr=log)
    after = r.signatures(r.ACTIVE)
    r.save(r.HERE / 'qa-after-upgrade.json', after)
    proof = allowed_upgrade_metadata(before, after, r.ACTIVE, metadata_before)
    r.save(r.HERE / 'qa-upgrade-preservation.json', proof)
    security_after = security_projection(r.ACTIVE)
    assert security_after == security_before
    r.save(r.HERE / 'qa-security-preservation.json', {'all_exact': True, 'tables': len(security_after), 'before': security_before, 'after': security_after})
    main_after = r.signatures('baseer_dev')
    r.save(r.HERE / 'main-after.json', main_after)
    assert main_after == json.loads((r.HERE / 'main-before.json').read_text(encoding='utf8'))
    versions = json.loads(r.sql(r.ACTIVE, "SELECT json_object_agg(name,latest_version) FROM ir_module_module WHERE name IN ('" + "','".join(r.MODULES) + "')"))
    assert versions == candidate['versions']
    r.run(command + ['up', '-d', '--no-deps', 'ic1_qa'], cwd=r.ROOT, capture_output=True)
    r.save(r.HERE / 'deployment.json', {'candidate_sha256': candidate['candidate_sha256'], 'database': r.ACTIVE, 'port': 18075, 'qa_business_tables_exact': len(after), 'qa_technical_metadata_changes': proof['technical_metadata_only'], 'main_tables_exact': len(main_after), 'versions': versions, 'filestore_volume': data_volume, 'github_changed': False, 'main_source_changed': False})
    print('QA_DEPLOYED', candidate['candidate_sha256'], 'TABLES_EXACT', len(after), flush=True)

if __name__ == '__main__':
    {'freeze': freeze, 'upgrade-clone': upgrade_clone, 'deploy': deploy}[sys.argv[1]]()
