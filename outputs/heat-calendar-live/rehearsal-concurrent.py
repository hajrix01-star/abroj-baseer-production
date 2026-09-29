"""Twenty authenticated calendar reads against the isolated rehearsal."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path
import time


spec = importlib.util.spec_from_file_location(
    "heat_perf", Path(__file__).with_name("rehearsal-performance.py"),
)
perf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(perf)


def one(opener, company_id):
    started = time.perf_counter()
    rpc_seconds = perf.calendar_call(opener, company_id)
    return time.perf_counter() - started, rpc_seconds


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--login", required=True)
    parser.add_argument("--password-env", default="HC_REHEARSAL_PASSWORD")
    parser.add_argument("--dashboard-id", type=int, required=True)
    parser.add_argument("--company-ids", required=True,
                        help="Comma-separated IDs discovered from the rehearsal itself.")
    parser.add_argument("--sessions", type=int, default=20)
    args = parser.parse_args()
    perf.configure(args)
    company_ids = tuple(int(value) for value in args.company_ids.split(",") if value)
    if not company_ids:
        raise RuntimeError("At least one rehearsal company ID is required")
    # Authentication is intentionally completed before the concurrent window.
    # Password hashing is not dashboard work; this isolates calendar RPC reads.
    openers = [perf.session()[0] for _ in range(args.sessions)]
    started = time.perf_counter()
    samples = []
    with ThreadPoolExecutor(max_workers=args.sessions) as executor:
        futures = [
            executor.submit(one, openers[index], company_ids[index % len(company_ids)])
            for index in range(args.sessions)
        ]
        for future in as_completed(futures):
            samples.append(future.result())

    elapsed = time.perf_counter() - started
    totals = sorted(sample[0] for sample in samples)
    rpc_times = sorted(sample[1] for sample in samples)
    index95 = int(len(samples) * 0.95 + 0.999999) - 1
    print(json.dumps({
        "concurrency": args.sessions,
        "completed": len(samples),
        "company_ids": company_ids,
        "wall_seconds": round(elapsed, 4),
        "calendar_p95_seconds": round(totals[index95], 4),
        "rpc_p95_seconds": round(rpc_times[index95], 4),
    }))
