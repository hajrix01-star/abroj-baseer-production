"""Verify the committed Noorix product-source policy in isolated QA."""

import json

TARGET_DATABASE = "baseer_noorix_data_migration_qa_20260912"

if env.cr.dbname != TARGET_DATABASE:
    raise RuntimeError("wrong target database")

ProductMap = env["baseer.noorix.product.map"].sudo()
mapped_templates = ProductMap.search([]).product_tmpl_id
purchase_templates = mapped_templates.filtered(
    lambda item: item.active
    and item.type == "consu"
    and item.purchase_ok
    and not item.sale_ok
)
sale_templates = mapped_templates.filtered(
    lambda item: item.active
    and item.type == "consu"
    and item.sale_ok
    and not item.purchase_ok
)
if len(mapped_templates) != 467 or len(purchase_templates) != 364 or len(sale_templates) != 103:
    raise RuntimeError("mapped product population differs")
if purchase_templates.filtered("is_storable"):
    raise RuntimeError("a purchase product still tracks inventory")

Option = env["baseer.procurement.purchase.option"].sudo()
option_counts = {}
catalog_counts = {}
price_mismatches = []
for company_id, expected in ((1, 279), (2, 85)):
    company = env["res.company"].sudo().browse(company_id)
    products = purchase_templates.filtered(lambda item: item.company_id == company).product_variant_ids
    options = Option.with_company(company).search([
        ("company_id", "=", company.id),
        ("product_id", "in", products.ids),
        ("catalog_default_key", "!=", False),
    ])
    option_counts[str(company_id)] = len(options)
    if len(products) != expected or len(options) != expected:
        raise RuntimeError("company product/default-option count differs")
    for option in options:
        if option.product_id.company_id != company or option.uom_id != option.product_id.uom_id:
            raise RuntimeError("default option identity differs")
        if option.last_price != option.product_id.with_company(company).standard_price:
            price_mismatches.append(option.id)
        if option.last_price_at:
            raise RuntimeError("opening price was marked as an observed purchase")
    Request = env["baseer.procurement.request"].sudo().with_company(company)
    catalog_total = env["product.product"].sudo().with_company(company).search_count(
        Request._catalog_product_domain()
    )
    catalog_counts[str(company_id)] = catalog_total
    if catalog_total != expected:
        raise RuntimeError("product-backed catalog count differs")

if price_mismatches:
    raise RuntimeError("opening option prices differ from company product costs")
if env["stock.quant"].sudo().search_count([]) or env["stock.move"].sudo().search_count([]):
    raise RuntimeError("policy created stock state")

print(json.dumps({
    "status": "verified",
    "mapped_templates": 467,
    "purchase_products": 364,
    "sale_only_products": 103,
    "tracked_purchase_products": 0,
    "default_options": option_counts,
    "catalog_products": catalog_counts,
    "opening_price_mismatches": 0,
    "stock_quants": 0,
    "stock_moves": 0,
}, sort_keys=True))
env.cr.rollback()
