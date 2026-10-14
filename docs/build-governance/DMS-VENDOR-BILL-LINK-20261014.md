# DMS vendor-bill attachment bridge — QA only

## G0–G3 proposed contract

User authorizes automatic QA indexing of vendor-bill images, company isolation,
and DMS deletion without deleting the bill original. LIVE and other integrations
are out of scope. Previous owner-only trial restriction remains; this request
authorizes the bill attachment journey on QA, not access for other users.

G0: account.move (in_invoice/in_refund) remains accounting source of truth.
No posting, amounts, journal entries, original attachment content or ownership
are changed. New invoice binary attachments are indexed automatically; existing
attachments are not bulk imported. Synthetic draft bills in two companies test
the journey; no real document extraction or content copying.

G1: owner personal multi-company use; volume unknown. Small bounded CI fixture,
no QA load, no bulk historical migration. New CI run justified by new attachment
hook/deletion and cross-company risk absent from prior trial evidence. Use indexed
attachment relation and unique link, transaction-atomic idempotency; no queue/cache.
Protected QA backup/recovery remains mandatory.

G2: original ir.attachment owns bytes; DMS stores a reference, not a second binary.
Use an opt-in company-specific bill storage/root. Restrict source to vendor bills,
binary non-field attachments. Source record company is authoritative, not context
company or a sudo root search. Exactly one index per source attachment; repeated
events idempotent. DMS unlink removes index only, source unlink removes index.
Re-link/replace/move must never point across company; prevent linked file content
edits from mutating original. Source ACL/rules must constrain linked read/download
in addition to DMS rules. Public token sharing not enabled for linked originals.
Deleting DMS index is not a financial deletion; no silent writeback to bill.
Native unscoped OCA auto-link for account.move remains disabled; intercept only
opt-in bridge. QA retains owner-only rules. Tests include single-company users
with private trial rules temporarily disabled only in isolated test transaction.

G3: reuse installed Odoo19/pinned OCA DMS, custom additive module or narrow existing
trial extension; no upstream runtime edits or new libraries. Use native file UI,
AR/EN labels. Direct path is a safe reference bridge instead of enabling native
autoattachment hook that deletes originals and lacks company-filtered root lookup.
Independent reviewer must approve concrete implementation boundary before code.

## Gates and operations

G0–G3: pending independent review. G4: native DMS UI, no redesign. G5: integration
and access tests plus HTTP download cases; G8 independent release review.
Read existing registry/trial evidence, OCA ir_attachment/dms_file and native private
rules; prior 13-test result reused for unchanged trial, new tests required for bridge.
Branch codex/dms-vendor-bill-link-20261014 from main9dbefe70; unrelated dirty docs preserved.
Official Odoo19 Documents documentation confirms accounting journal centralization
and HR employee folders/contracts/payslips; full installed integration inventory
requires source inventory, not assuming all Enterprise modules are on Community.

### Concrete boundary revision for reviewer

Implementation proposes separate `baseer_dms_bill_link` (account+dms) with
`bill_attachment_id`, leaving native `attachment_id` empty. This eliminates native
OCA original-unlink branch by construction. Nonstored content dereferences source;
no persistent image thumbnails for linked files. Owner confinement remains in
installed `baseer_dms_trial`; no new access granted. Freeze linked source, names,
content, directory, copy and tokens. Freeze configured root/ancestor ancestry and
storage company/save_type/model_ids/access inheritance. Global source permission
AND rule and direct original/bill checks must cover metadata and bytes; no token
on bill root/ancestor can bypass source rights. One unique source relation and row
lock enforce repeat safety. Source reassociation removes stale index/re-evaluates;
source deletion cascades only index. Reviewer considering this revision before code.

### Read-only evidence

2026-10-14: QA current87bbe0d5 unchanged; free2014269440bytes. LIVE currentf894b892
unchanged. Native OCA destructive attachment_id.unlink/root sudo observations
confirmed. User authorizes QA new attachment journey; no old-file bulk backfill.
Official reference https://www.odoo.com/documentation/19.0/applications/productivity/documents.html
confirms accounting and HR contracts/payslips. Official Odoo source PR74571
https://mergebot.odoo.com/odoo/enterprise/pull/74571 confirms project/fleet folders;
official translation catalog https://translate.odoo.com/projects/odoo-19/documents_product/
confirms product integration exists. No claim all Enterprise integrations are a
single generic toggle or automatically supported by OCA; HR/other connectors remain
future separately permission-tested work, not enabled here.

Read-only QA baseline08:41UTC: summary669/3cc77fb1c40cfe645ff5722a75ee6f33;
POS718/5047663e50f54c0c48e7e8e7481c092e; payments1896/a650b5b054949864dca0665892438149;
Sales0/null; moves8590/22aac86abae3b9baca21ec0a2f2c5c11;
lines21291/e581ce43bc158bebbc2ed880eb43a9d9. Existing private owner2 active.
No accounting mutations made by this task; same isolated sample modules installed.

Independent dms_bridge_gate revised G0–G3 GO: separate source relation/module
approved as safer original-unlink boundary. Conditions above mandatory, especially
direct attachment permission in addition to account.move query, acting-user checks
under token/sudo, no persistent derivatives, provenance not caller context, and
frozen source/topology. Implementation/runtime owner dms_bridge_implementation;
tests/workflow owner dms_bridge_tests; leader owns docs and protected QA operations.
G5/G8 still pending; no code approval implies release acceptance.

Candidate PR323/bb27ac0f: AST/XML PASS; source38537788066 and Odoo38537788209
running. Independent source review CONDITIONAL GO pendingCI; probe must catch
UserError for intentional mutations (corrected), pinnedcompanies1/2 and zero-lines
and syntheticrollback assertions added. Reviewer requested explicit root/storage
freeze test, added test18. Actual frozen settings are topology/company/storage type,
native model associations and source-permission inheritance, not DMS group membership:
native group rights still intersect source and company rules; QAprivate remains.
Final candidate adds AR labels/errors and bridge-only exemptions from DMS upload
size/extension constraints: a reference is not a second upload, original Accounting
policy remains authoritative. Normal DMS upload constraints unchanged; targeted
test required before finalCI. No originalcontent/name mutation by index.

Final cc564521: Source38538189453PASS; Odoo38538189483PASS19tests/0fail/0error.
IndependentG8 approved QA contingentbackup/provenance/activation. PR323 squash
sourceab0aa23d8315747447eb9e0bb370ab1ab5f81777. Policy installs
baseer_dms_bill_link only; THIRD_PARTY_MODULES empty retains exact installed OCA
and private trial, no othermodule upgrade. Protected request next; successqueue
is not serveracceptance. QAprobe persists configonly after rollback assertions.

PolicyCI38538605734 rejected empty THIRD_PARTY_MODULES line; staticguard accepts
omission, not emptyexplicitvalue. Removed optional line; runtime/source unchanged,
no Odoo retest needed. Merge blocked correctly. Initial queue38538790671 was
dispatched after rejected merge by sequential shell commands; main has no policy,
so cannot validate/sign request. Verify failure before validredispatch; no server
release created or guard bypass. Future merge/dispatch calls separated by checks.

Policy correctedHEAD5e2cab90/source38538897792PASS mergedPR324/de5e3d23.
Queue38538790671 failed at missingpolicy validation (no tag); validrequest
38539164015 queuedPASS but serverQA_POLLER=FAILED at capacity prefetch:
need1949668975/available1923108864. Current87bbe unchanged; noDBupgrade/backup
oractivation. Retry justified only after capacitychange.

Prior explicit owner permission to move old releases locally applied to one
code-only QA release, not database/filestore backups. Resolved exactoldtarget
/srv/baseer-qa/releases/ac43ebcedcfd-run-37930403855-20261009T123129Z;
RELEASE_COMMIT ac43ebcedcfdbc2cbefa60025a34e2fd44bbc113. Filename timestamp ordering
preserved latestfive87bbe/f894/caf5/06a5/3660; copied directory mtimes were equal,
so mtime not treated as chronology. Tar transferred and gzipvalidated; SHA256
7b31230b6b6f5a05dd852193e73109bbacf870f739d21ea0b9d85d54d76c988b matched both hosts;
all1502regularfile hashes matched source manifest, local archive:
D:/Codex/Baseer-odoo/.worktrees/baseer-gl-qa-policy/tmp/dms-bill-code-archive/qa-code-ac43ebcedcfd-20261014.tar.gz
and correspondingmanifest.sha256. UnderQAdeployflock, exactoldcode and temporary
serverarchive removed only after verification; recoverable local archive remains.
QAfree2134740992bytes. NoDB/filestorebackup orLIVEwrite. Newrequest38539932482
queued; wait for serverresult and modulelog, not queuealone.

Request38539932482 queuePASS but serverapproval FAILED: releaseid already approved
with different policy (approval binds runid too). No install orDBwrite; current87bbe
unchanged. Correct retry uses fresh releaseidbaseer-2026-10-14-dms-bill-link-r2,
sameab0aa23d and singlemodule, never overrides immutableapproval orprocessedmarker.
No further Odoo testneeded: deploymentpolicy only, unchanged19-case candidate.

## QA actual result — 2026-10-14

PR325/9fb5fe9c source38540289088PASS approved fresh-r2 policy. Request38540478688
queuePASS, QA_POLLER=GO, result.env QA_DEPLOY=GO source
ab0aa23d8315747447eb9e0bb370ab1ab5f81777. Current
/srv/baseer-qa/releases/ab0aa23d8315-run-38540478688-20261014T091209Z;
backup /srv/baseer-qa/backups/pre-ab0aa23d8315-38540478688-20261014T091209Z.
recovery.sha256 database.dump/filestore.tar verifiedOK; modulelog loaded
baseer_dms_bill_link and its XML, Modulesloaded, no othermoduleupgrade requested.
All12trackedmodulefileSHA256 matched Git sourceab0aa23d exactly.

Reviewedprobe executed09:14UTC non-sudo owner2, approved companyIDs1/2;
DMS_BILL_LINK_QA=PASS: roots8/9, oneoriginal, originalsurvivesindexunlink,
sourceunlinkremovesindex, repeatidempotent, linkedmove/content/copy/tokendenied.
Both syntheticemptydraftbills/JPGattachments/indexes rolledback beforecommit;
onlystorage/root/companyconfiguration persisted. Currentroot8ARZ/root9AlMoallem;
ownertrial sixrules kept, nopublictokens, no historicalattachmentbackfill.

Finalread09:15UTC sixfullrowtablefingerprints match08:41baseline EXACTLY:
summary669/3cc77fb1c40cfe645ff5722a75ee6f33;
POS718/5047663e50f54c0c48e7e8e7481c092e;
payments1896/a650b5b054949864dca0665892438149; Sales0/null;
moves8590/22aac86abae3b9baca21ec0a2f2c5c11;
lines21291/e581ce43bc158bebbc2ed880eb43a9d9. No financialrecordchanged by this task.
LIVEstillf894b8927bce-run-38252387973-20261012T125758Z, untouched.

Acceptance scope: backendQAactivation+lifecycle, isolatedCI19ORM/HTTPtests. No
authenticatedQAUI/mobile/visualacceptance claim. User can upload a NEW supplier
billattachment in company1/2 and find it in Documents955→فواتير المشتريات.
Oneir.attachmentownsbytes; DMSbill_attachment_id is metadata/reference only,
no binary or persistentthumbnailcopy. HR/projects/products/fleet/approvals are
not enabled here, not a parity claim for OCR/AI/Sign or allEnterpriseapps.
Conditionalowner-onlyQAapproval of originalDMS trial remains; this bridge freezes
linkedindexes and does not fix native movement of unrelated manualdocuments.

Independentfinal dms_bridge_gate: CONDITIONAL GO deployedowner-onlyQA journey.
Mergedab0aa23d matches reviewedcc564521runtime/tests/workflow/probe; operations
evidence closes backup/provenance/install/activation/financialpreservation.
Companyroots8/9 only; noUI/mobile/QAauthenticatedHTTPcertification, noLIVE,
additionalusers, HR orbackfill. CIHTTPacceptance is distinct from QAUI acceptance.

## Preview defect — 2026-10-14 (CONTROLLED UI repair)

Owner screenshot confirms indexing works, but linked PNG has generic icon and
plain binary download/edit controls; expects thumbnail and image/PDF opening
inside Documents. Not a proven regression: preview was never delivered in the
bridge. Source cause: linked image_1920 deliberately False to avoid persistent
copies, native icon_url uses image_128, and native form content has no preview
widget. Preserve this no-duplicate storage invariant; use authenticated transient
/web/image/dms.file/id/content/128x128 plus inline /web/content model=dms.file.
No new upload/storage/ACL/publictoken/controller policy; backend source access
checks remain. Small OWL dialog widget reuses native Dialog, image/PDF viewer,
AR/EN labels, linked fields read-only. No upstream edits or newlibraries.

Scope: same owner-onlyQA/company1/2, noLIVE/backfill or accounting writes.
Runtime/UI owner dms_bridge_implementation; focused HTTP/regression tests owner
dms_bridge_tests; independent dms_bridge_gate reviews source permission and actual
release. New CI justified by preview endpoint/widget change and image/PDF ACL
risk not previously exercised; existing isolated fixture, no newenv/load.
QA prior19-case lifecycle evidence reused, runs again only with changed module.
Browser connection attempted once using documented skill; EPERM on browser runtime
realpath before discovery. No alternate browser bypass or visualacceptance claim.
Use screenshots and focused HTTP/static verification, declare visual limit.

PreviewcandidatePR327/fdf54756: Source38546571533PASS and Odoo38546571600PASS24
cases, zeroerrors/failures. Gate sourceCONDITIONALGO pending assetscompile proof.
Verified installedOdoo19 assetAPI _get_asset_bundle/js/css and existingDialog
bodyClass/widgetprops import; added test25 for JS/XML/SCSS compilation and widget
registration (no browserclickclaim). Same CIfixture, test-onlydelta justifies next
run, no duplicatedenvironment/load or sourcepermissionschange. UXAraby produced
conciseArabicbuttons/status/errorlabels; no names or filenames translated.
