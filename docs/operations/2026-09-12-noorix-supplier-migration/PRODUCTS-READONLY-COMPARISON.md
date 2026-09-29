# Noorix products — read-only comparison with Odoo QA

Scope: the SHA-pinned Noorix archive, excluding `TEST` and `TEST1`, compared with the isolated QA database `baseer_noorix_data_migration_qa_20260912`.  This is an inventory and matching report only; it creates or changes no product, category, unit, stock quantity, price, account or financial document.

## Inventory

| Entity | Noorix business scope | Odoo QA current state |
| --- | ---: | ---: |
| Items | 798 total; 468 active; 330 inactive | 89 product templates; 37 active |
| Active item types | 365 purchased; 103 sale | Odoo product type mapping not yet evaluated |
| Categories | 59 active source rows; 52 normalized names | 40 product categories |
| Units | 75 active source rows; 27 normalized names | 30 units; 15 active |
| Sections | 7 active source rows | Not yet mapped |

The 468 active source items belong to `ARZ` (383) and `المعلم الشامي` (85).  Fourteen active item names are duplicated across source rows, so the source does not yet prove that every same-named item is one shared master product.  Twenty-one active items do not reference a source category, while all active items reference an inventory unit.

## Matching result

- Noorix has **no populated SKU** on any business-scope item; a code-based automatic match with Odoo `default_code` is therefore impossible.
- Exact normalized Arabic-name comparison finds **0** of 468 active Noorix items as a unique Odoo product match.
- Only **1** of 59 source category rows has an exact normalized Odoo category-name match; the remaining 58 need an explicit category crosswalk or new category decision.
- Exact normalized unit-name comparison finds **0** of 75 source unit rows as a unique Odoo unit match.  Unit dimensions and conversion factors must be reconciled before items can be imported.

## Decision required before a product QA write

1. Establish a durable product identity for Noorix items (new external/source key; never a guessed name merge).
2. Decide the sharing boundary: a same-name item in two companies remains separate unless code, approved mapping, and unit/dimension prove it is the same item.
3. Approve category and unit crosswalks, including explicit treatment of the 21 uncategorized active items.
4. Reconcile purchase/sale item types, inventory tracking and historical quantities/valuation separately from master-product creation.
