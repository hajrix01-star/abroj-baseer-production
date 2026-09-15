# Release receipt — Baseer unified operational dashboards

**Freeze date:** 2026-09-15

**Production source baseline:** `863bd851dc107ba8911b417263f21b83270701f0`
**Immutable release tag:** recorded only after the frozen commit and archive hashes
are generated.

## Included scope

- BASSER: owner-managed visibility of approved operational cards; cashier and
  accountant routes remain fixed server allowlists.
- Accountant BASSER: a read-only route to **Supplier bills and expenses**.
- Supplier-bill/expense dashboard: posted supplier bills and refunds only,
  restricted to the active company and selected period; it opens the original
  documents rather than creating any financial records.
- Sales dashboard: an Odoo-style, coloured category distribution card and
  doughnut chart based only on approved sales-summary allocations. Shares,
  highest/lowest category and the bounded **Other** bucket are computed on the
  server with `Decimal`; incomplete allocation coverage intentionally shows no
  percentage or rank.
- Heat calendar target editor and historical Saudi occasions already accepted
  in the candidate line.
- Cashier grouped-purchase workflow and the existing role/company guards.

## Installed module versions

- `baseer_access_roles 19.0.1.0.6`
- `baseer_procurement_requests 19.0.11.0.3`
- `baseer_purchase_batch 19.0.1.2.3`
- `baseer_sales_heat_calendar 19.0.1.0.8`
- `baseer_sales_dashboard 19.0.1.1.6`
- `baseer_purchase_expense_dashboard 19.0.1.0.1`
- `baseer_basser_workspace 19.0.1.0.3`

## Safety boundaries

This candidate does not import, amend, delete, or reconcile operational
business data. The dashboards are read-only and do not create accounting,
invoice, payment, stock, payroll, HR, sales-summary, target, or occasion
records. A production installation only upgrades the modules listed above.

The release archive excludes database dumps, filestores, `.env`, production
`odoo.conf`, sessions, compiled Python artifacts, Noorix source material and
rehearsal-only files. Its payload hash is computed from sorted
`relative-path + NUL + SHA-256(file-content) + newline` records, excluding this
receipt and release manifest; the archive checksum is stored beside the archive
to avoid a self-referential checksum.

## Promotion conditions

Before the production symlink changes, the release operator must:

1. verify the immutable Git tag, GitHub commit and archive/payload SHA-256;
2. rehearse the exact archive against a fresh, isolated DB and filestore copy;
3. take one new, consistent production DB + filestore recovery pair;
4. upgrade only the listed modules while the current release is still active;
5. compare the protected business snapshot before/after the upgrade; and
6. atomically change the `current` symlink only after local and public health
   checks pass. Until users resume work, any failure restores the exact
   database, filestore and prior symlink pair.
