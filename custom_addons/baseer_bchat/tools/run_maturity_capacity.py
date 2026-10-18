"""Odoo-shell stdin entrypoint; external runner owns the five-minute hard kill."""
import json

from odoo.addons.baseer_bchat.tests.maturity_capacity_probe import run


if 'env' not in globals():
    raise RuntimeError('Run the bounded capacity sample through isolated Odoo shell only')


def emit_capacity_sample(sample):
    print('BCHAT_MATURITY_CAPACITY_SAMPLE=' + json.dumps(sample, sort_keys=True), flush=True)


evidence = run(env, emit=emit_capacity_sample)
print('BCHAT_MATURITY_CAPACITY=' + json.dumps(evidence, sort_keys=True), flush=True)
if evidence['status'] != 'ok':
    raise RuntimeError('The bounded capacity sample failed; inspect its recorded evidence')
