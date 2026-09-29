"""Restore pre-upgrade backup only to a new isolated database and compare old columns."""
import json
import subprocess
from pathlib import Path
import environment_backups as b
import ic2_release as r

RESTORE = 'baseer_ic2_preservation_20260910'
backup = r.read_json(r.OUT / 'main-backup.json')
directory = Path(backup['directory'])
assert b.sha(directory / 'database.dump') == backup['files']['database.dump']['sha256']
assert b.inspect(b.MAIN_CONTAINER)['State']['Running'] is False
exists = b.sql('postgres', "SELECT count(*) FROM pg_database WHERE datname='" + RESTORE + "'")
if exists == '0':
    metadata = r.read_json(directory / 'database-metadata.json')
    b.run(['docker', 'exec', b.DB, 'createdb', '-U', 'odoo', '-O', 'odoo', '--template=template0',
           '--lc-collate=' + metadata['datcollate'], '--lc-ctype=' + metadata['datctype'], RESTORE], capture_output=True)
    with (directory / 'database.dump').open('rb') as handle:
        b.run(['docker', 'exec', '-i', b.DB, 'pg_restore', '-U', 'odoo', '--no-owner', '--exit-on-error', '-d', RESTORE],
              stdin=handle, capture_output=True)
columns = r.read_json(r.OUT / 'protected-columns.json')
before = {row['name']: row for row in r.read_json(r.OUT / 'protected-before.json')}
after = {row['name']: row for row in r.read_json(r.OUT / 'protected-after.json')}
differences = []
for table in before:
    if before[table] == after[table]:
        continue
    fields = ','.join('"' + name + '"' for name in columns[table])
    query = 'SELECT coalesce(json_agg(t),\'[]\'::json) FROM (SELECT ' + fields + ' FROM "' + table + '")t'
    rows_old = {row['id']: row for row in json.loads(b.sql(RESTORE, query))}
    rows_new = {row['id']: row for row in json.loads(b.sql(b.MAIN, query))}
    assert set(rows_old) == set(rows_new), table
    for row_id, row in rows_old.items():
        changes = {key: {'before': value, 'after': rows_new[row_id][key]}
                   for key, value in row.items() if value != rows_new[row_id][key]}
        if changes:
            differences.append({'table': table, 'id': row_id, 'changes': changes})
b.save(r.OUT / 'preservation-row-diff.json', differences)
print(json.dumps({'restore_database': RESTORE, 'changed_rows': len(differences),
    'fields': {table: sorted({field for item in differences if item['table'] == table for field in item['changes']})
               for table in sorted({item['table'] for item in differences})}}, indent=2))
