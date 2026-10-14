"""Fixed reviewed production preflight/setup, executed only by deploy wrapper.

This script never imports QA IDs, document bytes, employee names, or historical
attachments. Its sole write phase creates company document configuration.
"""
import json
import os
from types import SimpleNamespace

from odoo.tools.safe_eval import safe_eval


assert env.cr.dbname == "baseer_prod", "DMS setup requires the production database"
phase = os.environ.get("DMS_PRODUCTION_PHASE")
assert phase in ("preflight", "setup"), "Unknown DMS production phase"
env.cr.rollback()
if phase == "preflight":
    env.cr.execute("SET TRANSACTION READ ONLY")

required = {"base", "web", "mail", "http_routing", "onboarding", "portal", "account", "hr", "purchase"}
states = {module.name: module.state for module in env["ir.module.module"].sudo().search([("name", "in", sorted(required))])}
assert all(states.get(name) == "installed" for name in required), "Required native applications are not installed"
assert all(model in env for model in ("hr.employee", "hr.version", "purchase.order", "account.move")), "Required source models are missing"
for model in ("hr.employee", "hr.version", "purchase.order", "account.move"):
    assert "company_id" in env[model]._fields, "Source company field is missing"
assert "employee_id" in env["hr.version"]._fields, "Employment version employee field is missing"

owner = env.ref("base.user_admin").sudo()
assert owner.id == 2 and owner.active, "The private owner identity is not active"
actor = owner.with_user(owner)
assert not actor.env.su, "Owner role checks must use the ordinary owner environment"
assert actor.has_group("base.group_system") and actor.has_group("hr.group_hr_user"), "Owner system and HR roles are required"
companies = owner.company_ids.filtered("active").sorted("id")
assert companies, "The owner has no active allowed companies"

if phase == "preflight":
    print("DMS_PRODUCTION_PREFLIGHT=GO")
    print("DMS_COMPANY_COUNT=" + str(len(companies)))
    env.cr.rollback()
else:
    installed = {module.name: module.state for module in env["ir.module.module"].sudo().search([
        ("name", "in", ["dms", "baseer_dms_trial", "baseer_dms_bill_link", "baseer_dms_departments"])
    ])}
    assert len(installed) == 4 and all(state == "installed" for state in installed.values()), "The four private document modules must be installed"
    # DMS XML legitimately assigns its manager role to the existing administrator;
    # no manual grants of HR, accounting, system, company, or other business roles.
    assert actor.has_group("dms.group_dms_manager"), "Native DMS administrator assignment is missing"
    for name in ("private_storage", "private_directory", "private_file", "private_group", "private_share", "private_attachment"):
        rule = env.ref("baseer_dms_trial." + name).sudo()
        assert rule.active and rule["global"], "An owner-private global rule is disabled"
        assert all(rule[field] for field in ("perm_read", "perm_create", "perm_write", "perm_unlink")), "An owner-private rule permission is missing"
        assert safe_eval(rule.domain_force, {"user": SimpleNamespace(id=owner.id)}) == [], "The rule does not allow its owner"
        denied = safe_eval(rule.domain_force, {"user": SimpleNamespace(id=owner.id + 1)})
        expected = [("res_model", "not in", ["dms.file", "dms.directory"])] if name == "private_attachment" else [("id", "=", 0)]
        assert denied == expected, "The owner-private denial changed"
    for xmlid in (
        "baseer_dms_bill_link.bill_source_access", "baseer_dms_departments.managed_hr_directory_access",
        "baseer_dms_departments.managed_hr_file_directory_access",
    ):
        rule = env.ref(xmlid).sudo()
        assert rule.active and rule["global"], "A source or private HR global rule is disabled"

    files = env["dms.file"].sudo().with_context(active_test=False)
    before_links = files.search_count([("bill_attachment_id", "!=", False)])
    scoped = companies.with_user(owner).with_context(allowed_company_ids=companies.ids, lang=owner.lang)
    topology = scoped._setup_dms_departments()
    env.flush_all()
    assert set(topology) == set(companies.ids), "Company configuration is incomplete"
    assert all(len(folders) == 8 for folders in topology.values()), "Department scaffold is incomplete"
    directory_model = env["dms.directory"].sudo().with_context(active_test=False)
    before_folder_count = directory_model.search_count([("managed_key", "!=", False)])
    assert scoped._setup_dms_departments() == topology, "Department setup changed existing folder identities"
    env.flush_all()
    assert directory_model.search_count([("managed_key", "!=", False)]) == before_folder_count, "Department setup duplicated folders"
    assert files.search_count([("bill_attachment_id", "!=", False)]) == before_links, "Historical indexing is not authorized"
    managed = env["dms.directory"].sudo().with_context(active_test=False).search([("managed_key", "!=", False)])
    assert not managed.filtered("access_token"), "Managed folders contain public tokens"
    assert not files.search_count([("bill_attachment_id", "!=", False), ("access_token", "!=", False)]), "Original document references contain public tokens"
    blocked = env["ir.attachment"]._dms_managed_models()
    assert blocked == {"account.move", "purchase.order", "hr.employee", "hr.version"}, "The managed source allowlist changed"
    assert not env["dms.storage"].sudo().search_count([("model_ids.model", "in", sorted(blocked))]), "Native source indexing is enabled"
    for company in scoped:
        root = company.dms_company_root_id
        assert root.company_id == company and not root.parent_id, "Company hierarchy is invalid"
        assert root.group_ids and set(root.group_ids.mapped("explicit_user_ids").ids) == {owner.id}, "Company document access group is not owner-private"
        for counters in (False, True):
            response = scoped.env["dms.file"].with_context(allowed_company_ids=[company.id]).search_panel_select_range(
                "directory_id", enable_counters=counters
            )
            assert response.get("parent_field") == "parent_id", "Document search panel is invalid"
            ids = {item["id"] for item in response["values"]}
            assert root.id in ids and all(not item["parent_id"] or item["parent_id"] in ids for item in response["values"]), "Document search panel hierarchy is incomplete"
    env.cr.commit()
    print("DMS_PRODUCTION_SETUP=GO")
    print("DMS_COMPANY_COUNT=" + str(len(companies)))
    print("DMS_TOPOLOGY=" + json.dumps(topology, sort_keys=True))
