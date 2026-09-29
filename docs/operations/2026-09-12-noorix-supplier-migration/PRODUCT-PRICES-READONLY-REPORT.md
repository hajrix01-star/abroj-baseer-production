# Noorix product-price read-only report — 2026-09-12

## Scope and boundary

This report reads only the SHA-pinned Noorix archive through a disposable inspection database.  It makes no Odoo price, product, stock, accounting or source write.  It covers the two owner-approved product companies (`ARZ` and `المعلم الشامي`) and excludes two active `TEST`-company rows.

The accepted QA product-master wave has 467 company-scoped targets: 364 purchase-only targets and 103 sale-only targets.  The approved avocado unification reduces two ARZ purchase source identities to one target product.

## Source evidence

`orders_v4_price_history` contains 5,070 history rows for 279 active in-scope source products, dated from 2026-03-29 through 2026-09-12.  Only rows from received purchase documents are eligible for a candidate cost: 4,914 rows across the same 279 source items.  Reversed purchase rows (156) and prepared purchase rows (30 document lines) are excluded from the candidate rule.

There is **no sale-price master/history** in this source slice: all 103 sale-only active items have zero `orders_v4_price_history` rows.  Registration documents have price-bearing lines, but they are inventory/registration events rather than an approved selling-price master; they are excluded from automatic price selection.

For every eligible received-purchase source item, the source `unit_price` equals its `inventory_unit_price` at the latest record.  The inventory-unit price is therefore the only candidate for an Odoo purchase-cost decision; it is not a selling price.

## Latest received-purchase candidate partition

| Target group | Target products | Candidate latest cost | No eligible latest cost | Notes |
| --- | ---: | ---: | ---: | --- |
| ARZ purchase-only | 279 | 193 | 85 | One latest ARZ cost is zero; two avocado source histories resolve to one target. |
| المعلم الشامي purchase-only | 85 | 84 | 1 | One target has no eligible history. |
| All purchase-only | 364 | 277 | 86 | Plus one blocked zero-cost record; the approved 277 are eligible for QA cost only. |
| Sale-only | 103 | 0 | 103 | No sales-price source exists. |

One latest cost is zero and is blocked from any automatic use: ARZ `مساحه ارضيات / Floor Mop` (`v4m_61a8ba72b96a85f64618`), latest received-purchase price 0 on 2026-07-06.

The unified avocado target has two historical source prices: the owner-selected canonical source `v4m_5e72f130d19098f85987` has 20.36 on 2026-08-24; its alias `v4m_aa29dd6c8907b8135acf` has 25.00 on 2026-07-10.  A later price implementation must choose and document its rule (for example latest eligible received cost) rather than treating either source identity as silently authoritative.

The latest-candidate recency distribution is 160 September, 79 August, 30 July, 3 June, 5 May and 2 April-or-earlier source items.  This confirms that “latest” is a historical purchase cost, not necessarily a current contractual supplier price.

## Owner-approved QA cost outcome

The owner approved the 277 non-zero latest received-purchase candidates for the isolated QA database only.  Payload `f9894e12c31cd3e5d0408cf6880e7892800a4fc3496beaaff581bc6d07168d7c` committed as run `20260912-noorix-product-cost-qa-1` (run ID 15): 193 costs in company 1 and 84 in company 2.  It writes only company-dependent Odoo cost (`product.product.standard_price`); it does not write sales prices, price lists, vendor lines, taxes, currencies, stock quantities, valuations or financial documents.

The writer is atomic, source-to-target mapped and replay-safe.  It verified all 277 values after writing and a replay returned `already_committed`.  The QA accounting-move baseline remained 2 before and after, and no `stock.valuation.layer` model is present.  The 86 purchase-only products without eligible cost, the zero-cost floor mop and all 103 sale-only products remain excluded.  The sale-only products retain their pre-existing Odoo default `list_price` of `1.00`; that is not a Noorix selling price and was not altered by this cost wave.  No price is eligible for the protected original database without a separate promotion decision and review.
