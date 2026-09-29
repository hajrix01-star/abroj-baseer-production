"""Create the owner-approved missing Noorix supplier tags in the isolated QA DB.

Run through ``odoo shell --shell-file``.  Default mode is dry-run; set
``NOORIX_TAGS_APPLY=1`` to commit a single idempotent creation transaction.
"""

import json
import os
import re
import unicodedata


DESIRED_TAGS = [
    "نقدي غير مسمى",
    "أثاث",
    "أجهزة وإلكترونيات",
    "أصول ومعدات",
    "أكياس",
    "بضاعة تموينية",
    "بلاستيكات",
    "تعبئة وتغليف",
    "خامات",
    "خضار وفواكه",
    "دواجن",
    "شحوم",
    "شيشة",
    "علب وأكواب",
    "غاز طبخ",
    "مشروبات غازية",
    "فحم",
    "جهات تمويل",
    "قطع غيار",
    "قهوة وبن",
    "لحوم",
    "مستلزمات تشغيل مطبخ",
    "مشروبات",
    "معدات مكتبية",
    "معسل",
    "مواد غذائية",
    "وقود ومواصلات",
]


def normalized_name(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")
    return re.sub(r"[^\w\u0600-\u06ff]+", "", value)


if len({normalized_name(name) for name in DESIRED_TAGS}) != len(DESIRED_TAGS):
    raise RuntimeError("Desired tag names are not unique after normalization.")

Tag = env["res.partner.category"].sudo()
existing = Tag.search([], order="id")
by_normalized_name = {}
duplicate_existing = []
for record in existing:
    key = normalized_name(record.name)
    if key in by_normalized_name:
        duplicate_existing.append({"id": record.id, "name": record.name})
    else:
        by_normalized_name[key] = record

if duplicate_existing:
    raise RuntimeError(json.dumps({"duplicate_existing_tags": duplicate_existing}, ensure_ascii=False))

missing = [name for name in DESIRED_TAGS if normalized_name(name) not in by_normalized_name]
present = [name for name in DESIRED_TAGS if normalized_name(name) in by_normalized_name]
apply = os.getenv("NOORIX_TAGS_APPLY") == "1"
created = []
if apply:
    for name in missing:
        created.append(Tag.create({"name": name}).id)
    env.cr.commit()

print(json.dumps({
    "mode": "apply" if apply else "dry_run",
    "existing_tag_count": len(existing),
    "desired_tag_count": len(DESIRED_TAGS),
    "already_present": present,
    "missing": missing,
    "created_ids": created,
}, ensure_ascii=False, sort_keys=True))
