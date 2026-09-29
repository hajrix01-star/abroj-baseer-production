"""Freeze a PO-only R2 and restore exact pre-upgrade labels/metadata atomically.

No second module upgrade: R2 removes generated record translations only; all
functional code, schema, versions, views and static UI terms remain unchanged.
"""
import argparse
import importlib
import json
import shutil
import urllib.request
import time
from pathlib import Path
import environment_backups as b
import ic2_release as r

FAILED_OUT = r.OUT
FAILED_FOLDER = r.NEW_FOLDER
r.NEW_RELEASE += '-r2'
r.NEW_FOLDER += '-r2'
r.OUT = b.ROOT / 'docs/releases' / r.NEW_RELEASE
r.BACK = b.ROOT / '.local-backups' / r.NEW_FOLDER
r.SOURCE = r.BACK / 'candidate'
r.SUPPORTING_EVIDENCE += ('ic2_recovery.py', 'ic2_recovery_github.py',
                          'ic2-runtime-translation-filter.json', 'ic2-static-translation-equality.json')
FIELDS = {'account_account': {'name'}, 'account_journal': {'name'},
          'baseer_pos_payment_category': {'name'}, 'pos_payment_method': {'name'},
          'res_partner': {'write_date', 'write_uid'}}

def literal(value):
    return "'" + value.replace("'", "''") + "'"

def projection_sql(columns):
    parts = []
    for table, names in sorted(columns.items()):
        columns_sql = ','.join('"' + name + '"' for name in names)
        parts.append("SELECT '%s' name,count(*) rows,md5(coalesce(string_agg(h,'' ORDER BY h),'')) hash "
                     'FROM (SELECT md5(row_to_json(t)::text) h FROM (SELECT %s FROM "%s")t)s'
                     % (table, columns_sql, table))
    return 'SELECT jsonb_agg(t ORDER BY name) FROM (' + ' UNION ALL '.join(parts) + ')t'

def _recover():
    candidate = r.verify_candidate()
    r.review_go(r.OUT / 'PREDEPLOY-GO.md', candidate['commit'])
    r.review_go(r.OUT / 'RECOVERY-GO.md', candidate['commit'])
    failed = r.read_json(FAILED_OUT / 'candidate.json')
    changed = {key for key, value in candidate['files'].items() if failed['files'].get(key) != value}
    r.require(set(candidate['files']) == set(failed['files']) and changed and changed.issubset({
        'custom_addons/baseer_financial_correction/i18n/ar_001.po',
        'custom_addons/baseer_pos_summary/i18n/ar.po'}), 'R2 must differ only in the reviewed PO files')
    r.require(not b.inspect(b.MAIN_CONTAINER)['State']['Running'], 'MAIN must remain stopped')
    r.require(not (r.OUT / 'main-preservation.json').exists(), 'Do not repeat completed recovery')
    columns = r.read_json(FAILED_OUT / 'protected-columns.json')
    expected = r.read_json(FAILED_OUT / 'protected-before.json')
    failed_projection = r.read_json(FAILED_OUT / 'protected-after.json')
    r.require(r.projection(columns) == failed_projection, 'Failed-upgrade data changed; stop')
    diff = r.read_json(FAILED_OUT / 'preservation-row-diff.json')
    r.require(len(diff) == 47 and all(set(row['changes']) == FIELDS[row['table']] for row in diff), 'Unexpected restoration scope')
    backup = r.read_json(FAILED_OUT / 'main-backup.json')
    r.require(backup['coherent_no_clients'] is True and set(columns) == r.expected_protected_tables(), 'Expected coherent backup and all 372 original tables')
    r.require(r.read_sql("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()") == '0', 'Unexpected MAIN database clients')
    directory = Path(backup['directory'])
    r.require(b.sha(directory / 'database.dump') == backup['files']['database.dump']['sha256'], 'Backup hash differs')
    restore = 'baseer_ic2_preservation_20260910'
    r.require(json.loads(b.sql(restore, projection_sql(columns))) == expected, 'Restored pre-upgrade data differs')
    r.require(r.security_memberships() == r.read_json(FAILED_OUT / 'security-memberships-before.json'), 'Security memberships changed')
    r.require(r.role_assignments() == r.read_json(FAILED_OUT / 'role-assignments-before.json'), 'Roles changed')
    versions = r.read_json(FAILED_OUT / 'installed-versions-before.json')
    r.verify_preserved_versions(versions)
    after_columns = r.columns()
    r.require(set(after_columns) - set(columns) == r.NEW_TABLES, 'Unexpected new tables')
    for table, names in columns.items():
        added = r.ADDED_COLUMNS.get(table, set())
        actual = after_columns.get(table, [])
        r.require([name for name in actual if name not in added] == names and set(actual) - set(names) == added, 'Unexpected schema change: ' + table)
    r.require(r.read_sql("SELECT count(*) FROM baseer_financial_correction_audit WHERE operation IS DISTINCT FROM 'edit'") == '0', 'Unexpected audit defaults')
    r.require(r.read_sql("SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')") == '0', 'Pending modules')
    r.require(r.read_sql('SELECT count(*) FROM baseer_purchase_batch_line WHERE baseer_cancelled IS TRUE OR baseer_cancel_reason IS NOT NULL OR baseer_cancelled_by_id IS NOT NULL OR baseer_cancelled_at IS NOT NULL') == '0', 'Unexpected lifecycle mutations')
    old_prefix = './.local-backups/' + FAILED_FOLDER + '/candidate/'
    new_prefix = './.local-backups/' + r.NEW_FOLDER + '/candidate/'
    compose = {name: (b.ROOT / name).read_text(encoding='utf8') for name in ('compose.yaml', 'compose.main-release.yaml')}
    r.require(all(content.count(old_prefix) == 3 for content in compose.values()), 'Failed candidate compose differs')
    sql = ['BEGIN ISOLATION LEVEL SERIALIZABLE;', 'LOCK TABLE ' + ','.join('"' + name + '"' for name in columns) + ' IN SHARE ROW EXCLUSIVE MODE;']
    sql.append('DO $restore$ DECLARE observed jsonb; BEGIN')
    for row in diff:
        table, row_id, changes = row['table'], row['id'], row['changes']
        r.require(isinstance(row_id, int), 'Invalid row identity')
        names = sorted(changes)
        old = {name: changes[name]['before'] for name in names}
        new = {name: changes[name]['after'] for name in names}
        selected = ','.join('"' + name + '"' for name in names)
        # Also compare each claimed original value against the independently restored dump.
        source = json.loads(b.sql(restore, 'SELECT row_to_json(t) FROM (SELECT ' + selected + ' FROM "' + table + '" WHERE id=' + str(row_id) + ')t'))
        r.require(source == old, 'Restoration values differ from coherent backup')
        sql.append('SELECT to_jsonb(t) INTO observed FROM (SELECT ' + selected + ' FROM "' + table + '" WHERE id=' + str(row_id) + ')t;')
        sql.append('IF observed IS DISTINCT FROM ' + literal(json.dumps(new)) + "::jsonb THEN RAISE EXCEPTION 'Unexpected current restoration value'; END IF;")
        sql.append('UPDATE "' + table + '" SET (' + selected + ')=(SELECT ' + selected +
                   ' FROM jsonb_populate_record(NULL::"' + table + '",' + literal(json.dumps(old)) + '::jsonb)) WHERE id=' + str(row_id) + ';')
    sql.append('SELECT result INTO observed FROM (' + projection_sql(columns).replace('SELECT jsonb_agg(t ORDER BY name)', 'SELECT jsonb_agg(t ORDER BY name) AS result', 1) + ') verified;')
    sql.append('IF observed IS DISTINCT FROM ' + literal(json.dumps(expected)) + "::jsonb THEN RAISE EXCEPTION 'Full original projection differs'; END IF;")
    sql.extend(['END $restore$;', 'COMMIT;'])
    b.run(['docker', 'exec', '-i', b.DB, 'psql', '-U', 'odoo', '-d', b.MAIN, '-q', '-v', 'ON_ERROR_STOP=1'],
          input='\n'.join(sql), text=True, encoding='utf8', capture_output=True)
    after = r.projection(columns)
    r.require(after == expected, 'Post-restore old columns differ')
    for name in ('main-backup.json', 'installed-versions-before.json', 'protected-before.json', 'protected-columns.json',
                 'security-memberships-before.json', 'role-assignments-before.json', 'preservation-row-diff.json'):
        shutil.copy2(FAILED_OUT / name, r.OUT / name)
    b.save(r.OUT / 'protected-after.json', after)
    b.save(r.OUT / 'security-memberships-after.json', r.security_memberships())
    b.save(r.OUT / 'role-assignments-after.json', r.role_assignments())
    r.require(r.security_memberships() == r.read_json(r.OUT / 'security-memberships-before.json'), 'Post-restore security changed')
    r.require(r.role_assignments() == r.read_json(r.OUT / 'role-assignments-before.json'), 'Post-restore roles changed')
    b.save(r.OUT / 'main-preservation.json', dict(protected_tables=len(columns), existing_columns_exact=True,
        existing_rows_exact=True, candidate=candidate['commit'], existing_user_memberships_exact=True,
        existing_module_versions_exact=True, existing_user_presets_exact=True, no_automatic_role_assignments=True,
        existing_audit_preserved=True, new_lifecycle_defaults_exact=True, restored_rows=47,
        failed_candidate=failed['commit'], no_second_module_upgrade=True))
    for name, content in compose.items():
        shutil.copy2(b.ROOT / name, r.BACK / (name + '.before'))
        (b.ROOT / name).write_text(content.replace(old_prefix, new_prefix), encoding='utf8')
    helper = b.ROOT / 'docs/build-governance/environment_backups.py'
    helper_text = helper.read_text(encoding='utf8')
    r.require(r.OLD_RELEASE in helper_text and r.OLD_FOLDER in helper_text, 'Original backup mapping differs')
    shutil.copy2(helper, r.BACK / 'environment_backups.py.before')
    helper.write_text(helper_text.replace(r.OLD_RELEASE, r.NEW_RELEASE).replace(r.OLD_FOLDER, r.NEW_FOLDER), encoding='utf8')
    importlib.reload(b)
    b.save(r.OUT / 'post-release-backup.json', b.backup(b.MAIN))
    b.run(['docker', 'compose', '-p', 'baseer_odoo_dev', '-f', 'compose.yaml', 'up', '-d', '--no-deps', 'odoo'], cwd=b.ROOT, capture_output=True)
    for _ in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18069/web/login', timeout=3) as response:
                if response.status == 200:
                    break
        except OSError:
            pass
        time.sleep(2)
    r.verify_runtime()
    print('RECOVERED AND PUBLISHED', candidate['commit'])

def recover():
    b.BACK.mkdir(parents=True, exist_ok=True)
    lock = b.BACK / 'maintenance.lock'
    with lock.open('x', encoding='utf8') as handle:
        handle.write('IC2 R2 exact metadata restoration')
    try:
        _recover()
    finally:
        lock.unlink()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'recover', 'verify-runtime'))
    command = parser.parse_args().command
    {'freeze': r.freeze, 'recover': recover, 'verify-runtime': r.verify_runtime}[command]()
