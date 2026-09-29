"""Read the transient Odoo side effects of the QA policy and always roll back."""

import json
from pathlib import Path

payload = json.loads(Path(
    "/mnt/noorix-payload/runs/20260912-product-operational-policy-qa-1/"
    "product-operational-policy-payload.json"
).read_text(encoding="utf-8"))
template_ids = [row["target_product_tmpl_id"] for row in payload["products"]]
product_ids = [row["target_product_id"] for row in payload["products"]]

ProductValue = env["product.value"].sudo()
before_ids = set(ProductValue.search([]).ids)
env["product.template"].sudo().browse(template_ids).write({"is_storable": False})
env.flush_all()
after_flag_ids = set(ProductValue.search([]).ids)
flag_rows = ProductValue.browse(sorted(after_flag_ids - before_ids)).read([
    "product_id", "company_id", "value", "description", "move_id", "lot_id",
])
products = env["product.product"].sudo().browse(product_ids)
for company_id in (1, 2):
    company = env["res.company"].sudo().browse(company_id)
    company_products = products.filtered(lambda item: item.company_id == company)
    env["baseer.procurement.request"].sudo().with_company(company)._default_options_for_products(
        company_products
    )
env.flush_all()
after_options_ids = set(ProductValue.search([]).ids)
option_rows = ProductValue.browse(sorted(after_options_ids - after_flag_ids)).read([
    "product_id", "company_id", "value", "description", "move_id", "lot_id",
])
print(json.dumps({
    "flag_product_value_delta": len(after_flag_ids - before_ids),
    "flag_product_value_targets": len(set(
        row["product_id"][0] for row in flag_rows if row["product_id"]
    )),
    "all_targets": set(row["product_id"][0] for row in flag_rows if row["product_id"]) == set(product_ids),
    "samples": flag_rows[:5],
    "option_product_value_delta": len(after_options_ids - after_flag_ids),
    "option_product_value_targets": len(set(
        row["product_id"][0] for row in option_rows if row["product_id"]
    )),
    "option_all_targets": set(
        row["product_id"][0] for row in option_rows if row["product_id"]
    ) == set(product_ids),
    "option_samples": option_rows[:5],
}, ensure_ascii=False, sort_keys=True, default=str))
env.cr.rollback()
