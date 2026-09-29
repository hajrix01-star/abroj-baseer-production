"""Apply one approved Doha Consumer purchase-history month in QA only."""
import importlib.util
import json
import os

PAYLOAD_PATH = "/mnt/noorix-payload/runs/20260913-doha-consumer-purchases-qa-1/doha-consumer-purchase-payload.json"
EXPECTED_SHA256 = "7d784330b6b9caed701d1836854b28e467562dccafa7031736d1d432ac4954e6"
MONTH = os.environ.get("NOORIX_GENERAL_PURCHASE_MONTH", "").strip()
if "env" not in globals(): raise RuntimeError("QA Odoo shell required")
if MONTH not in {"2026-04","2026-05","2026-06","2026-07","2026-08","2026-09"}: raise RuntimeError("unapproved Doha month")
spec=importlib.util.spec_from_file_location("doha_gp_writer","/mnt/baseer-addons/baseer_noorix_migration/general_purchase_writer.py")
writer=importlib.util.module_from_spec(spec); spec.loader.exec_module(writer)
try:
    result=writer.apply_month(env,PAYLOAD_PATH,EXPECTED_SHA256,MONTH); env.cr.commit()
except Exception:
    env.cr.rollback(); raise
print(json.dumps(result,ensure_ascii=False,sort_keys=True))
