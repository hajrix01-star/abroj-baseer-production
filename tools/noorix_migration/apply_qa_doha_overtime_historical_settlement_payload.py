"""Thin QA Odoo-shell entry point for frozen Doha historical overtime evidence."""

import json

from odoo.addons.baseer_noorix_migration.doha_overtime_writer import apply_month


if "env" not in globals():
    raise RuntimeError("Run this entry point through the approved QA Odoo shell")

try:
    result = apply_month(env)
    env.cr.commit()
except Exception:
    env.cr.rollback()
    raise

print(json.dumps(result, ensure_ascii=False, sort_keys=True))
