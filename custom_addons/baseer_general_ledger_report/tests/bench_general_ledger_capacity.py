"""CI-only GL capacity diagnostic; seed and measure in separate Odoo shells.

The database name and phase guards forbid accidental use on QA or production.
Results are diagnostic until an independent G6 review accepts them.
"""

import gc
import json
import math
import os
import resource
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psutil

from odoo import Command, api
from odoo.tools.profiler import Profiler


EXPECTED_DATABASE = "baseer_gl_capacity_ci"
QA_PILOT = os.environ.get("BASEER_GL_QA_PILOT") == "true"
TARGET_LINES = 30000 if QA_PILOT else 100000
ACCOUNT_COUNT = 2000 if QA_PILOT else 5000
LINES_PER_MOVE = 100
BATCH_MOVES = 20
PERIOD = {"date_from": "2041-01-01", "date_to": "2041-12-31"}
PHASE = os.environ.get("BASEER_GL_BENCH_PHASE")
DIAG_TEN = os.environ.get("BASEER_GL_DIAG_TEN") == "true"
READONLY_LOGIN = "baseer_gl_capacity_readonly"
READONLY_NAME = "Baseer GL capacity read-only accountant"
READONLY_ID_PARAM = "baseer_gl_capacity_readonly_user_id"

if env.cr.dbname != EXPECTED_DATABASE:
    raise RuntimeError("Refusing benchmark access outside the dedicated CI database")
if PHASE not in ("seed", "measure"):
    raise RuntimeError("Select BASEER_GL_BENCH_PHASE=seed or measure")
if not env.user.has_group("account.group_account_manager"):
    raise RuntimeError("The shell user must have accounting manager rights")

company = env.company
process = psutil.Process()


def memory_snapshot():
    """Report process and cgroup headroom without assuming host RAM is ours."""
    vm = psutil.virtual_memory()
    soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_AS)
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
    if soft_limit != resource.RLIM_INFINITY:
        available_mb = min(available_mb, (soft_limit - process.memory_info().vms) // 1048576)
    return {
        "process_rss_mb": round(process.memory_info().rss / 1048576, 2),
        "process_vms_mb": round(process.memory_info().vms / 1048576, 2),
        "process_peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        "host_available_mb": vm.available // 1048576,
        "cgroup_limit_mb": cgroup["max"],
        "cgroup_current_mb": cgroup["current"],
        "cgroup_peak_mb": cgroup["peak"],
        "address_space_soft_limit_mb": None if soft_limit == resource.RLIM_INFINITY else soft_limit // 1048576,
        "address_space_hard_limit_mb": None if hard_limit == resource.RLIM_INFINITY else hard_limit // 1048576,
        "effective_headroom_mb": max(0, available_mb),
    }


def cpu_snapshot():
    times = process.cpu_times()
    snapshot = {"process_cpu_seconds": round(times.user + times.system, 4)}
    try:
        with open("/sys/fs/cgroup/cpu.max", encoding="ascii") as source:
            snapshot["cgroup_cpu_max"] = source.read().strip()
        with open("/sys/fs/cgroup/cpu.stat", encoding="ascii") as source:
            for line in source:
                key, value = line.split()
                if key in ("usage_usec", "nr_throttled", "throttled_usec"):
                    snapshot[f"cgroup_{key}"] = int(value)
    except (OSError, ValueError):
        snapshot["cgroup_cpu_stat"] = "unavailable"
    return snapshot


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
    journal = env["account.journal"].with_company(company).search([
        ("company_id", "=", company.id), ("type", "=", "general"),
    ], limit=1)
    if not journal:
        raise RuntimeError("A general journal is required in the throwaway database")

    started = time.perf_counter()
    account_ids = []
    for first in range(0, ACCOUNT_COUNT, 100):
        values = [{
            "code": f"97{index:06d}",
            "name": f"GL Capacity {index:04d}",
            "account_type": "asset_current",
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
            for line_index in range(LINES_PER_MOVE):
                account_index = (move_index * LINES_PER_MOVE + line_index) % ACCOUNT_COUNT
                lines.append(Command.create({
                    "name": "Synthetic GL capacity line",
                    "account_id": account_ids[account_index],
                    "debit": 1.0 if line_index % 2 == 0 else 0.0,
                    "credit": 1.0 if line_index % 2 else 0.0,
                }))
            move_values.append({
                "date": "2041-05-10", "journal_id": journal.id,
                "move_type": "entry", "line_ids": lines,
            })
        Move.create(move_values)._post(soft=False)
        env.cr.commit()
        if (first_move // BATCH_MOVES + 1) % 5 == 0:
            print("BASEER_GL_SEED_PROGRESS=" + json.dumps({
                "posted_lines": (first_move + BATCH_MOVES) * LINES_PER_MOVE,
                "elapsed_seconds": round(time.perf_counter() - started, 2),
                "memory": memory_snapshot(),
            }), flush=True)
    print("BASEER_GL_SEED_COMPLETE=" + json.dumps({
        "seed_seconds": round(time.perf_counter() - started, 2),
        "posted_lines_expected": TARGET_LINES,
        "synthetic_accounts": ACCOUNT_COUNT,
        "read_only_accountant_id": readonly.id,
        "memory": memory_snapshot(),
    }), flush=True)


def measure_capacity():
    # The second shell has no seed-process ORM cache; only the database cache is warm.
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
    accounts = env["account.account"].with_company(company).search([
        ("company_ids", "in", company.id),
        ("code", "=like", "97%"),
        ("name", "=like", "GL Capacity %"),
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
        raise RuntimeError(f"Expected {TARGET_LINES} posted GL lines, got {actual_lines}")
    first_account_id = accounts.sorted("code")[0].id
    del accounts

    filters = {"company_id": company.id, "journal_ids": [], **PERIOD}
    registry, uid = env.registry, readonly.id
    context = {"allowed_company_ids": [company.id], "lang": "en_US"}

    def measure(method, *args):
        before = memory_snapshot()
        with registry.cursor() as cursor:
            isolated = api.Environment(cursor, uid, context, su=False)
            report = isolated["baseer.general.ledger.report"].with_user(uid)
            if report.env.su or report.env.uid != uid:
                raise RuntimeError("Benchmark report escaped the read-only accountant identity")
            before_queries = cursor.sql_log_count
            started = time.perf_counter()
            started_thread_cpu = time.thread_time()
            try:
                result = getattr(report, method)(filters, *args)
            except Exception as error:
                print("BASEER_GL_BENCHMARK_FAILURE=" + json.dumps({
                    "method": method, "error": type(error).__name__,
                    "memory": memory_snapshot(),
                }), flush=True)
                raise
            seconds = time.perf_counter() - started
            thread_cpu = time.thread_time() - started_thread_cpu
            queries = cursor.sql_log_count - before_queries
        after = memory_snapshot()
        return {
            "seconds": round(seconds, 4),
            "thread_cpu_seconds": round(thread_cpu, 4),
            "sql_queries": queries,
            "rss_delta_mb": round(after["process_rss_mb"] - before["process_rss_mb"], 2),
            "peak_rss_delta_mb": round(after["process_peak_rss_mb"] - before["process_peak_rss_mb"], 2),
            "result": result,
        }

    first = measure("get_report", 1)
    print("BASEER_GL_BENCHMARK_FIRST=" + json.dumps({
        **{key: value for key, value in first.items() if key != "result"},
        "memory": memory_snapshot(),
    }), flush=True)
    last_page = first["result"]["page_count"]
    if first["result"]["account_count"] != ACCOUNT_COUNT or last_page != ACCOUNT_COUNT // 100:
        raise RuntimeError("The GL account count or page count is incomplete")
    last = measure("get_report", last_page)
    lines = measure("get_lines", first_account_id)
    action = measure("get_account_action", first_account_id)
    if (len(first["result"]["accounts"]) != 100
            or last["result"]["page"] != last_page
            or len(last["result"]["accounts"]) != 100
            or len(lines["result"]["lines"]) != 20
            or action["result"]["res_model"] != "account.move.line"):
        raise RuntimeError("A GL page, detail or source action was incomplete")

    single = {
        "status": "DIAGNOSTIC_ONLY_NOT_G6_GO",
        "posted_gl_lines": actual_lines,
        "synthetic_gl_accounts": ACCOUNT_COUNT,
        "read_only_accountant_id": uid,
        "read_only_accountant_su": False,
        "first_report_fresh_orm_warm_db": {k: v for k, v in first.items() if k != "result"},
        "account_last_page_fresh_orm": {k: v for k, v in last.items() if k != "result"},
        "account_detail_fresh_orm": {k: v for k, v in lines.items() if k != "result"},
        "source_action_fresh_orm": {k: v for k, v in action.items() if k != "result"},
        "memory_after_single_reads": memory_snapshot(),
    }
    print("BASEER_GL_BENCHMARK_SINGLE=" + json.dumps(single, sort_keys=True), flush=True)
    gc.collect()

    def concurrent_sample(readers, profile_sql=False):
        barrier = Barrier(readers)

        def one_read(_index):
            barrier.wait(timeout=30)
            if profile_sql:
                with Profiler(collectors=["sql"], db=None,
                              description="Baseer GL concurrent SQL diagnostic") as profile:
                    sample = measure("get_report", 1)
                sample["sql_wall_seconds"] = round(
                    sum(entry["time"] for entry in profile.collectors[0].entries), 4,
                )
            else:
                sample = measure("get_report", 1)
            return sample

        cpu_before = cpu_snapshot()
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=readers) as pool:
            values = list(pool.map(one_read, range(readers)))
        cpu_after = cpu_snapshot()
        durations = [item["seconds"] for item in values]
        result = {
            "readers": readers,
            "wall_seconds": round(time.perf_counter() - started, 4),
            "p50_seconds": round(statistics.median(durations), 4),
            "p95_seconds": round(sorted(durations)[math.ceil(0.95 * len(durations)) - 1], 4),
            "max_seconds": max(durations),
            "sql_queries_per_reader": [item["sql_queries"] for item in values],
            "thread_cpu_seconds_per_reader": [item["thread_cpu_seconds"] for item in values],
            "cpu_before": cpu_before, "cpu_after": cpu_after,
        }
        if profile_sql:
            result["sql_wall_seconds_per_reader"] = [
                item["sql_wall_seconds"] for item in values
            ]
            result["diagnostic_profiler_overhead"] = True
        return result

    growth_mb = max(
        *(sample[key] for sample in (first, last, lines, action)
          for key in ("rss_delta_mb", "peak_rss_delta_mb")),
        64,
    )

    def safe_for(readers):
        memory = memory_snapshot()
        # Two times the largest measured read allocation, plus 512 MiB for
        # runtime/ORM overhead. The prior fixed 256 MiB per reader exceeded
        # Odoo's own 2.5 GiB address-space limit before any ten-reader run.
        required_mb = math.ceil(readers * growth_mb * 2 + 512)
        return memory["effective_headroom_mb"] >= required_mb, memory, required_mb

    two_safe, two_memory, two_required = safe_for(2)
    if first["seconds"] <= 15.0 and two_safe:
        two_readers = concurrent_sample(2)
    else:
        two_readers = {
            "status": "SKIPPED_SAFETY_GUARD",
            "reason": "First report exceeds 15 s or measured headroom is insufficient",
            "required_headroom_mb": two_required, "memory": two_memory,
        }
    print("BASEER_GL_BENCHMARK_TWO_READERS=" + json.dumps(two_readers), flush=True)

    ten_safe, ten_memory, ten_required = safe_for(10)
    if (ten_safe and first["seconds"] <= 15.0
            and (DIAG_TEN or (first["seconds"] <= 3.0
                              and two_readers.get("max_seconds", 999) <= 5.0))):
        ten_readers = concurrent_sample(10)
        if DIAG_TEN:
            ten_readers["diagnostic_only"] = True
    else:
        ten_readers = {
            "status": "SKIPPED_SAFETY_GUARD",
            "reason": "Latency or measured headroom disallows ten concurrent reads",
            "required_headroom_mb": ten_required, "memory": ten_memory,
        }
    print("BASEER_GL_BENCHMARK=" + json.dumps({
        **single,
        "two_concurrent_reads": two_readers,
        "ten_concurrent_reads": ten_readers,
        "memory_after_concurrency": memory_snapshot(),
        "limitations": [
            "Synthetic equal-value balanced lines differ from QA/production distributions",
            "Fresh ORM cursor but warm database cache after seed",
            "CI runner is not deployment capacity; independent G6 review is required",
        ],
    }, sort_keys=True), flush=True)
    if DIAG_TEN and ten_readers.get("readers") == 10 and ten_readers["max_seconds"] <= 30:
        profile_safe, _, _ = safe_for(10)
        if profile_safe:
            try:
                profiled_ten = concurrent_sample(10, profile_sql=True)
                print("BASEER_GL_DIAG_TEN_SQL=" + json.dumps(profiled_ten), flush=True)
            except Exception as error:
                print("BASEER_GL_DIAG_TEN_SQL=" + json.dumps({
                    "status": "UNAVAILABLE", "error": type(error).__name__,
                }), flush=True)
    final_memory = memory_snapshot()
    vms_limit = final_memory['address_space_soft_limit_mb']
    cgroup_limit = final_memory['cgroup_limit_mb']
    memory_limits = {
        'vms_under_75pct_of_address_space': (
            final_memory['process_vms_mb'] <= vms_limit * 0.75
            if vms_limit is not None else 'unbounded'),
        'cgroup_under_75pct': (
            final_memory['cgroup_peak_mb'] <= cgroup_limit * 0.75
            if cgroup_limit is not None and final_memory['cgroup_peak_mb'] is not None
            else 'unbounded'),
    }
    print('BASEER_GL_MEMORY_LIMITS=' + json.dumps(memory_limits), flush=True)
    capacity_failed = (
        DIAG_TEN or "status" in two_readers or "status" in ten_readers
        or first["seconds"] > 3.0 or last["seconds"] > 3.0
        or two_readers.get("max_seconds", float("inf")) > 5.0
        or ten_readers.get("max_seconds", float("inf")) > 5.0
        or any(value is False for value in memory_limits.values())
        or all(value == 'unbounded' for value in memory_limits.values())
    )
    if capacity_failed:
        # Only a failed diagnostic receives profiler overhead. Never treat
        # the profiled repeat as a capacity measurement or persist its trace.
        with Profiler(collectors=['sql'], db=None,
                      description='Baseer GL isolated SQL diagnostic') as profile:
            profiled = measure('get_report', 1)
        patterns = defaultdict(lambda: {'count': 0, 'seconds': 0.0})
        callers = defaultdict(lambda: {'count': 0, 'seconds': 0.0})
        entries = profile.collectors[0].entries
        for entry in entries:
            duration = entry['time']
            pattern = ' '.join(entry['query'].split())[:140]
            patterns[pattern]['count'] += 1
            patterns[pattern]['seconds'] += duration
            source = next((frame[2] for frame in reversed(entry['stack'])
                           if 'baseer_general_ledger_report' in frame[0]), 'Odoo core')
            callers[source]['count'] += 1
            callers[source]['seconds'] += duration
        def top_groups(groups):
            return [
                {'name': name, 'count': item['count'],
                 'sql_seconds': round(item['seconds'], 4)}
                for name, item in sorted(groups.items(),
                                         key=lambda pair: pair[1]['seconds'],
                                         reverse=True)[:10]
            ]
        print('BASEER_GL_SQL_PROFILE=' + json.dumps({
            'diagnostic_only': True, 'profiled_seconds': profiled['seconds'],
            'profiler_seconds': round(profile.duration, 4),
            'total_sql_seconds': round(sum(e['time'] for e in entries), 4),
            'sql_count': len(entries), 'top_patterns': top_groups(patterns),
            'top_callers': top_groups(callers),
        }), flush=True)
        raise RuntimeError("GL capacity threshold was not met: not G6 GO")


if PHASE == "seed":
    seed()
else:
    measure_capacity()
