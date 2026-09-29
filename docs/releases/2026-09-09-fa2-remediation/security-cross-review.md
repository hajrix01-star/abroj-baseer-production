# FA2 independent POS / payroll boundary review

Reviewer: audit_security_quality. Scope: read-only review of the other owners' remediation delta and their runtime evidence. This is separate from the reviewer's own SECURITY-001/002/003 implementation, which root reviewed independently.

**Decision: ACCEPT the reviewed POS and payroll security/lifecycle boundaries on the frozen sources identified below. No unresolved P0/P1 boundary defect was found. This is a scoped independent acceptance, not the overall G8 release decision for the combined candidate.**

## Design and trust boundaries

- POS: manager plus accounting-manager authority; active company and source access rechecked inside correction; native owned moves reversed in one transaction; original source and links retained; replacement remains a draft in the same source period. Private Python identity token is not obtainable from JSON context. Public wizard action does not itself manufacture authority.
- Payroll: payroll manager plus accounting rights at confirmation; wizard source/company checked; source snapshot and employee/wizard locks; posted linked native entries rather than source rewriting. Paid salary may receive additional positive liability; reductions are limited to outstanding unsettled debt. Latest recovery must be reversed before earlier recovery, and advance disbursement only after all recoveries are undone.
- Reversal does not represent an external funds transfer. Legal/EOS calendar policy and salary formula choices remain the explicit approved design and the accounting owner's validation responsibility.

## Review observations sent to owners

1. POS replacement initially allowed changing business date/shift/schedule after creation. Owner added a source-period guard and protected replacement deletion; final freeze evidence will be checked.
2. Newly added loan `reversal_move_id` initially lacked the original model's create/default/write protection. Owner added it to the protected fields; final runtime forgery checks remain to be checked.
3. Requested distinct-wizard concurrency evidence: an advisory employee lock does not itself refresh a PostgreSQL repeatable-read snapshot. A correction must not rely on incidental sequence conflicts to detect a concurrently changed source. Same-wizard replay alone does not cover this boundary.
4. Requested loan snapshot coverage of reversed recovery history as well as active recoveries, avoiding an old review becoming apparently current after repayment then reversal restores the same balance.
5. Independently checked native `account.payment.move_id` / `pos_session_id` mutability and the risk of detaching a receipt from `_native_moves()`. The sales owner had concurrently added payment and statement-line create/write/unlink guards. The final targeted tests explicitly reject clearing either link and forging new receipt ownership.

These are remediation review observations, not claims of a demonstrated production exploit. Owners retain application-file ownership and implement any changes.

## Frozen POS slice: accepted

`sales-freeze.json` identifies 31 source files, all matched to the current workspace by an independent SHA256 comparison. Final freeze-file SHA256: `6fbe23801aa59f986d217c15495658aa6b3f25305cfaadaca169264ad212014d`; embedded staged-source manifest SHA256: `2a11541ff2d0aba485272b7c94a505da9e0ea6526e9c8889e4b176e30b32bf2b`. The final view-only update makes replacement period fields visibly readonly; accounting, correction and summary Python hashes remain identical to the reviewed logic, and the owner reran all 76 targeted checks successfully.

| Boundary | Inspected source | Evidence / conclusion |
|---|---|---|
| Correction authority and active company | `models/correction.py:14`, `:44`; `models/common.py:34`, `:50`; `models/summary.py:108` | Public wizard checks ownership and delegates to a private method that rechecks manager and source access. POS manager without accounting-manager and wrong active company are rejected. |
| Source and receipt ownership | `models/accounting.py:18`, `:51`, `:106`, `:137`; `models/pos_native.py:120` | Native move reset/edit/unlink, receipt relinking, forged reversal ownership, and boolean token fail. The narrowly scoped retained-order cancellation is private and requires the full posted reversal set. |
| Replacement period and permanent chain | `models/summary.py:189`, `:216`; `models/correction.py:73` | Replacement period/date/schedule cannot drift and replacement cannot be deleted. Original amounts and customers are retained. |
| Reversal/replay/closed date | `models/correction.py:49` | Rejects external settlements, locked source date, already reversed receipts and incomplete sources. Late failure rolls back; receipt-only reversal leaves sale approved and blocks later full correction. |
| Concurrency | `sales-runtime/sales-races.json` and `sales-races.py` | Three separate-cursor races / 14 checks: same original correction produces one replacement; same replacement approval creates one order/session; competing full correction and receipt reversal yields one coherent outcome after native retries. |

Owner evidence inspected: `sales-runtime/sales-checks.json` has 76/76 passing checks; races 14/14. The freeze inventories 357 checks including prior regression and cash/vendor parity. This reviewer inspected the boundary cases and race harness rather than independently rerunning all 357 checks. No unresolved P0/P1 boundary defect was identified in the frozen POS slice. This slice acceptance does not replace combined upgrade, UI, accounting or release acceptance.

## Frozen payroll slice: accepted

The final independent comparison found no drift across all 32 files in `payroll-source.json`, SHA256 `24b46aee8df261bbe2f099565536bca5ef2718a94c23e762e1becf120fe288b1`. Reviewed correction logic SHA256: `29f1cf80d743dc1494e497a89db61aea8b6ea4c744f870338be948e809e32da0`. The final translation update did not change this logic hash.

- `models/correction.py` rechecks manager/source/company and posted lifecycle at confirmation; accounting group is required before posting. Source/output/default fields reject caller injection. `account.move` links/reasons and immutable recovery links can be changed only with the private in-process identity token. The transient wizard does not expose that token in its returned action.
- `security/ir.model.access.csv:2` grants correction wizard access only to Payroll Manager; `views/correction_views.xml:3` supplies the global company rule. The standard transient creator boundary remains in force. Same-company manager success and payroll-manager-without-accounting denial are demonstrated by the concurrency fixture using ordinary non-admin users.
- `models/payroll.py:237` and `models/loan.py:88` retain employee serialization and force a new source-row version with `write_date=write_date`, preserving its value. Separate-cursor tests deliberately establish both snapshots before racing. The waiting writer retries after serialization failure and then sees stale reviewed evidence rather than posting against its old snapshot.
- The source snapshot now includes all recovery IDs and their reversal IDs. `payroll-security-result.json` demonstrates repayment then reversal restores the same balance while rejecting the earlier wizard. It also rejects forged loan reversal writes/defaults with a boolean token, forged calculation/source snapshots and correction links, reopening reversed sources, and redisbursing a reversed advance. Cancelled installment amounts remain historical while outstanding amounts are zero.
- Latest-first recovery reversal and paid-salary positive adjustment preserve original accrual/payment rows and create additive native entries. `payroll-independent-result.json` records 125 passing checks and no observation errors, including partial payment, full payment followed by an additional correction/payment, latest direct recovery reversal before payroll recovery, retained reversal history and duplicate reversal rejection. Formula/legal decisions remain outside this security acceptance.

`payroll-concurrency-result.json`: 3 real races / 10 passing checks. Different correction wizards: one success and one stale rejection after retry; same wizard: both requests succeed with one journal entry; payment versus salary reduction: one success and one stale rejection, with nonnegative salary debt. `payroll-security-result.json`: 4 assertions plus 9 expected denials, all passed.

`payroll-rpc-result.json`: 11/11 passing final micro-probes. Native public `call_kw` denies Officer create/confirm/payslip correction, denies wrong active company create/confirm, and permits non-admin manager plus accounting create/confirm. Native `get_public_method` rejects `_sources`, `_new_move`, `_salary_adjustment` and `_reverse_recovery`; the test does not bypass the dispatcher by calling a private method through an internal helper. Fixtures were rolled back. This closes the final permission evidence gap without repeating the large accounting suite.

## Evidence limits

The reviewer did not run duplicate legacy or security-slice tests, change application files, or write to QA/main. Source inspection, file-hash comparison and review of owner-run runtime evidence underpin this acceptance. Runtime account-payment field/dispatcher behavior was checked against the actual container source where relevant; local native-source equivalence is not assumed.

All five review observations above are resolved in the identified sources and evidence. Financial formulas, legal-policy selection, full PDF/UI quality, capacity and combined installation/upgrade preservation remain the accounting owner's and independent release review's responsibilities. The source versions include the two slices reviewed here; this document does not claim that every possible combination or future module overlay was tested. Any later change to authority, protected fields, source-link collection, snapshot semantics or reversal/payment lifecycle requires review of that delta.
