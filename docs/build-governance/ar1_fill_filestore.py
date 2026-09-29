"""Copy immutable MAIN attachment blobs into the isolated QA filestore only."""
import environment_backups as b
archive = b.ROOT / '.local-backups/access-roles-20260910/qa-filestore.tar'
target = '/var/lib/odoo/filestore/baseer_ar1_roles_20260910'
with archive.open('wb') as output:
    b.run(['docker', 'exec', b.MAIN_CONTAINER, 'tar', '-C', '/var/lib/odoo/filestore/baseer_dev', '-cf', '-', '.'], stdout=output)
b.run(['docker', 'exec', 'baseer_odoo_dev-roles_qa-1', 'mkdir', '-p', target], capture_output=True)
with archive.open('rb') as source:
    b.run(['docker', 'exec', '-i', 'baseer_odoo_dev-roles_qa-1', 'tar', '-C', target, '-xf', '-'], stdin=source, capture_output=True)
print('QA_FILESTORE_READY')
