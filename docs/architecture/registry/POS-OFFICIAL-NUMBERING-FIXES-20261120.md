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
test or new database needed for this client-only delta. Focused algorithm tests,
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
