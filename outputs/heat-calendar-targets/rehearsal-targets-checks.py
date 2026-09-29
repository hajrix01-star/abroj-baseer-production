"""Target-rule acceptance checks for the disposable production rehearsal.

Executed with ``odoo shell`` only against the fresh rehearsal database.  All
records below are left in the shell transaction and are rolled back on exit.
"""
from odoo import Command
from odoo.exceptions import AccessError


company = env["res.company"].search([("name", "=", "ARZ")], limit=1)
assert company, "ARZ company is required for this rehearsal"
base_group = env.ref("base.group_user")
pos_group = env.ref("point_of_sale.group_pos_user")
manager_group = env.ref("baseer_sales_heat_calendar.group_heat_calendar_manager")
Target = env["baseer.heat.calendar.target"]
Wizard = env["baseer.heat.calendar.target.wizard"]


def user(login, groups):
    return env["res.users"].sudo().with_context(
        no_reset_password=True,
        mail_create_nosubscribe=True,
    ).create({
        "name": login,
        "login": login,
        "email": f"{login}@example.invalid",
        "company_id": company.id,
        "company_ids": [Command.set([company.id])],
        "group_ids": [Command.set([base_group.id, pos_group.id, *groups])],
    })


manager = user("hct_rehearsal_manager", [manager_group.id])
pos_only = user("hct_rehearsal_pos", [])
context = {"allowed_company_ids": [company.id]}
source_before = env["baseer.pos.summary"].search_count([])

try:
    Wizard.with_user(pos_only).with_context(**context).default_get([
        "company_id", "year", "month", "weekday",
    ])
    raise AssertionError("POS reader opened target setup")
except AccessError:
    print("HCT_POS_TARGET_SETUP_DENIED")


def apply(weekday, amount):
    wizard = Wizard.with_user(manager).with_context(**context).create({
        "company_id": company.id,
        "year": 2099,
        "month": "1",
        "weekday": weekday,
        "target_amount": amount,
    })
    wizard.action_apply()


apply("3", 200)  # Thursday
apply("4", 100)  # Friday
assert Target.search_count([
    ("company_id", "=", company.id), ("year", "=", 2099),
    ("month", "=", 1), ("weekday", "=", 3),
]) == 1
assert Target.search_count([
    ("company_id", "=", company.id), ("year", "=", 2099),
    ("month", "=", 1), ("weekday", "=", 4),
]) == 1

existing = Wizard.with_user(manager).with_context(**context).create({
    "company_id": company.id,
    "year": 2099,
    "month": "1",
    "weekday": "3",
    "target_amount": 1,
})
existing._onchange_scope()
assert existing.target_amount == 200
apply("3", 50)
thursday = Target.search([
    ("company_id", "=", company.id), ("year", "=", 2099),
    ("month", "=", 1), ("weekday", "=", 3),
], limit=1)
assert thursday.target_amount == 50
assert env["baseer.pos.summary"].search_count([]) == source_before
print("HCT_EXACT_THURSDAY_FRIDAY_UPSERT_OK")
print("HCT_SOURCE_SUMMARIES_UNCHANGED")
