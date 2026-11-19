# POS-NUM1 — Official POS numbering fixes, QA only

Owner authorization: verify production, prepare official fixes, test QA; production
changes require the owner's later approval. No HiLo, new number format, historical
renumbering, no-reuse policy, accounting, tax, print transport or image upgrade.

Reference: existing POS/cache architecture in INDEX. Source base a8fdaeb86;
isolated branch codex/pos-official-numbering-fixes-20261120. Impact CONTROLLED:
client receipt allocation and recovery storage; native UUID remains authoritative.
No schema, access, company, payment, financial calculation or deployment boundary change.

G0–G3 scoped defect contract: reproduce retained-number reuse; port only the
official 19.0 algorithms fd7af53e (2026-10-02) and 1fe5b09b (2026-11-17).
Use existing cache-resilience addon and native patch/assets APIs, no dependency.
Acceptance: loaded/synced numbers reserved; device/config isolation; recovery
preserves every device counter and UUID; normal reload, payment and sync unchanged.
Actual observed concurrent namespace count: two SHAMI device identities. No load
test needed for this client-only delta. Focused algorithm tests,
QA asset compilation/runtime tests, independent review and rollback evidence.

2026-11-20 read-only runtime probe: both production and QA use
Odoo Server 19.0-20260817, image sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd.
Production source 41d78dda279c23b005325fd06b337c22a14b47b0; QA source
08f6b861323beb2f194f7d3d1031247c4ab70a06. Neither has removeUsedNumbers.
Important compatibility finding: normal reloadData does NOT clear localStorage
in this image. The critical-error reset_local_data.js DOES call localStorage.clear.
Therefore fix2 must preserve counters in that existing reset path, without adding
storage clearing to normal reload. Evidence: output/pos-official-numbering-fixes-20261120.

Adapter: patch DeviceIdentifierSequence/removeUsedNumbers and PosStore allocation
and post-sync hook. For critical reset, preserve its native implementation and
replace only the localStorage clear call with official selective clear, via an
asset replacement with the original module alias. No global Storage patch.
Existing recovery intentionally clears IndexedDB; this change does not promise
recovery of unsynced orders after the user invokes destructive native reset.

Rollback: previous cache-resilience module source + asset rebuild through approved
QA release. No data migration. Deployment/acceptance results appended below.

## QA acceptance — 2026-11-20 (Riyadh)

Official commit dates and base=19.0 confirmed independently. Source review GO
for QA only; original critical reset still deletes unsynced IndexedDB and must
not be represented as an unsynced-order recovery feature. Recompare the vendored
reset asset when the core Docker image changes.

An initial external Maven dependency failure blocked the required mobile CI
check and hence shared-QA promotion. To continue authorized QA safely, created
ONE owned internal QA network/database on the QA host, without ports or mounted
production/shared-QA data. Same pinned image, PostgreSQL 256MiB and Odoo 1280MiB,
0.25/0.65CPU. No capacity claim. The dependency failure resolved on the next
source revision's CI; no protection bypass or unrelated mobile change.

Candidate application/tests dba65fc18: baseline duplicate reproduced on actual
production DeviceIdentifierSequence/native allocation snapshots; 27 Node tests
PASS. First Odoo assertion incorrectly omitted the leading slash on asset paths;
fixed the TEST, reused the same isolated DB, and 4 Odoo tests PASS with 0 failures
and 0 errors. Actual pinned Odoo compiled 668 JS assets (3,565,997 bytes), original
reset removed, replacement exactly once, correct named alias. Executed the
Odoo-transpiled modules under a module-loader harness: restored-number allocation,
offline-local allocation, post-sync reservation and critical-reset preservation
PASS. ORM acceptance work rolled back. Owned PostgreSQL stopped after tests.

Evidence: output/pos-official-numbering-fixes-20261120/{SUMMARY.json,
ACCEPTANCE.json,odoo-tests-r2.log,compiled-modules.log,NODE-TESTS.log}.
Bundle SHA256:431e572aea7e4f9cc7267642bb4c3d28b01debb6b63dc4b48f298223bc0b5965.
This is actual QA-host Odoo and compiled-JS execution, not a physical cashier,
paper-print or real payment acceptance claim. Number format, accounting and
historical records unchanged by this patch. Production promotion NOT authorized.

Read-only before/after identity comparison found another production release
during this task (41d78dda to 08f6b861); same core image and numbering sources.
No production deployment or data write was issued by this task. Shared QA was
unchanged during the isolated test. PR: hajrix01-star/abroj-baseer-production#935.

## Owner-approved promotion — 2026-11-20

Owner explicitly selected: "انشر على الإنتاج بعد نجاح QA". Source PR935 passed
all checks, including 277 Odoo POS integration tests with zero failures/errors,
and merged as bcf84e8bc8f118aeef1fef24551e892eaff7b252. Scoped QA/production
policies upgrade ONLY baseer_pos_cache_resilience to19.0.1.0.2. The production
workflow must not be dispatched before shared-QA acceptance and independent
scoped delivery GO. Existing protected workflows, paired backups, rollback,
immutable source and Docker image remain the operational boundaries.
