"""Ephemeral GL HTTP benchmark: prepare in Odoo shell, then run client on CI host.

Never run this against a shared database or a non-loopback HTTP endpoint.
"""

import hashlib
import http.cookiejar
import json
import os
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path


DATABASE = "baseer_gl_capacity_ci"
BASE_URL = "http://127.0.0.1:8079"
PHASE = os.environ.get("BASEER_GL_HTTP_PHASE")
READONLY_ID_PARAM = "baseer_gl_capacity_readonly_user_id"
READONLY_LOGIN = "baseer_gl_capacity_readonly"
DENIED_LOGIN = "baseer_gl_capacity_denied"
PERIOD = {"date_from": "2041-01-01", "date_to": "2041-12-31"}
QA_PILOT = os.environ.get("BASEER_GL_QA_PILOT") == "true"
EXPECTED_ACCOUNTS = 2000 if QA_PILOT else 5000
EXPECTED_LINES = 30000 if QA_PILOT else 100000
EXPECTED_LAST_PAGE = EXPECTED_ACCOUNTS // 100
SESSIONS = 2 if QA_PILOT else 10


def prepare():
    from odoo import Command, api

    if env.cr.dbname != DATABASE or not env.user.has_group("account.group_account_manager"):
        raise RuntimeError("Refusing preparation outside the dedicated CI database")
    password = os.environ.get("BASEER_GL_HTTP_PASSWORD")
    if not password or len(password) < 40:
        raise RuntimeError("A random CI-only password is required")
    company = env.company
    account_ids = env["account.account"].with_company(company).search([
        ("company_ids", "in", company.id),
        ("code", "=like", "97%"),
        ("name", "=like", "GL Capacity %"),
    ]).ids
    if len(account_ids) != EXPECTED_ACCOUNTS:
        raise RuntimeError("The account seed is incomplete")
    line_count = env["account.move.line"].search_count([
        ("company_id", "=", company.id),
        ("parent_state", "=", "posted"),
        ("date", ">=", PERIOD["date_from"]),
        ("date", "<=", PERIOD["date_to"]),
        ("account_id", "in", account_ids),
    ])
    if line_count != EXPECTED_LINES:
        raise RuntimeError("The posted-line seed is incomplete")
    stored_id = env["ir.config_parameter"].get_param(READONLY_ID_PARAM)
    if not stored_id or not stored_id.isdecimal():
        raise RuntimeError("The seed read-only accountant is missing")
    user = env["res.users"].browse(int(stored_id)).exists()
    if (not user or user.id == api.SUPERUSER_ID or user.login != READONLY_LOGIN
            or user.has_group("account.group_account_manager")
            or not user.has_group("account.group_account_readonly")
            or company.id not in user.company_ids.ids):
        raise RuntimeError("Seed identity is not a read-only non-superuser accountant")
    user.write({"password": password})
    if env["res.users"].search([("login", "=", DENIED_LOGIN)], limit=1):
        raise RuntimeError("Synthetic denied user already exists")
    denied = env["res.users"].create({
        "name": "GL Capacity Denied User",
        "login": DENIED_LOGIN,
        "password": password,
        "group_ids": [Command.set([env.ref("base.group_user").id])],
        "company_id": company.id,
        "company_ids": [Command.set(company.ids)],
    })
    if any(denied.has_group(group) for group in (
            "account.group_account_readonly", "account.group_account_user",
            "account.group_account_manager")):
        raise RuntimeError("Denied fixture unexpectedly has accounting access")
    env.cr.commit()
    print("BASEER_GL_HTTP_PREPARED=" + json.dumps({
        "database": DATABASE, "company_id": company.id,
        "posted_lines": line_count, "accounts": len(account_ids),
        "user": {"login": user.login, "uid": user.id},
        "denied_user": {"login": denied.login, "uid": denied.id},
    }, sort_keys=True), flush=True)


def docker_processes(container):
    output = subprocess.check_output(
        ["docker", "top", container, "-eo", "pid,args"], text=True, timeout=15,
    )
    result = {}
    for line in output.splitlines()[1:]:
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdecimal():
            result[int(parts[0])] = parts[1]
    if not result:
        raise RuntimeError(f"No visible processes in isolated {container} container")
    return result


def docker_process_tree(container):
    output = subprocess.check_output(
        ["docker", "top", container, "-eo", "pid,ppid,args"],
        text=True, timeout=15,
    )
    rows = {}
    for line in output.splitlines()[1:]:
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0].isdecimal() and parts[1].isdecimal():
            rows[int(parts[0])] = {"ppid": int(parts[1]), "args": parts[2]}
    if not rows:
        raise RuntimeError(f"No process tree visible in isolated {container} container")
    return rows


def process_stats(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        fields = stat[stat.rfind(")") + 2:].split()
        status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    memory = {}
    for line in status.splitlines():
        if line.startswith(("VmRSS:", "VmSize:")):
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0]) / 1024
    ticks = os.sysconf("SC_CLK_TCK")
    return {
        "cpu_seconds": (int(fields[11]) + int(fields[12])) / ticks,
        "rss_mb": round(memory.get("VmRSS", 0), 2),
        "vms_mb": round(memory.get("VmSize", 0), 2),
    }


def process_group_stats(pids):
    return {str(pid): process_stats(pid) for pid in pids}


def postgres_wait_snapshot(container):
    # Only aggregate wait metadata from the throwaway database, never SQL text.
    sql = (
        "SELECT COALESCE(state,'unknown'), COALESCE(wait_event_type,'none'), "
        "COALESCE(wait_event,'none'), COUNT(*) FROM pg_stat_activity "
        "WHERE datname='baseer_gl_capacity_ci' GROUP BY 1,2,3 ORDER BY 1,2,3"
    )
    output = subprocess.check_output([
        "docker", "exec", "-e", "PGPASSWORD=odoo", container,
        "psql", "-X", "-A", "-t", "-F", "|", "-U", "odoo", "-d", "postgres",
        "-c", sql,
    ], text=True, timeout=5)
    rows = []
    for line in output.splitlines():
        state, wait_type, wait_event, count = line.split("|", 3)
        rows.append({"state": state, "wait_type": wait_type,
                     "wait_event": wait_event, "count": int(count)})
    return rows


def inspect_container(container):
    raw = subprocess.check_output(
        ["docker", "inspect", container], text=True, timeout=15,
    )
    item = json.loads(raw)[0]
    return {
        "oom_killed": item["State"]["OOMKilled"],
        "restarting": item["State"]["Restarting"],
        "restart_count": item["RestartCount"],
        "main_pid": item["State"]["Pid"],
        "memory_limit_mb": item["HostConfig"]["Memory"] // 1048576,
        "cpuset_cpus": item["HostConfig"]["CpusetCpus"],
    }


def new_session():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
    )
    return opener, jar


def rpc(opener, route, params, timeout=45):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "call", "params": params})
    request = urllib.request.Request(
        BASE_URL + route, data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} on {route}")
        body = json.load(response)
    if "error" in body:
        error = body["error"]
        raise RuntimeError(f"Odoo JSON error: {str(error.get('message', 'unknown'))[:160]}")
    if "result" not in body:
        raise RuntimeError("Odoo response has no result")
    return body["result"]


def assert_denied(opener, route, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "call", "params": params})
    request = urllib.request.Request(
        BASE_URL + route, data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with opener.open(request, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError("Denied-user probe returned unexpected HTTP status")
        body = json.load(response)
    error_name = body.get("error", {}).get("data", {}).get("name", "")
    if error_name != "odoo.exceptions.AccessError":
        raise RuntimeError(f"Denied-user probe did not raise AccessError: {error_name[:100]}")


def report_digest(report, expected_page):
    if (report.get("account_count") != EXPECTED_ACCOUNTS
            or report.get("page_count") != EXPECTED_LAST_PAGE
            or len(report.get("accounts", [])) != 100
            or report.get("page") != expected_page):
        raise RuntimeError("GL report count or page size changed")
    total = report.get("total", {})
    money = lambda key: Decimal(str(total[key]).replace(",", ""))
    if (money("opening") != 0 or money("debit") != Decimal(EXPECTED_LINES // 2)
            or money("credit") != Decimal(EXPECTED_LINES // 2) or money("closing") != 0):
        raise RuntimeError("GL report totals do not match the balanced synthetic seed")
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def client():
    if (BASE_URL != "http://127.0.0.1:8079"
            or os.environ.get("BASEER_GL_HTTP_PASSWORD") is None):
        raise RuntimeError("HTTP benchmark must use its local CI endpoint")
    prepared_path = Path(os.environ["BASEER_GL_HTTP_PREPARED_PATH"])
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    if (prepared.get("database") != DATABASE or prepared.get("accounts") != EXPECTED_ACCOUNTS
            or prepared.get("posted_lines") != EXPECTED_LINES
            or prepared.get("user", {}).get("login") != READONLY_LOGIN
            or prepared.get("denied_user", {}).get("login") != DENIED_LOGIN):
        raise RuntimeError("HTTP fixture identity or volume is incomplete")
    company_id = prepared["company_id"]
    filters = {"company_id": company_id, "journal_ids": [], **PERIOD}
    postgres = os.environ["BASEER_GL_HTTP_POSTGRES_CONTAINER"]
    cpuset = {int(part) for part in os.environ["BASEER_GL_HTTP_CPUSET"].split(",")}
    if len(cpuset) != 2 or inspect_container("baseer-gl-http")["cpuset_cpus"] != ",".join(map(str, sorted(cpuset))):
        raise RuntimeError("Odoo is not pinned to exactly two selected CPUs")
    if inspect_container(postgres)["cpuset_cpus"] != ",".join(map(str, sorted(cpuset))):
        raise RuntimeError("Postgres is not pinned to the same two CPUs")

    # Server readiness and independent logins are outside the report clock.
    for attempt in range(90):
        try:
            with urllib.request.urlopen(BASE_URL + f"/web/login?db={DATABASE}", timeout=3) as response:
                if response.status == 200:
                    break
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(1)
    else:
        raise RuntimeError("The two-worker Odoo HTTP server did not become ready")
    sessions = []
    session_ids = set()
    for _index in range(SESSIONS):
        opener, jar = new_session()
        identity = rpc(opener, "/web/session/authenticate", {
            "db": DATABASE, "login": prepared["user"]["login"],
            "password": os.environ["BASEER_GL_HTTP_PASSWORD"],
        })
        if identity.get("uid") != prepared["user"]["uid"] or identity["uid"] == 1:
            raise RuntimeError("HTTP session is not the intended non-superuser accountant")
        cookies = [cookie.value for cookie in jar if cookie.name == "session_id"]
        if len(cookies) != 1 or cookies[0] in session_ids:
            raise RuntimeError("The HTTP sessions are not independent")
        session_ids.add(cookies[0])
        sessions.append(opener)
    if len(sessions) != SESSIONS or len(session_ids) != SESSIONS:
        raise RuntimeError("The authenticated sessions are incomplete")

    def worker_pids():
        rows = docker_process_tree("baseer-gl-http")
        workers = {pid for pid, row in rows.items()
                   if "odoo: WorkerHTTP" in row["args"]}
        if not workers:
            # Some container/ps combinations show the original command line
            # even after Odoo sets worker titles. Odoo forks HTTP workers as
            # direct master children; its separate gevent child has "gevent"
            # in the command line. Keep the count and parent check fail-closed.
            master = inspect_container("baseer-gl-http")["main_pid"]
            workers = {pid for pid, row in rows.items()
                       if row["ppid"] == master
                       and "gevent" not in row["args"].lower()}
        if len(workers) != 2:
            master = inspect_container("baseer-gl-http")["main_pid"]
            children = [(pid, "gevent" in row["args"].lower())
                        for pid, row in rows.items() if row["ppid"] == master]
            raise RuntimeError(
                f"Expected two HTTP worker children, found {len(workers)}; "
                f"master={master}, direct_children={children}"
            )
        for pid in workers:
            if os.sched_getaffinity(pid) != cpuset:
                raise RuntimeError("An HTTP worker escaped the two-CPU affinity")
        return workers

    workers = worker_pids()
    expected = {"page": 1, "model": "baseer.general.ledger.report"}
    route = "/web/dataset/call_kw/baseer.general.ledger.report/get_report"

    denied_opener, _denied_jar = new_session()
    denied_identity = rpc(denied_opener, "/web/session/authenticate", {
        "db": DATABASE, "login": prepared["denied_user"]["login"],
        "password": os.environ["BASEER_GL_HTTP_PASSWORD"],
    })
    if denied_identity.get("uid") != prepared["denied_user"]["uid"]:
        raise RuntimeError("Denied-user HTTP session has the wrong identity")
    assert_denied(denied_opener, route, {
        "model": expected["model"], "method": "get_report",
        "args": [filters, 1],
        "kwargs": {"context": {"allowed_company_ids": [company_id]}},
    })

    def one_read(opener, page=1, barrier=None):
        if barrier is not None:
            barrier.wait(timeout=30)
        started = time.perf_counter()
        report = rpc(opener, route, {
            "model": expected["model"], "method": "get_report",
            "args": [filters, page],
            "kwargs": {"context": {"allowed_company_ids": [company_id]}},
        })
        seconds = time.perf_counter() - started
        return {"seconds": round(seconds, 4), "digest": report_digest(report, page)}

    def parallel(readers):
        barrier = threading.Barrier(readers + 1)
        with ThreadPoolExecutor(max_workers=readers) as pool:
            futures = [pool.submit(one_read, sessions[index], 1, barrier)
                       for index in range(readers)]
            started = time.perf_counter()
            barrier.wait(timeout=30)
            results = []
            errors = []
            for index, future in enumerate(futures):
                try:
                    results.append(future.result(timeout=60))
                except Exception as error:
                    errors.append({"session": index, "type": type(error).__name__,
                                   "message": str(error)[:160]})
            wall = time.perf_counter() - started
        if errors:
            print("BASEER_GL_HTTP_ERRORS=" + json.dumps({
                "readers": readers, "successes": len(results), "errors": errors,
            }, sort_keys=True), flush=True)
            raise RuntimeError("One or more authenticated HTTP report requests failed")
        return results, round(wall, 4)

    pg_pids = set(docker_processes(postgres))
    baseline_cpu = process_group_stats(workers | pg_pids)
    first = one_read(sessions[0])
    last_page = one_read(sessions[0], EXPECTED_LAST_PAGE)
    two, two_wall = parallel(2)
    if QA_PILOT:
        state = inspect_container("baseer-gl-http")
        if (any(sample["digest"] != first["digest"] for sample in two)
                or workers != worker_pids() or state["oom_killed"]
                or state["restarting"] or state["restart_count"] != 0):
            raise RuntimeError("QA pilot response mismatch or worker failure")
        result = {
            "status": "QA_PILOT_DIAGNOSTIC_NOT_RELEASE_GO",
            "posted_lines": prepared["posted_lines"],
            "account_count": prepared["accounts"],
            "last_page": EXPECTED_LAST_PAGE,
            "authenticated_sessions": len(session_ids),
            "denied_user_access_error": True,
            "first_page": first,
            "last_page_read": last_page,
            "two_readers": {"wall_seconds": two_wall,
                            "max_seconds": max(sample["seconds"] for sample in two),
                            "samples": two},
            "worker_pids_unchanged": sorted(workers),
            "memory_mb": process_group_stats(workers | pg_pids),
            "container_state": state,
            "limitations": ["Synthetic seed differs from actual QA distribution",
                            "CI runner is not QA; independent G6 review required"],
        }
        print("BASEER_GL_QA_PILOT=" + json.dumps(result, sort_keys=True), flush=True)
        if (first["seconds"] > 3 or last_page["seconds"] > 3
                or result["two_readers"]["max_seconds"] > 5):
            raise RuntimeError("QA pilot misses its predeclared G1 latency gate")
        return
    # Freeze monitored PIDs before the ten-reader clock; no Docker polling inside it.
    pg_pids = set(docker_processes(postgres))
    monitored = workers | pg_pids
    for pid in monitored:
        baseline_cpu.setdefault(str(pid), process_stats(pid))
    peaks = {str(pid): {"rss_mb": 0, "vms_mb": 0} for pid in monitored}
    missing_workers = set()
    postgres_wait_samples = []
    postgres_wait_errors = []
    stop = threading.Event()

    def monitor():
        while not stop.is_set():
            for pid in monitored:
                sample = process_stats(pid)
                if sample is None:
                    if pid in workers:
                        missing_workers.add(pid)
                    continue
                for key in ("rss_mb", "vms_mb"):
                    peaks[str(pid)][key] = max(peaks[str(pid)][key], sample[key])
            stop.wait(0.2)

    sampler = threading.Thread(target=monitor, daemon=True)
    def monitor_postgres_waits():
        while not stop.is_set():
            try:
                postgres_wait_samples.append(postgres_wait_snapshot(postgres))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                postgres_wait_errors.append(type(error).__name__)
                return
            stop.wait(1.0)

    wait_sampler = threading.Thread(target=monitor_postgres_waits, daemon=True)
    sampler.start()
    try:
        ten_cpu_start = process_group_stats(monitored)
        wait_sampler.start()
        ten, ten_wall = parallel(10)
        ten_cpu_end = process_group_stats(monitored)
    finally:
        stop.set()
        sampler.join(timeout=5)
        if wait_sampler.ident is not None:
            wait_sampler.join(timeout=6)
    end_cpu = process_group_stats(monitored)
    final_workers = worker_pids()
    container_state = inspect_container("baseer-gl-http")
    def cpu_delta(before, after, pids):
        return round(sum(
            after[str(pid)]["cpu_seconds"] - before[str(pid)]["cpu_seconds"]
            for pid in pids if before.get(str(pid)) and after.get(str(pid))
        ), 4)

    first_digest = first["digest"]
    if (any(sample["digest"] != first_digest for sample in two + ten)
            or len(ten) != SESSIONS or len(two) != 2
            or workers != final_workers or missing_workers
            or not postgres_wait_samples or postgres_wait_errors or wait_sampler.is_alive()
            or container_state["oom_killed"] or container_state["restarting"]
            or container_state["restart_count"] != 0):
        raise RuntimeError("HTTP response mismatch, worker restart or container memory failure")
    two_times = [sample["seconds"] for sample in two]
    ten_times = [sample["seconds"] for sample in ten]
    result = {
        "status": "DIAGNOSTIC_ONLY_NOT_G6_GO",
        "database": DATABASE,
        "posted_lines": prepared["posted_lines"],
        "account_count": prepared["accounts"],
        "read_only_uid": prepared["user"]["uid"],
        "independent_authenticated_sessions": len(session_ids),
        "denied_user_access_error": True,
        "worker_pids_unchanged": sorted(workers),
        "cpu_affinity": sorted(cpuset),
        "first_page": first,
        "page_50": last_page,
        "two_readers": {"wall_seconds": two_wall, "max_seconds": max(two_times),
                        "samples": two},
        "ten_http_readers": {"wall_seconds": ten_wall,
                             "p50_seconds": round(statistics.median(ten_times), 4),
                             "max_seconds": max(ten_times), "successful_responses": len(ten),
                             "samples": ten},
        "process_cpu_seconds_total": {
            "odoo_workers": cpu_delta(baseline_cpu, end_cpu, workers),
            "postgres_tracked": cpu_delta(baseline_cpu, end_cpu, pg_pids),
        },
        "process_cpu_seconds_ten_only": {
            "odoo_workers": cpu_delta(ten_cpu_start, ten_cpu_end, workers),
            "postgres_tracked": cpu_delta(ten_cpu_start, ten_cpu_end, pg_pids),
        },
        "process_peak_memory_mb": peaks,
        "postgres_wait_event_samples": postgres_wait_samples,
        "container_state": container_state,
        "limitations": [
            "Synthetic equal-value lines differ from real ledger distributions",
            "Postgres CPU covers tracked processes; new backends may be omitted",
            "Read-only Postgres wait sampling adds small observer overhead",
            "CI runner hardware is not QA; G6 requires independent review",
        ],
    }
    print("BASEER_GL_HTTP_BENCHMARK=" + json.dumps(result, sort_keys=True), flush=True)
    if (first["seconds"] > 3 or last_page["seconds"] > 3 or max(two_times) > 5
            or statistics.median(ten_times) > 5 or max(ten_times) > 8):
        raise RuntimeError("HTTP result misses the predeclared GL-27 G1 latency gate")


if PHASE == "prepare":
    prepare()
elif PHASE == "client":
    client()
else:
    raise RuntimeError("Select BASEER_GL_HTTP_PHASE=prepare or client")
