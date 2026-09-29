# SP1 independent delivery review

Date: 2026-09-09. Reviewer: services_accounting_advice.

## Decision at this checkpoint

**GO — SP1 QA candidate, 2026-09-09.** All blocking acceptance items described in the chronological review below are closed. This is QA acceptance only, not production deployment approval or capacity certification. The negative tests identified a validation-message defect that was corrected before this final bound candidate; transaction rollback remained intact throughout.

## Scope and independence

Read-only application review of `baseer_service_seed`, `baseer_purchase_batch`, `baseer_hr_services`, and `baseer_web_navigation` deltas, using `SHARED-PARTNERS.md` and previous CSS1/HRS1 evidence. This reviewer did not implement application code, run the migration, or modify live data. This reviewer authored `shared_partners_concurrency.py`; its execution/result must therefore be accepted by the lead or another independent reviewer, not self-certified here. Earlier HRS1 reviewer-authored tests remain disclosed in their own report.

## Requirements and implementation

- Verified catalog identities become twenty clean shared native `res.partner` records. The canonical creation copies only approved public catalog fields, not source chatter, bank details, private contacts or attachments. Existing arbitrary/private suppliers and employee contacts are outside migration selection.
- Per-company account/payment-term/category settings remain native `company_dependent` properties. Raw explicit values are copied by company, referenced targets are validated, and conflicts with another source or existing canonical values abort rather than overwrite. Native payable defaults are not blindly copied from another company's environment.
- Company-specific compatibility XMLIDs point to the one global identity. Global serialization uses an advisory transaction lock plus a durable no-op UPDATE to force stale Repeatable Read transactions to retry. The global identity is reused; archived or manually customized canonicals are not replaced silently.
- The explicit migration accepts only known catalog aliases and matching legacy name/VAT, rejects ambiguous aliases and other external identities, locks all selected sources, and scans FK and relevant generic references before creating/repointing/deleting. Only self-commercial links, partner tags and known native creation notifications are allowed. A savepoint encloses the operation, including property transfer, XMLID rewiring and native ORM unlink.
- Physical deletion supersedes the earlier archive proposal under the user's explicit request. Positive dry-run/applied evidence reports the 100 old seed records deleted, twenty shared replacements, all explicit properties verified, no dangling old XMLIDs and idempotent repeat. No posted financial source link is retargeted. Used suppliers are rejected, avoiding loss of historical duplicate-reference detection caused by switching commercial identities.
- Purchase Batch and HR Services accept a shared supplier or the active company's private supplier, and reject other companies' private supplier/commercial-parent records. Employees, products, maps, taxes, journals and accounting documents remain company-bound. Category lookup uses the current company. The existing duplicate-reference check stays company-specific.
- Optional Arabic and English fields compose the native searchable supplier name only when explicitly supplied/edited. Ordinary name-only edits and seed reruns preserve user changes. Shared canonicals receive both vetted names at creation; historical unrelated supplier names are not rewritten.
- Header language selector uses native Dropdown, installed Arabic/English languages, and the current user's own `res.users.lang`. No sudo, ACL expansion, language installation or change to another user is introduced. Native `clearUncommittedChanges` returns false on a prevented departure; language write/reload occurs only after that guard succeeds. No new UI library or financial calculation.

## Evidence inspected and pending

Inspected source: shared-provider migration/seed, bilingual partner model, provider identity ownership, current-company batch/service validation and domains, navigation component/templates/manifest, native `clearUncommittedChanges` implementation, migration/check/ops scripts.

`shared_partners_checks.json` reports **37 passed**, including shared identity/aliases, bilingual native search, company 6/10 independent category and payable, native supplier invoices/tax/account ownership, batch reference deduplication within each company, HR cross-company/accounting restrictions, own-user language changes and denial of changing another user. The fixtures roll back with financial/HR/user/partner fingerprints unchanged.

The lead reports actual UI switching EN→AR→EN and an invalid dirty service form (amount115, missing employee) refusing language change while preserving Arabic and entered values; `language-invalid-form.png` records that check. Native discard then cleaned the form. Desktop/mobile provider-card fields were inspected by the lead. This reviewer has not independently driven those browser sessions; final artifact evidence is to be inspected when supplied.

Pending before final QA GO:

1. Lead's rollback negative tests: business FK, attachment/private chatter, and property conflict. Verify refusal with partners/aliases unchanged, including rollback after any provisional canonical/property work.
2. Final preservation result: only the explicitly approved old seed contacts removed; original finance and unrelated data/main database unchanged. External backup and source→canonical lineage retained.
3. Final candidate SHA-256 and all files compared independently against source, ZIP and QA-mounted copies. Any runtime delta after tests requires proportionate regression evidence.

## Limits

QA-only consolidation of this enumerated unused seed set. It is not a general contact merge, not an authorization to delete used suppliers, and does not merge partner-ledger histories. Known creation notifications are deliberately removed along with unused sources. Backup/lineage evidence is the recovery route, not uninstalling the addon.

The migration should be run in a controlled maintenance window without competing UI/integration writes to source contacts: arbitrary generic model/res_id links do not obtain native partner FK locks. This private administrative method is not exposed as a user-facing concurrent migration action. Final preservation can establish what happened in this QA run, not prove every possible future concurrent importer.

No production deployment approval or 100-company/20,000-service load certification is given. Concurrency correctness of a small two-company fixture is separate from a full-capacity benchmark. Shared public supplier access does not imply access to other companies' bills, payments or HR records.

## Follow-up findings during negative acceptance

The requested negative checks exposed a concrete source issue: `_, current = ...` inside `_baseer_consolidate_service_providers` shadows Odoo's translation function `_` for the whole method. An early validation consequently raised `UnboundLocalError` instead of the intended `ValidationError`; later validations would also encounter a non-callable local value. Reported to the lead for the owning worker to rename that local and rerun negative checks. The transaction still rolled back; this is not evidence of partial deletion. Final approval awaits the corrected candidate/evidence.

The inspected dirty-form screenshot confirms the Arabic view retained its missing employee and entered values. It also showed VAT enabled with115 gross/115 net/0 VAT. The lead has been asked to check the completed form's unsaved preview before final approval; the existing native posted-invoice tax totals already passed. This observation is pending confirmation, not yet a proven persisted-accounting defect.

The intermediate preservation run detected only the test user's contact `lang`/`write_date` change from the explicitly exercised language selector while main remained unchanged. The final proof must distinguish that authorized UI preference change from financial/unrelated-data preservation instead of claiming absolute byte-for-byte equality of every row.

## Final-candidate verification checkpoint

The translation-shadow defect is corrected (`canonical_property_names` replaces the local `_`). Lead-owned `shared_partners_guards.json` now passes **23/23**, including business-FK, attachment, private chatter, other external identity, changed catalog identity, and property-conflict rejection; fingerprints prove rollback. The property-conflict case deliberately processes an earlier provider family first and confirms that its changes also roll back. A newly created Saudi fixture company reuses all twenty global providers while obtaining its own payable/category; repeat setup remains idempotent. These tests were inspected by this reviewer and authored/executed by the lead.

`service-vat-preview.png` was visually inspected: the completed service form shows115 total,100 before VAT and15 VAT. No persisted-accounting defect was found. Supplier Arabic mobile and invalid-language-change screenshots were also independently viewed; browser interaction itself remains lead-observed.

The reviewer independently recomputed the archive and **50 individual file hashes** and matched source, ZIP members and running QA container-mounted files for the four addons. Candidate SHA-256:

`e30376d74e9d969289d966e6a853d01d06680ff5ee29451e29cbea4cae54a9c7`

Applied migration evidence passes with100 physical deletions,20 shared canonicals, verified explicit properties, no dangling old XMLIDs and idempotent repeat. Independent read-only database checks confirm all100 old source IDs are absent,20 active shared global provider identities exist, and the disposable race database has been removed. No application/database mutation was performed by this reviewer.

The only pending closeout is the final preservation classification of the authorized test-user language preference change. The intermediate result did not report any changed accounting rows or main-database rows. No application blocker remains after the corrections above.

## Final decision — GO for QA

The final `preservation.json` has been read: **original financial rows unchanged, no unapproved changes, main unchanged, exactly100 authorized seed-source deletions, issues=[]**. The original user language is restored. Only the test user's contact `write_date` metadata remains changed by the explicitly exercised native language preference flow, and the evidence identifies that exception rather than masking it. The lead reports the one UI-created service draft was deleted through native Odoo; no test bill was approved in that UI check.

`candidate-verification.json` agrees with this reviewer's independently performed comparison:50 files match source/ZIP/QA mount, same SHA-256 `e30376d74e9d969289d966e6a853d01d06680ff5ee29451e29cbea4cae54a9c7`. Final QA update completed and the lead reran the37 workflow assertions successfully. The23 negative/future-company assertions remain applicable. The16 concurrency assertions are lead-reviewed evidence because this reviewer authored that test script; they are not presented as independently self-certified by this reviewer.

Bound module versions:

| Addon | Version |
|---|---|
| baseer_purchase_batch |19.0.1.2.3|
| baseer_service_seed |19.0.1.1.0|
| baseer_hr_services |19.0.1.1.0|
| baseer_web_navigation |19.0.1.1.0|

**No remaining P0/P1 finding. GO to use/review this installed QA candidate.** The user-authorized unused seed consolidation is complete:20 shared bilingual providers replace100 unused private seed copies; per-company financial/category behavior remains intact and future company setup reuses the shared identities. Deletion of used or ambiguous contacts remains prohibited by the consolidation preflight, not delegated to this approval.

All limitations in the Scope and Limits sections remain: no production/main migration authorization, no general supplier-history merge, no load certification, and future destructive runs require the same preflight, backup, controlled write window and transactional checks. Runtime changes after this candidate require a new bound candidate and proportionate review.
