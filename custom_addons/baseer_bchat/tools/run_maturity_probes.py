"""Odoo-shell stdin only; real two-connection probes in a synthetic database."""
import json

from odoo import Command
from odoo.addons.baseer_bchat.tests import permission_hint_concurrency_probe
from odoo.addons.baseer_bchat.tests import social_preferences_concurrency_probe


def run_probes(test_env):
    if test_env.cr.dbname != 'bchat_maturity_test_20261017':
        raise RuntimeError('Refusing probe role/fixtures outside the exact isolated test database')
    # Only the base-user row in this freshly initialized empty test database.
    admin = test_env.ref('base.user_admin')
    admin.write({'group_ids': [Command.link(test_env.ref('baseer_bchat.group_bchat_manager').id)]})
    test_env.cr.commit()
    permissions = permission_hint_concurrency_probe.run(test_env)
    social = social_preferences_concurrency_probe.run(test_env)
    print('BCHAT_REAL_PROBES=' + json.dumps({
        'database': test_env.cr.dbname, 'permissions': permissions, 'social': social,
    }, sort_keys=True, default=str), flush=True)


if 'env' not in globals():
    raise RuntimeError('Run this file through the isolated Odoo shell only')
run_probes(env)
