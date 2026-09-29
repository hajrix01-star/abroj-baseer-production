# Noorix purchase / expense replay — rehearsal only

This writer is restricted by `runtime_guard` to
`baseer_integrated_release_rehearsal_20260914` (18084).  It must never be
mounted in the production candidate, pointed at `baseer_dev`, or run against
the historical QA database.

## Offline dry-run (no Odoo, PostgreSQL, or business write)

Run before any Odoo-shell preflight:

```powershell
& D:\CodexData\skills\seo\.venv\Scripts\python.exe `
  rehearsal_addons\baseer_noorix_rehearsal_replay\purchase_dry_run.py `
  --manifest /mnt/noorix-source/source-manifest.json
```

Expected source-only result for the pinned manifest:

- 2,962 vendor bills, 2,963 payments/reconciliation scopes, 27 company-month waves.
- 2,211 ordinary purchase-VAT invoices and 751 no-tax invoices.
- 157 VAT classifications are inferred from `price_unit × 1.15 = gross` while
  `source_tax_raw` is zero; this is recorded by the contract checker and the
  invoice provenance canonical key.

The validator rejects source/archive drift, non-unique source invoice,
allocation or reconciliation identities, source arithmetic failure, ambiguous
VAT classification, an unapproved document decision, an unmapped category,
and the special two-payment settlement if it no longer totals its invoice.

## Read-only Odoo preflight

After the runtime add-on is installed on 18084 and only in a controlled Odoo
shell, call one exact scope (replace values from the dry-run output):

```python
from odoo.addons.baseer_noorix_rehearsal_replay import replay_writer
result = replay_writer.plan_purchase_month(
    env, "cmnf604ka009ay8lm556wgd9c", "2026-03"
)
print(result)
assert result["orm_writes"] == 0
assert not any(result["missing_or_ambiguous"].values())
```

The preflight reads only existing immutable source maps.  It refuses missing or
ambiguous supplier/vault/account targets, non-`BILL` purchase journal, and any
tax except the unique normal 15% purchase tax whose invoice repartition has
input-VAT account `104041`.  Reverse-charge (`104043`/`201017`) and
withholding taxes are rejected.

## Atomic rollback proof (test only)

Before the first financial wave, a reviewer may run
`purchase_atomic_rollback_probe.py` in the controlled Odoo shell.  It selects
the never-run ARZ March scope, deliberately fails after its first native
payment reconciliation, catches that expected failure, and asserts that the
before/after counts are identical for its run, all provenance maps, products,
account moves, payments and partial reconciliations.  Expected output is
`status: ok` with `no_planned_run`, `no_source_map`, `no_product`,
`no_account_move`, `no_payment` and `no_partial_reconcile`.  It issues no
commit and refuses to run if that wave already has any run record.

For the current Odoo 19 runtime, the probe also captures the native successful
post-reconciliation state before its forced rollback: payment state `paid`,
payment move state `posted`, payment `is_reconciled=True`, paid invoice and
zero invoice residual.  A valid payment uses `memo` for the immutable Noorix
allocation reference; Odoo 19 has no writable `account.payment.ref` field.

`purchase_idempotency_rollback_probe.py` is the complementary proof: it runs
the ARZ March wave once, runs it again to exercise full map/target verification,
asserts the second call creates no records and returns the same result, then
rolls the outer savepoint back.  It is expected to leave the exact original
counts for run/maps/products/moves/payments/partial reconciliations.

`purchase_karak_march_rollback_probe.py` is the equivalent complete-wave proof
for Karak March (`cmnvui7x70001etuf8p6xz3d0`, `2026-03`). It requires that
scope to be never-run, applies exactly three bills, three payments and three
native reconciliations, then calls the writer again so the full verifier checks
the immutable maps and targets. It deliberately rolls the outer savepoint back
and requires all run/map/product/move/payment/partial-reconciliation counts to
return exactly to baseline.

That proof also covers the one approved document asset override: the source
cashier computer `cmnyo9oxs000p9absv3j8y3dm` is represented only by the
company-specific service product `NOORIX-HIST-KARAK-CASHIER-COMPUTER` posting
to `106003` (`asset_fixed`). It must create no stock move and no
`account.asset`/`eh.asset` lifecycle record. The writer has no generic asset
override path and never invokes stock, asset or depreciation models.

## Controlled wave execution (requires separate G7 authorization)

Do not run this during dry-run or preflight.  A future approved runner invokes
`apply_purchase_month(env, source_company_id, month)` once per shell
transaction, in chronological order.  It locks exactly
`purchase:<source-company-id>:<month>` and makes one savepoint-scoped atomic
wave.  Each source document creates a native posted vendor bill, one or more
native posted outbound payments, then a native partial/full reconciliation.

The evidence scopes are deliberately separate:

- `purchase_category` → company historical service product
- `purchase_invoice` → `account.move`
- `purchase_payment` → `account.payment`
- `purchase_reconciliation` → `account.partial.reconcile`

The invoice map canonical key carries `vat_policy:vat15_inclusive` or
`vat_policy:no_tax`, so a policy change is a replay conflict.  Replaying a
committed wave verifies all target identities, journal/company, product,
account, tax, amount, partial reconciliation and zero residual; it creates
nothing.

The writer uses `with_company(company)` and
`allowed_company_ids=[company.id]` for every financial model access.  It does
not create stock, POS, sales, payroll, source-system rows, a second accounting
authority, or financial objects in another company.
