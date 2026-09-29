# Independent sales and reporting audit — 2026-09-09

**Scope decision: NO-GO for current POS summary configuration and lifecycle.** Two P1 findings remain open. This is the sales/reporting subreview; the root reviewer owns the overall release decision. No application source was changed. Runtime evidence is from `baseer_audit_sales_20260909`, restored from the actual QA database, using the current mounted source. QA/main were not test targets.

## Findings

### SALES-001 — P1 — Current dedicated POS cannot approve new sales (configuration/data)

- **Trigger:** validate or approve a summary under active dedicated configuration 1, company 6 (`QA ARZ`).
- **Evidence:** `sales-runtime/sales-config-inventory.json`: configuration 1 is the only active dedicated POS found; its product 29 is active but `type=consu`. The unmodified configuration fails `_validate_baseer_setup()` with “Configure an active summary service product for this company.”
- **Source:** `custom_addons/baseer_pos_summary/models/pos_configuration.py:184`; approval calls this guard at `summary.py:244`.
- **Expected:** the installed dedicated configuration can approve its supported service-only summary without generating stock movements.
- **Actual:** every nonzero approval is blocked before accounting. Zero-sales approval also runs configuration validation and is blocked.
- **Proposal:** investigate the data change that converted this configured summary product to consumable; restore or replace the dedicated service product through a reviewed configuration change, then re-run unmodified configuration acceptance. Prevent shared catalog/seed updates from silently changing the dedicated product semantics if that proves to be the cause.
- **Owner:** configuration/data maintainer. **Status:** open. **Limits:** this proves the state of QA-derived company 6, not a defect in the guard and not the state of production/company 10. The cause of the product change was not established in this subreview.

### SALES-002 — P1 — Native accounting correction breaks approved-summary provenance (code lifecycle)

- **Trigger:** an authorized accounting operator resets the original posted session entry to draft, or uses the native reversal wizard on that session entry.
- **Evidence:** `sales-runtime/sales-independent-result.json`, `observations`: an approved 1,150 SAR summary (net 1,000, VAT 150) remained `approved`, and the daily report still reported 1,150, while posted income became 0 after either operation. Native reversal was posted (probe reversal ID 1456). Each mutation was independently rolled back.
- **Source:** `custom_addons/baseer_pos_summary/models/daily_report.py:80` trusts summary state; `summary.py:83` uses the native order amounts; `_verify_posting` at `summary.py:304` only runs during approval. `pos_native.py` protects session/order/order-line/payment models, but does not protect their `account.move`/`account.move.line` counterparts or synchronize a correction lifecycle.
- **Expected:** an approved summary retains posted original accounting evidence. A supported correction must update source state/report treatment and all necessary accounting legs coherently, or be blocked until that workflow exists. A draft original move must not remain silently represented as a valid approved financial source.
- **Actual:** native accounting APIs accept these operations while the approved summary, customers, operating-day denominator and WhatsApp source remain unchanged. The ledger and daily sales report can diverge silently. The operator cannot repair summary values using the existing immutable summary form.
- **Proposal:** protect owned original accounting entries against reset/edit/delete; add a narrow, reviewed correction workflow that preserves original history and explicitly models corrected/reversed sales and affected receipts. Distinguish sales corrections from receipt-only reversals; do not automatically erase a valid sale when only its collection is reversed.
- **Owner:** POS/accounting integration maintainer. **Status:** open. **Limits:** tested with the authorized admin identity, not as an unauthorized access escalation. The test temporarily changed product 29 to service in its own rolled-back transaction to get past SALES-001. A native receipt-only reversal was separately verified: cash net becomes 0 while sales remain 115; this distinction is valid and should be preserved.

### SALES-003 — P2 — Archive marks a completed partial-closure day as missing a shift

- **Trigger:** an approved morning summary with split schedule and a confirmed evening closure for the same date.
- **Evidence:** `sales-runtime/sales-independent-result.json`, `observations`: daily status `complete`; archive `state=approved`, `missing_shift=true` for 2026-02-04.
- **Source:** `custom_addons/baseer_pos_summary/models/day_archive.py:55` checks only count of summary periods; the daily authority at `daily_report.py:89` includes confirmed closures. Archive closure rows at `day_archive.py:81` only cover all-day closures.
- **Expected:** “Missing shift” agrees with the documented complete-day calculation; the closure is available as the reason the second sales shift is absent.
- **Actual:** the date contributes to daily averages yet appears under “Missing shift” in the archive.
- **Proposal:** use the same period-coverage definition for archive completeness and drill into the half-day closure. Add a regression with approved morning + confirmed evening closure and with two half-day closures.
- **Owner:** POS reporting maintainer. **Status:** open. **Limits:** totals themselves were correct in the tested daily report. This is inconsistent operational status, not duplicated monetary posting.

## Executed evidence

All financial fixture tests used the named isolated clone. Where approval was needed, product 29 was temporarily made `service` to exercise the code despite SALES-001; the original `consu` value was restored by rollback, or explicitly restored after the concurrency transaction. These are conditional code results, not acceptance of the actual installed configuration.

| Evidence file in `sales-runtime/` | Current-source result |
|---|---|
| `sales-config-inventory.json` | Actual configuration blocker reproduced, without fixture changes |
| `sales-independent-result.json` | 32 checks passed; independent gross/net/tax, cash/platform timing, dates, customer average, zero/dayoff/split denominator, overlap, idempotence, message composition, late failure rollback; three findings above observed |
| `sales-legacy-result.json` / `pos_summary_backend_checks.json` | Re-executed prior tests: backend 42, operating-day report 46, S6 shift mapping 48, WhatsApp composition 24; all passed after declared service fixture |
| `sales-cash-adapter-result.json` | Re-executed 76 real-ledger adapter checks: multi-method attribution, partial platform receipts across months, invoice-tax evidence, drilldown, internal transfer exclusion, rounded cents, accounting-only access fallback, no external send |
| `sales-concurrency-result.json` | Three real two-cursor races passed: double approval is idempotent with retry; all-day vs morning allows one; confirmed closure vs summary allows one |
| `sales-vendor-parity-result.json` | 25 checks passed: rendered ERP Heritage P&L, trial balance, general ledger and cash report agree with a 115 SAR source and its exact AMLs; receipt-only reversal preserves sales and zeroes net cash |

The concurrency fixture is intentionally retained only in the disposable audit clone: summary 378, order 103, session 110, accounting moves 1495/1496. No immutable application history was deleted to clean it up. One competitor overlap draft and a closure can also remain in this exclusive clone. The original product type was restored to `consu` after the race. Other synthetic financial changes were rolled back. Earlier exploratory runs encountered the future-date native auto-post rule and a probe expecting a monthly-only totals key in a single-period payload; these were test harness corrections, not application findings.

## Report/source reconciliation map

| View/report | Source and basis | Independent verified relationship |
|---|---|---|
| Summary / day entry | Per-shift allocations + manually supplied customer count; approved monetary values from native order | cash115 + bank230 + platform805 = gross1150; net1000 + VAT150 =1150; customers100 →11.50/customer |
| Native accounting | One service order and dedicated closed session; payment/statement moves use business date | Debit cash115 + bank230 + platform current asset805; credit income1000 + VAT150; intermediary AR clears |
| Daily sales/customers | Approved summaries grouped by business date; closure coverage determines completeness | Both shifts345/30 customers count one date; zero-sale worked day counts another; average172.50 and15 across these two complete dates |
| Day archive | SQL grouping of all saved summary states by company/date; drafts included, separately labelled | Saved draft amounts are not posted revenue. Half-day closure completeness differs from daily authority (SALES-003) |
| Cash report including tax | Posted `asset_cash` AMLs only; trace reconciliations to source evidence | Initial actual collections345; platform805 adds no cash; later actual platform settlement115 appears on its own cash date |
| Cash report excluding evidenced tax | Same cash legs with proportionate evidenced net amounts | Initial345 becomes300; later115 becomes100. Actual cash movement remains unchanged and excluded-tax bridge reconciles it |
| Cash monthly sales denominator | Positive evidenced customer collections on selected tax basis; refunds separately classified | Adapter tests verify platform receipts count once, internal treasury transfers do not add collections, inaccessible/unproven evidence does not claim sales |
| ERP Heritage P&L | Posted AML income/expense account types, period dates | Retained115 fixture shows income100 and net profit100, not gross115 |
| ERP Heritage trial balance | Posted AML debit/credit opening/period/closing columns | Accounts1185 cash debit115;447 AR debit115/credit115;507 VAT credit15;595 income credit100 |
| ERP Heritage general ledger | Exact posted AMLs with source identifiers | AMLs3733–3737 appear exactly once, with every debit/credit matching native source |

**Average definition:** daily sales = VAT-inclusive sales of complete operating dates ÷ number of complete operating dates. Daily customers = sum of customer counts of those dates ÷ the same denominator. Two shifts are one date. Explicit worked-zero dates contribute zero and one denominator day. Closed, missing and incomplete dates are excluded from averages; approved amounts on incomplete dates remain included in “recorded totals.” A planned single shift is complete by itself; a split day can be completed by the other shift’s confirmed closure. Per-customer average is gross sales ÷ entered customer count, with 0 returned when no customers are entered. Customer counts are operator-provided, not distinct people measured from transactions.

## Reproduction

Use the existing audited runner, with the named sales clone ready:

```powershell
& 'C:/Users/hp/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -X utf8 docs/build-governance/full_audit_ops.py run sales docs/audits/2026-09-09-full/sales-config-inventory.py
```

Repeat with `sales-independent-probe.py`, `sales-legacy-suite.py`, `sales-cash-adapter.py`, `sales-concurrency.py`, and `sales-vendor-parity.py`. Concurrency requires its fixture dates/references to be absent; run it once on a fresh disposable clone, or choose new audited fixture dates. The parity script consumes the retained concurrency fixture. Do not run these scripts against QA/main. The runner enforces clone name and collects stdout/logs/JSON under the audit directory.

Limits: no screenshot/mobile/PDF visual acceptance was performed by this specialist; root owns browser/print review. The 76 adapter checks exercise rendered vendor integration but do not constitute a complete audit of every ERP Heritage report or multicurrency behavior. The report explicitly supports SAR and bounded rows/months; no claim of unbounded capacity is made. No automatic message was sent and no recipient was selected.
