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
