"""Approved QA shell entrypoint for the one Al Moallem split-paid rent bill."""

import json

from odoo.addons.baseer_noorix_migration.almoallem_rent_split_writer import apply


if "env" not in globals():
    raise RuntimeError("Run through the isolated QA Odoo shell only")

try:
    result = apply(env)
    env.cr.commit()
except Exception:
    env.cr.rollback()
    raise

print(json.dumps(result, ensure_ascii=False, sort_keys=True))
