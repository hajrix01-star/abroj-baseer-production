# ABROJ-COST-ACCESS-1 — Company access boundary

- Classification: ARCHITECTURAL (multi-company authorization).
- Owner: Abroj project-costing module; alternate: ERP security reviewer.
- Baseline: `codex/abroj-company-access-qa`, parent commit `6a021f73`; `lastVerifiedCommit` for module source: `ee764f9`. QA-only; live out of scope.
- Evidence: QA company ARZ (id 1) has `abroj_project_costing_enabled = false`, while project 1 belongs to ARZ and opens by direct URL. Company Abroj (id 56) is enabled. The existing JavaScript filters only the app tile; module record rules use all `company_ids`, so a multi-company user can still open a disabled company's records.

## Access contract

- The selected company in the Odoo header is the only company exposed by project-costing models. Its `abroj_project_costing_enabled` flag must also be true. Other allowed companies do not broaden this access.
- The company form remains available to system administrators to re-enable the app. Disabling hides records but does not delete or transfer them. The existing group/owner permissions continue to narrow access within the selected enabled company.
- Odoo's native company switch rechecks read access and reloads the action; the server-side rule is the authority, while the existing JavaScript only filters the app tile.
- Project `default_get` must reject a disabled company before its trusted `sudo()` default-seeding helper can write category or material setup data.
- Apply one global record rule per persistent costing model and the material-import wizard, in addition to existing group rules. Do not rely on menu filtering for authorization. Background migrations/default seeding using deliberate `sudo()` remain separate trusted paths.
- All read/search/group, create, write and delete paths must be checked; direct record URLs and dashboard RPCs must obey the same rule. Existing receipts/reports remain attached to their original company.

## Risk and verification

- Risk: a global rule can block legitimate users or historical records if evaluated against the wrong company. Test a user authorized for both companies with ARZ selected versus Abroj selected; test manager/admin direct reads, searches, and create/write; test re-enable without data loss; test child records and the import wizard.
- Compatibility: no schema/data migration. Rollback is the previous module version/rules; records are unchanged. Do not deploy to live without independent release review and normal Git/PR route.

## QA verification — 2026-09-29

- Candidate `abroj_project_costing 19.0.1.4.3` was upgraded on a restored QA database clone first. The full module suite passed 12 tests with zero failures/errors, including a regular project owner, manager, system administrator, direct URLs, search, create/write, `default_get`, child receipt, import wizard, receipt numbering, and re-enable.
- QA itself was upgraded after a module archive and database dump. A read-only Odoo shell with the real administrator confirmed ARZ-selected project 1: search `0`, direct read denied, new-project defaults denied; Abroj-selected project 5: search `1`, direct read allowed.
- The same administrator's project-report HTML render for ARZ project 1 raised `AccessError`; report URLs are not a bypass for the disabled company.
- Before/after QA data counts remained 3 projects, 5 receipts, 252 materials. Project 1 remains with ARZ; the ARZ flag remains false. No records were deleted or transferred.
- The browser visual check could not complete because the browser's security permission verification failed. Odoo's native company switcher statically shows it rechecks read access and reloads the action. This limits the visual acceptance claim, not the server-side denial proof. A direct dashboard client action may still mount an empty/error shell for a disabled company; all underlying model reads are denied. Independent scoped decision: CONDITIONAL GO for QA only, NO-GO for live pending normal PR/release review.

## Local project-form layout follow-up — 2026-09-29

- Classification: LOCAL UI. `abroj_project_costing` alone owns the change; no model, API, data, record-rule, report, or other Odoo form contract changed.
- Source commit `27608ca8`, module `19.0.1.4.5`: a marker in the project form scopes one backend CSS rule that lifts Odoo's 1400px sheet limit to the available width. The x2many tables retain their native horizontal scrolling when space is narrow.
- The isolated QA-clone upgrade and QA upgrade both exited successfully. Read-only QA checks confirmed the installed version, scoped marker, and registered asset. A browser visual check remained unavailable because browser permission verification failed; no visual acceptance is claimed.

## Local dashboard scroll fix — 2026-09-29

- Classification: LOCAL UI; no model, security, data, financial calculation, or report change. Source commit `963a5d3`, module `19.0.1.4.6`.
- Root cause: Odoo's action manager clips overflow, while the custom dashboard root had no bounded scrolling container. The dashboard now fills the action area and owns vertical scrolling, including touch momentum on mobile.
- QA-clone and QA module upgrades passed; QA reported the installed version and the published CSS hash matched source. Browser permission verification remained unavailable, so desktop/mobile visual scrolling is not claimed as tested.

## Local material-list header readability — 2026-09-29

- Classification: LOCAL UI. `abroj_project_costing` owns the material-list view and its scoped CSS; no model, price, security, report, or shared Odoo list behavior changes.
- Module `19.0.1.4.7` marks only the material library list and allows its header labels to wrap to at most two lines. Cost columns have a readable minimum width; Odoo's existing horizontal list scrolling remains available on narrow screens.
