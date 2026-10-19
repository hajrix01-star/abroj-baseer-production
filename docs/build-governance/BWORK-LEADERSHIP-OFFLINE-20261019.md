# BWork leadership offline snapshots — BWO-20261019

## G0 contract and reuse map (approved)

Owner requests offline leadership overview and sales calendar like remembered
chat; explicitly rejects a new warning banner or last-update timestamp. Existing
global connection status stays visible. Base branch is compact-calendar source
`210be6b2c3eaa3e8f8ec7e61cfcd904b208fd939` (PR423); preserve that owner's separate
display-only ceiling decision. Work branch `codex/bwork-leadership-offline-20261019`.
Impact ARCHITECTURAL: persisted private financial display, lease/lifecycle and
runtime/UI contract. No Odoo calculation, source schema/API, target write, role
grant, third-party dependency, deployment or APK publication is in this change.

Reuse central-sales C1 map/R17/R32 and R33 compact-calendar evidence rather than
rediscover financial sources or rerun unchanged ORM/load tests. Odoo stays the
sole owner of exact decimal amounts, goals, comparisons, forecast and dedup.
Offline data is an immutable snapshot of an already validated ordinary-user
response, never a new balance, aggregate or permission authority.

```text
Odoo ordinary-user GET -> strict decoder -> LeadershipEngine -> existing UI
                                                |
                             bounded app-private snapshot store
                                                |
ChatEngine valid actor/24h lease -> cached read only (never HTTP authority)
```

Acceptance: after an authorized connected read, same remembered account can
reopen overview/calendar and inspect cached days, details and comparisons without
network, including after app restart. Only previously visited exact company and
date/filter combinations are available; never synthesize a missing period or
partial-company total. Returning online triggers current options/ACL/report
verification and replaces snapshot silently. A source denial/session loss clears
display and invalidates cached access, never falls back to a remembered grant.
No new banner/timestamp. Offline must not claim a day is Live/In progress in
badges, detail, accessibility or a blue current-day marker; keep selected-day
styling and original source incomplete/missing/future evidence. Exact details and R33 display formatting
remain unchanged; no offline writes or goal edits.

## G1 capacity and retention (approved)

Reuse current report limits: max10 combined companies, <=1MiB response, no source
IDs or raw ledger exports. Only user-visited reports are saved, no prefetch/jobs.
Assume one active mobile account/device, bounded to8 query snapshots and1MiB
UTF-8 JSON total per actor; evict oldest entries at either bound. These are
conservative product caps, not a measured production-usage claim. LRU read must
not extend freshness. Each snapshot expires no later than24h after its connected
read AND the existing account's remaining chat display lease. Clock rollback,
expired lease and malformed/oversized cache fail closed. No indefinite retention
or growing history, no second database/media archive or new background service.
G6 uses a bounded synthetic quota/concurrency test, not shared-QA load.
The single actor envelope is capped at1MiB (including options/metadata) to avoid
AsyncStorage Android per-item read limits; skip an oversized tuple without hiding
the online report. This intentionally lowers the initial4MiB draft cap.

## G2 contracts and lifecycle (approved; focused source seams verified)

Focused mapper verified ChatEngine identity/accountScope/lease getters and private
remembered flag. Add only a generic readonly rememberedLeaseRemainingMs getter;
runtime builds separate snapshot display scope, including permissions.revision.
applicationOrdersIdentity and native transport remain verified-online-only.
cancelNative/reset/restoreOffline clear memory only, never disk snapshots.
Native login/logout and refresh (including failed later reads after bootstrap)
reconcile authority; leadership 401/403 and options can_view=false revoke explicitly.

- Separate verified online identity from offline display authority. A remembered
  bootstrap/positive lease can authorize only reading the matching local
  snapshot; it must NEVER bypass the existing native HTTP identity checks.
- Actor key contains exact origin, database and uid. Cache authorization binds
  the complete sorted authorized-company set, dashboard switch and permission
  revision. Query key includes company/all scope, month, period and custom date;
  today/yesterday also bind the absolute Riyadh business date on save AND lookup/restart so midnight cannot silently
  relabel a previous day's amount. Revalidate cached payload with the same strict
  wire decoder, including all-company scope and exact original decimal fields.
- Existing AsyncStorage is app-private, NOT claimed to be application-level
  encrypted storage. No credentials, cookies, signing keys or source transaction
  details are stored in this cache. Persistence requires remembered-account
  authorization; exact existing seam is verified before implementation.
- Logout, account/origin/database change, withdrawn company/dashboard access and
 401/403 invalidate private display and the financial snapshot namespace only.
  Never touch chat history, outbox, media, orders or task caches. Expiry blocks
  access even if deletion fails. Generations/actor stamps fence late reads and
  writes. Serialize store edits so a stale write cannot resurrect purged data.
  Write a durable blocked marker before deleting an actor's envelope; failed
  deletion cannot restore access on restart. Only a new verified connected report
  may replace this blocked incarnation. Offline revocation is unknowable until
  observed; the remembered lease is historical-display permission, not current ACL
  verification. If all persistent writes fail, deny in-process and report storage
  failure; no claim of crash durability under total storage failure is possible.
  Track a persistent clock high-water mark; rollback below save/high-water time
  blocks reads. Chat's original verification age and the initial remaining lease
  cap snapshot expiry; subsequent chat renewal cannot extend that saved expiry.
- A valid online response can still display if local saving fails; offline cache
  failure yields no private report. No request-error fallback: only explicit offline
  connectivity enters cached-read mode, never malformed wire/4xx/5xx/unavailable.
- Online options/read flow stays authoritative and unchanged. Offline options
  are saved from an already authorized options response paired with the report.
  Company filters cannot expand the cached authorized set. Missing cached filters
  use a concise AR/EN empty state, not a guessed response or network call.

## G3/G4 direct path and UI (approved local source)

Reuse React Native/TypeScript, AsyncStorage, injected transport and strict
validation. No dependency install, native module, timer service or server change.
Small feature-local snapshot storage helper is justified by the owner-requested
offline journey, not a new generic cache framework. Existing read-only cards,
heatmap, detail panel, Company chips, DateTimeField, Button/IconButton/Label and
translation dictionaries stay the named component owners. Reuse their colors,
English digits and AR/EN direction. No animation or UI library is needed.
Keep existing global offline indicator; no new banner/timestamp. Reconnect is
silent for the same filter; account/permission denial never retains numbers.

## Gates and verification

| Gate | State | Owner / independent reviewer | Evidence required |
| --- | --- | --- | --- |
| G0 | GO | root / independent gate reviewer | owner scope, no warning/time, source map and read-only financial boundary |
| G1 | GO | root / independent gate reviewer |8 reports/1MiB/24h caps and no unbounded prefetch |
| G2 | GO | root / bridge mapper + gate reviewer | actual lease/remembered/logout seams, durable tombstone, strict decoder, midnight/highwater and1MiB cap approved |
| G3 | GO | root / independent gate reviewer | reuse installed stack, no new dependency |
| G4 | GO local | root / quality review | existing components, AR/EN empty state, no live semantics or new warning/time offline |
| G5 | implemented | root / focused store and bridge workers | isolated snapshot helper, separate display/HTTP authority; no dependencies or backend changes |
| G6 | GO local | root / independent evidence review | cumulative gate103 behaviors, typecheck and56 leadership cases; runtime38 including production store restart-denial seam |
| G7 | source review GO, freeze confirmation pending | independent delivery reviewer | all reported P1/P2 closed; no native/QA/financial-parity claim |
| G8 | source candidate only | root / independent delivery reviewer | separate branch, explicit source paths only; no APK build/publication or QA/Live deployment |

Do not write application code before independent G0–G3 approval. Verify offline
restart, no-remember, lease expiry/rollback, cross-actor/company, malformed data,
clock midnight, source denial, permission revocation and asynchronous resurrection;
quota eviction, exact decimals, silent same-query refresh, AR/EN UI and existing
chat/navigation regression. No runtime QA or financial parity claim from mocks.

## Live log (append only)

- O01: user requested offline financial viewing; then explicitly removed proposed
  banner/update time. Root read alpha-build/architecture/governance/scale/ERP and
  design-catalog instructions; existing C1/R33, leadership engine/types/tests,
  ChatEngine display lease and runtime adapter show connected-only reader plus a
  reusable24h chat display lease. No app code changed. Bridge mapper is checking
  exact identity/remembered/cleanup seams independently. G0–G3 remain draft.
- O02: focused mapper confirmed the actual seams above. Independent reviewer
  approved G0/G1/G3 and held G2 for durable revocation, offline live semantics,
  midnight/clock binding and genuine-offline-only behavior; these are now explicit.
- O03: independent reviewer accepted revised G2 semantics and identified Android
  per-key read risk; reduce single actor envelope to1MiB instead of4MiB, max8
  entries unchanged. G2 final confirmation requested for this bounded choice.
- O04: independent reviewer granted final G2 GO with1MiB serialized cap. G0–G3
  complete before app code. Root owns engine/UI; focused workers own new snapshot
  helper/tests and runtime/generic remembered-lease seam without overlapping files.
- O05: independent acceptance review found and closed three privacy/authority
  seams: generic chat500/malformed responses no longer enable financial offline
  mode; current-new-epoch revocation cannot be skipped because an older writer
  exists; HTTP /orders epoch is not used as display-cache epoch. Real runtime
  production-store test proves online save -> offline restore ->403 -> blocked
  restore and fresh-store restart. Same-authority reconnection also retains its
  original cached deadline while options verify, without reviving Live styling.
- O06: final local cumulative command, from mobile/chatwoot:
  `BWORK_PYTHON=<bundled Python> node tools/check-bwork.cjs` PASS in16.73s,
  TypeScript included. Results: gate5/5, Odoo293/294 (one existing optional archive
  benchmark skipped by the unchanged gate), brand5/5, orders98/98, tasks48/48,
  leadership56/56; zero failures. All103 approved behaviors executed and passed.
  Leadership includes20 bounded storage cases and5 actual-engine offline cases;
  runtime38 and ChatEngine55 are included in the cumulative Odoo suite. Existing
  source financial contract producer test also passes; it is not QA reconciliation.

## Focused delivery decision and limitations

Reuse the map above and unchanged C1 financial-source map; only the local snapshot
storage/trust boundary is new. Independent reviewer combines quality, private-data
security, capacity, contracts, financial-source and owner-journey acceptance for
this limited delta. No outstanding P0/P1 after O05. No new team/tool/dependency was
installed; existing focused agents reused. Source review is GO subject to final
frozen-commit confirmation. Financial amounts, goals, dedup and authorizations are
still backend-owned; the client rounds calendar LABELS only under R33, never
details or calculations.

Acceptance evidence: remembered restart, exact filters/companies, full decimals,
expiry/clock rollback/midnight, bounded UTF8 eviction, deletion-failure tombstone,
stale async completion, cold login/logout and observed rights revocation covered
locally. AR/EN host-render tests inspect readonly cards, day/comparison details,
no new banner/update time, no stale Live/a11y/current marker, same-filter silent
reconnection and expiration of open financial pixels.

Not executed: an APK containing this delta, native Android AsyncStorage quota or
crash experiment, native offline screenshots, QA actual financial parity or host
upgrade receipt. Host test doubles are not device evidence;1MiB single-item cap
is conservative relative to documented Android item limits, not a measured device
capacity guarantee. Total persistent I/O failure cannot guarantee crash-durable
revocation; observed failures deny local reads in-process and cached control-read
errors fail closed. Offline viewing requires a previously opened report and the
same remembered account's valid lease, not a new financial offline login for
dashboard-only sessions without remembered chat identity. No financial writes or
offline goal edits. Rollback is source revert via PR; snapshot keys are isolated
and old versions ignore them. QA, Live, dependencies, roles and the published
0.1.22 APK remain untouched.

## O07 — owner-authorized QA APK delivery (2026-10-19)

After receiving the explicit two-change publication list, owner approved update
and publication: compact ceiling calendar R33 plus offline snapshots, without a
new warning/update time. Target normal QA APK0.1.23/build24, same application ID,
QA origin/database and existing signing certificate. Reuse source acceptance
8e365962,505 passed/103 protected behaviors and independent source GO; only trial
version/versionCode change. Preserve stable Chatwoot version4.9.11, dependencies,
permissions and all server modules. No QA-host migration/upgrade request is needed
for this mobile-only delta; do not repeat prior queue39286507372. Existing server
completion UNKNOWN/actual canonical financial parity UNTESTED remain limitations,
not a new deployment-success claim. Live remains untouched.

Build/verify one frozen normal APK; prove source/bundle/signature/upgrade and
bounded native offline acceptance before publication. Independently review the
release-only Draft -> Publish -> public hash verification path. Merge source only
through a successful PR with expected head; use prerelease/non-Latest distribution
and disclose the actual verification scope. Keep generated APK/evidence out of
Git. Release progress/artifact proof live in ignored output under release-0.1.23.
