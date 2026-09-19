# Representative petty-cash settlement UI fix — 2026-09-19

## Scope

QA-only correction in `baseer_procurement_requests 19.0.14.0.1`.  It changes
only the invoice settlement picker presentation and its read of the current
representative balance.  It does not change historical movements, accounting
accounts, settlement entries, company scope, or approval authority.

## Finding and decision

The server computes one representative's current balance within its company as
posted funding minus returns and settlements.  The picker, however, cached the
RPC response per company for the lifetime of the browser session.  A funding
posted after an existing batch screen was opened could therefore continue to
display an earlier zero balance.

The representative route deliberately stores `is_credit=True` as a technical
compatibility marker: it prevents the ordinary bank/cash payment path, then
approval settles the vendor bill against the representative's balance.  It is
not an actual supplier credit.  Showing the ordinary `Credit` switch for that
route made the correct accounting state look like deferred payment.

## Correction

- Cache only simultaneous picker RPC calls; discard the monetary response once
  it resolves.
- Refresh choices immediately before assigning a representative.
- Disable the picker only for a real `credit` source, not for the technical
  representative marker.
- Replace the visible credit switch with the existing translated
  `Representative Petty Cash` label when that source is selected.
- Keep all server-side balance, company, permission, locking, settlement and
  reconciliation checks unchanged.

## Acceptance checks

1. A fresh settlement-choice RPC reports the balance after representative
   funding; the focused server test covers zero then funding of SAR 25.
2. With a funded representative selected, the picker shows the current balance
   and `Representative Petty Cash`, not `Credit`.
3. An actual credit row alone disables the settlement picker.
4. Approval remains server-authoritative: it rejects spending above available
   balance and settles an in-range bill without creating a bank/cash payment.

## QA evidence

- Alpha financial and UI reviewers independently approved the bounded
  front-end-only correction.  Both confirmed that `is_credit=True` must remain
  internal for the representative route.
- The current QA-mirror source was upgraded locally and the focused Odoo test
  `ProcurementFlowCase.test_purchase_batch_settles_from_representative_petty_cash_without_payment`
  passed.  It includes the new assertion that the settlement-choice RPC reads
  SAR 25 immediately after funding, then confirms paid settlement without a
  direct bank/cash payment.
- The backend loaded the updated module and the browser opened the purchase
  batch screen after the new assets were loaded, without an asset/template
  failure.  A separate funded representative row remains the required final
  visual acceptance on the shared Tailscale QA environment before production
  release.

## Limits

This is not production deployment authority.  QA browser verification is
required before any separate production approval.
