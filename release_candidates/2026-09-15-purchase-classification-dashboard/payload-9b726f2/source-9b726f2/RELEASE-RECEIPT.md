# Release receipt — Baseer purchase classification and dashboard

**Candidate date:** 2026-09-15  
**Source baseline:** `f54d83bcda4ac3f771661b997c49ad7c193a35df`  
**Candidate commit:** recorded only after this receipt is committed and the
archive is recreated from that commit.

## Included scope

- `baseer_purchase_classification` adds company-isolated reporting categories,
  supplier category mappings, rules and immutable classification legs.
- When a vendor bill or vendor refund is posted, the selected classification is
  captured as a snapshot for that document line. The posting itself remains the
  native Odoo accounting action.
- `baseer_purchase_expense_dashboard` reads those snapshots to show parent and
  child reporting categories. It continues to calculate amounts from native
  posted accounting move lines.
- No Contact Tags are used as the classification source.

## Module versions

- `baseer_purchase_classification 19.0.2.1.0`
- `baseer_purchase_expense_dashboard 19.0.2.0.0`

## Historical-data boundary

This candidate does **not** backfill, modify, delete, reconcile or repost any
historical invoices, invoice lines, payments, stock, payroll or partner data.
Posted invoices created before this feature have no snapshot and remain
**Unclassified** until a separately approved preview, reconciliation and
controlled historical migration are completed.

## Promotion conditions

Before the production symlink changes, the release operator must:

1. verify the committed candidate, archive SHA-256 and payload receipt;
2. rehearse the exact archive against a fresh, isolated copy of the production
   database and filestore;
3. take one new, verified production DB + filestore recovery pair;
4. upgrade only the two modules above and verify the protected financial
   snapshot has not changed;
5. exercise an allowed-company classification, an unclassified invoice, a
   posted vendor bill and a vendor refund in the isolated rehearsal; and
6. atomically change the `current` symlink only after local and public health
   checks pass. Any failure before users resume work restores the exact backup
   and prior symlink pair.
