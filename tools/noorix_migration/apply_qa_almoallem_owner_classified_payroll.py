"""QA Odoo-shell entry point for one frozen Al Moallem payroll month."""
import json
import os
from odoo.addons.baseer_noorix_migration.almoallem_historical_payroll_writer import apply_month

if "env" not in globals():
    raise RuntimeError("Run through approved QA Odoo shell")
month = os.environ.get("NOORIX_ALMOALLEM_PAYROLL_MONTH", "")
expected = os.environ.get("NOORIX_ALMOALLEM_PAYROLL_PAYLOAD_SHA256", "")
try:
    result = apply_month(env, expected_sha256=expected, month=month)
    env.cr.commit()
except Exception:
    env.cr.rollback()
    raise
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
