"""QA-only activation with rollback-only synthetic bill lifecycle checks."""
import base64
import json
from pathlib import Path

import odoo.addons.dms as dms_package
from odoo.exceptions import AccessError, UserError, ValidationError

assert env.cr.dbname == "baseer_live_qa_clean_20260928"
env.cr.rollback()
owner = env.ref("base.user_admin")
assert owner.id == 2 and owner.active
assert env["ir.module.module"].search([
    ("name", "=", "baseer_dms_bill_link"), ("state", "=", "installed")
])
for suffix in ("private_storage", "private_directory", "private_file",
               "private_group", "private_share", "private_attachment"):
    assert env.ref("baseer_dms_trial." + suffix).active
companies = owner.company_ids.sorted("id")[:2]
assert len(companies) == 2
assert companies.ids == [1, 2], "Only approved QA companies 1 and 2"
oe = env["res.company"].with_user(owner).with_context(
    allowed_company_ids=companies.ids, lang="ar_001"
).env
assert not oe.su
group = oe["dms.access.group"].browse(2)
assert group.exists() and group.explicit_user_ids == owner
prefix = "QA Bill DMS 20261014"
roots = []
for company in companies:
    oc = oe["res.company"].browse(company.id)
    assert not oc.dms_bill_root_id, "Refuse overwriting an existing root"
    storage = oe["dms.storage"].create({
        "name": prefix + " — " + company.name,
        "company_id": company.id, "save_type": "file",
        "model_ids": [(5, 0, 0)], "include_message_attachments": False,
        "inherit_access_from_parent_record": False,
    })
    root = oe["dms.directory"].create({
        "name": "فواتير المشتريات — " + company.name,
        "is_root_directory": True, "storage_id": storage.id,
        "group_ids": [(6, 0, group.ids)],
    })
    env.flush_all()
    oc.write({"dms_bill_root_id": root.id})
    roots.append(root)

payload = base64.b64encode(
    (Path(dms_package.__file__).parent / "test" / "image01.jpg").read_bytes()
)
assert 0 < len(base64.b64decode(payload)) < 1048576


def denied(call):
    try:
        with env.cr.savepoint():
            call()
            raise AssertionError("Forbidden mutation succeeded")
    except (AccessError, UserError, ValidationError):
        pass


class RollbackSynthetic(Exception):
    pass


observations = []
try:
    with env.cr.savepoint():
        for company, root in zip(companies, roots):
            scoped = oe["account.move"].with_company(company).env
            journal = scoped["account.journal"].search([
                ("company_id", "=", company.id), ("type", "=", "purchase")
            ], limit=1)
            assert journal, "A native purchase journal is required"
            bill = scoped["account.move"].create({
                "move_type": "in_invoice", "company_id": company.id,
                "journal_id": journal.id, "partner_id": company.partner_id.id,
                "ref": "QA DMS rollback-only synthetic",
            })
            before = bill.read(["state", "amount_total", "company_id", "move_type"])
            assert not bill.line_ids and bill.state == "draft"
            attachment = scoped["ir.attachment"].create({
                "name": "QA — صورة فاتورة وهمية.jpg", "type": "binary",
                "res_model": "account.move", "res_id": bill.id,
                "datas": payload, "mimetype": "image/jpeg",
            })
            link = scoped["dms.file"].search([
                ("bill_attachment_id", "=", attachment.id)
            ])
            assert len(link) == 1 and link.company_id.id == company.id
            assert link.directory_id == root
            assert not link.attachment_id and not link.content_file and not link.content_binary
            assert link.content == payload
            assert not scoped["ir.attachment"].search([
                ("res_model", "=", "dms.file"), ("res_id", "=", link.id)
            ])
            attachment._sync_dms_bill_links()
            assert scoped["dms.file"].search_count([
                ("bill_attachment_id", "=", attachment.id)
            ]) == 1
            denied(lambda: link.write({"directory_id": roots[1 if company == companies[0] else 0].id}))
            denied(lambda: link.write({"content": payload}))
            denied(lambda: link.write({"access_token": "INVALID-PROBE"}))
            denied(lambda: link.copy())
            checksum = attachment.checksum
            link.unlink()
            assert attachment.exists() and attachment.datas == payload
            assert attachment.checksum == checksum
            assert bill.read(["state", "amount_total", "company_id", "move_type"]) == before
            attachment._sync_dms_bill_links()
            recreated = scoped["dms.file"].search([
                ("bill_attachment_id", "=", attachment.id)
            ])
            assert len(recreated) == 1
            attachment.unlink()
            assert not recreated.exists()
            observations.append({"company_id": company.id, "root_id": root.id,
                                 "single_original": True, "original_survives_index_unlink": True})
        raise RollbackSynthetic()
except RollbackSynthetic:
    pass

assert not env["account.move"].search([
    ("ref", "=", "QA DMS rollback-only synthetic")
])

for company, root in zip(companies, roots):
    assert oe["res.company"].browse(company.id).dms_bill_root_id == root
    assert not root.access_token and not root.storage_id.model_ids
env.cr.commit()
print("DMS_BILL_LINK_QA=PASS", json.dumps(observations))
print("SYNTHETIC_BILLS=ROLLED_BACK; ROOT_CONFIGURATION=PERSISTED; LIVE=UNTOUCHED")
