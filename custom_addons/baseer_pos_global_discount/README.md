# Baseer POS invoice discount

Owned Odoo 19 addon. Uses the native **server** `account.tax` global discount
helper and native invoice / Saudi EDI conversion. No third-party ZIP or core
patch is required. This source is a QA candidate, not a ZATCA certification.

## Operation

1. A POS manager uses the existing **Global Discounts** card in native POS
   settings. Set the maximum percentage and optionally a maximum amount; amount
   limit `0` means the percentage limit and basket total still apply. Enabling
   the feature prepares a company-local discount product automatically.
2. Choose the original **Actions → Discount** button. The dialog opens with a
   fixed amount selected and its input focused. Enter the amount and apply, or
   switch to a percentage. No reason is requested. A fixed amount is the
   reduction in the customer's total **including VAT**. The server returns the
   complete calculated order; user, time and command are audited automatically.
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

The POS settings also have an explicit manager-only action to assign
a company-owned product to the native discount setting. This prepares the
product only; it does not change the current managed discount workflow.

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

Managed shared drafts cancelled or removed on the server are removed locally when neither copy has payments. A POS manager can audit and discard a stuck local copy after checking local payments against the terminal. An unavailable server leaves the copy protected.

### Native fixed discount option

When the legacy invoice-discount flow is not active, managers can enable fixed
amounts on the native discount button and choose who may use them. The optional
maximum is tax-inclusive; zero adds no cap beyond the eligible total. Use the
company product setup button to assign a dedicated native discount product.
The amount can be applied offline, but payment requires a connection to avoid
two devices paying different snapshots of a shared order. Fixed discounts are
recalculated when the order changes. The legacy flow remains in charge when its
existing setting is enabled.
