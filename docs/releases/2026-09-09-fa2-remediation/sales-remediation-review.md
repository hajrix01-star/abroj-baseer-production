# FA2 sales remediation — reviewed candidate

2026-09-09. Module `baseer_pos_summary` **19.0.1.4.0**. Exclusive database `baseer_fix_sales_20260909`, isolated source `/tmp/fa2-source-sales`. The module's final 31 source files match `sales-source.json`; `sales-freeze.json` records hashes and verifies the match. No FA1 evidence changed. No QA/main write or external message was made by this owner.

## Findings addressed

| FA1 finding | Change | Current evidence |
|---|---|---|
| SALES-001, P1, dedicated product misconfiguration | Upgrade assigns a separate copied service to invalid dedicated configurations. Never converts product29 or rewrites stock history. Creation/assignment/type guards stop recurrence through configuration or product edits. | Actual config1/company6: product29 remains `consu`; service268 assigned; configuration validates; repair is idempotent; ordinary POS still posts. |
| SALES-002, P1, native accounting changes leave approved sales | Owned moves and lines reject financial edit/reset/delete and unreviewed sales reversal. Receipt/payment wrappers reject financial/link tampering and forged creation. Linked manager correction reverses originals, retains their source, cancels the source/order and opens a same-period replacement draft. | 1150 → reversal → replacement230; income200, VAT30, cash230, customers20, one operating day. Native POS, custom reports and ERP Heritage agree. Receipt-only reversal leaves the sale intact and blocks later full correction with a clear message. |
| SALES-003, P2, half closure inconsistent with archive | Archive missing-shift evaluation and daily WhatsApp warning use daily report coverage, including confirmed half-shift closure. Archive provides closure source action. | Morning115 + evening closure: daily complete/one operating date and archive missing_shift=False; closure is accessible. Prior closure/zero/day-off cases passed. |

## Accounting and review contract

Correction requires POS manager **and** accounting manager permissions, access to the source in the active company and a nonempty reason of at most2000 characters. A transaction locks the summary then serializes the company. A repeat request returns the same replacement. The original business date must be open; the operation never shifts it. All original owned entries must remain posted and unreversed. Any full or partial matching to a move outside the owned original set blocks correction; a tested platform settlement of50 retained its matching and65 residual after rejection.

Native `_reverse_moves(cancel=True)` produces and reconciles original counter-entries. The service verifies one reversal per original and zero account/partner/currency balance and foreign amount for every pair, as well as date/company/journal and posted state. Original order/allocation/customer values stay historical. Cancelled originals are excluded from live daily/archive/WhatsApp and native POS default analysis. A linked draft retains the date, shift, schedule and source chain, cannot be deleted, and must be reviewed and approved. An approved replacement can itself be corrected through the same controlled chain.

Native POS `write` forbids done→cancel. The specific private `_mark_summary_corrected` extension skips that single native layer only after source/reversal validation, using ORM for **state alone**. It does not edit source monetary values or remove payment rows. The internal identity token cannot be represented by RPC JSON. Injecting failure after native reversals, and separately after source/order state cancellation before draft creation, left every financial document count, reconciliation count, original state and order state intact after rollback.

An independent native receipt reversal remains available to both managers, under the source lock, and retains ownership on its counter-entry. It changes collections, not the approved sale. Later full correction rejects the already-reversed original instead of silently reversing it again. External settlement removal is never implicit in the full sales correction.

## Source-to-report map and averages

| View/report | Authority | Corrected example |
|---|---|---|
| Retained original summary/order | Original native line/tax/payment facts plus external customer count | Original gross1150/customer10 retained with cancelled state and reversal/replacement links |
| Live replacement summary | New native order/session/moves after approval | Gross230/net200/VAT30/customer20 |
| Daily operating report | Approved noncancelled sources + confirmed closure coverage | Sales230/customers20/one complete operating date |
| Daily archive | Noncancelled source projection; shared daily closure coverage |230/customers20; linked original remains reachable from replacement |
| WhatsApp | Approved noncancelled sources in the daily entry | Only current approved source; no actual message sent |
| Native `report.pos.order` | Native order lines with the action's default `not_cancelled` filter |1150 →0 →230; original cancelled row remains available when deliberately including all states |
| ERP Heritage P&L | Posted native move lines | Income/net profit200 |
| ERP Heritage trial balance | All original, reversal and replacement posted lines | Income debit1000/credit1200, net credit200 |
| ERP Heritage general ledger | Exact native AML identifiers | Original + counter-entry + replacement retained, no missing or duplicated source IDs |
| Cash categories | Actual cash/bank ledger receipts and reconciliation evidence | Net230; deferred platform clearing does not become immediate cash |

Average daily sales = sales on **complete operating dates**, divided by the count of those dates. Two shifts completing a date count once; approved zero-sales operations count in the denominator; closed dates and incomplete/missing dates do not. Daily customer average uses the corresponding complete-date customer totals and denominator. Average per customer = sales/customer count, with zero when the count is zero. Native POS order count represents one aggregated external source and must not be interpreted as the external customer count.

## Evidence and validation

All runtime JSON resides in `sales-runtime/`, and each runner stdout/log is retained. `sales-freeze.py` rejects failed checks and a source mismatch.

| Evidence | Passed |
|---|---:|
| `sales-checks.json`: correction, guards, upgrade, rollback, partial settlement/date, reporting, Arabic labels |76|
| `sales-races.json`: three separate-cursor races and invariant checks |14|
| `sales-cash-adapter-result.json`: mixed cash/bank/platform, settlement, refunds, reversals, ordinary POS |76|
| `sales-vendor-parity-result.json`: P&L/TB/GL/cash and full correction |31|
| `sales-legacy-result.json`: backend42 + operating46 + S648 + WhatsApp24 |160|
| **Total assertions** |**357**|

The three real races were concurrent correction/correction, replacement approval/approval and full correction/receipt reversal. The losing snapshot retried in every race. Both repeated-correction callers received replacement441. Exactly one new order/session and one reversal per original remained. Race fixtures are retained only in the disposable clone; all other fixtures roll back.

Python syntax parsed for17 files, XML parsed for10 files, and module upgrade completed after loading the Arabic catalog.42 correction/guard/coverage terms were translated; actual Arabic field and cancelled-state labels were verified. No application tests were run against the shared source while another owner was editing it.

One legacy malformed payload omits required `session_id`: in the current142-module clone, native `pos_online_payment_self_order` raises `KeyError('session_id')` before Baseer code. That exact legacy test now records native rejection with unchanged document counts; no other check accepts KeyError. A separate valid native-shaped forged request with `session_id` present verifies the intended Baseer AccessError and zero side effects. This is a native malformed-input presentation limitation, not the evidence for Baseer authorization.

## Upgrade and integration instructions

Run the approved isolated runner: `fa2_ops.py stage sales`, then `upgrade sales`, then the release test scripts. The migration drops the old unconditional period uniqueness and installs active-only uniqueness so a cancelled source and its same-period replacement can coexist. It repairs dedicated product assignments and backfills original/reversal ownership. A repeated upgrade/repair is safe. Fresh installation uses normal configuration creation with service-type validation. There is no automatic rollback migration that would discard correction chains; use the approved database/filestore/source backup procedure if deployment must be reverted.

The final source manifest SHA256 is `2a11541ff2d0aba485272b7c94a505da9e0ea6526e9c8889e4b176e30b32bf2b`. The last view-only refinement makes replacement date/shift/schedule read-only, matching their tested server invariant; isolated upgrade validated the inherited views. Root owns integrated QA-clone/main-clone rehearsal, independent security signoff and desktop/mobile review before any launch decision. The candidate was not deployed by this owner.

Operational limits: the missing-shift search caps at5000 saved dates and directs larger searches to a bounded daily report; manager correction intentionally rejects locked periods or external matches; a replacement remains an explicit draft until approved. Historical cancelled records can be deliberately included in native all-state analysis, consistent with normal POS analysis semantics. The FA1 cause of product29's bad type was not established; no speculative cross-module seed change was made.
