"""Fixed negative seam after dependency modules have loaded/committed."""
import os


def post_init_hook(env):
    if os.environ.get('BWORK_CANONICAL_SYNTHETIC') != '1':
        raise RuntimeError('BWORK_CANONICAL_FAILURE_FIXTURE_FORBIDDEN')
    if not env.cr.dbname.startswith('bwork_canonical_ci_'):
        raise RuntimeError('BWORK_CANONICAL_FAILURE_DATABASE_FORBIDDEN')
    # Prove the intended late seam was reached; a dependency/registry failure is
    # not accepted as the expected negative test. The driver independently checks
    # the committed ledger/schema using a new PostgreSQL connection afterwards.
    if 'baseer.bwork.service' not in env or 'baseer.bchat.service' in env:
        raise AssertionError('Canonical registry was not loaded before failure.')
    core = env['ir.module.module'].sudo().search([('name', '=', 'baseer_bwork')])
    admin = env['ir.module.module'].sudo().search([('name', '=', 'baseer_bwork_admin')])
    if core.state != 'installed' or admin.state != 'installed':
        raise AssertionError('Canonical dependencies did not finish before failure.')
    raise RuntimeError('BWORK_CANONICAL_EXPECTED_LATE_MODULE_FAILURE')
