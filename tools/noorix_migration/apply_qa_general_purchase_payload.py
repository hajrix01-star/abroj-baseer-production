"""Approved QA-only Odoo-shell entrypoint for general historical purchases."""

import json

from odoo.addons.baseer_noorix_migration.general_purchase_writer import apply_month


if "env" not in globals():
    raise RuntimeError("Run this entrypoint through the approved QA Odoo shell")

try:
    result = apply_month(env)
    env.cr.commit()
except Exception:
    env.cr.rollback()
    raise

print(json.dumps(result, ensure_ascii=False, sort_keys=True))
