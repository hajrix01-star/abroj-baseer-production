# Baseer POS invoice discount

Owned Odoo 19 addon. Uses the native **server** `account.tax` global discount
helper and native invoice / Saudi EDI conversion. No third-party ZIP or core
patch is required. This source is a QA candidate, not a ZATCA certification.

## Operation

1. A POS manager opens the POS configuration and selects **Set up invoice
   discount**. The action creates one company-local service product. Set the
   maximum percentage and optionally a maximum amount; amount limit `0` means
   the percentage limit and basket total still apply. The feature starts off.
2. Synchronize the unpaid basket, then choose **Actions → Invoice discount**.
   Choose percentage or fixed amount and enter a reason. A fixed amount is the
   reduction in the customer's total **including VAT**. The server returns the
   complete calculated order.
3. Remove the discount before changing the basket, customer, preset, pricelist
   or taxes. Repeat commands are idempotent. A lost reply blocks payment until
   the exact command is reconciled; do not clear browser storage to bypass it.
4. To refund, select original products in the native ticket screen. The server
   restores their proportional share of the original discount and tax. The last
   refund consumes remaining rounded cents. Finish or cancel another draft
   refund of the same source product before preparing the next one.

Apply/remove/refund preparation requires an online connection. Original native
payment, receipt, invoice, credit-note and Saudi EDI ownership is preserved.
Arabic/English native OWL controls support desktop and touch screens.

## Candidate boundaries

- Company currency with `0.01` rounding; no cash rounding.
- Explicit percentage taxes, including explicit zero/exempt categories.
- Baskets containing unclassified taxes, formula/fixed taxes (including tobacco
  rules), tips, combos or protected substitution items are rejected explicitly.
- Historical refunds require unchanged relevant tax configuration. The addon
  never silently applies current tax settings to a changed historical sale.
- Existing records are not migrated and discount configuration is not enabled
  globally on installation.

## Verification

`node --test custom_addons/baseer_pos_global_discount/tests/*.test.mjs`

Run Odoo with `--test-tags=/baseer_pos_global_discount` on an isolated database.
See `docs/build-governance/POS-GLOBAL-DISCOUNT-QA.md` for exact source, independent
review, actual accounting/XML evidence, QA deployment and outstanding release
gates. A successful XML export alone does not establish ZATCA acceptance.
