# Noorix products — company-scoped QA plan

## Owner decision

Products are **company-specific**, unlike the previously migrated global suppliers.  A Noorix item is never made shared in Odoo merely because another company has the same name.  Every created target product must have the mapped target `company_id` and retain its immutable Noorix item identity in a private source map.

## Verified company mapping

| Noorix company | Source items | Active | Odoo QA company | Target company ID | Product policy |
| --- | ---: | ---: | --- | ---: | --- |
| `ARZ` | 713 | 383 | `ARZ` | 1 | Company-specific only |
| `المعلم الشامي` | 85 | 85 | `المعلم الشامي` | 2 | Company-specific only |

`TEST` and `TEST1` are excluded.  The other source companies contain no product items in this archive slice.

## Proposed master-data write after approval

- Create 382 active company-1 products for `ARZ` and 85 active company-2 products for `المعلم الشامي`: **467 target products** in total from 468 active source rows.  Owner approved unification of the two ARZ `افوكادو` spelling variants into one company-1 purchase product; the deterministic primary source is `v4m_5e72f130d19098f85987` and both source identities map to that target.  All 330 inactive source items are excluded from the target product-master write by owner direction.  One of them is referenced by a source document line, but remains source evidence only; a later historical-document decision must not silently create it as an operational Odoo product.
- Create no shared (`company_id=False`) product from Noorix.
- Reuse no existing Odoo product.  Noorix has no populated SKU, and exact normalized-name comparison found no unique target product match.
- Store one immutable source map per Noorix item: `(source_system, tenant_id, source_company_id, source_item_id) → company-scoped product`.
- Map source usage exactly: the 364 canonical `purchased` products receive `purchase_ok=True, sale_ok=False`; the 103 `sale` products receive `purchase_ok=False, sale_ok=True`.  No product receives both flags in this slice.  Product type is fixed to Odoo `Goods` and source tracking maps to `is_storable`; stock quantities and valuation remain separate decisions.
- Create no stock quantity, stock valuation, price, sale order, purchase order, invoice, account, tax or journal in the product-master slice.  Product type is fixed to Odoo `Goods` (`type='consu'`); the Noorix `track_inventory` field maps only to Odoo `is_storable` and does not create inventory valuation or quantity.

## Categories and units are separate prerequisites

Odoo product categories and units are global technical masters; they do not make a product global.  Product company isolation is enforced by `product.template.company_id`.

### Categories

- Noorix has 58 referenced product categories across the two item-owning companies; 248 ARZ items have no category (21 of them active).
- The target has one direct category-name match only.  A category crosswalk/new-category plan must be approved before product creation, rather than inferring a category from a product name.

### Units used by products

Twelve source unit records resolve to nine logical unit labels across the two item-owning companies.

| Group | Source units | Status |
| --- | --- | --- |
| Measured/count units | `حبة`, `جرام`, `كيلو`, `لتر`, `مل` | Source dimension and conversion factor are present; map only after Odoo UoM-category validation. |
| Package units | `can/carton`, `packet`, `صندوق`, `قارورة` | **Blocked from automatic conversion**: source has no canonical conversion factor.  They must remain an explicit package unit or receive an owner-approved conversion. |

## Duplicate guard

The creation writer must never merge an item merely because its name matches.  Read-only analysis found no exact normalized-name candidate among existing Odoo QA products and no populated Noorix SKU.  It found six repeated active names inside `ARZ`; five differ in source type or category and are retained as distinct source items.  One group is a strong possible duplicate: two active `افوكادو` purchase items have the same unit and category.  Both source identities are retained in evidence, but the product writer must hold that group out of automatic creation until the owner chooses one canonical item or explicitly requests two separate products.  Eight same-name groups span different source companies and are not duplicates under the owner-approved company-specific product policy.

## Reconciliation gates

1. All 467 target products must have exactly the intended company ID; zero must be shared.
2. Counts must reconcile 382 active products to company 1 and 85 active products to company 2; source-map count remains 468.
3. Every product must have an approved unit; the four package-unit labels cannot be silently converted to `حبة`.
4. Every source row must have exactly one immutable mapping, and a replay with the same payload must be a no-op.
5. A separate inventory/valuation migration must reconcile opening quantities and cost later; it is outside this product-master slice.

## Review-label normalization

- The product review payload preserves every existing Noorix English product label.  It supplies an English translation for each of the 143 source product rows that has no English label (140 distinct Arabic labels).  A Shisha-category product is never given a newly inferred English product translation; the current snapshot has zero missing-English products in that category.
- The category-review payload keeps the raw Noorix category value visible, but puts the approved Arabic and English values in their correct columns.  For example, raw `DRINK`, `FOOD`, `OFFER`, `Shisha` and `SWEETS` are represented as `مشروبات / DRINK`, `مواد غذائية / FOOD`, `عروض / OFFER`, `شيشة / Shisha` and `حلويات / SWEETS` respectively.  The same rule defensively corrects an Arabic value found in the English field.
- This is a review-payload transformation only.  It does not update the Noorix archive, source-inspection database, Odoo QA, or the protected original Odoo database.  The approved bilingual labels become inputs to a later category/product write after the remaining category and UoM gates are approved.

## Proposed QA category and UoM setup

- The current QA has the global roots `Food` and `Goods`.  The reviewed product payload proposes 47 distinct active category leaves beneath those existing roots.  Equivalent Noorix labels across companies resolve to the same global technical category; this does not make any product shared.  Products remain assigned only to their mapped company.
- Source categories with no active product (`FOOD`, `OFFER`, and `بترول` in this slice) are not created.  The 21 active source products without a category retain that source exception and use the existing `Goods` root as a conservative default rather than receiving an inferred leaf category.
- Five source units map safely to existing Odoo units: `حبة → الوحدات`, `جرام → g`, `كيلو → كجم`, `لتر → L`, and `مل → مل`.  They cover 456 active source rows, or 455 canonical target products after the approved avocado unification.
- Twelve active source rows use `can/carton`, `packet`, `صندوق`, or `قارورة`.  Noorix provides no factor for any of them.  The proposal is four separate QA root UoMs with factor `1` and no conversion relationship to `الوحدات` or to one another.  No package label may be silently converted to `حبة`.
- The Excel import-plan workbook is the source-to-target crosswalk and readiness evidence.  It remains read-only planning evidence until the QA technical-master write and the 467-product writer are explicitly run and reconciled.

## QA execution field contract

For each product, the QA writer may set only the bilingual name, company, mapped category, mapped UoM, `type='consu'`, source `track_inventory → is_storable`, `tracking='none'`, active state, and the owner-approved purchase/sale flag.  New product-category records are more limited: Odoo 19 exposes only one non-translatable `name`, so they store the approved Arabic label while the approved English label remains in the hash-pinned crosswalk evidence.  Noorix has no populated SKU, so no internal code is created.  Odoo 19 has no separate purchase-UoM field in the installed target model; the mapped source inventory UoM is the only UoM set.  No price, vendor, route, tax, accounting, valuation, stock, image or description field may be written.

The 59 source category records reconcile as 56 active-referenced category identities, two inactive-only referenced identities (`FOOD` and `OFFER`), and one unreferenced identity (`بترول`).  The 56 active identities reduce to 47 semantic target leaves; 21 active items have no source category and use the existing `Goods` root with a visible source-exception flag.  The 75 source UoM records reconcile as 12 active-referenced identities and 63 unused by an active item.  The 12 identities map to nine target UoMs: five existing and four new standalone package roots.
