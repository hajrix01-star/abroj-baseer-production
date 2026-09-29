# POS-S2 independent gate and delivery review

Reviewer: s2_review — حارس البوابات / المراجع المستقل. Date: 2026-09-07. Target: QA database and port 18070 only.

## R1 — G0–G3 feasibility review before application changes

Read POS-SUMMARY-S2.md, the QA1 HANDOFF map, models/summary.py and common.py, existing ACLs, alpha-build-team governance and alpha-delivery-team roles. No application source or database changed by this review.

**G0, G1, G2, G3: approved for implementation.** Scope, native money authority, existing company MVCC serialization, bounded 366-day aggregation, no new dependency and isolated QA restore route are appropriate. This is gate approval, not a completed-feature GO. G4–G8 remain pending executable evidence.

Reuse QA1 map; local delta is Summary → operating-day aggregation ← confirmed closures, with a native report/timeline over the aggregation. The native order/payment/session → ledger route remains unchanged for positive sales; explicit zero operating records and closures must never enter that route.

The following acceptance interpretations are binding clarification of the existing contract, not additional feature scope:

1. A split day with one approved shift and no opposing approved shift/confirmed closure is incomplete, including when the other shift has a draft. Recorded totals remain visible but are excluded from both numerator and denominator of complete-day averages. A planned morning-only/evening-only day is complete with its approved record. An explicit zero-sales operating record counts as one operating day, without native ledger documents.
2. Full closure, or two non-overlapping confirmed half-day closures covering both halves, is a closed day. A lone half-day closure without another summary is not evidence of a complete operating day. No summary or closure means missing, never zero. Timeline must not manufacture zero points for missing/incomplete days; label its complete-day coverage.
3. Company-day period overlap checks cover creation, date/period/schedule edits, approval, closure confirmation/cancellation; use the same real MVCC company write and native transaction retry. Existing summaries, including drafts, reserve their period against closures. Competing confirms and summary creates require a two-cursor test, not only sequential validations. Consistent lock ordering must avoid unnecessary deadlocks.
4. Averages use complete daily sales/customer totals divided by unique complete operating dates; never average per-shift averages. No complete days produces visibly unavailable averages, not an apparent zero. Customer counts are declared visits/counts, not deduplicated identities across shifts.
5. The schedule choice is visible and persisted; the default split schedule must not silently classify a lone morning record as a full day. Existing all-day and shift records infer all/split respectively without changing their original money or documents.
6. Generated report lines are server-owned, user-isolated and company-scoped; direct RPC cannot fabricate authoritative report values or read another user's transient. Source actions enforce the same access boundaries. Confirmed closures preserve who/when; manager cancellation requires reason and leaves audit history.

## Pending delivery evidence

Source artifact SHA/manifest and QA backup identity; financial regressions and preservation; zero-operation no-ledger proof; report arithmetic fixture covering all/split/single/incomplete/zero/missing/closed/partial closure/cancel; true overlap concurrency; ACL/company/immutable guards; 366-day timing; Arabic/English desktop/mobile entry and native graph/source drill; retained preview and documented limitations. No original-database release is approved by this document.

## R2 — independent concurrency execution

After lead confirmed QA upgrade to 19.0.1.1.0, reviewer authored and executed `pos_s2_concurrency.py` through the QA container's native Odoo shell, using real separate PostgreSQL cursors and `odoo.service.model.retrying`. Evidence: `pos_s2_concurrency.json` and `.log`, marker `POS_S2_CONCURRENCY_OK`.

**PASS, 3 cases:** two simultaneous closure-confirm/summary-create pairs and one overlapping closure-confirm/closure-confirm pair. Every pair had exactly one successful transition; each loser experienced an actual serialization failure, retried with a fresh snapshot, then raised the expected domain validation. Test ranges were isolated 2038 dates proven empty before use; every exact fixture was cleaned afterward. Confirmed fixtures used native cancellation before SQL deletion of their exact test-only IDs, because production confirmed/cancelled closures are intentionally immutable. No order/session/ledger documents created. This proves concurrent overlap protection and preserves QA business preview data.

Read-only source check also confirms report classification handles half closures, incomplete split days and server-owned result rows. Native timeline uses categorical ISO dates to avoid manufactured temporal zero points. UI source hides unavailable daily averages and hides missing/closed amount cells. Final QA delivery remains pending artifact and full journey evidence.

## R3 — combined day-entry scope steering

Reviewed S2-006 and existing PaymentAmountGrid before the new transient implementation. **Reopened G0/G2/G4 approved for bounded implementation.** One screen composing two native amount-grid cards and producing existing summary records is appropriate; native accounting approval stays explicit. Existing G1 capacity and G3 dependencies remain valid (maximum two cards, 25 methods each, no new libraries).

Acceptance requires all-or-none summary creation within a savepoint, server-owned saved record links, active-company and transient-creator authorization, a real lock before checking the saved flag, and repeated-save idempotence including concurrent requests. After save the transient must be immutable or clearly readonly; changed inputs must not be silently ignored on replay. A fresh entry for an already saved date remains rejected by original summary overlap validation. Original separate summaries remain reachable for review and approval, and an unsaved/empty card cannot become a zero-sales record without explicit declaration. Atomic partial-failure and replay tests plus actual desktop/mobile two-card save are required before final GO.

## R4 — combined save concurrency and private vacuum review

Independent `pos_s2_day_entry_concurrency.py` executed on upgraded QA: **PASS**. Two simultaneous saves of the same persisted entry returned the same form and generated exactly two original draft summaries, morning115/10 customers and evening230/20 customers. A real row-lock serialization failure retried natively; no duplicate summaries or financial documents. Exact test fixtures cleaned. Evidence JSON/log contain marker `POS_S2_DAY_ENTRY_CONCURRENCY_OK` and attempt counts1/2.

Read-only review of the private transient cleanup extension confirms the special unlink route is authorized by an in-process object identity token introduced only by the underscore-prefixed native vacuum hook. A JSON/RPC context cannot manufacture that token. Durable source history remains the original summary records, not the temporary day-entry form; document this distinction in handoff. Explicit combined approval retains original per-summary action_approve calls with an outer savepoint, source snapshot mismatch rejection and summary-before-company lock ordering. Late-second-approval rollback evidence is still required from the execution owner before GO.

## R5 — final independent acceptance, QA2

**القرار النهائي: GO لمعاينة QA فقط. G4–G8 معتمدة ومقفلة لهذا النطاق. لا موانع جوهرية مفتوحة.**

Candidate `baseer_pos_summary 19.0.1.1.0`, release directory `docs/releases/2026-09-07-pos-summary-qa2`. Independently recomputed every source/evidence hash and every archive-entry hash: **24 source files, 22 evidence files, 24 ZIP entries, zero mismatches**. Verified28 shared report-layout/purchase files against QA1 manifest: unchanged. Archive SHA256 **ac34905a318bdfde7c950397dedcd5e3bc122c822082a84778066a3d94bc561d**. No Git commit is claimed; the frozen archive/manifest identify the reviewed candidate.

The review reuses the approved QA1 map with the bounded QA2 delta shown in HANDOFF.md. Depth is focused on UI and deep on money authority, tenant isolation, transaction rollback, completeness denominators, closure conflicts and concurrent replay. No new dependency or broader system discovery was needed. Source ownership stayed separate from independent gate review; independent reviewer directly authored/executed the four concurrency cases and inspected other owners' reproducible acceptance evidence.

| Gate | Evidence and result |
|---|---|
| G4 | Arabic/English desktop/mobile card screenshots inspected; visible labelled native amount boxes, separate shift customer counts, two-column390px layout and one visible Save. UI source distinguishes saved drafts from explicit approval. Daily report explains incomplete-day exclusion and hides unknown cells. |
| G5 |25 summary checks,46 operation/report checks and38 combined-entry checks PASS. Late second approval test actually completes first native approval, forces the second to fail, then proves both drafts and no ledger; replay, changed-source guards, permission/context checks and native vacuum covered. |
| G6 | Four real two-cursor cases directly run by reviewer; actual serialization failures retried natively.366-day aggregation0.002786s on bounded QA fixtures; this is not a production or full-retention load certificate. |
| G7 |41 native financial plus76 cash-report regressions PASS; total226 logical checks plus four concurrency cases. Original financial before/after fingerprints are byte-identical for63 moves,147 move lines and1 POS order. Native accounting remains authoritative. |
| G8 | Frozen source/evidence/archive validated, preview and cleanup documented, matching before-change DB/source backup identifiers recorded, QA-only restore procedure and operational boundaries present. Main read-only evidence shows no new module and0 moves/lines. |

Combined desktop Save produced exactly original draft227/228 for Sep4 with115/230SAR and10/20 customers. Mobile actual Save produced120/240SAR and12/24 customers, then exact mobile fixtures were cleaned. Final retained state is original approved summary82 plus the two clearly described QA drafts; zero retained closure rows. Default browser form is Arabic entry action497. Closure ranges, single/two-shift complete-day means, missing-data semantics, explicit zero-day declarations and monthly shift filters all have source and executable evidence.

Handoff accurately states durable history is original summaries; temporary entry/report cleanup does not erase them. WhatsApp remains manual from original approved summaries; no external message was sent. Active-company6 demonstration configuration, gross VAT-inclusive daily metrics, existing platform-clearing policy,366-day report/range bound, and future-dashboard scope are explicit. Restore the documented QA backup plus matching source for rollback; uninstall is not the accepted rollback. No release to the original database is authorized or implied by this GO.
