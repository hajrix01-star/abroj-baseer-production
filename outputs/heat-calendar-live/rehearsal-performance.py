"""HTTP performance probe for the isolated Hostinger rehearsal only."""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar


BASE_URL = DATABASE = LOGIN = PASSWORD = None
DASHBOARD_ID = None


def configure(args):
    """Receive rehearsal identity at runtime; never bake it into evidence code."""
    global BASE_URL, DATABASE, LOGIN, PASSWORD, DASHBOARD_ID
    BASE_URL = args.base_url.rstrip("/")
    DATABASE = args.database
    LOGIN = args.login
    PASSWORD = os.environ.get(args.password_env)
    DASHBOARD_ID = args.dashboard_id
    if not PASSWORD:
        raise RuntimeError(f"Missing temporary password environment variable: {args.password_env}")


def percentile95(values):
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(len(ordered) * 0.95 + 0.999999) - 1))]


def rpc(opener, path, params):
    payload = json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}).encode()
    request = urllib.request.Request(
        f"{BASE_URL}{path}", payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=15) as response:
            decoded = json.loads(response.read().decode())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"HTTP failure: {exc}") from exc
    elapsed = time.perf_counter() - started
    if decoded.get("error"):
        raise RuntimeError(f"RPC error: {decoded['error']}")
    return decoded.get("result"), elapsed


def session():
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    result, elapsed = rpc(opener, "/web/session/authenticate", {
        "db": DATABASE, "login": LOGIN, "password": PASSWORD,
    })
    if not result or not result.get("uid"):
        raise RuntimeError("Rehearsal login was rejected")
    return opener, elapsed


def calendar_call(opener, company_id, dashboard_id=None):
    dashboard_id = dashboard_id or DASHBOARD_ID
    result, elapsed = rpc(opener, "/web/dataset/call_kw/spreadsheet.dashboard/get_baseer_heat_calendar", {
        "model": "spreadsheet.dashboard",
        "method": "get_baseer_heat_calendar",
        "args": [[dashboard_id], "2026-09"],
        "kwargs": {"context": {
            "lang": "en_US", "tz": "Asia/Riyadh",
            "allowed_company_ids": [company_id],
        }},
    })
    if not result or result.get("company", {}).get("id") != company_id:
        raise RuntimeError("Calendar returned an unexpected company")
    if len(result.get("weekdays", [])) != 7:
        raise RuntimeError("Calendar weekday header is incomplete")
    return elapsed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--login", required=True)
    parser.add_argument("--password-env", default="HC_REHEARSAL_PASSWORD")
    parser.add_argument("--dashboard-id", type=int, required=True)
    parser.add_argument("mode", choices=("cold", "warm"))
    parser.add_argument("company_id", type=int)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--sample-id", type=int)
    args = parser.parse_args()
    configure(args)

    if args.mode == "cold":
        started = time.perf_counter()
        opener, _auth_seconds = session()
        rpc_seconds = calendar_call(opener, args.company_id)
        print(json.dumps({
            "mode": "cold", "company_id": args.company_id,
            "sample_id": args.sample_id,
            "end_to_end_seconds": round(time.perf_counter() - started, 4),
            "rpc_seconds": round(rpc_seconds, 4),
        }))
    else:
        opener, _auth_seconds = session()
        samples = [calendar_call(opener, args.company_id) for _ in range(args.runs)]
        print(json.dumps({
            "mode": "warm", "company_id": args.company_id, "runs": len(samples),
            "p50_seconds": round(statistics.median(samples), 4),
            "p95_seconds": round(percentile95(samples), 4),
            "max_seconds": round(max(samples), 4),
        }))
