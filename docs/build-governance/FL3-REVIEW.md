# FL3 independent review

Decision: GO.

Scope: accepted working-source FL3/FL3B candidate, ready to freeze for an exact-candidate predeployment review. This is not confirmation of MAIN deployment.

Reviewer: icons_release. Scope: Financial register All-mode native POS sales contributions over IC2 R2 `3d96581c2eef324df3b5ed69f7ba526bb37035fc`; no application changes or MAIN mutation by reviewer. G0–G3 are approved in FINANCIAL-REGISTER-SALES.md, including company-currency row/card parity and unchanged Cash mode.

## Initial release-helper review

The new helpers retain the appropriate one-addon update, pinned runtime/1181-file parent, no new dependency/schema, 373-table original-column/data preservation, exact security/preset/other-module checks, exclusive maintenance lock, coherent stopped-service pre/post backups and source-only public export. No freeze/publish/export was executed by this reviewer.

Before freezing, restore the accepted evidence-integrity guards: include SHA256 bindings for copied acceptance/review/governance/helpers (including the GitHub helper), verify those hashes during candidate validation, and recheck unchanged parent files outside the addon, changed-file inventory and exact candidate/module/image identity. Save after-security/preset snapshots alongside the checked before snapshots. These are bounded operational refinements, not changes to the financial implementation.

Final review will cover the assigned source delta and independently produced native accounting/Cash/security/row-card-drill evidence, actual Arabic/English/mobile UI and exact source binding. No final source or release GO is asserted yet.

## First implementation review

The three operational refinements above are now implemented and independently rechecked: frozen evidence/supporting hashes, complete parent/prefix delta and candidate identity validation, and persisted after-security/preset evidence. No remaining helper blocker was found; no helper was executed.

The first backend review found two concrete numeric coverage defects. A fully invoiced/net-zero POS family row fell back to the entry's native debit turnover; the revised compute preserves its projected zero. Incomplete rows now hide the monetary figure in list and kanban and expose an Unavailable source action. The second defect remains pending focused coverage evidence: a mixed session with some valid receivable lines can silently omit another misclassified product-display receivable line. Checking only missing receivable lines and explicit payment terms is insufficient. The backend owner is adding a bounded check against actual posted accounts occupying native configured POS receivable roles, without reimplementing native amounts or inventing historical configuration.

The recursive family uses exact primary-session/late-invoice identities, same-company descendants and deduplicating UNION. Monetary queries intersect caller-visible move and line searches; public projection/search methods enforce the accounting gate, including explicit cashier denial. Typed fixed-key SQL predicates and numeric rounding are shared by cards and row/search projection. No new financial write, source-model sudo amount read, or treasury contribution was found in this initial delta. Final acceptance remains pending the focused native POS, invoice/Cash regression and actual UI evidence.

## Coverage refinement review

The expected-account refinement is now present. It matches actual nonzero source lines against native company, combined-payment and split-partner receivable roles; the split property expression delegates company-dependent defaults and field access to native `_field_to_sql`. It does not classify unrelated COGS/tax lines as receivables or add their amounts. Monetary sums remain restricted by both native searches. Fixed source-role metadata affects coverage only. This is a current-configuration coverage check, not reconstruction of past configuration changes.

The zero-POS and mixed-role defects are statically resolved, pending their native fixture assertions. The unavailable list action checks the source's read access; kanban retains a clear unavailable label and source anchor. Existing invoice PASS62 and Cash PASS63 evidence records full rollback, commit guards and module preservation. Expected-account metadata currently spans authorized closed sessions before final line filtering; no capacity claim is accepted beyond the actual bounded timing evidence. No new static release blocker was found in this refinement.

## FL3B initial adapter review

The user reopened the Incoming/outgoing policy before release; the FL3B G0–G3 approval is recorded in the contract. The former final-release boundary is paused until this adapter's tests and final UI binding are accepted. All-mode PASS101 POS plus PASS3 edge cases and the existing invoice/Cash regression evidence remain reusable for unchanged branches.

Initial source inspection confirms private request-local `ContextVar` provenance with guaranteed reset, explicit accounting access, native payment/move/line visibility, bounded reversal traversal and separate primary-sale versus receipt reversal families. The unadjusted captured rows are checked against the native cash report before applying operational additions and settlement adjustments. No original cash-report formula or financial write was added.

Two focused acceptance checks remain explicit: signed subfragments returned from a recognized receipt trace must preserve unrelated fee/mixed counterparts, and a known platform cash path with unprovable origin must retain original cash with an incomplete-attribution warning. The first decorator tags every fragment returned at its recognized trace point; this requires actual native fee/partial/refund allocation evidence, not a synthetic gross-only assertion. The initial implementation collects platform accounts but does not yet use them to detect an unrecognized platform trace. These observations were sent to the backend owner. No final FL3B source/release GO is asserted.

## FL3B backend acceptance

The final targeted evidence records PASS78 with rollback, hard commit guard and installed-version preservation. Reviewed hashes match current source: cash_register.py `e5762b154c0bda5710354957af20c5fee3100f83a889f4d1fee014d3248b7ea8`, platform.py `6cf94607be38c0fb5ca231a663b4f186a449d38e4962006db61fef6e209d3cb2`, unchanged projection.py `b154003a0b1b0df52714d2fcb4f5d97527b118e90c865e8762315fb6681776a9`.

Both initial adapter concerns are resolved by source and native fixtures: a 300 collection into 270 bank retains its signed −30 fee; unmatched platform 70 retains cash with a visible warning; unrelated platform 20 outgoing receives no invented refund adjustment. The 230 negative sale and partial 100/130 actual refunds retain one −230 recognition, with later-month settlement net zero. Primary cancellation, receipt-only reversal, date scope, private move/line denial, cashier/domain denial and card/row/drill parity pass. Original native report exact totals remain unchanged. Measured snapshots are 15.50–62.08 ms on this small isolated fixture, not a production capacity certification.

The fixture's no-write label checks row counts and therefore does not independently exclude updates; final read-only smoke should enforce a read-only transaction. Backend source acceptance has no remaining blocker. Final source/release decision still awaits actual final UI/source binding and the read-only smoke. Existing financial suites need no repetition without a related change or new finding.

## Final working-source acceptance — 2026-09-10

Decision: GO. The earlier pending items above are resolved. Accepted focused financial evidence totals 307 assertions: invoices62, original native cash63, POS101, edge3 and FL3B78, with rollback and commit guards. The final smoke has 36 parity checks under an actual `SET TRANSACTION READ ONLY`, across three companies, resolving the earlier no-write evidence limitation. It preserves the July 1,580 incoming/net and September −1,000 actual outgoing example.

The final UI evidence binds all 13 addon files and 26 browser artifacts; every listed SHA256 was independently checked against disk. Thirteen recorded journeys cover retained All-mode behavior and the final Incoming/outgoing mode. Independent visual inspection of the English desktop and Arabic 480px screenshots confirms three correctly labelled values, native signed source rows/kanban and legible RTL layout. The recorded mobile document width equals scroll width at 480px. Native card drilling and source navigation are supported by the recorded DOM journeys; no browser mutation was performed by the reviewer.

The final helper additions bind FL3B, edge, read-only and UI evidence plus their supporting scripts using the already-reviewed exact-source/evidence guards. Static translation references remain module-owned. The protected 373-table, security/preset/version and coherent backup sequence is unchanged. No outstanding scoped source blocker remains. Freeze must preserve these hashes; production execution still requires a separate exact-commit PREDEPLOY-GO and postdeployment preservation/runtime evidence.

Limits: Incoming/outgoing is the user-approved mixed operational measure and includes Applications settlement adjustments; it is not cash balance or profit. Original cash-category reporting is unchanged. SAR/single-company/monthly operational-mode bounds and measured small-fixture capacity remain explicit. The stock edge fixture proves exclusion of balanced COGS/inventory ledger additions, not a full warehouse workflow test.
