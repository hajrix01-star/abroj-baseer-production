"""Approved QA-shell entry point for the two frozen supplier provenance links."""
import json
import os
from odoo.addons.baseer_noorix_migration.almoallem_supplier_provenance_writer import apply

if "env" not in globals():
    raise RuntimeError("Run through approved QA Odoo shell")
expected = os.environ.get("NOORIX_ALMOALLEM_SUPPLIER_PROVENANCE_SHA256", "")
try:
    result = apply(env, expected_sha256=expected)
    env.cr.commit()
except Exception:
    env.cr.rollback()
    raise
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
