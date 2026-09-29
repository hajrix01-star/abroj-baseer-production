"""Measure 20-row custody batch approval on one disposable PRC database.

Run with::

    odoo shell -d baseer_prc_capacity_20260912 \
        < tools/prc_capacity_approve_probe.py

The probe commits financial fixtures and results.  Its exact database guard is
intentional: never point this script at QA, production, or a shared database.
"""

from statistics import median
from time import perf_counter
from uuid import uuid4

from odoo import Command, SUPERUSER_ID, api, fields


EXPECTED_DATABASE = "baseer_prc_capacity_20260912"
ROUNDS = 5
ROWS_PER_ROUND = 20
AMOUNT_PER_ROW = 10.0

if env.cr.dbname != EXPECTED_DATABASE:
    raise RuntimeError(
        "Capacity probe is restricted to %s; refusing %s."
        % (EXPECTED_DATABASE, env.cr.dbname)
    )

company = env["res.company"].browse(2).exists()
if not company or company.currency_id.name != "SAR":
    raise RuntimeError("The isolated capacity database lacks SAR company 2.")

context = {"allowed_company_ids": [company.id], "lang": "en_US"}
probe_env = api.Environment(env.cr, SUPERUSER_ID, context)
registry = probe_env.registry
token = uuid4().hex[:10].upper()

warehouse = probe_env["stock.warehouse"].search([
    ("company_id", "=", company.id),
], limit=1)
cash_journal = probe_env["account.journal"].search([
    ("company_id", "=", company.id),
    ("type", "in", ("cash", "bank")),
    ("default_account_id", "!=", False),
    ("active", "=", True),
], limit=1)
mapping = probe_env["baseer.purchase.category.map"].search([
    ("company_id", "=", company.id),
    ("active", "=", True),
], limit=1)
custody = probe_env["baseer.procurement.custody"].search([
    ("company_id", "=", company.id),
    ("is_company_pool", "=", True),
    ("state", "=", "open"),
], limit=1)
if not all((warehouse, cash_journal, mapping, custody)):
    raise RuntimeError("The isolated database lacks a valid capacity fixture.")

representative = probe_env["res.partner"].create({
    "name": "Capacity representative %s" % token,
    "company_id": company.id,
    "is_company": False,
})
representative.with_company(company).write({"is_purchase_representative": True})
supplier = probe_env["res.partner"].create({
    "name": "Capacity supplier %s" % token,
    "supplier_rank": 1,
})
uom = probe_env.ref("uom.product_uom_unit")
raw_category = probe_env["product.category"].create({
    "name": "Capacity raw category %s" % token,
})
raw_product = probe_env["product.product"].create({
    "name": "Capacity raw material %s" % token,
    "categ_id": raw_category.id,
    "uom_id": uom.id,
    "is_storable": True,
})
option = probe_env["baseer.procurement.purchase.option"].create({
    "name": "Capacity unit %s" % token,
    "company_id": company.id,
    "product_id": raw_product.id,
    "uom_id": uom.id,
})


def completed_request(quantity=1.0):
    request = probe_env["baseer.procurement.request"].create({
        "company_id": company.id,
        "warehouse_id": warehouse.id,
        "representative_partner_id": representative.id,
        "line_ids": [Command.create({
            "option_id": option.id,
            "requested_qty": quantity,
            "requested_price": AMOUNT_PER_ROW,
        })],
    })
    request.action_mark_sent()
    request.line_ids.manager_received_qty = quantity
    request.action_confirm_manager_receipt()
    request.line_ids.write({
        "actual_qty": quantity,
        "actual_price": AMOUNT_PER_ROW,
    })
    request.action_confirm_actual_purchase()
    if company.currency_id.compare_amounts(
        request.actual_total, quantity * AMOUNT_PER_ROW
    ):
        raise AssertionError("Completed request total is incorrect.")
    return request


batch_ids = []
batch_request_ids = {}
for round_number in range(1, ROUNDS + 1):
    # Exact primary workflow: one received request is selected once in the
    # batch header and its actual total is split over twenty supplier rows.
    request = completed_request(quantity=ROWS_PER_ROUND)
    probe_env["baseer.procurement.custody.event"].create({
        "custody_id": custody.id,
        "event_type": "funding",
        "event_date": fields.Date.context_today(probe_env.user),
        "amount": ROWS_PER_ROUND * AMOUNT_PER_ROW,
        "cash_journal_id": cash_journal.id,
        "representative_partner_id": representative.id,
        "procurement_request_id": request.id,
        "reference": "PRC capacity funding %s-%02d" % (token, round_number),
    }).action_post()
    line_commands = []
    for index in range(1, ROWS_PER_ROUND + 1):
        values = {
            "sequence": index * 10,
            "partner_id": supplier.id,
            "supplier_ref": "CAP-%s-%02d-%02d" % (token, round_number, index),
            "invoice_date": fields.Date.context_today(probe_env.user),
            "entry_type": "purchase",
            "category_map_id": mapping.id,
            "gross_amount": AMOUNT_PER_ROW,
            "is_credit": True,
        }
        line_commands.append(Command.create(values))
    batch = probe_env["baseer.purchase.batch"].create({
        "company_id": company.id,
        "procurement_request_id": request.id,
        "procurement_custody_id": custody.id,
        "procurement_representative_partner_id": representative.id,
        "line_ids": line_commands,
    })
    batch_ids.append(batch.id)
    batch_request_ids[batch.id] = request.id

probe_env.cr.commit()

elapsed_ms = []
for round_index, batch_id in enumerate(batch_ids, start=1):
    with registry.cursor() as action_cr:
        action_env = api.Environment(action_cr, SUPERUSER_ID, context)
        batch = action_env["baseer.purchase.batch"].browse(batch_id)
        balance_before = custody.with_env(action_env)._representative_balance(
            representative.with_env(action_env)
        )
        started = perf_counter()
        batch.action_approve()
        elapsed = (perf_counter() - started) * 1000.0
        action_cr.commit()

    with registry.cursor() as check_cr:
        check_env = api.Environment(check_cr, SUPERUSER_ID, context)
        batch = check_env["baseer.purchase.batch"].browse(batch_id)
        lines = batch.line_ids.sorted(lambda line: (line.sequence, line.id))
        bills = lines.move_id
        settlements = check_env["baseer.procurement.custody.settlement"].search([
            ("batch_line_id", "in", lines.ids),
            ("state", "=", "active"),
        ])
        settlement_moves = settlements.move_id
        request = check_env["baseer.procurement.request"].browse(
            batch_request_ids[batch_id]
        )
        balance_after = custody.with_env(check_env)._representative_balance(
            representative.with_env(check_env)
        )

        if batch.state != "approved" or len(lines) != ROWS_PER_ROUND:
            raise AssertionError("The 20-row batch did not approve atomically.")
        if len(bills) != ROWS_PER_ROUND or len(settlements) != ROWS_PER_ROUND:
            raise AssertionError("Expected exactly 20 bills and 20 settlements.")
        if len(settlement_moves) != ROWS_PER_ROUND:
            raise AssertionError("Expected exactly 20 custody settlement moves.")
        if any(
            line.move_id.ref.strip() != line.supplier_ref.strip()
            or line.move_id.partner_id != line.partner_id
            for line in lines
        ):
            raise AssertionError("Bulk creation changed the line-to-bill order or supplier mapping.")
        if any(move.state != "posted" for move in bills | settlement_moves):
            raise AssertionError("Every generated accounting move must be posted.")
        if any(move.payment_state != "paid" for move in bills):
            raise AssertionError("Every supplier bill must be fully settled.")
        if lines.filtered("payment_id"):
            raise AssertionError("Custody approval must not create direct payments.")
        if batch.procurement_request_id != request:
            raise AssertionError("The selected request was not preserved in the batch header.")
        if company.currency_id.compare_amounts(
            sum(lines.mapped("gross_amount")), request.actual_total
        ):
            raise AssertionError("The header request actual total was not allocated exactly once.")
        if company.currency_id.compare_amounts(
            sum(lines.mapped("gross_amount")), ROWS_PER_ROUND * AMOUNT_PER_ROW
        ):
            raise AssertionError("Approved gross total is incorrect.")
        if company.currency_id.compare_amounts(
            balance_before - balance_after, ROWS_PER_ROUND * AMOUNT_PER_ROW
        ):
            raise AssertionError("Representative custody balance did not fall by 200 SAR.")
        for move in bills | settlement_moves:
            if not company.currency_id.is_zero(sum(move.line_ids.mapped("balance"))):
                raise AssertionError("Generated move %s is unbalanced." % move.display_name)

        elapsed_ms.append(elapsed)
        print(
            "PRC_CAPACITY_ROUND round=%d elapsed_ms=%.3f bills=%d "
            "settlements=%d settlement_moves=%d balance_before=%.2f balance_after=%.2f"
            % (
                round_index, elapsed, len(bills), len(settlements),
                len(settlement_moves), balance_before, balance_after,
            )
        )

ordered = sorted(elapsed_ms)
if not company.currency_id.is_zero(balance_after):
    raise AssertionError("The five rounds did not fully settle their dedicated funding.")
p95_index = max(0, int(0.95 * len(ordered) + 0.999999) - 1)
print(
    "PRC_CAPACITY_APPROVE_PROBE PASS rounds=%d rows_per_round=%d "
    "min_ms=%.3f median_ms=%.3f p95_ms=%.3f max_ms=%.3f "
    "bills=%d settlements=%d final_balance=%.2f"
    % (
        ROUNDS, ROWS_PER_ROUND, min(elapsed_ms), median(elapsed_ms),
        ordered[p95_index], max(elapsed_ms), ROUNDS * ROWS_PER_ROUND,
        ROUNDS * ROWS_PER_ROUND, balance_after,
    )
)
