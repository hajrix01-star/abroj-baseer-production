"""Apply exactly one frozen SHAMI TAX purchase month in the isolated QA DB."""

from __future__ import annotations

import importlib.util
import json
import os


PAYLOAD_PATH = "/mnt/noorix-payload/runs/20260913-shami-tax-purchases-qa-1/shami-tax-purchase-payload.json"
EXPECTED_SHA256 = "ebfcb6c334a9abde3b849a57f105992297566a5ec528f030917dcf2735c0f498"
WRITER_PATH = "/mnt/baseer-addons/baseer_noorix_migration/general_purchase_writer.py"
MONTH = os.environ.get("NOORIX_GENERAL_PURCHASE_MONTH", "").strip()


if "env" not in globals():
    raise RuntimeError("Run this entrypoint through the approved QA Odoo shell")
if MONTH not in {"2026-04", "2026-06", "2026-07"}:
    raise RuntimeError("NOORIX_GENERAL_PURCHASE_MONTH must be one approved SHAMI TAX month")

spec = importlib.util.spec_from_file_location("shami_tax_general_purchase_writer", WRITER_PATH)
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)

try:
    result = writer.apply_month(env, PAYLOAD_PATH, EXPECTED_SHA256, MONTH)
    env.cr.commit()
except Exception:
    env.cr.rollback()
    raise

print(json.dumps(result, ensure_ascii=False, sort_keys=True))
