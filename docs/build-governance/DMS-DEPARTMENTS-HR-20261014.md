# DMS departments and HR — QA only

## G0 contract (review pending)
Owner request: company → department → required subfolders, Purchases and HR
automatic references, isolation and no duplicate files. Reuse DMS bill link
source54de52fa, owner-only trial and image/PDF preview; no LIVE or user grants.
Each of seven actual QA companies gets private company root; Purchases contains
Vendor Bills and Purchase Orders; Human Resources contains Employees, with
per-employee Documents and Contracts (hr.version in Odoo19, not hr.contract).
Sales and Administration can have empty departmental folders; no auto-link yet.
Original ir.attachment remains authority; DMS index deletion never deletes it.
No new invoices, purchase orders, employees, payroll or financial entries.
Synthetic acceptance data is rolled back. Existing bill reference5840 retained.
No mass retrospective HR import: new/updated attachments link automatically;
existing bill indexes are rehomed, not cloned. Additional historical indexing
must be bounded and recorded separately, not an unbounded startup migration.

## G1 capacity (review pending)
Known actual scope: seven companies, current DMS is owner2-only trial; no claim
of employee-wide usage. Assumption: initial QA metadata tens of directories,
one index per source attachment; no duplicate binary or persisted thumbnails.
Attachment sync locks authoritative row, database uniqueness prevents duplicate
retries; native paginated DMS used. Folder creation serialized per company/employee.
No new environment/load test: use existing OdooCI fixture; safety delta is HR and
PO source-read permissions, not a measured load increase. No capacity promise.
Recovery through protected QA backup; configuration rollback does not erase originals.

## G2 architecture and acceptance (review pending)
New additive baseer_dms_departments module depends on existing bill link/hr/purchase.
Retain one original-reference column and its UNIQUE constraint, no competing
native attachment index. Generalize source dispatch for account.move vendor bills,
purchase.order, hr.employee and hr.version only. Native auto-index disabled for
all four models; URL/res_field/internal image attachments excluded.
Search/list/read/content/thumbnail/download must intersect DMS with original
attachment ACL and source record rules plus active company; HR additionally
requires HR officer/manager (owner admin eligible). Do not expose employee names
via searchable folder metadata to non-HR users; private owner rule remains.
No public/share tokens, arbitrary moves, context-provenance injection, source edits,
copy/migration of protected indexes. Handle original update/unlink/reassignment,
source company reassignment and employee/version relation updates transactionally.
Tests: company switches, HR-denied users including public employee readers,
PO-denied users, original attachment denied, direct HTTP and thumbnails, delete
index/original independently, retry uniqueness, hierarchy creation idempotency,
rehome existing bill without source/content mutation, existing preview regressions.

## G3 direct path (review pending)
Reuse Odoo19 ORM/DMS and built-in preview, LGPL existing module; no new library,
network provider or UI component. Existing 25 bill tests reused in sameCI only
when changed paths justify them; new module tests added to existing OdooCI route.
No direct main commits or manual live-module edits; source PR successful checks,
independent release gate, one protected QA policy, result.env/upgrade/backup checks.
No LIVE release. Core bill hook generalization only if needed; not parallel bridges.

## Operations
- Read registry/bill-link source and existing acceptance; preserved unrelated edits.
- Created codex/dms-departments-hr-20261014 from official/main aca2680d.
- Read-only QA metadata confirms installed purchase19.0.1.2/hr19.0.1.1,
  hr.employee and hr.version available, hr.contract absent, seven company IDs.
  No employee records or contents read. G0–G3 awaiting independent gate before code.

Independent dms_bridge_gate G0–G3 GO: additive baseer_dms_departments extends
explicit bridge hooks, no HR dependency added to base bridge and no second index.
HR directory metadata (search/read/name_search/count) needs its own role/source
intersection, not only file rules. Source company/relation changes rejected while
indexed (supersedes transactional remapping draft); bytes/name original update stays.
Existing bill attachment reassociation behavior remains for bill-only legacy path,
but new HR/PO paths reject reassociation while linked. Sources require explicit
company; version employee/company must agree. Stable managed-directory identity
with database uniqueness and parent row locks; name alone not identity.
Private server setup can reparent existing bill leaf only within samecompany/storage
with exact invariant validation and retained IDs; no context bypass, public moves
or tokens on managed ancestry. All new links exclude res_field-backed images.
Owner-only remains. G0–G3 approved for this scope, 2026-10-14.

Owner scope decision: company deletion/archive behavior explicitly excluded after
question. Existing DMS rules check allowed company IDs, not company.active;
automatic archive hiding/reappearance and company deletion guard NOT delivered.
No actual company deletion/archive test or operation. Keep organization/linking
only; this limit must appear in handoff, not silently claim synchronization.

Runtime: additive module19.0.1.0.0 and base bridge19.0.1.0.2, explicit source
dispatch/destination/relation/query hooks. Managed directory identity UNIQUE and
company row locks. HR directory and file-directory global rules protect names
and content. Source record FK cascade removes only indexes on source removal;
managed employee directory FK restrict remains. Original attachment is still the
single canonical reference. 25 existing cases plus new department cases scheduled
in same CI; no load or extra environment. Independent source review found no
demonstrated P0/P1 bypass; frozen CI evidence still required.

Capacity: owner explicitly approved transfer of QA backup
pre-01cb9a0ea135-37909342585-20261009T090905Z (2026-10-09).
Local recoverable directory:
D:/Codex/Baseer-odoo/.worktrees/baseer-gl-qa-policy/tmp/dms-departments-backup-archive/pre-01cb9a0ea135-37909342585-20261009T090905Z
database.dump SHA256 fc09c8ae7e3d1fd4c8308a7ace1b0cecb4fcf988e6d23af5a10efbe58954a574
filestore.tar SHA256 04a1863a551ec5c068b582591272b900228844af3515f904f216695f0225520c
Both hashes matched local and server recovery.sha256; pg_restore parsed all dump
output into /dev/null (not a database restoration), tar path/link validation and
802 filestore content SHA1 hashes passed. Under QA deployment lock, exact two
verified old files removed; logs/recovery metadata and latest backup preserved.
Trailing CRLF blank produced shell exit1 AFTER successful removals and df result;
do not repeat deletion. Available2036191232 bytes. No LIVE changes.
Readonly preflight proves owner already allowed all seven company IDs, private
six rules active, original5840 checksum/fullrow fingerprint unchanged.

Frozen6c69b07f/PR329: source38552491155 PASS; Odoo38552491160 failed with
0 failures/2 errors of40. Legacy bill reassociation to nonbill fails cleanup
because new source eligibility check rejects stale link before unlink; fix atomic
prewrite legacy cleanup under original write permission without read/context bypass.
PO unlink fixture must use native cancel before unlink, not weaken production rule.
Independent parser review also proved missing odoo-python PO comment markers;
fix catalog and add Arabic-context folder creation regression (names persist).
No QA deployment of failed candidate, reopen affected G5 checks only; same CI
environment justified by actual failures and new verified translation defect.

Corrected runtime: preunlink only changed legacy bill association, original write
ACL and ordered locks first; strict reads unchanged, new HR/PO guard runs first.
Both catalogs now mark Python code rows. Added native rollback preserving SAME
index ID, no-op association ID stability, and Arabic-context actual folder names;
PO fixture follows native button_cancel. Independent targeted source CONDITIONAL
GO pending corrected43-case CI; no weaker assertions or repeated environment.

Corrected2dcd85a9: source38553210306 PASS and Odoo38553210316 PASS, explicit
0 failures/0 errors of43. Independent G8 GO for protected owner-only QA and reviewed
metadata activation, subject to result/backup/upgrade/hash/probe evidence.
PR329 merged source7e42bd54dc891ab90f083fe4c044d5e78c5e88b4.
Release policy scopes exactly baseer_dms_bill_link and baseer_dms_departments,
retaining OCA/private rules/other modules; no LIVE. Activation still pending.

Policy PR330/b678f29a passed source38553798878 and merged f919af04. Request
38553908111 queued successfully but server FAILED before prefetch: required
1957194379, available1945120768 while temporary approval Git fetch existed.
Current QA stayed54de52fa; no module/database upgrade or new backup occurred.
Archive existing authorized code-only release06a58d0ec088 (not current, latest
five retained). Local archive tmp/dms-departments-code-archive/
qa-code-06a58d0ec088-dms-departments-20261014.tar.gz SHA256
81a239f5b982beebb61a5507a8cf6d45fd5343cb3ed8706fdf5b40c5b30dfd5d;
all1548 regular-file hashes match source manifest, gzip integrity passed.
Archive creation completed before a trailing Windows carriage-return error;
verified artifact was not recreated. Removal script normalized remote CR input,
revalidated source/current/latest-five/manifest under deploy lock, removed exact
old code and temporary remote archive only; local recovery retained, backups/LIVE
untouched. Available2157998080. Retry38554520293 uses same successful tested
source/policy; no repeated CI or module edit. Actual deployment still pending.

Retry38554520293 rejected at approval BEFORE deployment: release id already
approved with different request-bound policy. Do not modify approved policy or
bypass guard; fresh-r2 release ID points at identical7e42bd54 and two modules.
Current QA remains54de52fa, business data untouched; no runtimeCI rerun needed.

Final hook readback rationale: actual QA has222 installed-module composition vs60
in CI, source attachment-hook interoperability not covered by isolatedCI; current
usage is owner only. One transient attachment against an existing company1 HR
employee and purchase order if available, row fingerprints unchanged, cross-company
denial and index deletion verified, all synthetic attachments/lazy folders rollback.
No new environment or load, no employee/order creation, source writes or messages.

## Final QA acceptance — 2026-10-14
Fresh-r2 policy PR331/source-check38554894040 PASS, merged e70d2c98; request
38555027412 produced QA_DEPLOY=GO and QA_POLLER=GO. Release
/srv/baseer-qa/releases/7e42bd54dc89-run-38555027412-20261014T111428Z
with recovery pair under pre-7e42bd54dc89-38555027412-20261014T111428Z;
both recovery SHA256 checks OK. Log loaded/upgraded base bridge19.0.1.0.2,
installed departments19.0.1.0.0, loaded both ar.po catalogs for ar_001 and
Modules loaded. All29 tracked module file SHA256 match reviewed7e42bd54 source.

Committed activation probe passed on all seven companies. Company root IDs
1→10,2→17,3→24,54→32,55→40,56→48,57→56; eight managed nodes per company,
Arabic department names/parent topology/private storage validated. Repeated setup
returned same IDs/counts. Existing bill leaves8/9 and DMSfile10 retained.
Original5840 checksum74d64754a79987d2ccce685c06ef553cd8930931 and full-row
MD5f5c49b2644b09fd6a4edbec26dc7c988 unchanged; original-reference count1.
File count and HR original attachment count unchanged, no historical import or grants.

Independent gate approved single actual-QA composition probe. Existing company1
hr.employee and purchase.order BOTH passed source auto-index uniqueness, readable
payload, company2 denial, original survival after index deletion, source row
fingerprint preservation. Forced savepoint and final rollback completed, no retained
synthetic attachments or lazy folders. No financial/source record writes.

Final independent CONDITIONAL GO covers owner-only QA backend/configuration,
new/updated non-field binary attachments. No LIVE, wider users, historical backfill,
company deletion/archive synchronization or manual legacy-file reorganization.
Visual browser/click/mobile acceptance unverified (earlier runtime EPERM), not claimed.
Existing image/PDF preview sources unchanged, prior visual limitation retained.
LIVE current still f894b8927bce-run-38252387973-20261012T125758Z.

## Reopened G5 — native search-panel compatibility defect
User actual browser RPC at11:22:58Z: dms.file.search_panel_select_range raises
TypeError at OCA dms_file.py357 indexing parent[0]. Readonly owner/company1
reproduction11:26:32 confirms search_read parent values bool/int and both counter
modes fail identically. Native OCA assumes legacy Many2one tuple; web client was
not observed in prior conditional acceptance, missing actual panel-call coverage.
Historical same-context success is unproven; classify native compatibility defect
exposed by hierarchy, not an invented data or permissions failure.
CONTROLLED adapter in additive module only, no vendor/core/bridge/auth/schema
changes; version19.0.1.0.1. Preserve empty folders, active-directory behavior,
visible-parent sanitization, counters, other-field delegation, source/global rules.
Add direct native model and authenticated RPC regression for folder tree/company/HR
privacy. SameCI fixture, no new environment/load. Prior overall visual acceptance
not granted; folder-list journey now NO-GO until this exact path passes on QA.

PR333/frozen6b8fe804: source38557203378 PASS; Odoo38557203401 failed1/1errors
of46. Exact authenticated RPC test caught countercore requiring tuple AFTER
sanitization (web/models/models.py1719/1768), not an authorization fault.
Local helper now returns visible internal(parent_id,emptylabel) / hiddenFalse;
outer RPC values remain int/False. No parent name read/sudo, assertions unchanged.
Independent targeted source CONDITIONAL GO pending corrected46-case CI.

Corrected33dd4ceb: source38557929953 PASS and Odoo38557929964 PASS, explicit
0 failures/0 errors of46 including authenticated RPC. Independent GO for QA-only
single-module release and same readonly reproduction after deployment.
PR333 merged470fbf819c00e88e178f4ccc9789f39551a27c12. Policy upgrades only
baseer_dms_departments19.0.1.0.1; basebridge/OCA/private rules remain unchanged.

Capacity for panel fix: six old code releases ab772e83a185/52ed6d8a4140/
8c5927360e89/d9ea28aeb5f3/714d7b2719ec/55c07f093d6b resolved and commits
verified; authorized code-only archive at local tmp/dms-panel-code-archive/
qa-code-dms-panel-six-20261014.tar.gz SHA256
461ace93dc229d69c0194cdbe9b6ba76983bd763b134344ebb8ad74ff97dce2c.
All9220 regular-file SHA256 matched source manifest; gzip passed. Under deployment
lock current7e42/latestfive/identities/hashes rechecked, exact six old code releases
and temporary remote archive removed, recoverable local. No DB/filestore backups
or LIVE touched. Available2331033600 bytes; new request pending, no sourceCI repeat.

### Search-panel repair actual QA acceptance
Policy PR334/af05a058 source38558518532 PASS, merged8fd60564;
protected request38558653864 QA_DEPLOY=GO and QA_POLLER=GO. Current release
/srv/baseer-qa/releases/470fbf819c00-run-38558653864-20261014T114456Z,
recovery pre-470fbf819c00-38558653864-20261014T114456Z database.dump/filestore.tar
SHA256 OK. Upgrade log loaded departments19.0.1.0.1 only, Modules loaded.
All29 module hashes match (departments13 from470fbf81, bridge16 unchanged7e42).
The SAME readonly owner2/company1 reproduction now passes both countersFalse/True,
11 values each; raw parent values still bool/int, adapter handles them correctly.
Readonly preservation check passes seven root IDs and topology,56 managed folders,
original5840 checksum/full-rowMD5 unchanged, DMS10/leaf8/count1, six private-owner
and two HR global rules active unchanged. No hierarchy reconfiguration or original
write; no browser visual claim or LIVE. Independent CONDITIONAL GO accepts deployed
backend RPC repair, with visual/click/mobile verification still excluded.
