"""Regression probe for bulk bill order and the native direct-payment route.

This script commits fixtures only in the disposable capacity database.
"""

from uuid import uuid4

from odoo import Command, SUPERUSER_ID, api, fields
from odoo.exceptions import ValidationError


EXPECTED_DATABASE = "baseer_prc_bulk_regression_20260912"
if env.cr.dbname != EXPECTED_DATABASE:
    raise RuntimeError("Bulk approval probe may run only on the disposable capacity database.")

company = env["res.company"].browse(2).exists()
probe_env = api.Environment(
    env.cr, SUPERUSER_ID, {"allowed_company_ids": [company.id], "lang": "en_US"}
)
mapping = probe_env["baseer.purchase.category.map"].search([
    ("company_id", "=", company.id), ("active", "=", True),
], limit=1)
payment_method = probe_env["account.payment.method.line"].search([
    ("journal_id.company_id", "=", company.id),
    ("journal_id.type", "in", ("bank", "cash")),
    ("payment_type", "=", "outbound"),
], limit=1)
if not company or not mapping or not payment_method:
    raise RuntimeError("The disposable database lacks the direct-payment fixture.")

token = uuid4().hex[:10].upper()
partners = probe_env["res.partner"].create([
    {"name": "Bulk supplier A %s" % token, "supplier_rank": 1},
    {"name": "Bulk supplier B %s" % token, "supplier_rank": 1},
    {"name": "Bulk supplier C %s" % token, "supplier_rank": 1},
])
today = fields.Date.context_today(probe_env.user)
specs = [
    (partners[0], "BULK-A-%s" % token, 11.0, payment_method),
    (partners[1], "BULK-B-%s" % token, 12.0, False),
    (partners[2], "BULK-C-%s" % token, 13.0, payment_method),
]
batch = probe_env["baseer.purchase.batch"].create({
    "company_id": company.id,
    "line_ids": [Command.create({
        "sequence": index * 10,
        "partner_id": partner.id,
        "supplier_ref": reference,
        "invoice_date": today,
        "entry_type": "purchase",
        "category_map_id": mapping.id,
        "gross_amount": amount,
        "is_credit": not bool(method),
        "payment_method_line_id": method.id if method else False,
    }) for index, (partner, reference, amount, method) in enumerate(specs, start=1)],
})
batch.action_approve()
probe_env.cr.commit()

lines = batch.line_ids.sorted(lambda line: (line.sequence, line.id))
if batch.state != "approved" or len(lines) != 3:
    raise AssertionError("The mixed three-row batch did not approve.")
for line, (partner, reference, amount, method) in zip(lines, specs):
    bill = line.move_id
    if (not bill or bill.state != "posted" or bill.partner_id != partner
            or bill.ref.strip() != reference or company.currency_id.compare_amounts(bill.amount_total, amount)):
        raise AssertionError("Bulk create/post changed the line-to-bill mapping.")
    if method:
        if not line.payment_id or bill.payment_state != "paid" or line.payment_id.state != "paid":
            raise AssertionError("The native direct-payment row was not paid and reconciled.")
    elif line.payment_id or bill.payment_state == "paid":
        raise AssertionError("The credit row unexpectedly created a direct payment.")

# Duplicate supplier references must fail before any bulk-created bill remains.
duplicate_ref = "BULK-DUP-%s" % token
duplicate_batch = probe_env["baseer.purchase.batch"].create({
    "company_id": company.id,
    "line_ids": [Command.create({
        "sequence": index * 10,
        "partner_id": partners[0].id,
        "supplier_ref": duplicate_ref,
        "invoice_date": today,
        "entry_type": "purchase",
        "category_map_id": mapping.id,
        "gross_amount": 5.0,
        "is_credit": True,
    }) for index in (1, 2)],
})
try:
    duplicate_batch.action_approve()
except ValidationError:
    pass
else:
    raise AssertionError("A duplicate supplier reference was accepted.")
if duplicate_batch.state != "draft" or duplicate_batch.line_ids.move_id:
    raise AssertionError("Duplicate-reference rejection left a bill or approved batch.")

# Force a failure immediately after native multi-post.  The approval savepoint
# must roll back every created/posted bill and preserve the draft batch.
atomic_refs = ["BULK-ROLLBACK-%s-%d" % (token, index) for index in (1, 2, 3)]
atomic_batch = probe_env["baseer.purchase.batch"].create({
    "company_id": company.id,
    "line_ids": [Command.create({
        "sequence": index * 10,
        "partner_id": partners[index - 1].id,
        "supplier_ref": reference,
        "invoice_date": today,
        "entry_type": "purchase",
        "category_map_id": mapping.id,
        "gross_amount": 7.0 + index,
        "is_credit": True,
    }) for index, reference in enumerate(atomic_refs, start=1)],
})
move_class = type(probe_env["account.move"])
original_action_post = move_class.action_post


def forced_failure_after_post(records):
    result = original_action_post(records)
    if any((record.ref or "") in atomic_refs for record in records):
        raise ValidationError("Forced bulk-post rollback probe")
    return result


move_class.action_post = forced_failure_after_post
try:
    try:
        atomic_batch.action_approve()
    except ValidationError as error:
        if "Forced bulk-post rollback probe" not in str(error):
            raise
    else:
        raise AssertionError("The forced post failure was not raised.")
finally:
    move_class.action_post = original_action_post

atomic_batch.invalidate_recordset()
atomic_batch.line_ids.invalidate_recordset()
leaked_moves = probe_env["account.move"].search_count([
    ("company_id", "=", company.id), ("ref", "in", atomic_refs),
])
if atomic_batch.state != "draft" or atomic_batch.line_ids.move_id or leaked_moves:
    raise AssertionError("The forced multi-post failure was not rolled back atomically.")

probe_env.cr.commit()
print(
    "PRC_PURCHASE_BATCH_BULK_PROBE PASS rows=3 mapped=3 direct_paid=2 "
    "credit_open=1 duplicate_rejected=1 atomic_rollback=1 leaked_moves=0"
)
