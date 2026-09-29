"""QA-only runtime proof for the procurement POS catalogue.

Runs against the isolated QA database over Odoo XML-RPC.  It measures the
catalogue/quote contracts and proves that two concurrent retries with one
idempotency token create exactly one draft, then removes that draft.
"""

from __future__ import annotations

import json
import os
import hashlib
import statistics
import time
import uuid
import xmlrpc.client
from concurrent.futures import ThreadPoolExecutor


URL = os.environ.get("BASEER_QA_URL", "http://127.0.0.1:18081")
DB = "baseer_procurement_qa_20260911"
USERNAME = os.environ.get("BASEER_QA_USER", "admin")
PASSWORD = os.environ["BASEER_QA_PASSWORD"]


def authenticate():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(DB, USERNAME, PASSWORD, {})
    if not uid:
        raise RuntimeError("QA authentication failed")
    return uid


def execute(model, method, args, kwargs=None):
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)
    return models.execute_kw(DB, UID, PASSWORD, model, method, args, kwargs or {})


def p95(milliseconds):
    ordered = sorted(milliseconds)
    return round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2)


def timed(callable_, repetitions=30):
    values = []
    for _ in range(repetitions):
        started = time.perf_counter()
        callable_()
        values.append((time.perf_counter() - started) * 1000)
    return {"p50_ms": round(statistics.median(values), 2), "p95_ms": p95(values), "max_ms": round(max(values), 2)}


def main():
    user = execute("res.users", "read", [[UID], ["company_id"]])[0]
    company_id = user["company_id"][0]
    page = execute("baseer.procurement.request", "catalog_page", ["", False, 0, 48])
    if not page["items"]:
        raise RuntimeError("QA catalogue is empty")
    option = page["items"][0]
    warehouses = execute("stock.warehouse", "search_read", [[["company_id", "=", company_id]], ["name"]], {"limit": 1})
    purchasers = execute("hr.employee.public", "search_read", [[["company_id", "=", company_id]], ["name"]], {"limit": 1})
    if not warehouses or not purchasers:
        raise RuntimeError("QA warehouse or purchaser fixture is missing")

    lines = [{"option_id": option["id"], "quantity": "1.25"}]
    token = str(uuid.uuid4())
    create_args = [lines, warehouses[0]["id"], purchasers[0]["id"], False, token]
    expected_payload = {
        "warehouse_id": warehouses[0]["id"],
        "purchaser_id": purchasers[0]["id"],
        "whatsapp_number": "",
        "lines": [{"option_id": option["id"], "quantity": "1.25"}],
    }
    expected_hash = hashlib.sha256(json.dumps(expected_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def create_once():
        return execute("baseer.procurement.request", "create_from_catalog", create_args)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create_once) for _ in range(2)]
        ids = []
        errors = []
        for future in futures:
            try:
                ids.append(future.result())
            except Exception as exc:  # diagnostics are emitted before cleanup
                errors.append(repr(exc))

    token_rows = execute(
        "baseer.procurement.request",
        "search_read",
        [[["client_token", "=", token]], ["client_token", "client_payload_hash", "warehouse_id", "purchaser_id", "whatsapp_number"]],
    )
    if errors:
        for row in token_rows:
            execute("baseer.procurement.request", "unlink", [[row["id"]]])
        raise RuntimeError(f"Concurrent create errors={errors}; expected_payload={expected_payload}; expected_hash={expected_hash}; token_rows={token_rows}")

    unique_ids = sorted(set(ids))
    count = execute("baseer.procurement.request", "search_count", [[["client_token", "=", token]]])
    if len(unique_ids) != 1 or count != 1:
        raise RuntimeError(f"Idempotency failed: ids={ids}, count={count}")

    quote_call = lambda: execute("baseer.procurement.request", "quote_catalog_cart", [lines])
    page_call = lambda: execute("baseer.procurement.request", "catalog_page", ["", False, 0, 48])
    search_call = lambda: execute("baseer.procurement.request", "catalog_page", [option["product_name"], False, 0, 48])

    timings = {
        "catalogue_page": timed(page_call),
        "catalogue_search": timed(search_call),
        "server_quote": timed(quote_call),
    }
    with ThreadPoolExecutor(max_workers=10) as pool:
        concurrent_pages = list(pool.map(lambda _: page_call(), range(10)))
    if any(not response["items"] for response in concurrent_pages):
        raise RuntimeError("One of the 10 concurrent catalogue reads was empty")

    execute("baseer.procurement.request", "unlink", [unique_ids])
    remaining = execute("baseer.procurement.request", "search_count", [[["client_token", "=", token]]])
    if remaining:
        raise RuntimeError("QA cleanup failed")

    result = {
        "database": DB,
        "idempotency": {"parallel_calls": 2, "returned_same_id": True, "created_records": count},
        "capacity": {"page_size": len(page["items"]), "parallel_reads": len(concurrent_pages)},
        "timings": timings,
        "cleanup": "passed",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    UID = authenticate()
    main()
