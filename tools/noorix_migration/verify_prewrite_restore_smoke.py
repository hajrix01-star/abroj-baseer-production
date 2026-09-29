"""Read database and filestore content from the disposable pre-write restore."""

import json

TARGET_DATABASE = "baseer_noorix_prc_product_source1_restore_smoke_20260913"

if env.cr.dbname != TARGET_DATABASE:
    raise RuntimeError("wrong restore-smoke database")

Attachment = env["ir.attachment"].sudo()
stored = Attachment.search([
    ("store_fname", "!=", False),
    ("file_size", ">", 0),
], order="file_size desc", limit=50)
readable = []
for attachment in stored:
    content = attachment.raw
    if content:
        readable.append({
            "id": attachment.id,
            "bytes": len(content),
            "store_fname": attachment.store_fname,
        })
if not stored or len(readable) != len(stored):
    raise RuntimeError("database/filestore pair is not readable through Odoo")

print(json.dumps({
    "status": "restore_verified",
    "database": env.cr.dbname,
    "database_attachments": Attachment.search_count([]),
    "stored_sample_count": len(stored),
    "readable_sample_count": len(readable),
    "readable_sample_bytes": sum(row["bytes"] for row in readable),
    "sample": readable[:3],
}, sort_keys=True))
env.cr.rollback()
