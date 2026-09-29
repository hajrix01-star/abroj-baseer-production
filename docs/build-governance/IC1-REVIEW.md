# IC1 independent implementation review

Decision: GO

Source acceptance for freezing the reviewed IC1 candidate. Exact frozen-candidate verification and the protected MAIN publication checks remain required before release.

Reviewer: icons_release. Scope: `baseer_financial_correction` over accepted FL2. Read the approved IC1-GOVERNANCE contract, native correction research/source mapping and current core/dispatcher/batch/security source. No application edits or MAIN mutations by reviewer.

## Initial source findings

| ID | Priority | Finding | Owner/status |
|---|---|---|---|
| IC1-R01 | P1 | Untagged payroll settlement cash payments could pass generic owner correction and leave their source stale. | Resolved: protected marker, fixed settlement existence and original/proposed HR account checks inspected; negative cases PASS in the 63-case suite. |
| IC1-R02 | P1 | Grouped taxes could conceal cash-basis children or changed child configuration. | Resolved: native flattened hierarchy and full child fingerprint; grouped-tax positive, cash-basis negative and stale-child cases PASS. |
| IC1-R03 | P2 | A concurrent transient-line edit could persist after confirmation. | Resolved: parent wizard locks and completed revalidation; real concurrent confirm/edit evidence PASS. |
| IC1-R04 | P1 | Audit remained visible after its invoice became payroll-private because a tautological relation predicate was optimized. | Resolved: exact native non-sudo source read domains, preserved Domain objects and actual company context; audit/wizard/line negative search/read tests PASS. |

## Controls reviewed

The shared dispatcher resolves fixed native/source relations and enforces owner/accountant/accounting-manager access, current company and source write rights. Source-owned routes retain their own action checks. Generic financial execution uses native draft/edit/post/reconcile within one savepoint, with no sudo mutation or external payment provider callback. R01 introduces narrowly scoped sudo reads only for a protected classification boolean, fixed company HR account IDs and existence of the exact payment in fixed settlement relations; they reject unsafe correction and expose no HR record or amount. Payment amount/counterparty/journal correction is explicit; invoice amount is not treated as actual paid amount. The capability is an in-process object used only by private audit/batch methods, with no client-equivalent context value.

Wizard creation and baseline/source/completion fields are server-owned; line IDs cannot be reassigned or publicly created. Confirmation rechecks company/state/source/settlements against the baseline, locks native source records, prevents repeated completion and validates posted state, unchanged dates, balance, cash direction and residual afterward. Failure must remain transactional. Immutable audit has a unique operation token and dynamic source/company record rules; transient rules also follow current source visibility. Audit/privacy behavior still requires negative tests, particularly permission/configuration changes after preview.

Batch adapter uses original single-line category/tax and native gross quote, checks duplicate supplier reference, updates only its selected row through a private capability and verifies final native totals. Broader approved-row write bypasses are not introduced. Native locks/hash/EDI/shared settlement/FX/clearing/statement exclusions were reviewed, with effective grouped-tax gap noted above.

Focused accounting, rollback, permission/privacy, duplicate/concurrency and real desktop/mobile UI evidence is now available and accepted below.

Pre-existing native manual reset actions outside the new dispatcher are not globally replaced or disabled by IC1. In particular, this review does not claim global enforcement of purchase-batch consistency against every legacy accounting edit. IC1's audited wizard synchronizes its selected source; broad reset/cancellation policy changes require their own source-owner compatibility scope. This boundary was reviewed with the parent and is not a new regression or an IC1 release blocker.

## Focused source route verification

Independent `ic1_source_checks.py` executed on isolated `baseer_ic1_20260910`: PASS20, rollback=true, commit_guard=true, modules_preserved=true. Actual native dispatcher/source entry actions route POS summaries, payslips and loans to their owning correction models; accountant and cashier do not acquire source-manager rights, direct generic source eligibility is denied, current-company mismatch is denied, and an independent journal opens native reversal. Route execution leaves synthetic entries posted/balanced and creates no generic correction audit. The tests intentionally supply synthetic source links/approved POS state to isolate routing; they do not claim to revalidate complete existing source posting/correction engines. Earlier attempts failed only incomplete fixture metadata and rolled back; final accepted evidence is the PASS20 result.

Release and source-only export helpers were independently reviewed against FL2/FL1 patterns: all1167 accepted files preserved, only the new correction addon added, source/UI/evidence bound, new-addon install only with already-installed dependencies, protected368 existing tables/columns/memberships/presets/versions, and empty new audit required. Exporter correction retains the18→19 custom-module count in README. No helper execution or publication was performed by this reviewer.

## Accepted focused evidence and permission amendment

The final `ic1-checks.json` records PASS63 with rollback, module preservation and a hard commit guard. It resolves R01's protected HR payment/proposed-account path, R02's grouped-tax and stale child configuration cases, and R04's dynamic payroll and independent native move-rule privacy cases. The final concurrency evidence resolves R03: one of two confirmations commits, the stale competing operation is rejected, and a concurrent line edit after completion is rejected with the line preserved. These concurrency fixtures were committed only in isolated QA; they are not represented as rollback-only tests. PASS20 source-routing evidence remains accepted with the fixture limitations above.

Seven UI journeys cover Arabic/English, the native register entry, nested invoice-line editing and confirmation at 480px. The reviewer visually inspected the narrow Arabic line editor and the English register correction dialog: the native fields/actions are readable and the dialog is editable. The final action-context correction is local UI initialization; accounting execution did not change. Existing measured evidence is bounded native fixtures, not a large historical database or production load test.

Before freezing, the user authorized a per-user correction setting controlled by the owner/settings administrator. The approved amendment preserves the default enabled behavior for existing accountants; owners retain correction access and cashiers remain unconditionally denied. Accountant/native accounting-manager callers must pass the setting at the server entry and confirmation checks. Acceptance additionally requires focused enabled/disabled checks, mid-wizard revocation, denied self-grant through write/create/default context, and visibility of the native setting/actions. Previously accepted financial tests are reused unless this amendment changes their execution logic or exposes a defect. No MAIN publication has been accepted yet.

## Final amendment acceptance and source binding

`ic1-permission-checks.json` supplies PASS26 with rollback, hard commit guard and module preservation. It covers default compatibility, all three entry flags, denied invoice/payment/source routing, direct factory bypass, revocation of an open wizard without accounting/audit effects, direct and combined native-preference self-grant, forged create/default context, unconditional cashier denial, owner override and a successful real correction after re-enabling. The reviewed implementation checks the exact user flag at the server boundary and again through `_require_owner` during confirmation; no financial execution algorithm was changed. The new sudo read is limited to the caller's protected permission boolean. Only owner/settings administrators may set it; native source permissions continue to apply.

Final UI evidence contains ten journeys. The reviewer additionally inspected the Arabic owner permission checkbox and the disabled-accountant invoice screenshot, and checked the saved unchecked state in the DOM evidence. The shared correction action is absent for the disabled accountant; existing native actions remain as explicitly scoped. All ten addon SHA256 hashes and all eighteen UI artifact hashes independently match `ic1-ui-checks.json` exactly. The final core hash is `a1003bed71b9a234b78ba02e9ba77ce875fbbf68e30944b6684928b78b6033b8`; dispatcher is `03ff732b250ad647f87b66b3cd771dfcf8135e7b536503878b850ab0398b84d9`; the complete authoritative inventory is that evidence file's `source_sha256` object.

Release helper evidence includes the permission suite and harness. The schema addition is explicitly the default-true user permission field alongside correction/audit models; protected comparisons retain all pre-existing column values, memberships and presets. Source-only export remains addon-only. No unresolved release blocker was found within the approved scope; no broad financial suite was repeated for the permission/UI amendment.
