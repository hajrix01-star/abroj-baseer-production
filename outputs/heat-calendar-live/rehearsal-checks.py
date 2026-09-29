"""Disposable rehearsal-only checks, executed through `odoo shell`.

The accounts are created only in baseer_heat_rehearsal.  They are never
copied to or run against the production database.
"""
import json
import os

from odoo import Command
from odoo.exceptions import AccessError


company_names = ("ARZ", "المعلم الشامي", "دوحة المستهلك", "SHAMI TAX")
companies = env["res.company"].search([("name", "in", company_names)])
assert len(companies) == 4, f"Expected four live companies, found {len(companies)}"
rehearsal_password = os.environ["HC_REHEARSAL_PASSWORD"]
protected_models = (
    "account.move", "account.move.line", "account.payment", "hr.employee",
    "hr.payslip", "res.partner", "baseer.pos.daily.report",
)


def protected_snapshot():
    """Count business records without test-user contact records.

    Odoo creates a contact for every disposable rehearsal user.  Those are
    deliberately excluded from the business-partner count, while all partner
    records with no linked user still prove that operational contact data was
    not changed by this acceptance script.
    """
    return {
        model: env[model].sudo().with_context(active_test=False).search_count(
            [("user_ids", "=", False)] if model == "res.partner" else [],
        )
        for model in protected_models
    }

base_user = env.ref("base.group_user")
pos_user_group = env.ref("point_of_sale.group_pos_user")
probe = env["res.users"].sudo().with_context(
    no_reset_password=True,
    mail_create_nosubscribe=True,
).search([("login", "=", "hc_release_probe")], limit=1)
values = {
    "name": "Heat Calendar Release Probe (rehearsal only)",
    "login": "hc_release_probe",
    "email": "hc-release-probe@example.invalid",
    "password": rehearsal_password,
    "company_id": companies[0].id,
    "company_ids": [Command.set(companies.ids)],
    "group_ids": [Command.set([base_user.id, pos_user_group.id])],
}
if probe:
    probe.write(values)
else:
    probe = env["res.users"].sudo().with_context(
        no_reset_password=True,
        mail_create_nosubscribe=True,
    ).create(values)
# `odoo shell` rolls its transaction back on exit.  Commit only this disposable
# rehearsal account so a separate HTTP worker can authenticate it; all later
# target/role probes remain within the shell transaction and are rolled back.
env.cr.commit()

# The committed HTTP-only probe account has a partner by design.  Take the
# protected-data baseline after that declared, rehearsal-only setup; all role
# and target probes below remain inside the rollback-only shell transaction.
protected_before = protected_snapshot()

auth_info = env["res.users"].authenticate({
    "type": "password",
    "login": "hc_release_probe",
    "password": rehearsal_password,
}, {})
assert auth_info["uid"] == probe.id, "Rehearsal HTTP probe authentication mismatch"
probe.with_user(probe)._check_credentials({
    "type": "password",
    "password": rehearsal_password,
}, {"interactive": True, "REMOTE_ADDR": "172.28.0.1"})
print("HC_REHEARSAL_LOGIN_OK")

dashboard = env["spreadsheet.dashboard"].search(
    [("baseer_dashboard_kind", "=", "sales_heat_calendar"), ("is_published", "=", True)],
    limit=1,
)
assert dashboard, "Published heat calendar dashboard missing"
print("HC_METADATA|" + json.dumps({
    "dashboard_id": dashboard.id,
    "companies": [{"id": company.id, "name": company.name} for company in companies],
}, ensure_ascii=False, sort_keys=True))

for company in companies:
    payload = dashboard.with_user(probe).with_context(
        allowed_company_ids=[company.id],
    ).with_company(company).get_baseer_heat_calendar("2026-09")
    assert payload["company"]["id"] == company.id
    assert payload["month"] == "2026-09"
    assert len(payload["weekdays"]) == 7
    print(f"HC_COMPANY_OK|{company.id}|{company.name}|{len(payload['weeks'])}")

company_a, company_b = companies[0], companies[1]
manager_group = env.ref("baseer_sales_heat_calendar.group_heat_calendar_manager")
system_group = env.ref("base.group_system")
Target = env["baseer.heat.calendar.target"]
foreign_target = Target.sudo().create({
    "company_id": company_b.id,
    "year": 2099,
    "month": 1,
    "weekday": 1,
    "target_amount": 1,
})
try:
    for login, group in (
        ("hc_release_manager_a", manager_group),
        ("hc_release_system_a", system_group),
    ):
        user = env["res.users"].sudo().with_context(
            no_reset_password=True,
            mail_create_nosubscribe=True,
        ).search([("login", "=", login)], limit=1)
        values = {
            "name": login,
            "login": login,
            "email": f"{login}@example.invalid",
            "company_id": company_a.id,
            "company_ids": [Command.set([company_a.id])],
            "group_ids": [Command.set([base_user.id, pos_user_group.id, group.id])],
        }
        if user:
            user.write(values)
        else:
            user = env["res.users"].sudo().with_context(
                no_reset_password=True,
                mail_create_nosubscribe=True,
            ).create(values)
        denied = foreign_target.with_user(user).with_context(
            allowed_company_ids=[company_a.id],
        )
        try:
            denied.read(["target_amount"])
            raise AssertionError(f"{login} read foreign target")
        except AccessError:
            pass
        try:
            denied.write({"target_amount": 2})
            raise AssertionError(f"{login} wrote foreign target")
        except AccessError:
            pass
        print(f"HC_CROSS_COMPANY_DENIED|{login}")

    manager = env["res.users"].sudo().search([("login", "=", "hc_release_manager_a")], limit=1)
    local_target = Target.with_user(manager).with_context(
        allowed_company_ids=[company_a.id],
    ).create({
        "company_id": company_a.id,
        "year": 2099,
        "month": 1,
        "weekday": 2,
        "target_amount": 1,
    })
    local_target.unlink()
    print("HC_MANAGER_LOCAL_CREATE_OK")

    pos_only = env["res.users"].sudo().with_context(
        no_reset_password=True,
        mail_create_nosubscribe=True,
    ).create({
        "name": "hc_release_pos_a",
        "login": "hc_release_pos_a",
        "email": "hc_release_pos_a@example.invalid",
        "company_id": company_a.id,
        "company_ids": [Command.set([company_a.id])],
        "group_ids": [Command.set([base_user.id, pos_user_group.id])],
    })
    try:
        dashboard.with_user(pos_only).with_context(
            allowed_company_ids=[company_b.id],
        ).with_company(company_b).get_baseer_heat_calendar("2026-09")
        raise AssertionError("limited POS user accessed another company")
    except AccessError:
        print("HC_LIMITED_POS_CROSS_COMPANY_DENIED")
finally:
    foreign_target.sudo().unlink()

protected_after = protected_snapshot()
assert protected_before == protected_after, "Protected business data changed during rehearsal checks"
print("HC_PROTECTED_SNAPSHOT|" + json.dumps({
    "before": protected_before,
    "after": protected_after,
}, sort_keys=True))
print("HC_REHEARSAL_ORM_ACCEPTANCE_OK")
