# S5 independent gates and delivery review

Reviewer s2_review; 2026-09-08; QA only. No application edits by reviewer.

## R1 — bounded role and draft/archive gates

Read POS-SUMMARY-S5.md including S5-002 and the independent source/API audit in POS-SUMMARY-S5-ACCESS-NOTES.md. **G0–G4 approved for the role-only implementation described in S5-002.** This approves building and testing the narrowly scoped native posting bridge, not final delivery or employee assignment. No actual user receives the role outside rollback-only acceptance fixtures.

The strict group implies base.group_user only, has a separate entry menu and no archive/dashboard/report ACL. Own summary/allocation/closure and transient access plus proven necessary readonly masters is appropriate. Rejecting incompatible POS/accounting/EH role coassignment is sound; existing managers remain on their existing unchanged role path. Group membership validation must cover direct user edits, group-side membership changes and implied-group changes that could otherwise introduce forbidden effective memberships.

Before private sudo posting, preserve original caller role, creator, company, immutable-state and input authorization and acquire source locks. Inside the fixed operation validate actual dedicated config, method membership, product/tax/journals, dates and native amounts; keep original uid and in-process identity token. Never return sudo-enabled records/executors or accept scope/model/ids from a public caller. Required company-wide overlap checks may use narrowly bounded internal reads even when other users' source rows are hidden. Original native posting and transaction rollback remain the only financial engine.

**G0/G2/G4 also approved for a separate bounded lifecycle slice:** manager-only is_archived metadata on durable sources, presentation filter in archive, and all-or-none deletion of an entirely draft day through original source unlink. Use is_archived rather than active so archived rows remain in reports, daily averages and overlap checks. Archive/unarchive must use manager/current-company/source-lock checks and may change only presentation fields. For daily projection, define a consistent whole-day archive policy when two shifts exist; do not silently hide a nonarchived shift because only its sibling is archived. Re-query/lock every original shift before draft delete; mixed or approved sources reject the entire action. Runtime delete confirmation is appropriate; merely adding the button does not authorize deleting existing demonstration/user records.

**Not approved by this review:** deleting/cancelling confirmed DAY OFF records, deleting financially approved summaries, any tax-setting/data migration, or changing previous prices. These remain outside this bounded gate decision pending the user's clarified instructions and subsequent contract review. G5–G8 remain open until least-privilege positive posting, denied RPC/report/data access, no coassignment, owner/company overlap, draft/archive lifecycle and preservation evidence is available.

## R2 — subsequent user steering puts role on hold

Immediately after R1, lead reported the user is reconsidering reuse of native cashier permissions and is choosing between strict entry-only role and native permissions as-is. **The role portion of R1 is now HOLD / reopened pending that choice; do not implement it based on R1.** This is user-scope steering, not a new permission requirement invented by review. No role application changes were made before hold.

**Lifecycle-only G0–G4 remain approved:** manager-only source is_archived metadata, reversible default archive filter, original reports/overlap unaffected, and atomic deletion of all-draft source days only. Existing approved/mixed days and confirmed closure deletion/cancellation remain excluded. Pending role and tax choices do not block this independent authorized lifecycle slice.

## R3 — native cashier permissions chosen

User explicitly chose the existing native cashier permissions as-is. **Custom restricted-role work is cancelled, not deferred.** No custom group, employee assignment, elevated posting bridge, report-denial guards or owner-rule changes belong to S5. The source/API audit remains informational; the original POS user's native report permissions must not be described as entry-only isolation. Lifecycle implementation may proceed under its approved bounded gates. Confirmed-closure and pricing changes still await their separate clarified contracts.

## R4 — final independent QA5 lifecycle delivery decision

**GO for the lifecycle-only QA candidate, version 19.0.1.3.0. G5–G8 close for this bounded slice.** No material unresolved issue was found in the reviewed archive, restore and whole-day draft deletion implementation. This is neither a production rollout decision nor completion of the pending pricing/confirmed-closure requests.

Independently verified all 26 source hashes and 11 evidence hashes in `docs/releases/2026-09-08-pos-summary-qa5/manifest.json`, plus all 26 source entries inside its release archive. No mismatches. ZIP SHA256 is `7d5f1465ff8fbb72523de0ccb50e3a1cd231b9f07df3cbeb7f4379184b84f90a`. Eleven module files differ from QA4; security ACL/group files, financial report engines and dependencies remain unchanged. The accompanying HANDOFF describes scope, recovery and exclusions accurately.

Read the source guards and independent operations evidence: 40 lifecycle checks and 90 regression checks pass with rollback fixtures. Lifecycle tests cover denied native-cashier/current-company RPCs, all-or-neither mixed-selection failures, approved/confirmed-source retention, both draft shifts deleted together, archive/restore range deduplication, unchanged reporting denominators and byte-for-byte accounting move/line preservation. Reviewed the stale-entry correction: a saved form verifies its exact original summary IDs or closure before delegating, so replacement records on the same date cannot be targeted by the old form. Source locks and the existing company serialization protect the subsequent whole-day operation. The final return-only native reload change is included in the frozen source and repeated lifecycle evidence.

The daily SQL projection uses `is_archived` presentation metadata and `BOOL_AND` for a paired day; it does not filter original accounting/operating evidence. Server-side manager checks accompany the native UI controls. Deletion still delegates original source unlink and rejects any approved/mixed day or confirmed closure atomically. Reviewed the Arabic mobile permanent-deletion confirmation: the irreversible action and retained approved sales are clear, with visible cancel/confirm controls. The documented actual desktop/mobile journey used only new draft fixtures 310/311, then removed both; it did not post finances. Main remains outside the mutation scope.

Native cashier rights remain as explicitly chosen, including their existing native reports. No custom role or elevated posting path was introduced. Pricing/tax-default changes and deletion of confirmed closed records remain **outside this GO and pending their clarified scope**. Existing authorized lifecycle work is reviewable and complete in QA; those open items must remain visible in the user handoff.
