"""Export the read-only QA supplier/tag state for a Noorix payload build.

Run through ``odoo shell`` and copy the generated JSON from the QA container.
"""

import json
from pathlib import Path


output_path = Path("/tmp/noorix_qa_supplier_target.json")
Partner = env["res.partner"].sudo()
Tag = env["res.partner.category"].sudo()

partners = []
for record in Partner.with_context(active_test=False).search([], order="id"):
    partners.append({
        "id": record.id,
        "vat": record.vat or None,
        "name": record.name or "",
        "active": bool(record.active),
        "parent_id": record.parent_id.id or None,
        "company_id": record.company_id.id or None,
        "supplier_rank": record.supplier_rank,
    })

tags = []
for record in Tag.search([], order="id"):
    tags.append({
        "id": record.id,
        "name": {
            "en_US": record.with_context(lang="en_US").name or "",
            "ar_001": record.with_context(lang="ar_001").name or "",
        },
    })

output_path.write_text(
    json.dumps({"partners": partners, "tags": tags}, ensure_ascii=False, sort_keys=True, indent=2),
    encoding="utf-8",
)
print(json.dumps({"partner_count": len(partners), "tag_count": len(tags), "output": str(output_path)}))
