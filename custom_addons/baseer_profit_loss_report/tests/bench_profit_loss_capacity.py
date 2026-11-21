"""Diagnostic CI-only benchmark. Run seed then measure in separate Odoo shells.

The guarded database is ephemeral. Synthetic results are not a G6 certificate.
"""

import gc
import json
import math
import os
import resource
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psutil

from odoo import Command, api


EXPECTED_DATABASE = "baseer_pl_capacity_ci"
TARGET_LINES = 100000
ACCOUNT_COUNT = 5000
LINES_PER_MOVE = 100
BATCH_MOVES = 20
PERIOD = {"date_from": "2041-01-01", "date_to": "2041-12-31"}
KINDS = (
    "income", "income_other", "expense_direct_cost",
    "expense", "expense_other", "expense_depreciation",
)
PHASE = os.environ.get("BASEER_PL_BENCH_PHASE")
READONLY_LOGIN = "baseer_pl_capacity_readonly"
READONLY_NAME = "Baseer P&L capacity read-only accountant"
READONLY_ID_PARAM = "baseer_pl_capacity_readonly_user_id"

if env.cr.dbname != EXPECTED_DATABASE:
    raise RuntimeError("Refusing benchmark access outside the dedicated CI database")
if PHASE not in ("seed", "measure"):
    raise RuntimeError("Select BASEER_PL_BENCH_PHASE=seed or measure")
if not env.user.has_group("account.group_account_manager"):
    raise RuntimeError("The shell user must have accounting manager rights")

company = env.company
process = psutil.Process()


def memory_snapshot():
    """Read process RSS and cgroup limit/current when available."""
    vm = psutil.virtual_memory()
    rlimit_soft, rlimit_hard = resource.getrlimit(resource.RLIMIT_AS)
    cgroup = {}
    for key in ("max", "current", "peak"):
        try:
            with open(f"/sys/fs/cgroup/memory.{key}", encoding="ascii") as source:
                raw = source.read().strip()
            cgroup[key] = None if raw == "max" else int(raw) // 1048576
        except (OSError, ValueError):
            cgroup[key] = None
    available_mb = vm.available // 1048576
    if cgroup["max"] is not None and cgroup["current"] is not None:
        available_mb = min(available_mb, cgroup["max"] - cgroup["current"])
    if rlimit_soft != resource.RLIM_INFINITY:
        available_mb = min(available_mb, (rlimit_soft - process.memory_info().vms) // 1048576)
    return {
        "process_rss_mb": round(process.memory_info().rss / 1048576, 2),
        "process_vms_mb": round(process.memory_info().vms / 1048576, 2),
        "process_peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        "host_available_mb": vm.available // 1048576,
        "cgroup_limit_mb": cgroup["max"],
        "cgroup_current_mb": cgroup["current"],
        "cgroup_peak_mb": cgroup["peak"],
        "address_space_soft_limit_mb": None if rlimit_soft == resource.RLIM_INFINITY else rlimit_soft // 1048576,
        "address_space_hard_limit_mb": None if rlimit_hard == resource.RLIM_INFINITY else rlimit_hard // 1048576,
        "effective_headroom_mb": max(0, available_mb),
    }


def seed():
    if env["res.users"].search([("login", "=", READONLY_LOGIN)], limit=1):
        raise RuntimeError("Synthetic capacity accountant already exists")
    readonly = env["res.users"].create({
        "name": READONLY_NAME,
        "login": READONLY_LOGIN,
        "group_ids": [Command.set([
            env.ref("base.group_user").id,
            env.ref("account.group_account_readonly").id,
        ])],
        "company_id": company.id,
        "company_ids": [Command.set(company.ids)],
    })
    env["ir.config_parameter"].set_param(READONLY_ID_PARAM, str(readonly.id))
    env.cr.commit()
    Account = env["account.account"].with_company(company)
    Move = env["account.move"].with_company(company)
    asset = Account.search([
        ("company_ids", "in", company.id),
        ("account_type", "=", "asset_current"),
        ("reconcile", "=", False),
    ], limit=1)
    journal = env["account.journal"].with_company(company).search([
        ("company_id", "=", company.id), ("type", "=", "general"),
    ], limit=1)
    if not asset or not journal:
        raise RuntimeError("A non-reconcilable asset account and general journal are required")

    started = time.perf_counter()
    account_ids = []
    for first in range(0, ACCOUNT_COUNT, 100):
        values = [{
            "code": f"98{index:06d}",
            "name": f"Capacity {index:04d}",
            "account_type": KINDS[index % len(KINDS)],
            "company_ids": [Command.set(company.ids)],
        } for index in range(first, first + 100)]
        account_ids.extend(Account.create(values).ids)
        env.cr.commit()

    for first_move in range(0, TARGET_LINES // LINES_PER_MOVE, BATCH_MOVES):
        if time.perf_counter() - started > 2400:
            raise RuntimeError("Synthetic seed exceeded the 40-minute safety budget")
        move_values = []
        for move_index in range(first_move, first_move + BATCH_MOVES):
            lines = []
            debit_total = credit_total = 0.0
            for line_index in range(LINES_PER_MOVE):
                account_index = (move_index * LINES_PER_MOVE + line_index) % ACCOUNT_COUNT
                kind = KINDS[account_index % len(KINDS)]
                debit = 1.0 if kind.startswith("expense") else 0.0
                credit = 1.0 - debit
                debit_total += debit
                credit_total += credit
                lines.append(Command.create({
                    "name": "Synthetic capacity line",
                    "account_id": account_ids[account_index],
                    "debit": debit, "credit": credit,
                }))
            lines.append(Command.create({
                "name": "Synthetic capacity balancing line",
                "account_id": asset.id,
                "debit": max(credit_total - debit_total, 0.0),
                "credit": max(debit_total - credit_total, 0.0),
            }))
            move_values.append({
                "date": "2041-05-10", "journal_id": journal.id,
                "move_type": "entry", "line_ids": lines,
            })
        Move.create(move_values)._post(soft=False)
        env.cr.commit()
        if (first_move // BATCH_MOVES + 1) % 10 == 0:
            print("BASEER_PL_SEED_PROGRESS=" + json.dumps({
                "posted_lines": (first_move + BATCH_MOVES) * LINES_PER_MOVE,
                "elapsed_seconds": round(time.perf_counter() - started, 2),
                "memory": memory_snapshot(),
            }), flush=True)
    print("BASEER_PL_SEED_COMPLETE=" + json.dumps({
        "seed_seconds": round(time.perf_counter() - started, 2),
        "posted_lines_expected": TARGET_LINES,
        "read_only_accountant_id": readonly.id,
        "memory": memory_snapshot(),
    }), flush=True)


def measure_capacity():
    # Fresh process: no ORM cache survives seed. Validate exact source volume.
    stored_id = env["ir.config_parameter"].get_param(READONLY_ID_PARAM)
    if not stored_id or not stored_id.isdecimal():
        raise RuntimeError("Synthetic read-only accountant identity was not seeded")
    readonly = env["res.users"].browse(int(stored_id)).exists()
    if (not readonly or readonly.id == api.SUPERUSER_ID
            or readonly.login != READONLY_LOGIN or readonly.name != READONLY_NAME
            or company.id not in readonly.company_ids.ids
            or not readonly.has_group("account.group_account_readonly")
            or readonly.has_group("account.group_account_manager")):
        raise RuntimeError("Synthetic read-only accountant identity or groups changed")
    Account = env["account.account"].with_company(company)
    accounts = Account.search([
        ("company_ids", "in", company.id),
        ("code", "=like", "98%"),
        ("name", "=like", "Capacity %"),
    ])
    if len(accounts) != ACCOUNT_COUNT:
        raise RuntimeError(f"Expected {ACCOUNT_COUNT} synthetic accounts, got {len(accounts)}")
    actual_lines = env["account.move.line"].search_count([
        ("company_id", "=", company.id),
        ("parent_state", "=", "posted"),
        ("date", ">=", PERIOD["date_from"]),
        ("date", "<=", PERIOD["date_to"]),
        ("account_id", "in", accounts.ids),
    ])
    if actual_lines != TARGET_LINES:
        raise RuntimeError(f"Expected {TARGET_LINES} posted P&L lines, got {actual_lines}")
    del accounts

    filters = {"company_id": company.id, "journal_ids": [], **PERIOD}
    registry, uid = env.registry, readonly.id
    context = {"allowed_company_ids": [company.id], "lang": "en_US"}

    def measure(method, *args):
        before = memory_snapshot()
        with registry.cursor() as cursor:
            isolated = api.Environment(cursor, uid, context, su=False)
            report = isolated["baseer.profit.loss.report"].with_user(uid)
            if report.env.su or report.env.uid != uid:
                raise RuntimeError("Benchmark report escaped the read-only accountant identity")
            before_queries = cursor.sql_log_count
            started = time.perf_counter()
            try:
                result = getattr(report, method)(filters, *args)
            except Exception as error:
                print("BASEER_PL_BENCHMARK_FAILURE=" + json.dumps({
                    "method": method, "error": type(error).__name__,
                    "memory": memory_snapshot(),
                }), flush=True)
                raise
            seconds = time.perf_counter() - started
            queries = cursor.sql_log_count - before_queries
        after = memory_snapshot()
        return {
            "seconds": round(seconds, 4),
            "sql_queries": queries,
            "rss_delta_mb": round(after["process_rss_mb"] - before["process_rss_mb"], 2),
            "peak_rss_delta_mb": round(after["process_peak_rss_mb"] - before["process_peak_rss_mb"], 2),
            "result": result,
        }

    first = measure("get_report")
    print("BASEER_PL_BENCHMARK_FIRST=" + json.dumps({
        **{k: v for k, v in first.items() if k != "result"},
        "memory": memory_snapshot(),
    }), flush=True)
    page1 = measure("get_accounts", "income", 1)
    page5 = measure("get_accounts", "income", 5)
    if len(page1["result"]["accounts"]) != 100:
        raise RuntimeError("The income account page is not full")
    if len(page5["result"]["accounts"]) != 100:
        raise RuntimeError("The fifth income account page is not full")

    single = {
        "status": "DIAGNOSTIC_ONLY_NOT_G6_GO",
        "posted_profit_loss_lines": actual_lines,
        "synthetic_profit_loss_accounts": ACCOUNT_COUNT,
        "read_only_accountant_id": uid,
        "read_only_accountant_su": False,
        "first_report_fresh_orm_warm_db": {k: v for k, v in first.items() if k != "result"},
        "account_page_1_fresh_orm": {k: v for k, v in page1.items() if k != "result"},
        "account_page_5_fresh_orm": {k: v for k, v in page5.items() if k != "result"},
        "memory_after_single_reads": memory_snapshot(),
    }
    print("BASEER_PL_BENCHMARK_SINGLE=" + json.dumps(single, sort_keys=True), flush=True)
    gc.collect()

    def concurrent_sample(readers):
        barrier = Barrier(readers)

        def one_read(_index):
            barrier.wait(timeout=30)
            sample = measure("get_report")
            return (sample["seconds"], sample["sql_queries"])

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=readers) as pool:
            values = list(pool.map(one_read, range(readers)))
        times = [item[0] for item in values]
        return {
            "readers": readers,
            "wall_seconds": round(time.perf_counter() - started, 4),
            "p50_seconds": round(statistics.median(times), 4),
            "p95_seconds": round(sorted(times)[math.ceil(0.95 * len(times)) - 1], 4),
            "max_seconds": max(times),
            "sql_queries_per_reader": [item[1] for item in values],
        }

    # Reserve 1 GiB, plus 1.5x observed per-read growth per concurrent reader.
    growth_mb = max(
        first["rss_delta_mb"], first["peak_rss_delta_mb"],
        page1["rss_delta_mb"], page1["peak_rss_delta_mb"],
        page5["rss_delta_mb"], page5["peak_rss_delta_mb"], 512,
    )

    def safe_for(readers):
        memory = memory_snapshot()
        required_mb = math.ceil(readers * growth_mb * 1.5 + 1024)
        return memory["effective_headroom_mb"] >= required_mb, memory, required_mb

    two_safe, two_memory, two_required = safe_for(2)
    if first["seconds"] <= 15.0 and two_safe:
        try:
            two_readers = concurrent_sample(2)
        except MemoryError:
            print("BASEER_PL_BENCHMARK_FAILURE=" + json.dumps({
                "readers": 2, "error": "MemoryError", "memory": memory_snapshot(),
            }), flush=True)
            raise
    else:
        two_readers = {
            "status": "SKIPPED_SAFETY_GUARD",
            "reason": "First report exceeds 15 s or measured headroom is insufficient",
            "required_headroom_mb": two_required, "memory": two_memory,
        }
    print("BASEER_PL_BENCHMARK_TWO_READERS=" + json.dumps(two_readers), flush=True)

    ten_safe, ten_memory, ten_required = safe_for(10)
    if (first["seconds"] <= 3.0 and two_readers.get("max_seconds", 999) <= 5.0
            and ten_safe):
        try:
            ten_readers = concurrent_sample(10)
        except MemoryError:
            print("BASEER_PL_BENCHMARK_FAILURE=" + json.dumps({
                "readers": 10, "error": "MemoryError", "memory": memory_snapshot(),
            }), flush=True)
            raise
    else:
        ten_readers = {
            "status": "SKIPPED_SAFETY_GUARD",
            "reason": "Latency or measured memory headroom disallows ten concurrent reads",
            "required_headroom_mb": ten_required, "memory": ten_memory,
        }
    print("BASEER_PL_BENCHMARK=" + json.dumps({
        **single,
        "two_concurrent_reads": two_readers,
        "ten_concurrent_reads": ten_readers,
        "memory_after_concurrency": memory_snapshot(),
        "limitations": [
            "Synthetic equal-value lines differ from QA/production distributions",
            "Fresh ORM cursor but warm database cache after seed",
            "CI runner is not deployment capacity; independent G6 review is required",
        ],
    }, sort_keys=True), flush=True)


if PHASE == "seed":
    seed()
else:
    measure_capacity()
