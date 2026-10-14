"""Profile one GL read on a synthetic, isolated CI database only.

This is diagnostic instrumentation, not a capacity pass or a production hook.
"""

import cProfile
import gc
import json
import os
import pstats
import time
from decimal import Decimal

from odoo import api
from odoo.tools.profiler import Profiler


DATABASE = "baseer_gl_capacity_ci"
READONLY_ID_PARAM = "baseer_gl_capacity_readonly_user_id"
READONLY_LOGIN = "baseer_gl_capacity_readonly"
PERIOD = {"date_from": "2041-01-01", "date_to": "2041-12-31"}

if env.cr.dbname != DATABASE or not env.user.has_group("account.group_account_manager"):
    raise RuntimeError("Refusing profiler outside the isolated CI database")
if os.environ.get("BASEER_GL_PROFILE_PHASE") != "profile":
    raise RuntimeError("Explicit BASEER_GL_PROFILE_PHASE=profile is required")

company = env.company
stored_id = env["ir.config_parameter"].get_param(READONLY_ID_PARAM)
if not stored_id or not stored_id.isdecimal():
    raise RuntimeError("The synthetic accountant is missing")
readonly = env["res.users"].browse(int(stored_id)).exists()
if (not readonly or readonly.id == api.SUPERUSER_ID
        or readonly.login != READONLY_LOGIN
        or not readonly.has_group("account.group_account_readonly")
        or readonly.has_group("account.group_account_manager")
        or company.id not in readonly.company_ids.ids):
    raise RuntimeError("The profiler identity is not the read-only accountant")

accounts = env["account.account"].with_company(company).search([
    ("company_ids", "in", company.id),
    ("code", "=like", "97%"),
    ("name", "=like", "GL Capacity %"),
])
line_count = env["account.move.line"].search_count([
    ("company_id", "=", company.id), ("parent_state", "=", "posted"),
    ("date", ">=", PERIOD["date_from"]), ("date", "<=", PERIOD["date_to"]),
    ("account_id", "in", accounts.ids),
])
if len(accounts) != 5000 or line_count != 100000:
    raise RuntimeError("The 100k/5k synthetic source is incomplete")
del accounts

filters = {"company_id": company.id, "journal_ids": [], **PERIOD}
context = {"allowed_company_ids": [company.id], "lang": "en_US"}


def check_result(result):
    if (result["account_count"] != 5000 or result["page_count"] != 50
            or len(result["accounts"]) != 100):
        raise RuntimeError("Profiled report is incomplete")
    total = result["total"]
    money = lambda key: Decimal(total[key].replace(",", ""))
    if (money("opening") != 0 or money("debit") != 50000
            or money("credit") != 50000 or money("closing") != 0):
        raise RuntimeError("Profiled report totals differ from the synthetic source")


def read_once(profile=None, sql_profile=False):
    with env.registry.cursor() as cursor:
        isolated = api.Environment(cursor, readonly.id, context, su=False)
        report = isolated["baseer.general.ledger.report"].with_user(readonly.id)
        if report.env.su or report.env.uid != readonly.id:
            raise RuntimeError("Profiler escaped the non-superuser identity")
        started = time.perf_counter()
        cpu_started = time.process_time()
        before_queries = cursor.sql_log_count
        if sql_profile:
            with Profiler(collectors=["sql"], db=None,
                          description="Isolated GL stage diagnosis") as collector:
                result = report.get_report(filters, 1)
        else:
            profile.enable()
            try:
                result = report.get_report(filters, 1)
            finally:
                profile.disable()
            collector = None
        sample = {
            "wall_seconds": round(time.perf_counter() - started, 4),
            "process_cpu_seconds": round(time.process_time() - cpu_started, 4),
            "sql_queries": cursor.sql_log_count - before_queries,
        }
        check_result(result)
        return sample, collector


def top_functions(stats, position, limit=25):
    rows = []
    for (filename, lineno, name), (primitive, calls, self_seconds,
                                   cumulative_seconds, _callers) in stats.stats.items():
        short_path = "/".join(filename.replace("\\", "/").split("/")[-3:])
        rows.append({
            "function": f"{short_path}:{lineno}:{name}",
            "calls": calls,
            "self_seconds": round(self_seconds, 4),
            "cumulative_seconds": round(cumulative_seconds, 4),
        })
    return sorted(rows, key=lambda row: row[position], reverse=True)[:limit]


profile = cProfile.Profile(timer=time.thread_time)
first, _ = read_once(profile=profile)
stats = pstats.Stats(profile)
print("BASEER_GL_STAGE_PROFILE=" + json.dumps({
    "status": "DIAGNOSTIC_ONLY_NOT_G6_GO",
    "read_only_uid": readonly.id,
    "posted_lines": line_count,
    "first_profiled_read": first,
    "profile_timer": "time.thread_time",
    "top_self_cpu_seconds": top_functions(stats, "self_seconds"),
    "top_cumulative_cpu_seconds": top_functions(stats, "cumulative_seconds"),
    "cprofile_overhead": True,
}, sort_keys=True), flush=True)

gc.collect()
second, collector = read_once(sql_profile=True)
entries = collector.collectors[0].entries
sum_entries = [entry for entry in entries if "SUM(debit)::text" in entry["query"]]
print("BASEER_GL_STAGE_SQL=" + json.dumps({
    "status": "DIAGNOSTIC_ONLY_NOT_G6_GO",
    "second_profiled_read": second,
    "sql_wall_seconds": round(sum(entry["time"] for entry in entries), 4),
    "exact_sum_queries": len(sum_entries),
    "exact_sum_sql_wall_seconds": round(sum(entry["time"] for entry in sum_entries), 4),
    "sql_profiler_overhead": True,
}, sort_keys=True), flush=True)
