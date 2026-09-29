"""Rename QA-only supplier tags to concise product/service classifications.

Run through ``odoo shell``.  Default mode is dry-run; set
``NOORIX_TAGS_APPLY=1`` to apply one checked transaction.
"""

import json
import os
import re
import unicodedata


RENAMES = {
    "موردون نقديون غير مسمين": "نقدي غير مسمى",
    "موردو أثاث": "أثاث",
    "موردو أجهزة وإلكترونيات": "أجهزة وإلكترونيات",
    "موردو أصول ومعدات": "أصول ومعدات",
    "موردو أكياس": "أكياس",
    "موردو بضاعة تموينية": "بضاعة تموينية",
    "موردو بلاستيكات": "بلاستيكات",
    "موردو تعبئة وتغليف": "تعبئة وتغليف",
    "موردو خامات": "خامات",
    "موردو خضار وفواكه": "خضار وفواكه",
    "موردو دواجن": "دواجن",
    "موردو شحوم": "شحوم",
    "موردو شيشة": "شيشة",
    "موردو علب وأكواب": "علب وأكواب",
    "موردو غاز طبخ": "غاز طبخ",
    "موردو مشروبات غازية": "مشروبات غازية",
    "موردو فحم": "فحم",
    "موردو قطع غيار": "قطع غيار",
    "موردو قهوة وبن": "قهوة وبن",
    "موردو لحوم": "لحوم",
    "موردو مستلزمات تشغيل مطبخ": "مستلزمات تشغيل مطبخ",
    "موردو مشروبات": "مشروبات",
    "موردو معدات مكتبية": "معدات مكتبية",
    "موردو معسل": "معسل",
    "موردو مواد غذائية": "مواد غذائية",
    "موردو وقود وخدمات نقل": "وقود ومواصلات",
}


def normalized_name(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")
    return re.sub(r"[^\w\u0600-\u06ff]+", "", value)


if len({normalized_name(name) for name in RENAMES.values()}) != len(RENAMES):
    raise RuntimeError("Target tag names are not unique after normalization.")

Tag = env["res.partner.category"].sudo()
all_tags = Tag.search([], order="id")
tags_by_normalized_name = {normalized_name(tag.name): tag for tag in all_tags}
rename_records = []
already_renamed = []
checked_records = []
for old_name, new_name in RENAMES.items():
    record = tags_by_normalized_name.get(normalized_name(old_name))
    renamed_record = tags_by_normalized_name.get(normalized_name(new_name))
    if record and renamed_record and renamed_record.id != record.id:
        raise RuntimeError(f"Target name already belongs to another tag: {new_name}")
    if record:
        rename_records.append((record, new_name))
        checked_records.append(record)
    elif renamed_record:
        already_renamed.append({"id": renamed_record.id, "name": new_name})
        checked_records.append(renamed_record)
    else:
        raise RuntimeError(f"Expected QA tag is missing: {old_name}")

tag_ids = [record.id for record in checked_records]
linked_partner_count = env["res.partner"].sudo().search_count([("category_id", "in", tag_ids)])
env.cr.execute(
    "SELECT COUNT(*) FROM baseer_noorix_supplier_category_map WHERE category_id = ANY(%s)",
    [tag_ids],
)
linked_category_map_count = env.cr.fetchone()[0]
if linked_partner_count or linked_category_map_count:
    raise RuntimeError(json.dumps({
        "linked_partner_count": linked_partner_count,
        "linked_category_map_count": linked_category_map_count,
    }))

apply = os.getenv("NOORIX_TAGS_APPLY") == "1"
if apply:
    for record, new_name in rename_records:
        record.write({"name": new_name})
    env.cr.commit()

print(json.dumps({
    "mode": "apply" if apply else "dry_run",
    "rename_count": len(RENAMES),
    "pending_rename_count": len(rename_records),
    "already_renamed_count": len(already_renamed),
    "linked_partner_count": linked_partner_count,
    "linked_category_map_count": linked_category_map_count,
    "already_renamed": already_renamed,
    "renames": [{"id": record.id, "old": record.name if not apply else old, "new": new} for (record, new), old in zip(rename_records, RENAMES)],
}, ensure_ascii=False, sort_keys=True))
