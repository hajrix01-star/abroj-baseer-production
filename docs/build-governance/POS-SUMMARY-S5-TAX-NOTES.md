# S5 — tax-inclusive prices: read-only settings audit

2026-09-08, Asia/Riyadh. QA database `baseer_reports_qa_20260907` only. Installed source: Odoo `19.0-20260817`. This audit made no configuration, source, product-price, tax, or accounting changes. The settings query ended with an explicit transaction rollback. Main was not queried or changed. Clarification of existing prices versus future entry remains with the lead.

## Finding

Odoo already supports tax-inclusive prices through native settings. No new calculation engine is needed. There are two separate controls:

1. Company default `res.company.account_price_include`: `tax_included` / `tax_excluded`. It affects a tax only when that tax has no explicit override.
2. Per-tax `account.tax.price_include_override`: `tax_included` / `tax_excluded` / unset. It overrides the company default. `price_include` itself is computed, not the input setting to write.

The company-wide setting is intentionally locked once accounting lines exist. The model checks any accounting line in the company/descendants, not only paid invoices or posted invoices. All four Saudi QA companies already have accounting lines, so the current company-default route is blocked by native Odoo. This is not evidence that tax-inclusive entry requires custom code: the native per-tax override remains the supported control to evaluate.

## Observed QA settings

| Company | ID | Company price default | Accounting lines / moves | Default sales tax | Default purchase tax |
|---|---:|---|---:|---:|---:|
| QA ARZ | 6 | tax_excluded | 89 / 37 | 83 | 100 |
| QA المعلم الشامي | 7 | tax_excluded | 16 / 8 | 122 | 139 |
| QA دوحة المستهلك | 8 | tax_excluded | 16 / 8 | 161 | 178 |
| QA الفئات النقدية | 9 | tax_excluded | 59 / 23 | 200 | 217 |

All listed companies use SAR and `round_globally`. Their ordinary 15% sales and purchase taxes have no override and currently compute tax-excluded. A read-only native `compute_all(115, quantity=1)` returns net115 / gross132.25 for these ordinary taxes. The additional purchase taxes `15% R C` are special reverse-charge records and must not be included in a blanket ordinary-tax update; their observed total_included remains115 because of their repartition configuration.

Company1, My Company, is USD with zero accounting lines and tax-excluded pricing; it is outside the Saudi rollout target.

QA ARZ POS configurations1 (dedicated summaries) and4 (ordinary cashier) both already use `iface_tax_included='total'`. This is a display setting: it selects the computed included amount for display. It does not change whether an entered/catalogue price is interpreted as gross or net. The dedicated summary product29 currently has list_price1.0; this is not the total of entered external summaries, which use their entered gross amount.

## Existing entry flows

- Baseer sales summaries already take gross including VAT. `models/common.py:native_quote` extracts net with native `force_price_include=True`, then chooses a native invoice/order unit price according to `tax.price_include`. For gross115, both supported tax modes are intended to produce net100 + tax15 = gross115. The current audit only read this code; it did not change or retest an alternative setting.
- Baseer purchase batch uses the same pattern in `models/purchase_batch.py:native_quote`, and creates ordinary supplier bills with that native unit price. Its gross input does not need to be relabelled or multiplied when an included-tax configuration is adopted.
- Ordinary product `list_price` is a stored sales-price number. Changing tax interpretation does not automatically convert that catalogue value. If a stored100 currently means net100/gross115, switching its tax to included while keeping100 means gross100/net86.96. Keeping the customer total115 requires a separate, explicitly chosen catalogue-price conversion.
- Supplier pricelist `product.supplierinfo.price` is a separate purchase-unit price. Native purchase lines adapt supplier/product taxes using `_fix_tax_included_price_company`. Vendor price conventions must therefore be reviewed alongside purchase taxes; a sales-only switch is not sufficient for all purchase entry.
- Product `standard_price` is accounting/inventory cost used for valuation and margin calculations. It is not a universal VAT-inclusive customer price and must not be multiplied or relabelled in a blanket “all prices” operation.
- New-product default sales/purchase taxes come from company default tax IDs. Existing products already store their sales/purchase tax links and require explicit scope decisions; merely changing the default does not replace all existing product tax relations. Fiscal-position mappings, pricelist rules and imported/manual invoice lines must be included in any prospective rollout check.

## Minimum native rollout to prepare after scope clarification

1. Decide whether existing catalogue/vendor amounts must preserve their final gross value, or be treated as newly entered gross amounts. Do not infer or silently reprice existing products.
2. For a truly empty company, use native company Prices → Tax Included before any accounting lines. For these already-used QA companies, do not bypass `_check_set_account_price_include` or force SQL updates.
3. Prefer new native copies of the ordinary 15% sale/purchase taxes with `price_include_override='tax_included'`, preserving the original tax accounts, repartition, tags and Saudi localization semantics. Keep the old tax records for historical interpretation. This is a proposed route, not an action already performed.
4. Assign prospective company defaults and the intended products/vendor entry mappings to the included taxes. Review the dedicated summary tax and purchase-batch default selection so that both continue to use their native gross adapters. Retain zero/exempt/reverse-charge distinctions.
5. Check representative normal sale, supplier bill, POS item, sales summary and purchase batch: entered115 → net100/tax15/gross115; verify discounts, multiple quantities, refunds, zero-tax cases and both company isolation and historical totals. Do not broadly rerun unrelated financial changes.

Historical posted documents must not be rewritten or bulk-recomputed. Changing a tax in place changes the meaning of its linked unit prices when drafts, copies, refunds, or price computations use the current tax definition. The native tax write method itself does not contain a price-override history guard; absence of that guard is not assurance that an in-place change preserves every historical presentation/recalculation. Use a before/after fingerprint and prospective tax IDs for a clean boundary. Existing `round_globally` should not be changed incidentally: rounding is a separate financial behavior and needs its own justification and examples.

## Source evidence

Installed container paths, inspected directly:

- `account/models/company.py:272`: company price selection; `:325` native change constraint; `:992` `_existing_accounting` searches accounting lines.
- `account/views/res_config_settings_views.xml:69–75`: Prices setting readonly after accounting starts; adjacent rounding help explains per-line advice for included prices.
- `account/models/account_tax.py:137–148`: computed `price_include` and explicit override; `:306–323` resolution/search rules; `:634–676` sanitized create/write path.
- `account/models/product.py:39–51`: product sales and supplier tax defaults from the company.
- `product/models/product_template.py:94–106`: sales price versus inventory cost; `product/models/product_supplierinfo.py:30`: vendor unit price.
- `purchase/models/purchase_order_line.py:448,465`: native supplier/product included-tax price adaptation.
- `point_of_sale/models/pos_config.py:111`: tax display; `point_of_sale/static/src/app/models/accounting/product_template_accounting.js:202–209` chooses total_included versus total_excluded for display.
- `l10n_sa/data/template/account.tax-sa.csv`: ordinary Saudi15% templates leave the override empty; special/reverse-charge templates remain distinct.
- Workspace `custom_addons/baseer_pos_summary/models/common.py:55–71` and `custom_addons/baseer_purchase_batch/models/purchase_batch.py:63–90`: existing gross-entry adapters.

Read-only conclusion for the lead: **settings first, native per-tax override if company default is locked, no custom bypass of the accounting lock; resolve old-versus-new price semantics before any changes.**
