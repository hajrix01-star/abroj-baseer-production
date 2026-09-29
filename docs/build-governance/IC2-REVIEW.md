# IC2 independent lifecycle review

Decision: GO

Source acceptance for freezing the exact reviewed IC2 candidate. Frozen-candidate verification and protected production/publication acceptance remain separate required steps.

Reviewer: icons_release. Scope: IC2 delta over frozen IC1 `24bc64d2a778590e8e8e6577eb3866d18727bc24`; no application edits, production test mutations or repeated baseline audit. Approved G0–G4 are recorded in IC2-GOVERNANCE.md.

## Initial static findings

| ID | Finding | Required focused disposition |
|---|---|---|
| IC2-R01 | `LifecycleMove` guards `_reverse_moves` on existing owned records but initially lacks target checks when creating/writing an unowned record with `reversed_entry_id` pointing to an owned record. The initial payment guard also checks only the old move when changing `move_id`. | Guard explicit/default reversal targets and new payment move targets; demonstrate direct RPC/default bypass rejection without breaking native lifecycle calls. |
| IC2-R02 | Ordinary linked payment association can initially be removed through `account.payment.invoice_ids`, or inverse `account.move.matched_payment_ids`, before calling guarded cancellation/reset. | Reject destructive detachment of posted associations outside the validated lifecycle while preserving ordinary native matching/reconciliation. Test both directions. |
| IC2-R03 | Summary wizard and amount-line writes initially check completion without taking the parent wizard lock, reproducing the IC1 edit/confirmation race on the new model. | Serialize parent/line writes with confirmation and revalidate completed state; prove the same-source race. |
| IC2-R04 | The inherited POS accounting guard still permits separate original-receipt reversal for a POS/accounting manager, outside the new shared permission/source lifecycle. | Route or deny the external receipt reversal under IC2; retain source-engine internal reversal. If a separate settlement operation remains supported, explicitly define and test its source/permission contract. |

The summary snapshot also initially omits payment-method account/tax configuration despite showing those accounts in the preview. The worker was asked to bind relevant configuration or otherwise prove that a changed configuration cannot silently invalidate the preview; external settlements remain checked by the native reversal engine.

## Controls inspected

Core cancellation requires a server-owned operation choice, reason and explicit payment bookkeeping acknowledgement. It resolves native invoice/payment association together with reconciliation, rejects shared/conflicting/unsupported sources, preserves actual partial amounts, calls native payment cancellation while its entry is posted, then cancels the invoice. It verifies retained document/line identities, original dates, balanced history, cancelled states and no active reconciliation. It does not create cash receipt/refund entries or call a bank API. Edit still rejects an already-cancelled invoice. Confirm uses existing source locks, stale snapshots, source-scoped private capability, atomic source update and immutable audit classification.

Batch cancellation preserves the original row/documents and records reason/actor/time through the private adapter; active totals exclude the cancelled row. Summary edit/cancel reuses the existing exact source reversal engine, and replacement approval remains inside the outer savepoint. Reuse of native approval preserves POS/invoicing checks without new manager memberships. These controls need the declared native integration, permissions, rollback and UI evidence before final acceptance.

MAIN historical cancelled-invoice examples are not automatically repaired or used as fixtures. Whole-batch cancellation remains optional; no acceptance claim is made for an unimplemented whole-batch operation.

## Focused re-review

R01 fixes now inspect explicit/default original reversal targets and payment move targets. R02 handles persistent links in both directions and native partial-reconciliation evidence; its narrow additive `Command.link` exception requires the proposed payment already to appear in the exact native reconciliation graph, preserving native payment registration without permitting detachment. R03 now serializes summary wizard and line writes with confirmation and touches the parent MVCC version for line-only changes. R04 blocks external summary receipt reversal while preserving the original engine's private internal scope. These structural fixes await final targeted evidence; no broad bypass permission was introduced.

Additional IC2-R05: direct reset/cancel/state mutation of an ordinary linked payment's underlying `account.move` entry initially bypasses the payment-model gate, because the move guard filters invoice move types. Parent was asked to check the entry's origin payment and native invoice/reconciliation graph as well, with exact direct journal-entry negative cases. Owned batch entries are already guarded. The fixed guard must preserve normal native registration/reconciliation.

Payment-method accounts, journal/config timestamps and the exact reconciliation graph are now included in the summary preview fingerprint. The worker was asked to add effective tax financial values as well as timestamps, avoiding the already-known same-transaction timestamp limitation. Parent was also notified that owned batch bill reference edits and relevant journal-item reporting fields should follow the immutable source guard.

Release and source-only export helpers were independently inspected: two already-installed modules updated over the 1,177-file IC1 baseline, 372 protected old tables including correction history/transients, exact original column values/security/presets/versions, explicit new-field/table whitelist, no deployment-time cancellation, stopped-service coherent backup mapping and unchanged 19-module export. No helper execution or production mutation was performed by this reviewer. Final candidate hashes and UI/source bindings remain required.

## Focused backend evidence accepted

Final `ic2-core-checks.json` currently records PASS59 with hard commit guard, full rollback and installed-module preservation. It proves paid/partial/unpaid and customer cancellation, native association and partial-only resolution, the already-cancelled invoice/posted-payment fixture, no new/refund/reversal entries for ordinary cancellation, original identity retention, native cash-report/register removal, audit/idempotency, changed/shared link refusal, permission revocation/cashier denial, batch history and active/report totals, and rollback after both native cancellations. R01/R02 target/default/link guards and R05 direct underlying journal state/reset/cancel checks pass. Native registration and the existing edit path remain functional after the narrowly permitted reconciled additive-link change.

`ic2-summary-checks.json` records PASS38 with the same rollback/commit/module guards. An actual accountant approves the native cash/bank/application source, atomically reverses and replaces it without manager-group grants, preserves original evidence and exact account-level reversal, and cancels the replacement without another draft. Reporting counts/sales, zero-sales, stale requests, external settlement refusal, locked-date refusal, acknowledgement/creator/baseline restrictions and injected replacement-approval failure all pass. Full effective tax values are now in the fingerprint; a same-transaction tax-rate edit correctly invalidates preview. Recorded bounded timing is about 1.35 seconds for the summary edit and about 0.60 seconds at the upper end of the recorded core fixture samples; neither is production-scale certification.

R05 is resolved: the guard now checks an underlying entry's origin payment before reset/cancel and also checks old/new origin-payment links on reassignment. Final core evidence is PASS60, including the exact ordinary `origin_payment_id=False` detachment denial; rollback, commit guard and module preservation remain true. No further backend blocker was found in this scoped re-review.

Both real concurrency harnesses and JSON results were inspected. Competing paid-invoice edit/cancel yielded one commit, one stale rejection, one audit and a balanced consistent invoice/payment result. Summary amount edit versus confirmation yielded an edit commit followed by a serialization retry and confirmation using the updated amount: request and replacement both 215. The harness also permits the opposite valid order, in which confirmation succeeds and the later edit is rejected. These fixtures commit only in the isolated QA database and are not represented as rollback-only tests.

Final native summary mobile layout and AR/EN/480px source binding are now complete and accepted below. Previously accepted backend evidence is reused; no additional broad suite or MAIN financial fixture is required.

## Final source and UI acceptance

Independently matched all 47 final source-file SHA256 hashes across the correction and summary addons, and all 20 screenshots/DOM artifacts, against `ic2-ui-checks.json`. That evidence file SHA256 is `d16f1524b8dc3141fbd8b9b7a9885f91ce936e5b3e0b423e3005bf9c61074f81`. The final mobile native summary payment cards show method/account and original/correct amount with a labelled acknowledgement; the reviewer visually inspected this Arabic 480px view and the English invoice/payment cancellation preview. The final UI-only title/group/kanban changes leave accepted financial handlers unchanged.

The actual browser batch cancellation retains the cancelled original invoice/payment/row and its 500 original amount, while the untouched neighboring row contributes the remaining active 500. The actual summary edit changes 690 to an approved replacement of 790 with 15 customers. `ic2-ui-accounting.json` and its inspected read-only verification script confirm exact original reversal by account and one audit for each browser action. No production business records were used.

Acceptance consists of PASS60 core checks, PASS38 summary checks, two actual concurrency cases, six grouped UI journeys with 20 bound artifacts, and the browser-result accounting verification. R01–R05 and the configuration-fingerprint refinement are resolved. The release helper now binds both race results and browser accounting verification/scripts as well as source/UI evidence. No remaining blocker was found within the approved IC2 scope.

Limits remain explicit: cancellation corrects erroneous bookkeeping and never performs a real bank refund; whole-batch cancellation is omitted, with one atomic operation per row; external/shared settlements and protected unrelated sources retain their native workflows. Native mobile kanban is selected when opening at mobile width; an already-open desktop list keeps its mode after resizing. This source GO authorizes freezing for the already-requested protected rollout, not bypassing exact candidate/data-preservation checks.

## R2 translation-only recovery amendment

Decision: GO for freezing the separate R2 candidate, with exact-candidate and recovery-runner approval still required before recovery execution.

The first candidate installed successfully but failed the original-data preservation gate and was not started. Its recorded diff has exactly 47 rows: 15 account names, 6 journal names, 9 payment-category names, 15 payment-method names, and write_uid/write_date on 2 partners. No amounts, account mappings or transaction states changed. Failed source and evidence remain immutable.

The reviewer independently compared the working R2 source with that failed candidate. Only `baseer_pos_summary/i18n/ar.po` differs: 45 generated `payment_seed_*` record occurrences and 12 now-unreferenced entries are removed; all 451 retained static entries have identical message strings, plurals, flags and static references. Correction PO and every functional Python/XML/version/schema remain unchanged. All 47 rebound UI source hashes and the same 20 UI artifact hashes match. Existing functional/UI evidence therefore remains applicable without another module update or broad retest.

The separately reviewed recovery runner uses an exclusive maintenance lock, stopped MAIN/no-client checks, exact failed projections, a coherent backup hash and independently restored full pre-upgrade projections. A single serializable transaction locks all 372 original tables, checks each current changed field against its captured failed value, restores only the whitelisted original values verified against the restored backup, and compares all 372 original projections before COMMIT. Schema/default/security/preset/module checks, coherent post-backup and pinned runtime checks remain required. No second module update is performed because installed functional state already matches R2. Exact runner/hash and candidate approval follow the separate freeze; this amendment does not claim restoration has run or passed.
