# POS-S3 independent gate / delivery review

Reviewer: s2_review (independent حارس البوابات / فريق تسليم ألفا). Date: 2026-09-07. Target QA only.

## R1 — G0–G4 before implementation

Read POS-SUMMARY-S3.md and existing day_entry.py; reused QA2 map and accepted accounting/ACL/transaction evidence. No application changes by reviewer.

**G0–G4 approved for the bounded implementation described.** A read-only grouped projection plus reconstruction of the existing two-card form is the shortest reliable route that gives a durable daily archive without a second financial source or synchronization layer. Native list/controller extension is appropriate; unchanged G1 bounds and existing G3 dependencies are adequate. G5–G8 remain pending executable and UI evidence.

Required acceptance interpretations:

1. Archive group key is company/date; SQL totals retain numeric precision and the same authorized source set as summary reads. Archive ACL and company rule must prevent aggregate leakage; no public factory accepts forged source links, company, status or amounts.
2. `MIN(source.id)` is a unique deterministic view ID, but not immutable if the minimum draft is deleted. Reopening must re-query and validate the current group; a stale row must fail clearly rather than show another day. No persistent foreign key or claim of permanent day identity may depend on this view ID.
3. Missing morning/evening stays explicitly missing, not an apparent zero card and not a created summary. Mixed draft/approved and incomplete day states are represented honestly; approval remains gated by actual source coverage and existing safeguards. Original corrected drafts, existing approved totals and source links remain authoritative after every reopen.
4. The historical-method reconstruction path must be private and source-derived. Any allowance for inactive or formerly configured methods is restricted to readonly reconstruction of authorized existing allocations; normal entry validation cannot be weakened by a JSON/RPC context flag. Newly configured methods must not silently change old day values or imply a historic allocation.
5. Reconstructed entry is creator-scoped, readonly and disposable. Vacuum followed by reopen reproduces the same source amounts/customers without new summaries, orders, payments, sessions or ledger entries. Existing explicit approval keeps the tested savepoint/idempotence route; opening the archive never posts.
6. One menu and New route must coexist with original source drill actions; do not globally hijack every summary list into the daily archive. The scoped controller affects only the unified archive, preserving native report drilldowns and individual draft correction.

Evidence required for final QA GO: old all-day82 and paired drafts227/228 reopen, one company/day row345/30, vacuum reconstruction, missing/partial and mixed states, inactive historical methods, row/aggregate company access, readonly SQL model, stale row behavior, no financial fingerprint changes, native positive/replay regression as appropriate, desktop/mobile new-and-reopen journey and frozen source/archive hashes.

## R2 — native list action simplification

Lead identified native Odoo19 `list_arch_parser.js` lines227–231, independently read in the installed QA container: the parser sets `openAction` from root list `action` and `type` attributes. **Approved and preferred**: `<list action="action_open" type="object" create="0">` with an always-visible native header New action opening the existing entry. This supersedes the proposed custom ListController extension; no frontend JavaScript is necessary. G3/G4 stay approved on this simpler native route. Original source list/report actions remain unaffected.

## R3 — explicitly requested one-step Save

Reviewed S3-003 and existing action_save/action_approve transaction paths. **Reopened G0/G2 approved for the one-step wrapper; G5 acceptance contract approved, executable G5 closure pending.** User explicitly requests Save to finish posting, superseding QA2's separate approval UI. Calling the existing methods inside one outer savepoint is the shortest safe implementation; it does not introduce new posting logic or grant broader accounting permissions.

The sole visible Save must clearly represent final saving/posting, and no redundant confirmation/approval step is required. New records must finish approved with native posting, or on any failure leave no new summary, order, session, payment or ledger record. For pre-existing saved drafts, failure must preserve their prior draft state and links. Already-approved replay must be idempotent. Financial posting authorization remains enforced by original action_approve; opening/reconstructing archives stays read-only. Incomplete historical split days must not bypass the missing-shift safeguards. Required evidence adds real late-second-post failure after first posting, complete outer rollback including newly created summaries, successful one-step UI save, and retry/no-duplicate behavior.

## R4 — independent one-step concurrency

Ran `pos_s3_concurrency.py` on the final wrapper lock-order revision in QA. **PASS:** simultaneous one-step saves of a fresh entry, and a saved entry's one-step Save racing an independent original-summary approval. Both cases encountered real PostgreSQL serialization failures, retried natively and finished with exactly the expected two approved sources per date. No deadlock or duplicate. Tests used explicit zero-sales days to avoid committed financial records; positive posting and complete late-failure rollback are covered separately by the34 execution-owner checks. Exact temporary entry/summary fixtures were cleaned. Evidence `pos_s3_concurrency.json` and `.log`, marker `POS_S3_CONCURRENCY_OK`.

Read-only archive/factory review found the private historical-method allowance derives values from authorized same-company/date original summaries, uses an unforgeable in-process token and returns a readonly transient snapshot. Normal create/write still enforce configured active methods and caller permissions. The SQL archive adds no stored accounting authority.

## R5 — Save and WhatsApp bounded addition

Reviewed S3-005 and existing native WhatsApp URL composition. **G0/G4 approved; G5 contract approved pending execution.** Reuse the exact atomic Save-and-post path followed by native `ir.actions.act_url` composition; retain ordinary Save and permit re-opening the message after approval. No new transport, service or dependency is required. Employee selects recipient/chat and sends manually; opening WhatsApp must never be represented as delivery confirmation.

Message values must be rebuilt from authorized approved original summaries, with explicit company/date/per-shift counts and totals; no cached editable transient data as authority, no fabricated missing shifts. Tests must decode the URL and assert source-derived Arabic/English totals, repeat/no-duplicate behavior, and failure before creating any message action when save/post fails. Browser verification can inspect only launch; no Send click or contact message is authorized.

## R6 — DAY OFF range in the same entry

Reviewed S3-006 and the existing audited closure authority. **Reopened G0/G2/G4 approved for implementation; G5 contract approved pending executable evidence.** Reusing closure create+confirm inside one savepoint is preferable to a separate absence/zero-sales model. No POS configuration is needed to record an authorized closure; sales mode must still require the original configuration. The mode toggle hides sales cards and metrics while preserving unsaved input until the employee chooses a mode; no hidden sales document is created by saving a closure.

Archive expansion is acceptable: confirmed full-day ranges only, inclusive dates bounded366, readonly closure-source link, closed status and visibly unavailable sales/customer values. Numeric negative IDs `-(closure_id*1000+offset)` cannot collide with positive summary IDs for offsets0..365; calculate in PostgreSQL bigint to avoid integer multiplication overflow. Native ORM/list negative-ID row navigation must be exercised in the browser. Existing half-day closure rules/report denominator remain unchanged.

Required evidence: reason enum plus nonblank custom notes for Other; reversed/oversized ranges rejected; full outer rollback on overlap; repeated/concurrent Save creates one closure only; source-derived company/date/reason on reopen and WhatsApp; no native financial documents or operating-day denominator additions. Cancellation through the original closure screen must remove archive dates and prevent an old transient from falsely sharing the cancelled closure as currently confirmed or silently recreating it. A stale archive row must fail honestly. Guard readonly source IDs/state from RPC input; mode switching before Save cannot bypass company/closure/sales validation. Measure bounded archive query with expanded closure rows; do not describe SQL NULLs as missing if the UI renders them as zero.

## R7 — DAY OFF entry implementation check

Read the updated day_entry.py after lead implementation, before archive integration/final runtime acceptance. No material defect found in this bounded source review. Configuration may be absent for closure mode, while the ordinary summary create path still requires valid native sales configuration. `_save_day_off` encloses original closure creation, confirmation and protected source-link/state update in one savepoint. Replaying a saved entry verifies its original closure is still confirmed and does not recreate cancelled closures. `_from_closure` checks read access, active company, full-day scope and confirmation before producing a private readonly snapshot. WhatsApp uses the original closure's dates/reason/notes and rejects cancelled sources. No application file edited by reviewer. Runtime archive negative-ID opening, hidden sales cards and acceptance suite remain pending final G5–G8 evidence.

## R8 — final QA3 delivery decision

**GO لمعاينة QA فقط. G4–G8 معتمدة ومقفلة للمرشح المحدد أدناه؛ لا موانع جوهرية مفتوحة.**

Candidate: `baseer_pos_summary 19.0.1.2.0`, `docs/releases/2026-09-07-pos-summary-qa3/manifest.json`. Independently recomputed **26 source hashes,19 evidence hashes,26 ZIP-entry hashes and the archive digest: zero mismatches**. Verified28 shared report-layout/purchase files against the accepted previous manifest, unchanged. Frozen archive SHA256 **607d4c5a92a7fd3170654e8e24871833a0f76a977cbd54ca97c4303775633d65**. Workspace has no release commit; source manifest and matching archive are the candidate identity.

Review reused QA2's accepted money/posting map and followed only S3 changes: original sources → read-only daily archive → reconstructed native entry; one-step Save → original atomic save/post; DAY OFF → original audited closure; authorized source text → manual WhatsApp URL. Depth was deep on financial transactions, company isolation, source reconstruction and overlap/replay, focused on UI and native navigation. Reviewer authored/executed the two real concurrency scenarios and reviewed other owners' final reproducible evidence. No application edits or unnecessary suite reruns occurred during final review.

| Gate | Final evidence |
|---|---|
| G4 | Arabic/English native desktop/mobile screenshots inspected; one archive menu, two shift cards, ordinary Save and optional Save/WhatsApp, DAY OFF range with cards hidden.390px archive shows full dates and blank financial cells for closed days without horizontal overflow. Negative-ID date-cell row opening was verified after a scoped readonly date-widget hit-target fix. Native code inspection confirmed no negative-ID navigation restriction. |
| G5 |34 archive/reopen/atomic-posting,24 WhatsApp and32 DAY OFF checks PASS:90 targeted checks. Includes actual first native posting followed by forced second failure with complete rollback, repeated save/share, missing and mixed historic shifts, inactive historic methods, original-source vacuum/reopen, no-POS closure, maximum366-day inclusive range, cancelled-source rejection and source/aggregate ACL. |
| G6 | Two independent two-cursor Save/approval races actually hit serialization failures and retried to the correct result, without duplicates or deadlock. Native archive80-row measurement0.000626s on small QA fixtures; no production-scale claim. Prior closure-company concurrency evidence remains applicable to reused original closure engine. |
| G7 | Actual mobile Save/WhatsApp completed two original approved sources287/288,345gross/45tax/30customers, then opened prepared WhatsApp text without clicking Send. Original approved82 and draft227/228 preserved and old pair reopens together. Original financial-row audit confirms unchanged63 moves/147 lines/1 order/3 payments/3 sessions; intentional QA preview adds exactly4 moves/10 lines/2 orders/2 payments/2 sessions tied to287/288. |
| G8 | Frozen candidate/evidence/source and shared files independently matched; retained QA demonstrations, recovery backup/source IDs, transient-history boundaries, manual-send behavior and local measurement limits documented in HANDOFF.md. Main read-only evidence reports0 moves,0 lines and no installed summary addon. |

The retained DAY OFF demonstration is closure30, September1–2, confirmed maintenance with explicit test notes; it adds no financial documents. The September1–7 daily report reconciles to2145 approved sales/90 customers over2 complete operating days,2 closed and3 missing dates, means1072.50 sales and45 customers. SQL closed amounts remain NULL; the ORM's numeric coercion to0 is not exposed as sales because closed-row fields are hidden. Missing historical shifts are not synthesized.

QA-only boundaries remain: actual company6 configuration, existing platform-clearing accounting policy,25 methods/card,366-day report/closure range, durable original source history versus disposable native transient forms, and manual WhatsApp sending. No live message delivery or production load was certified. Rollback restores the documented matching QA database/source backup, not financial-addon uninstall. This GO does not authorize installation or writes in the original database.
