"""Standalone PRC close/settlement race probe for an isolated Odoo database.

Run with ``odoo shell -d <temporary-db> < tools/prc_concurrency_probe.py``.
The script deliberately commits fixtures and race results; never point it at a
shared or production database.  The caller must drop the temporary database.
"""

from datetime import timedelta
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

from odoo import Command, SUPERUSER_ID, api, fields


EXPECTED_DATABASE_PREFIX = "baseer_prc_capacity_"
if not env.cr.dbname.startswith(EXPECTED_DATABASE_PREFIX):
    raise RuntimeError("Concurrency probe may run only on the isolated capacity database.")


company = env["res.company"].browse(2).exists()
if not company:
    raise RuntimeError("The isolated clone does not contain QA company 2.")
context = {"allowed_company_ids": [company.id], "lang": "en_US"}
probe_env = api.Environment(env.cr, SUPERUSER_ID, context)
registry = probe_env.registry

custody = probe_env["baseer.procurement.custody"].search([
    ("company_id", "=", company.id),
    ("is_company_pool", "=", True),
], limit=1)
if custody and custody.state != "open":
    # This probe is guarded to an isolated disposable clone.  Re-open its
    # copied pool so both race directions start from the same known fixture;
    # the shared QA database is never changed by this operation.
    probe_env.cr.execute(
        "UPDATE baseer_procurement_custody SET state = 'open' WHERE id = %s",
        [custody.id],
    )
    custody.invalidate_recordset(["state"])
warehouse = probe_env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
option = probe_env["baseer.procurement.purchase.option"].search([
    ("company_id", "=", company.id), ("active", "=", True),
], limit=1)
cash_journal = probe_env["account.journal"].search([
    ("company_id", "=", company.id), ("type", "in", ("cash", "bank")),
    ("default_account_id", "!=", False), ("active", "=", True),
], limit=1)
mapping = probe_env["baseer.purchase.category.map"].search([
    ("company_id", "=", company.id), ("active", "=", True),
], limit=1)
supplier = probe_env["res.partner"].search([
    ("supplier_rank", ">", 0), "|", ("company_id", "=", False), ("company_id", "=", company.id),
], limit=1)
if not all((custody, warehouse, option, cash_journal, mapping, supplier)):
    raise RuntimeError("The isolated clone lacks a valid custody probe fixture.")


def build_case(label):
    token = "%s-%s" % (label, uuid4().hex[:8])
    representative = probe_env["res.partner"].create({
        "name": "Concurrency representative %s" % token,
        "company_id": company.id,
        "is_company": False,
    })
    representative.with_company(company).write({"is_purchase_representative": True})
    request = probe_env["baseer.procurement.request"].create({
        "company_id": company.id,
        "warehouse_id": warehouse.id,
        "representative_partner_id": representative.id,
        "line_ids": [Command.create({
            "option_id": option.id,
            "requested_qty": 4,
            "requested_price": 10,
        })],
    })
    request.action_mark_sent()
    request.line_ids.manager_received_qty = 4
    request.action_confirm_manager_receipt()
    request.line_ids.write({"actual_qty": 4, "actual_price": 10})
    request.action_confirm_actual_purchase()

    today = fields.Date.context_today(request)
    prior_day = today.replace(day=1) - timedelta(days=1)
    probe_env["baseer.procurement.custody.event"].create({
        "custody_id": custody.id,
        "event_type": "funding",
        "event_date": prior_day,
        "amount": 40,
        "cash_journal_id": cash_journal.id,
        "representative_partner_id": representative.id,
        "procurement_request_id": request.id,
        "reference": "Concurrency funding %s" % token,
    }).action_post()
    batch = probe_env["baseer.purchase.batch"].create({
        "company_id": company.id,
        "entry_date": prior_day,
        "procurement_request_id": request.id,
        "procurement_custody_id": custody.id,
        "procurement_representative_partner_id": representative.id,
        "line_ids": [Command.create({
            "partner_id": supplier.id,
            "supplier_ref": "RACE-%s" % token,
            "invoice_date": prior_day,
            "entry_type": "purchase",
            "category_map_id": mapping.id,
            "gross_amount": 40,
            "is_credit": True,
        })],
    })
    close = probe_env["baseer.procurement.custody.period.close"].create({
        "custody_id": custody.id,
        "representative_partner_id": representative.id,
        "month_start": prior_day.replace(day=1),
        "note": "Concurrency %s" % token,
    })
    return {"batch_id": batch.id, "close_id": close.id}


close_first = build_case("close-first")
settle_first = build_case("settle-first")
probe_env.cr.commit()


def error_code(error):
    return getattr(error, "pgcode", None) or getattr(getattr(error, "__cause__", None), "pgcode", None)


def run_action(model_name, record_id, method_name, application_name, results,
               ready=None, release=None, prelock=None):
    for attempt in range(1, 4):
        with registry.cursor() as cr:
            try:
                cr.execute("SELECT set_config('application_name', %s, true)", [application_name])
                worker_env = api.Environment(cr, SUPERUSER_ID, context)
                if attempt == 1 and prelock:
                    prelock(cr)
                if attempt == 1 and ready:
                    ready.set()
                if attempt == 1 and release and not release.wait(15):
                    raise AssertionError("Timed out waiting to release the winning transaction.")
                getattr(worker_env[model_name].browse(record_id), method_name)()
                cr.commit()
                results.append(("ok", attempt))
                return
            except Exception as error:
                cr.rollback()
                if error_code(error) == "40001" and attempt < 3:
                    results.append(("retry", attempt))
                    continue
                results.append(("error", type(error).__name__, str(error)))
                return


def wait_for_lock(application_name, timeout=15):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        with registry.cursor() as cr:
            cr.execute(
                """SELECT COALESCE(bool_or(wait_event_type = 'Lock'), false)
                     FROM pg_stat_activity
                    WHERE datname = current_database() AND application_name = %s""",
                [application_name],
            )
            if cr.fetchone()[0]:
                return
        sleep(0.05)
    raise AssertionError("The competing transaction never waited on the custody lock.")


def run_race(winner, loser, prelock):
    winner_ready, winner_release, loser_started = Event(), Event(), Event()
    winner_results, loser_results = [], []
    winner_thread = Thread(
        target=run_action,
        args=(winner[0], winner[1], winner[2], winner[3], winner_results,
              winner_ready, winner_release, prelock),
        daemon=True,
    )
    loser_thread = Thread(
        target=run_action,
        args=(loser[0], loser[1], loser[2], loser[3], loser_results, loser_started),
        daemon=True,
    )
    winner_thread.start()
    if not winner_ready.wait(15):
        raise AssertionError("Winning transaction did not acquire its ordered locks: %r" % winner_results)
    loser_thread.start()
    if not loser_started.wait(15):
        raise AssertionError("Competing transaction did not start: %r" % loser_results)
    try:
        wait_for_lock(loser[3])
    finally:
        winner_release.set()
    winner_thread.join(20)
    loser_thread.join(20)
    if winner_thread.is_alive() or loser_thread.is_alive():
        raise AssertionError("A race worker did not terminate.")
    return winner_results, loser_results


def prelock_custody(cr):
    cr.execute("SELECT id FROM baseer_procurement_custody WHERE id = %s FOR UPDATE", [custody.id])
    cr.execute("UPDATE baseer_procurement_custody SET id = id WHERE id = %s", [custody.id])


close_results, settle_results = run_race(
    ("baseer.procurement.custody.period.close", close_first["close_id"], "action_close", "prc_probe_close_wins_close"),
    ("baseer.purchase.batch", close_first["batch_id"], "action_approve", "prc_probe_close_wins_settle"),
    prelock_custody,
)
close_first_close_results = list(close_results)
close_first_settle_results = list(settle_results)
if close_results[-1][0] != "ok":
    raise AssertionError(close_results)
if not any(row[0] == "retry" for row in settle_results):
    raise AssertionError(settle_results)
if settle_results[-1][0] != "error" or "month is closed" not in settle_results[-1][2]:
    raise AssertionError(settle_results)

with registry.cursor() as cr:
    check_env = api.Environment(cr, SUPERUSER_ID, context)
    close = check_env["baseer.procurement.custody.period.close"].browse(close_first["close_id"])
    batch = check_env["baseer.purchase.batch"].browse(close_first["batch_id"])
    if (close.state, close.funded_amount, close.settled_amount, close.carry_forward_amount) != ("closed", 40, 0, 40):
        raise AssertionError("Close-first snapshot is incorrect.")
    if batch.state != "draft" or batch.line_ids.move_id or batch.line_ids.procurement_settlement_id:
        raise AssertionError("Close-first loser left a financial effect.")


def prelock_batch_and_custody(cr):
    cr.execute("SELECT id FROM baseer_purchase_batch WHERE id = %s FOR UPDATE", [settle_first["batch_id"]])
    cr.execute("SELECT id FROM baseer_procurement_custody WHERE id = %s FOR UPDATE", [custody.id])
    cr.execute("UPDATE baseer_procurement_custody SET id = id WHERE id = %s", [custody.id])


settle_results, close_results = run_race(
    ("baseer.purchase.batch", settle_first["batch_id"], "action_approve", "prc_probe_settle_wins_settle"),
    ("baseer.procurement.custody.period.close", settle_first["close_id"], "action_close", "prc_probe_settle_wins_close"),
    prelock_batch_and_custody,
)
settle_first_settle_results = list(settle_results)
settle_first_close_results = list(close_results)
if settle_results[-1][0] != "ok":
    raise AssertionError(settle_results)
if not any(row[0] == "retry" for row in close_results) or close_results[-1][0] != "ok":
    raise AssertionError(close_results)

with registry.cursor() as cr:
    check_env = api.Environment(cr, SUPERUSER_ID, context)
    close = check_env["baseer.procurement.custody.period.close"].browse(settle_first["close_id"])
    batch = check_env["baseer.purchase.batch"].browse(settle_first["batch_id"])
    if (close.state, close.funded_amount, close.settled_amount, close.carry_forward_amount) != ("closed", 40, 40, 0):
        raise AssertionError("Settlement-first snapshot is incorrect.")
    if batch.state != "approved" or len(batch.line_ids.procurement_settlement_id) != 1:
        raise AssertionError("Settlement-first winner did not produce exactly one settlement.")

print("PRC_CONCURRENCY_PROBE PASS close-wins=%r settle-wins=%r" % (
    (close_first_close_results, close_first_settle_results),
    (settle_first_settle_results, settle_first_close_results),
))
