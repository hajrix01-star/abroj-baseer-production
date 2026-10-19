# BWORK-CENTRAL-SALES-20261019

## Build contract and scope (G0, draft)

Owner approved: make Odoo heat calendar, BWork heat calendar, and BWork overview
match the existing Sales summaries total without duplicate sales. Targets remain
central in Odoo. Approved preview is `output/bwork-dashboard-concept-20261019/leadership-three-cards.html`;
its fixtures/calculations are design evidence only and must not ship as business data.

Fingerprint: base `8ddf6f6e`, clean tracked tree; branch
`codex/bwork-central-sales-dashboard-20261019`. Architecture impact: ARCHITECTURAL,
limited to read-only reporting, central heat calendar and BWork report navigation.
Stable BWork 0.1.20 and current Tasks 0.1.21 are regression baselines. No chat,
orders, receipts, tasks, media, stock, journal, invoice or summary writes.
No QA/Live deployment, release, target edits or production test data authorized by
this step. Do not change the canonical Sales summaries metric to make tests pass.

### Accounting / acceptance

- Sole sales authority: `spreadsheet.dashboard.get_baseer_sales_metrics`, final
  override in `baseer_sales_dashboard/models/unified_sales.py`,
  `cards.sales.value/display`. Includes approved summary gross amounts, disjoint
  non-bridge paid/done POS and restaurant orders, posted Sales-linked invoices /
  credits, VAT included, signed refunds. Existing bridge and POS-invoice/reversal
  exclusions remain authoritative. Session opening date in Riyadh for POS,
  summary business date, invoice date: identical to the summary's own rules.
- Heat daily money must reuse the SAME `_baseer_unified_period` result, never add
  native POS to summaries, duplicate its source SQL, or silently substitute cash.
  One period's displayed daily values reconcile exactly to the summary headline
  for identical company/date/currency. Future-dated records in the selected
  canonical period must not silently disappear; status/evaluation are separate.
- Targets: existing `baseer.heat.calendar.target` only; company/year/month/weekday
  uniqueness, inactive targets ignored, native fallback median/occasion logic
  retained. No mobile goal table, independent target calculation, or goal writes.
- Weekday averages: completed days with positive sales only; zero/missing/current
  incomplete days excluded. The server calculates averages, ratios, forecasts,
  multi-company totals and formatting (Decimal, HALF_UP, two-decimal money,
  English digits in both languages). Client never aggregates business values.
- All-company mode includes only authorized companies, defaults to all; a single
  authorized company is automatic. No silent partial totals if a source or company
  is unreadable. A BWork dashboard user option gates access but does not grant
  Odoo report ACLs. No sudo for report/target reads.
- Overview uses the approved three cards, current-month trend / same-period
  comparison, day/date filters and server-derived current-month averages. Preserve
  missing versus zero, independent current-month comparison, silent refresh,
  cancellation of stale responses and clearing on account/company revocation.
- Reuse existing purchase/expense authority, clearly label its available scope;
  do not invent broad ledger expenses or call Sales minus spending profit/cash.
  No fabricated client percentages such as the preview's 35%/15%.
- AR/EN, RTL/LTR, full numbers (no abbreviated thousands/currency repeats),
  compact heatmap tab, day details and chart inspection on small/large screens.

## Capacity profile (G1, proposed)

Reuse canonical limits (100k source rows, explicit range guards) and existing
heat-calendar month + 8-week baseline bounds. Current observed product context:
7 authorized companies; assumption <=20 concurrent reporting users, not a measured
capacity claim. API should accept bounded month and one day/date period, cap
company count explicitly, return only daily aggregates, not source rows, and
never truncate without error. Reuse current indexes/read-only sessions and native
transport. No new cache tier/queue or dependency. Any cache is short-lived memory,
scope-keyed, read-only, cleared on session loss and explicit permission denial.
Performance target: warm response <2s for normal owner workload, measured only
where a safe representative local/isolated environment is available. No live load.

## Architecture / contracts (G2, proposed)

`canonical unified sales reader -> Odoo heat day adapter -> existing heat target,
occasion/status evaluator -> Odoo heat UI and BWork read-only reporting bridge`.
`canonical summary RPC -> BWork overview server response`.
Add an optional isolated BWork reporting bridge add-on if needed rather than
making the chat core depend on financial modules. Reuse native session/auth, existing
navigation/design components and translation dictionaries. Target management stays
in Odoo. Existing BWork endpoints and old APK behavior remain compatible; new
capability is optional and unsupported servers show an update-required state.
Document exact route schema/ACL/limits before its implementation.

## Technology / verification (G3, proposed)

Keep Odoo19/Python and existing BWork React/TypeScript/native session stack. No
package installation, framework migration, or external chart runtime. Reuse existing
SVG/DOM primitives/components. Tests: Odoo actual ORM parity across all four sources,
signed refunds, bridge/invoice dedup, cross-date summaries, zero/missing/partial
days, targets, company/record ACLs; mobile transport/state/UI tests and
`npm run check:bwork`. Python compile or source seams are not ORM verification.
Native/browser AR/EN narrow/wide acceptance must be identified separately, not
inferred from JSDOM. Financial parity on actual QA data requires authorized
authenticated reads, not the invoice-only QA reports connector.

## Gates

| Gate | State | Evidence / independent reviewer |
|---|---|---|
| G0 | GO, bounded local implementation | independent sales_summary_source_review; canonical metric unchanged, no deployment/data writes; R04 |
| G1 | GO with enforced budgets | month + 8-week window; canonical access/capacity checks before materialization; bridge company/request cap frozen before bridge code; R04 |
| G2 | GO for canonical heat adapter, targets and C1 bridge | shared source authority, exact C1 wire/routes/limits; bridge implementation released under R06 boundaries |
| G3 | GO | existing Odoo/BWork stack, no dependencies; actual ORM parity and mobile state/UI verification remain required; R04 |
| G4 | GO, actual native synthetic UI accepted | source69db5f8d; AR/EN320/900 after geometry repairs; R24, not QA financial proof |
| G5 | Local + actual isolated Odoo PASS | local466 PASS/1 existing optional skip/95 invariants; current-head run39267547320 reports0 failed/0 errors of110 tests, no actual test skips; R23 |
| G6 | Independent local source review accepted | central_sales_independent_review; findings below closed by delta review |
| G7 | QA candidate0.1.22/build23 requested | source metadata frozen; synthetic preview only, ordinary APK not built/published |
| G8 | Source-only merge GO; QA/APK NO-GO | independent source/native/current CI accepted R24; installed dependency preflight, host receipt and authenticated QA parity still missing |

The first isolated failures in R12 and newly exposed R16 failures are repaired;
the same pinned workflow now passes at the exact R17 source head. This is actual
isolated ORM/HTTP proof, not native visual acceptance or QA financial parity.
Owner authorized QA-first order in R20. Independent source-only merge approval
is recorded in R24; QA deployment/publication prerequisites remain enforced.

### Maintained architecture / authority map

```text
Odoo authenticated user + protected BWork switch + native report/source ACLs
  ├─ Sales summaries public RPC ────────────────→ overview headline
  └─ canonical unified sales reader → heat evaluator ← central Odoo targets
                                       ├─ Odoo heat calendar UI
                                       └─ optional BWork GET bridge → scoped native engine → dashboard UI
supplier-bill private ACL/domain/totals helpers ──→ bridge spending/difference
```

Verified source boundaries: existing summaries/heat target models; new routes,
permission switch and native facade. Capacity/concurrency figures are assumptions,
not measured production claims. All financial values and comparisons are owned by
the backend; client arithmetic is restricted to graph point coordinates/calendar
presentation. Same snapshot and source-read transaction, no writes from reports.
No duplicated mobile target table, source mutations, offline financial cache,
report sudo or alternate financial engine. This updates the registry map only;
there is no full-system rediscovery or separate duplicate map artifact.

## Append-only operations

- R01 (2026-10-19), intent/result: reuse previous read-only source audit and registry
  rather than repeat discovery. Canonical identity/RPC/metric, heat scope mismatch,
  target scope and permissions verified in source. QA actual parity NOT established.
  No business data reads/writes, dependency installation or deployment.
- R02, intent/result: create independent local branch. First git-switch attempt
  failed on read-only shared git metadata; scoped approved escalation succeeded.
  Working directory remains the existing task-owned worktree, base unchanged.
- R03, intent: independent gate review of this draft; no application implementation
  until accepted. Source contract details may be tightened by reviewer.
- R07, intent/result: implement isolated heat adapter, optional reporting bridge,
  native report engine/UI and additive navigation under accepted C1. Root owns
  runtime/shell/drawer integration, workers own disjoint new report folders and
  heat module; no frozen chat/order/task calculators changed. Dashboard-only
  non-chat admission is explicit and does not confer chat/orders/tasks rights.
  Focused actual session/shell/navigation execution: 45 PASS, 0 FAIL/skip.
  Source heat compile/XML/diff checks PASS; actual ORM unavailable (Docker daemon
  pipe absent), no environment started. Independent source review is running.
- R08, intent/result: independent heat/bridge/native source review and closure.
  Fixed shared summary/allocation budget to cover drafts, deterministic SAR/date
  test fixtures, ISO shared bridge timestamp, conditional stored-currency bulk
  fixture, and Arabic presentation. Added fail-closed public headline/central-day
  reconciliation for selected/current/prior periods, including future recorded
  money. Fixed complete verified-company options equality and visible percent
  units/sign semantics. Review confirms closures and no remaining functional
  blocker found in reviewed local source; this is not runtime approval.
- R09, final local verification: bundled Node `tools/check-bwork.cjs` from
  `mobile/chatwoot` PASS in 12.93s including TypeScript: gate4, Odoo-client288,
  brand5, orders98, tasks48, leadership21 =464 tests, 463 PASS, 0 FAIL, 1 pre-existing
  optional archive-capacity skip. All92 named guards executed and passed; no old
  invariant or test deleted/skipped for this feature. Final Python compile and
  three pure contract tests PASS. Module manifest/XML parsed. Actual production
  Python serializer with synthetic sources → actual strict TypeScript decoder
  now runs automatically in leadership suite; proves wire compatibility ONLY.
  No changes to canonical sales module, chat core, order or task business code.
  Isolated Odoo workflow extended to install/test the optional bridge, but not run
  remotely. No source push, PR, merge, QA/Live update, APK or goal/business writes.
- R10 (2026-10-19), owner explicitly approved source upload to a review branch
  and isolated Odoo CI, with results reported before any merge/deployment.
  Test profile: canonical heat/bridge source change; ORM financial/ACL/HTTP risk
  not covered by local compile/host tests; observed owner scope7 companies,
  existing assumption<=20 concurrent readers (not a new load claim). Reuse the
  existing disposable pinned Odoo19/PostgreSQL workflow; no QA/Live load/data.
  Local candidate `f97d40fcb10c94e018aba3b55b4aaa36dbf52f90` uploaded unchanged to
  `codex/bwork-central-sales-dashboard-20261019`. CLI gh token was invalid, but
  Git credential-manager dry-run verified scoped push permission; no credentials
  were requested, exposed or changed. Current main fetched read-only.
  Clean review commit `f6897e215daacfd23819150c7d121c4166be7546` is based on
  main`b1e871b8a6e3db26c0ec05ebe113e0961c4c95e5`, tree`33b382f45d58c0fb9d9b7285dfc32d0391c71e9b`.
  It applies the feature/workflow/doc delta and imports the complete frozen BWork
  subtree`f3c754cd46c7e4c548c7a6bc14a8ed47d28441bd` (not previously in main), without
  copying unrelated local main divergences or overwriting QA policies. Product
  paths compare byte-for-byte equal to local f97; canonical sales/BChat/ops diff
  versus main is empty. Draft PR420 opened, no reviewers/auto-merge requested.
  Run39258483362 is the actual isolated Odoo run; no merge/deploy authorized.
- R11, initial external evidence: cumulative contracts run39258483265 succeeded.
  Source integrity run39258483309 failed `git diff --check` on existing imported
  mobile files: `.cursor/rules/about.mdc` and five vendor patches (clipboard,
  menu, ffmpeg, iOS utilities, reanimated). These files were unchanged between
  reviewed base8dd and candidatef97; initial import into main made their existing
  whitespace visible to the whole-PR gate. Do not trim patch context blindly,
  weaken the gate or claim source integrity passed. Actual Odoo run remained in
  progress at this observation; its result is independent and not inferred.
- R12, completed external result (2026-10-19T13:19:41Z): isolated Odoo run
  [39258483362](https://github.com/hajrix01-star/abroj-baseer-production/actions/runs/39258483362),
  job118079706252, FAILED. Final Odoo summary reports`1 failed, 6 error(s) of101 tests`;
  do not sum overlapping per-module statistics or infer that unstarted class
  methods passed. Checkout merge`ede9f3b1e445b5043a942ee2a5ef40ff8228acb4` is recorded
  in logs; review head remainsf6897e21 and PR420 draft/open/unmerged.
  Findings:
  - RT-01: `HeatPosCase.test_order_and_session_rules_intersect_and_company_session_scope_is_enforced`,
    test_heat_pos.py:421, expected AccessError after a rule hides contributing
    sessionB; no error was raised. Root cause is NOT established; do not weaken
    the assertion or classify it as harmless before diagnosing rule/caching/read
    behavior under the pinned runtime. This blocks source permission acceptance.
  - RT-02: `TestHeatUnifiedSales.setUpClass` fails creating spreadsheet.dashboard
    under its accounting-fixture identity, so new unified parity methods did not
    run. Four bridge test methods fail creating Sales-order fixtures; a fifth
    fails changing dashboard visibility. These six setup/access errors must be
    fixed in isolated fixture preparation without elevating report readers or
    granting production source rights. No actual full-source parity pass exists.
  - RT-03: source-integrity run39258483309 fails initial-import legacy whitespace
    as described in R11. Preserve meaningful vendor patch context and do not
    bypass the source gate. Cumulative contracts run39258483265 PASSED.
  Result posted on PR420 (conversation comment6268228060). No product/test fixes,
  retries, merge, QA/Live deployment or APK/release were performed in this turn;
  the user requested the result before any further merge/deployment action.
- R13, repair authorization: owner approved diagnosing/fixing and rerunning,
  explicitly forbidding weaker permissions or bypassed tests; still no merge or
  deployment. Reuse the current architecture map and pinned runtime. RT-01 cause:
  native Odoo19 applies comodel record rules to dotted session domains, so a
  readable POS order can disappear before mapped-session access validation. No
  prior same-environment success was established; do not call this a proven
  runtime regression. The new report's fail-closed requirement was not met.
  Independent source review ruled out simple rule-cache staleness (rule creation
  clears native rule caches) and accepted a bounded ordinary-rule session-link
  probe before relational date filtering. Shared guard is in canonical source
  authorization, not in financial aggregation; no sum/date/refund/dedup formula
  changed, no sudo/hidden date or amount read. This strengthens refusal for any
  readable confirmed own-company order linked to an inaccessible session; its
  global scope matches the existing missing-date safety guard. Sales and heat
  now share the refusal. Sales module patch version19.0.1.7.1.
  Existing failing assertion retained; added warm-cache, direct-link, explicit
  session-denial, pre-materialization and public Sales RPC regression coverage.
- R14, RT-02 repair: isolated fixture creators use an explicit privileged fixture
  environment for native source/target/dashboard/user setup. All report calls
  remain with separate ordinary readers; added non-sudo/non-system assertions.
  No ACL/record-rule or negative test weakened; no skipped/removed test. Separate
  independent reviewer accepted both fixture files and the shared source guard.
- R15, RT-03 repair: reformatted only blank context/removal patch lines using the
  installed pinned pnpm10.11.0 parser/applier semantics; insertion and meaningful
  content untouched. Independent in-memory proof over7 installed native files:
  original and converted forward patches produce byte-identical targets; Git
  patch syntax/reverse checks pass. Reverse restoration of removed whitespace
  can differ, but authoritative forward installation output is identical.
  Twenty offending patch lines and ordinary Cursor-doc trailing spaces removed;
  no .gitattributes exemption, source-gate or workflow bypass. All affected lock
  hash references updated mechanically. Frozen/offline/lockfile-only pnpm check
  PASS371ms without scripts, package installation or network. Added exact patch
  fingerprint/lockfile guard; full BWork gate465 cases/464 PASS/one existing skip,
  all93 invariants and TypeScript PASS12.81s. Correct-root Python compile PASS;
  first compile invocation had wrong cwd and was not counted as evidence.
  Next isolated run reuses same disposable pinned workflow: changed source
  authorization + fixture setup; uncovered risk is actual ACL/financial/HTTP
  execution, actual owner scope7 companies, assumption<=20 readers (not load).

- R16, first repaired isolated execution at review head`e4556bd4`:
  source-integrity39261319099 and cumulative-contract39261319299 PASS. Actual
  Odoo39261319103/job118089404998 FAILED, final`3 failed, 1 error(s) of109 tests`.
  Independent log review confirmed both the original heat hidden-session case
  and added public Sales regression executed without failure; both HTTP cases
  and all7 unified-heat methods ran. No longer blocked by fixture ACL setup.
  The newly exposed failures have two causes: all3 bridge failures hit native
  translation fallback when context language is absent; local date`cursor`
  is mistaken for the database cursor by Odoo's `_get_cr`. Both baseline and
  occasion date-loop variables renamed, preserving native user-language fallback
  rather than forcing English. Added ordinary-reader missing-language regression
  with positive sales and a confirmed occasion; heat module19.0.1.1.4.
  The remaining heat error is real Saudi future-invoice validation during setup.
  Fixture posting must use a consistent later clock (including l10n_sa's own
  datetime clock), then report at the earlier test clock; never bypass the
  validation, alter posted dates or remove future-money/target assertions.
  Same pinned isolated suite rerun required after these actual code/fixture
  changes; no load retest (owner7companies, assumed<=20readers). No merge/deploy.

- R17, repaired source mirror`93f4a641ef6fe7c417d3c3a81da3369b9274bb79`
  uploaded to clean review head`1f0f49fe94b7f54a0d44467c1a67c17e34cb28ec`;
  product paths verified byte-identical. PR420 remains draft/open/unmerged.
  Pinned isolated Odoo run[39262869103](https://github.com/hajrix01-star/abroj-baseer-production/actions/runs/39262869103),
  job118094798203, checkout merge`627f989656fbcca2950a6bf7a9f00083fbabb3df`,
  SUCCESS: final`0 failed, 0 error(s) of110 tests`;110 actual test starts and no
  actual skipped tests. All7 unified-heat cases,10 leadership ORM cases,2 HTTP
  cases, original heat/new Sales hidden-session cases and missing-language
  regression executed. Source39262869092 and cumulative contracts39262869085
  also PASS. Test setup now posts through the real Saudi validator with its
  own Python datetime clock wrapped, preserving real combine/normalization;
  asserts posted state and actual confirmation timestamp before earlier-clock
  report assertions. No ACL/rule relaxed, failed assertion removed, test skip
  added, source gate excluded or financial formula changed. No QA/Live data,
  targets, APK/release or deployment touched. Existing non-failing translation
  fallback warnings remain (including occasion-name generator); do not claim a
  warning-free log or complete native-language acceptance. Documentation after
  this tested source is evidence only and does not require rerunning unchanged
  product tests. Owner is to receive this result before any merge/deployment.
  Independent central_sales_independent_review fetched final job logs and
  confirmed110 unique test starts/zero actual skips, exact tested head, all
  specified cases and valid native Saudi posting fixture. Accepted repaired
  source + isolated CI only; no native UI/QA parity/merge/deployment approval.

- R18, owner now authorizes native preview and authenticated QA parity; only if
  acceptance succeeds, merge through PR, protected QA-only deployment and APK
  publication on GitHub download page. Live explicitly excluded. Reuse R17
  source/110-case runtime and current architecture; no repeated unchanged ORM
  or capacity run. Alpha delivery conducts independent candidate/operations
  acceptance. Native proof gap: LeadershipScreen has only host/design evidence;
  use existing AVD with isolated synthetic uipreview package, actual screen/engine,
  AR/EN320/900 and no real HTTP/account/storage or normal app mutation. Owner
  scope7companies/assumption<=20readers; this is layout acceptance, not load.
  Existing QA workflow only accepts main-ancestor policy commits, so candidate
  parity cannot precede merge/deploy through that approved path. Connected QA
  reports expose invoice-only totals, not the canonical union; no usable browser
  session is available (CUA inventory onlyMCPapps; IAB unavailable). Independent
  operations reviewer confirmed the prerequisite conflict and access gap.
  Asked owner whether to authorize QA deployment before financial parity (APK
  remains withheld until parity), and for an approved authenticated QA path.
  No merge, deployment, account grant or publication while prerequisites missing.
- R19, bounded QA connectivity with a fresh anonymous in-memory cookie container:
  known database login returned200 at`/en/web/login`; new leadership/options
  returned404 at`/en/bchat/api/v2/leadership/options`. This proves connectivity
  and that anonymous request's outcome only, not installed commit, authenticated
  capability, accounting parity or a valid before/after activation comparison.
  No existing browser cookies/private storage inspected and no credentials read.
  Native agent approved to boot existing AVD without wipe/normal-app mutations,
  build one offline isolated uipreview fixture of the real screen/engine and
  capture AR/EN320/900. Any fixture is ignored output, never ordinary APK data.
  Remaining financial acceptance once authorized access exists: same ordinary
  account/company/date/currency reads from canonical Sales summary, Odoo heat
  and BWork leadership; exact monthly/daily monetary parity, all-company scope,
  signed refunds/dedup and central target identity, plus denial without partial
  totals. No fiscal/goal writes or shared-environment load test authorized.
- R20, owner explicitly approved revised order: after tests/native preview and
  independent acceptance, merge and deploy QA first, then actual authenticated
  parity before APK publication. Live remains excluded. Owner asked to clarify
  access; explained that reading the full report needs signed-in QA account,
  not just the URL, and no password/token should be sent in chat. Authenticated
  parity and exact QA host result remain unproved; this approval does not turn
  the invoice-only connector or a queued request into that evidence. Candidate
  release metadata planned0.1.22/build23 only after preview build input is frozen.
- R21, isolated preview build frozen before metadata edit: packageuipreview only,
  no normal app overwrite. Candidate changes only trial version0.1.22/code23 in
  app.config.ts; Chatwoot version, package IDs, dependency lock, permissions and
  all reporting/calculation/product logic unchanged. Run existing BWork gate for
  candidate metadata/source provenance, then update draft review and retain exact
  current-head mandatory CI checks. No new Odoo/load environment, and no source
  backend change justifying a discretionary repeated ORM run. Generated Android
  metadata belongs to the later ordinary candidate build, not a tracked source
  override. Final native acceptance and QA prerequisites still gate merge/deploy.
- R22, native900 surfaced two genuine presentation/inspection defects; G4/G5/G8
  reopened, not classified as proven regressions (no prior same-environment
  success). Default SVG`meet` centers320px art inside710px touch bounds while
  handler uses full width: tapping visible day6 selected day12. Percentage-width
  flexWrap heat slots round into6columns at900 under7weekday headers, shifting
  dates. Root/independent reviewer confirmed code and actual PNG evidence under
  `output/bwork-leadership-20261019/native/`. Alpha bug-resolution applied.
  Minimal local fixes: SVG preserveAspectRatio=none matches existing inverse;
  explicit non-wrapping7-slot week rows include leading/trailing blanks, share
  header slot geometry, and center weekday money locally. No backend amount,
  date/filter calculation, ACL, dependencies or frozen module changed. Both
  regression tests failed before repair and pass after it; corrected host-tree
  child traversal in the calendar test, not its assertions. Add2 protected
  invariants, run candidate gate, then one justified offline preview rebuild for
  real AR/EN320/900 chart-hit/calendar-alignment proof. Owner7companies/assumed
  <=20readers; native geometry risk not covered by host doubles, no load rerun.
  P2only observations remain: extra date/time fields in month control, small
  narrow calendar touch widths and English Estimate wrap. No silent polish scope.
- R23, repaired candidate69db5f8d uploaded to clean review head
  `e6a4e3f8712c9abab528cea89c157c846f71aae9`, tree
  `ee8abde05b88cb65bb4af967536d733dab402b06`. Product paths including current
  governance verified byte-identical to local frozen source. Full local gate:
  467cases/466PASS/one existing optional capacity skip,95invariants+TypeScript,
  13.96s. Current-head CI source39267547211/contracts39267547315/Odoo39267547320
  all SUCCESS; Odoo job118110966883 final0failed/0errors of110,110actualstarts
  and zero actualtestskip markers. This is mandatory PR-head validation, not a
  newly invented financial/load environment. Independent delta review accepted
  causal layout fixes and additive tests/guards; native closure remains pending.
  Owner repeated to follow the prior publication method; do not interpret this
  as waiving QA financial parity or expanding dependency initialization. Read-only
  QA preflight gap confirmed by actual wrapper315–377: it checks explicit module
  states, not dependency closure; installing bridge can implicitly install absent
  native_spend and run its root-plan configuration hook. Old source archives
  prove code presence only; historical Live installation is not current QA state.
  No approved SSH alias config is present; browserChrome/IAB unavailable and
  anonymous QA is login-only. No credential/secret-file discovery attempted.
  Before queueing3-module policy need installed/compatible dependency evidence;
  coherent QA backup does not authorize unknown initialization scope. No QA request
  or APK publication until its prerequisites can actually be satisfied.
- R24, final native closure and independent acceptance: actual AR/EN320/900,
  12native plot taps (days1/6/30) all selected the exact expected date; all4heat
  geometries show7columns (Oct1Thu/Oct2Fri/Oct3Sat), weekday average centers
  within1px. Postfix proof under`native/69db5f8d/` plus APK/bundle manifests in
  `output/bwork-leadership-20261019/`; fixture APK65,623,360bytes SHAprefix9F060082
  belongs to isolateduipreview0.1.21/build22, NOT ordinary0.1.22/build23. Same
  synthetic harness; ordinary installed0.1.21 app preserved. Independent reviewer
  verified actual PNG/XML/touch evidence, hashes, exact current CI head and all
  110unique tests. GO for PR420 source merge ONLY at e6a4e3f8; QA dispatch/APK
  remain NO-GO pending explicit dependency/host/authenticated parity proof. Main
  verifiedb1e871b8; automatic workflows are PR checks only, Live dispatch remains
  separately manual/protected. Intent: expected-head squash merge, verify exact
  merged tree matches reviewedee8abde0 and parentb1e871b8; no release/deploy call.
- R25, source PR420 merged by expected-head squash after independent source-only
  GO. Actual commit`3497dc5d1bb0351fd2282fb16120899b8c634759`, parent
  `b1e871b8a6e3db26c0ec05ebe113e0961c4c95e5`, full tree
  `ee8abde05b88cb65bb4af967536d733dab402b06` exactly equals the tested review
  tree; fresh PR metadata confirms closed/merged. No QA policy/dispatch or Live
  approval/deploy call was made. QA request stays blocked on current installed
  dependency/state proof; actual financial parity and host receipt unavailable.
  Ordinary0.1.22/build23 APK not built/published: generated Android release bytes
  currently belong to explicitly synthetic uipreview, never distribute them.
  Future normal build must synchronize ignored native metadata23, regenerate
  normal entry/bundle/APK and pass normal-artifact/signature/upgrade verifier.
  Agent restored320x640/density160/font1.0 and normal installed0.1.21 app unchanged;
  final12touch/4geometryproof and coherent report read by root. Operational
  release decision NO-GO until missing QA access/dependency/host/parity gates;
  do not substitute prior QUEUED-only method for verified financial acceptance.

## Local handoff / remaining acceptance

| Area | Owner / evidence | Result |
|---|---|---|
| Truth of money / ACL / capacity | source review and actual isolated Odoo110 cases R17; canonical sum/date/dedup unchanged | isolated ORM/HTTP PASS; operational QA parity still unproven |
| API consumer / revocation / language | strict decoder, real React host execution, generation/denial cases | local PASS, not native visual acceptance |
| Regression / links / simplicity | unchanged frozen calculators; additive optional bridge/native routes; full baseline | PASS, no dependencies added |
| Operation / candidate / acceptance | uploaded draft PR420, same pinned workflow PASS | not merged/deployed; owner review + operational acceptance pending |

Remaining blockers before operational release:

1. Report R17 success to owner and preserve the explicit stop before merge or
   deployment. R12/R16 isolated blockers are resolved; do not rerun unchanged
   tests or equate this passing isolated DB with real QA financial parity.
2. Verify actual native AR/EN narrow/wide rendering and representative response
   times against the fixed source candidate. React host tests do not establish
   font/layout/keyboard/device acceptance. No representative load was applied.
3. For a later authorized QA release: authenticated parity against the visible
   Sales summaries for identical company/date/currency, user-rights smoke check,
   build/verify fixed APK provenance, and publish through approved PR/release path.
   The invoice-only reports connector is not that financial-parity authority.

Minor residual: the native heat RPC captures its own clock per invocation. The
bridge controller/service share one timestamp and money reconciliation fails
closed, but a midnight-crossing request can still have mixed native day-status
clock evaluation; no end-to-end atomic status-clock claim.

Activation after accepted isolated verification: install/update heat adapter and
optional `baseer_bwork_dashboard` together; an administrator enables the new user
option only for users who already hold the required native report/source rights.
Default remains off; no existing user permissions were changed in this task.
Targets continue to be edited only in the existing Odoo central target model.
Rollback/source boundary: previous stable app/source are untouched, no financial
schema/data migration; disable optional dashboard switch before rolling back the
optional reader/UI, using the normal approved release path rather than live edits.

## Bridge contract amendment C1 (G2 review before bridge implementation)

Optional add-on `baseer_bwork_dashboard` depends on BChat, sales heat calendar,
supplier-bill dashboard. It owns `res.users.bwork_dashboard_view` (default false,
administrators edit only) and additive effective/bootstrap `dashboard_view` plus
`leadership_version=1`. No source ACL escalation: sudo permitted ONLY to read
this user's own protected switch like existing BChat; never for reporting.
Disabling switch increments native permission revision/publishes permission hint.
Existing endpoints/old APK remain compatible. New reporting paths require actual
user session, internal active user, switch and all native source ACLs.

- GET `/bchat/api/v2/leadership/options`, no query/body: `{api_version:2,
  leadership_version:1,can_view:boolean,companies:[{id,name}],max_companies:10}`.
- GET `/bchat/api/v2/leadership`: exact keys `company_id?` (positive ID; absent means
  all), `month` (YYYY-MM), `period` (`yesterday|today|month|date`), `date?` (required
  only for date, ISO calendar date within requested month). No unknown params,
  body, public/auth-token/sudo fallbacks, goal writes or business mutations.
- All-company max10; source budget100k across requested companies over the union
  of month, prior comparison and 8week history, preflight before materialization.
  No silent truncation/partial-company total. Response <=1MiB, no-store.
- Bound selected range: month=full calendar month, day presets=current Riyadh day
  or yesterday, custom date within month. Call canonical summary public RPC for
  selected headlines with identical native range; never use heat total as headline.
  Return exact filter dates, currency, company scope and `source='sales_summary'`.
- Reuse canonical heat RPC per company, same source revision and snapshot. No
  duplicated goal storage. On `all`, day target can sum ONLY if every contributing
  company has an active explicit target; otherwise null/neutral, not a mixed
  target+baseline ratio. Other status/missing/coverage must remain explicit.
- Current-month comparison uses completed past dates (not a partial current day
  against a full previous day); label its actual bounds. Weekday averages positive
  completed sales days only; normal daily mean includes known recorded zero days.
  Forecast is clearly estimated, server-calculated, unavailable for insufficient
  complete observations. Historical chart month does not redefine current-month KPIs.
- Supplier-bill spending reuses current supplier dashboard's gross signed bill /
  credit authority and is explicitly scoped as supplier bills, NOT all ledger OPEX.
  No preview35%/15% fabricated split. Sales minus it is a difference, not profit.

### Wire schema (additive version1, exact decimals as strings)

`Amount={value:string|null,display:string,available:boolean}`; every financial
result uses Amount. `Day={date:ISO,day:int,weekday:int(Monday0),sales:Amount,
status:string,status_label:string,has_sales:boolean,target:Amount,basis:Amount,
basis_kind:target|baseline|none,ratio:Amount,heat_level:string,coverage_label:string}`.

Response:

```text
{api_version:2,leadership_version:1,source:'sales_summary',
 companies:[{id,name}],company_id:int|null,currency:'SAR',as_of:string,
 filters:{month:string,period:string,from:string,to:string},
 overview:{sales:Amount,spending:Amount,difference:Amount,
  spending_ratio:Amount,difference_ratio:Amount,spending_scope:string,
  current_month:{month:string,from:string,to:string,sales:Amount,
   daily_average:Amount,forecast:Amount,sales_change:Amount,
   spending_change:Amount,difference_change:Amount,completed_days:int,
   previous_sales:Amount,previous_daily_average:Amount,comparison_label:string}},
 calendar:{month:string,label:string,week_start:5,days:Day[],
  weekdays:[{weekday:int,name:string,average:Amount,sample_count:int}]},
 previous_calendar:{month:string,label:string,week_start:5,days:Day[]}}
```

No point-level source IDs/private details in mobile response. Drill-down is local
day/amount/goal comparison, not arbitrary Odoo action execution. App forwards
server displays/English digits, keeps compact tabs, full prior month series,
scope-keyed last results during silent refresh; abort on filter/session changes
and never retain financial results on explicit permission/session loss.

R05 intent: review C1 independently before bridge or mobile producer/consumer
code. Heat adapter alone proceeds under R04. G4 central UI catalogue is existing
`src/odoo/ui/components`, `CompanySelector`, `NavigationDrawer`, `DateTimeField`,
`Brand`; dashboard-only heat/series presenters remain local. No new UI dependency
or animation; immediate keyboard/graph feedback per emil-design-eng. Actual UI
render/native verification remains a separate acceptance gate.
- R04 (2026-10-19), independent sales_summary_source_review G0–G3 decision:
  GO for bounded local implementation of the canonical heat day adapter and
  read-only reuse of existing targets. Read this contract fully and checked the
  current unified source reader, heat aggregation/evaluator, target model and
  target ACL/company rules. No application code, business data, deployment or
  external state changed by this review. Mandatory implementation boundaries:
  `_baseer_unified_period` is private and does not itself enforce source-model
  access or capacity; invoke `_baseer_unified_access` and
  `_baseer_check_capacity` on the full month plus eight-week history window
  before materializing it, under a clean single-company Riyadh context and the
  caller's ordinary ACLs. Keep its bridge checks, global POS invoice/reversal
  exclusions, Decimal daily amounts and approved-summary/daily-report subtotal
  reconciliation. Preserve signed refunds and all canonical selected-period
  money, including future records; no old POS `now` filter or `invoiced`-state
  union may alter that money. Valid mixed canonical sources are not a duplicate
  or a conflict merely because they share a day. Preserve real closure/manual
  completeness and open-session evidence for evaluation; dates on or after
  Riyadh today remain incomplete/unevaluated, and weekday averages and fallback
  samples use positive completed past days only. Do not turn unknown guest
  counts into transaction counts or zero. Existing active company/year/month/
  weekday target reads remain central, ordinary-ACL protected and unchanged.
  The optional bridge may be designed next, but its exact route/request/response,
  explicit company-count and total request budgets, authorized-company
  selection, all-or-error source access and stale/denied-state behavior must be
  recorded before bridge implementation; this is a bounded implementation
  dependency, not permission to invent a second calculator. G5/G8 require actual
  ORM daily/headline parity, refund/dedup/date/ACL/target evidence and independent
  review of the resulting delta; this GO does not claim those tests or live parity.
- R06 (2026-10-19), independent sales_summary_source_review C1 decision:
  GO; G2 bridge implementation released for the optional add-on and complete
  dashboard UI within C1, using the unchanged source stack and no dependencies.
  Independently read the full amended contract and checked the existing supplier
  spending seam. C1 now defines the session/switch authority, exact additive
  versioned routes and payload, ten-company limit, 100k preflight budget, 1MiB
  response bound, canonical sales RPC, target ownership and no-store/revocation
  behavior sufficiently for local implementation. Interpret the combined source
  budget over every distinct source domain required by the request, including
  selected period, selected and previous calendar histories, independently
  current-month KPIs and their comparisons, and supplier spending; no per-company
  budget reset or unbounded gap materialization between disjoint periods.
  Canonical ancestry/payment guards remain additional existing fail-closed limits.
  Each requested company must pass ordinary native dashboard/source/target access;
  a foreign or unreadable requested company must fail the request, never shrink
  the total. An all-company explicit target requires an active target in every
  requested company, including a company without sales; never silently remove
  its target or substitute its baseline. Preserve incomplete/missing-day evidence
  across companies before deriving any aggregate evaluation or completed-day mean.
  Supplier spending may reuse `_baseer_purchase_assert_access`,
  `_baseer_purchase_domain` and `_baseer_purchase_totals` from
  `baseer_purchase_expense_dashboard/models/dashboard.py` with ordinary ACLs and
  the existing same-currency supplier-bill/credit scope. Do not invoke its full
  `get_baseer_supplier_bill_metrics`: that existing method also reads a manual-only
  summary sales denominator with sudo and is not the permitted sales/ratio seam.
  Return that spending scope explicitly. Forecast/comparison bounds, denominator
  and insufficient-sample handling must be stated alongside the implementation
  and covered by focused tests; no preview percentages or hidden partial periods.
  G5/G8 financial, ACL, transport/state and AR/EN UI evidence remain outstanding.
  This review changes documentation only and makes no runtime/live-data or release
  claim; no deployment or business/target mutation is authorized.
