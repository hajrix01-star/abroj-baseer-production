"""Thin Odoo-shell entrypoint for the import-safe Karak payroll writer."""

import json

from odoo.addons.baseer_noorix_migration.karak_payroll_writer import apply_settlement


if "env" not in globals():
    raise RuntimeError("Run this entrypoint through the approved QA Odoo shell")

try:
    result = apply_settlement(env)
    env.cr.commit()
except Exception:
    env.cr.rollback()
    raise

print(json.dumps(result, ensure_ascii=False, sort_keys=True))
