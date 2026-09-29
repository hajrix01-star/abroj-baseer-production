"""Offline, source-only purchase replay contract check.

Run from the repository root (or an Odoo container mount) before any Odoo
shell writer invocation::

    python rehearsal_addons/baseer_noorix_rehearsal_replay/purchase_dry_run.py \
      --manifest /mnt/noorix-source/source-manifest.json

The command never imports Odoo and never opens PostgreSQL.  It validates the
pinned archive/manifest identity, all 2,962 document identities, the exact
vendor-bill/payment/reconciliation source scopes, purchase VAT policy, source
math, price precision, category decisions, monthly totals, and the one
two-payment settlement.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from purchase_contract import build_purchase_contract, load_pinned_manifest


def main():
    parser = argparse.ArgumentParser(description="Validate Noorix purchase replay input without Odoo or database access")
    parser.add_argument("--manifest", required=True, help="Pinned source-manifest.json path")
    args = parser.parse_args()
    contract = build_purchase_contract(load_pinned_manifest(args.manifest))
    waves = Counter("%s:%s" % key for key in contract["by_wave"])
    print(json.dumps({
        "status": "ok",
        "vendor_bills": contract["invoice_count"],
        "payments": contract["payment_count"],
        "reconciliation_scopes": contract["payment_count"],
        "company_month_waves": len(waves),
        "generic_company_month_waves": contract["generic_wave_count"],
        "vat_policy_counts": contract["vat_policy_counts"],
        "vat_inferred_when_raw_zero": len(contract["vat_inferred_when_raw_zero"]),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
