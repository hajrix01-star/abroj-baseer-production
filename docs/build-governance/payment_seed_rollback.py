"""Restore the exact stopped-MAIN preseed backup after the preservation guard."""
import json
import shutil
import subprocess
import environment_backups as b

out = b.ROOT / 'docs/releases/2026-09-09-pos-payment-seed'
info = json.loads((out / 'main-backup.json').read_text())
backup = b.Path(info['directory'])
assert info['database'] == b.MAIN and info['coherent_no_clients']
assert not b.inspect(b.MAIN_CONTAINER)['State']['Running']
assert b.sql('postgres', "SELECT count(*) FROM pg_stat_activity WHERE datname='baseer_dev'") == '0'
assert b.sha(backup / 'database.dump') == info['files']['database.dump']['sha256']
with (backup / 'database.dump').open('rb') as source, (out / 'rollback.log').open('wb') as log:
    b.run(['docker','exec','-i',b.DB,'pg_restore','-U','odoo','--clean','--if-exists',
        '--exit-on-error','--no-owner','-d',b.MAIN],stdin=source,stdout=log,stderr=log)
assert b.signatures(b.MAIN) == json.loads((backup / 'rows.json').read_text()), 'Restore differs'
# Restore the original filestore as well; no clients have run since the snapshot.
image = b.inspect(b.MAIN_CONTAINER)['Config']['Image']
with (backup / 'filestore.tar.gz').open('rb') as source:
    b.run(['docker','run','--rm','-i','--network','none','--volumes-from',b.MAIN_CONTAINER,
        '--entrypoint','tar',image,'-xzf','-','-C','/var/lib/odoo/filestore'],stdin=source,stdout=subprocess.DEVNULL)
for name in ('compose.yaml','compose.main-release.yaml'):
    shutil.copy2(b.ROOT / '.local-backups/pos-payment-seed-20260909' / (name + '.before'), b.ROOT / name)
b.save(out / 'rollback.json', {'restored':True,'all_tables_exact':True,'tables':info['table_count'],
    'filestore_restored':True,'original_candidate':'96dd7960f30a0863772139423e037e127faf3c52'})
b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','up','-d','--no-deps','odoo'],capture_output=True)
print('ORIGINAL_RESTORED_ALL_TABLES_EXACT',flush=True)
