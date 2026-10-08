"""Diagnostic Odoo-shell benchmark on an ephemeral CI database only.

This file is deliberately not imported by tests/__init__.py and must never be
run against QA or production. It creates synthetic posted entries in the
throwaway database named by the workflow, then prints BASEER_PL_BENCHMARK JSON.
The measurements describe the CI runner, not an acceptance certificate.
"""

import json
import math
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psutil

from odoo import Command, api


EXPECTED_DATABASE = "baseer_pl_capacity_ci"
TARGET_LINES = int(os.environ.get("BASEER_PL_BENCH_LINES", "100000"))
ACCOUNT_COUNT = int(os.environ.get("BASEER_PL_BENCH_ACCOUNTS", "5000"))
LINES_PER_MOVE = 100
BATCH_MOVES = 20
PERIOD = {"date_from": "2041-01-01", "date_to": "2041-12-31"}
KINDS = (
    "income", "income_other", "expense_direct_cost",
    "expense", "expense_other", "expense_depreciation",
)

if env.cr.dbname != EXPECTED_DATABASE:
    raise RuntimeError("Refusing capacity writes outside the dedicated CI database")
if TARGET_LINES != 100000 or ACCOUNT_COUNT != 5000:
    raise RuntimeError("The benchmark contract is exactly 100k P&L lines and 5k accounts")
if not env.user.has_group("account.group_account_manager"):
    raise RuntimeError("The shell user must have accounting manager rights")

company = env.company
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

seed_started = time.perf_counter()
account_ids = []
for first in range(0, ACCOUNT_COUNT, 100):
    values = []
    for index in range(first, first + 100):
        values.append({
            "code": f"98{index:06d}",
            "name": f"Capacity {index:04d}",
            "account_type": KINDS[index % len(KINDS)],
            "company_ids": [Command.set(company.ids)],
        })
    account_ids.extend(Account.create(values).ids)
    env.cr.commit()

for first_move in range(0, TARGET_LINES // LINES_PER_MOVE, BATCH_MOVES):
    if time.perf_counter() - seed_started > 2400:
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
                "debit": debit,
                "credit": credit,
            }))
        lines.append(Command.create({
            "name": "Synthetic capacity balancing line",
            "account_id": asset.id,
            "debit": max(credit_total - debit_total, 0.0),
            "credit": max(debit_total - credit_total, 0.0),
        }))
        move_values.append({
            "date": "2041-05-10",
            "journal_id": journal.id,
            "move_type": "entry",
            "line_ids": lines,
        })
    Move.create(move_values)._post(soft=False)
    env.cr.commit()
    if (first_move // BATCH_MOVES + 1) % 10 == 0:
        print(
            f"BASEER_PL_SEED_PROGRESS={first_move + BATCH_MOVES}/"
            f"{TARGET_LINES // LINES_PER_MOVE} moves",
            flush=True,
        )
    if (first_move // BATCH_MOVES + 1) % 10 == 0:
        print("BASEER_PL_SEED_PROGRESS=" + json.dumps({
            "posted_lines": (first_move + BATCH_MOVES) * LINES_PER_MOVE,
            "elapsed_seconds": round(time.perf_counter() - seed_started, 2),
        }), flush=True)

filters = {"company_id": company.id, "journal_ids": [], **PERIOD}
actual_lines = env["account.move.line"].search_count([
    ("company_id", "=", company.id),
    ("parent_state", "=", "posted"),
    ("date", ">=", PERIOD["date_from"]),
    ("date", "<=", PERIOD["date_to"]),
    ("account_id", "in", account_ids),
])
if actual_lines != TARGET_LINES:
    raise RuntimeError(f"Expected {TARGET_LINES} posted P&L lines, got {actual_lines}")
seed_seconds = time.perf_counter() - seed_started

registry = env.registry
uid = env.uid
context = {"allowed_company_ids": [company.id], "lang": "en_US"}
process = psutil.Process()


def measure(method, *args):
    """Use a fresh ORM environment; count SQL generated by the RPC method."""
    with registry.cursor() as cursor:
        isolated = api.Environment(cursor, uid, context)
        report = isolated["baseer.profit.loss.report"]
        before_queries = cursor.sql_log_count
        before_rss = process.memory_info().rss
        started = time.perf_counter()
        result = getattr(report, method)(filters, *args)
        elapsed = time.perf_counter() - started
        return {
            "seconds": round(elapsed, 4),
            "sql_queries": cursor.sql_log_count - before_queries,
            "rss_delta_mb": round((process.memory_info().rss - before_rss) / 1048576, 2),
            "result": result,
        }


first = measure("get_report")
first_page = measure("get_accounts", "income", 1)
late_page = measure("get_accounts", "income", 5)
if len(first_page["result"]["accounts"]) != 100:
    raise RuntimeError("The income account page is not full; pagination sample is invalid")
if len(late_page["result"]["accounts"]) != 100:
    raise RuntimeError("The fifth income account page is not full")


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


available_mb = psutil.virtual_memory().available / 1048576
if first["seconds"] <= 15.0 and available_mb >= 2048:
    two_readers = concurrent_sample(2)
else:
    two_readers = {
        "status": "SKIPPED_SAFETY_GUARD",
        "reason": "Single report exceeds 15 s or available memory is below 2 GiB",
    }
if (first["seconds"] <= 3.0 and two_readers.get("max_seconds", 999) <= 5.0
        and available_mb >= 4096):
    ten_readers = concurrent_sample(10)
else:
    ten_readers = {
        "status": "SKIPPED_SAFETY_GUARD",
        "reason": "First/two-reader latency exceeds guard or available memory is below 4 GiB",
    }

results = {
    "status": "DIAGNOSTIC_ONLY_NOT_G6_GO",
    "database": EXPECTED_DATABASE,
    "runner": "GitHub ubuntu-24.04 ephemeral",
    "posted_profit_loss_lines": actual_lines,
    "synthetic_profit_loss_accounts": ACCOUNT_COUNT,
    "available_memory_before_concurrency_mb": round(available_mb, 2),
    "seed_seconds": round(seed_seconds, 2),
    "first_report_fresh_orm_warm_db": {k: v for k, v in first.items() if k != "result"},
    "account_page_1_fresh_orm": {k: v for k, v in first_page.items() if k != "result"},
    "account_page_5_fresh_orm": {k: v for k, v in late_page.items() if k != "result"},
    "two_concurrent_reads": two_readers,
    "ten_concurrent_reads": ten_readers,
    "limitations": [
        "Synthetic equal-value journal lines; not representative of QA/production distributions",
        "Fresh ORM cursor but warm database cache after seeding",
        "CI runner latency and memory do not certify deployment capacity",
    ],
}
print("BASEER_PL_BENCHMARK=" + json.dumps(results, sort_keys=True), flush=True)
