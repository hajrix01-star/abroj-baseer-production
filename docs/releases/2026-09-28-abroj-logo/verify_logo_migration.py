"""Run in an isolated QA Odoo shell; every write is rolled back."""
import base64
import hashlib
import runpy

EXPECTED = 'a7356f89ccf9040d20f75f8be108d711192d0e14cfe7e76efa55e12aa76864ab'
assert env.cr.dbname == 'abroj_preview', 'QA-only verifier'
website = env.ref('website.default_website')
others = env['website'].search([('id', '!=', website.id)])
others_before = others.read(['logo', 'write_date'])
marker = env['ir.model.data'].search([
    ('module', '=', 'website'), ('name', '=', 'default_website')
])
try:
    marker.write({'noupdate': True})
    website.write({'logo': False})
    migrate = runpy.run_path(
        '/mnt/logo-candidate/abroj_website/migrations/19.0.1.5.2/post-migration.py'
    )['migrate']
    migrate(env.cr, '19.0.1.5.1')
    env.invalidate_all()
    actual = hashlib.sha256(base64.b64decode(website.logo)).hexdigest()
    assert actual == EXPECTED, actual
    assert marker.noupdate is True
    assert others.read(['logo', 'write_date']) == others_before
    migrate(env.cr, '19.0.1.5.1')
    assert hashlib.sha256(base64.b64decode(website.logo)).hexdigest() == EXPECTED
    print('PASS: native logo hash, protected XML-ID, other websites unchanged, idempotent')
finally:
    env.cr.rollback()
    print('QA transaction rolled back')
