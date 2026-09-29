# BP-S5 — native work schedule seeds independent review

Reviewer: om_review. Date: 2026-09-08. Ownership limited to this document. BP-S4 19.0.1.2.0 remains the accepted baseline. Reviewer performs no application/database mutations.

## R1 — G0–G4 GO

Read `BASEER-WORK-SCHEDULES.md` and native resource calendar/attendance definitions. **G0, G1, G2, G3 and G4 are GO; implementation may begin.** The user authorized two optional native schedule templates for existing QA companies and automatically for subsequently created companies: 84 weekly hours across 7 days and 60 across 6 days. Using the existing payroll addon, native resource models and original forms is a proportionate direct path. No new calendar engine, frontend, dependency or schema is needed.

Binding acceptance details:

1. Seed exactly two company-owned calendars, with 7 full_day rows of 12 hours and 6 full_day rows of 10 hours, using native duration-based mode and computed totals. Native duration inversion centers intervals around noon internally; these are optional duration templates, not a claim about actual employee shift clock times. The six-day template omits Friday as an explicit editable assumption. Do not assign either to company/resource/employee defaults or alter monthly payroll basis or previously posted payroll.
2. Native authorized company creation must complete its super call before narrowly scoped privileged seeding of those returned companies. Existing-company initialization is a trusted module-install/update path. The helper must be private/non-RPC; it must not offer a public arbitrary-company sudo operation. Clear inherited `default_*` context for both calendar and attendance creation and supply owner/timezone/duration/rows explicitly. Preserve existing native calendar ACLs and company rules.
3. Lock each company before examining deterministic per-company XML IDs and creating missing records. Existing referenced calendars remain untouched, including administrator-customized names, durations, weekdays and archived records. Validate any existing XML ID's model/company rather than silently overwriting a mismatched record. Document deleted-template behavior if encountered; never treat absence by active/name search as permission to duplicate an archived/renamed template. XML IDs are noupdate and unique; all creations occur in the caller transaction.
4. Verify existing-company seeds, authorized new and multi-create companies, exact weekly/day totals, native selection visibility, repeat initialization/update and preservation of customized/archived templates. Check explicit context pollution and owner isolation, no default assignment, rollback and original financial/employee/version/calendar/attendance/company values. Report actual local creation/replay measurements only; 100 companies and concurrent administration are design scope, not an unmeasured SLA.
5. Freeze a separate 19.0.1.2.1 QA candidate, coherent backup and evidence, retaining BP-S4 artifact and main unchanged. Native employee UI itself is unchanged; focused visibility/source checks are enough without rerunning unaffected payroll financial/PDF suites. Do not use module uninstall as rollback for schedules already in use.

WSR-001: G0–G4 explicit GO communicated before source edits. Only this review document changed; G5–G8 remain pending implementation and focused delivery evidence.

## R2 — implementation and native access clarification

Read `models/work_schedules.py` and native resource security plus `hr.version.resource_calendar_id`. No source-level blocker found. Native `res.company.create` runs before privileged seeding of only its returned companies. Both helpers are private, creation context is cleaned, the company row is locked before checking XML identity, explicit native duration rows are supplied, and existing references are validated for model/company without overwriting renamed/customized/archived schedules. A stale/deleted reference fails clearly instead of creating an undocumented replacement. No company or employee default assignment is present.

Clarification accepted: native `resource.calendar` has internal-user read ACL and no general calendar multi-company read rule. The requirement is to preserve that native visibility and verify the native employee/version selection domain and `check_company=True` assignment boundary, rather than add a new rule or assert nonexistent read isolation. New company-owned templates do not contain payroll amounts or employee history. This evidence correction does not broaden privileges or change application security.

Native exact totals/create/idempotence/context checks are reported passing at the initial runtime checkpoint. Final G8 awaits the corrected assignment-boundary checks, repeat upgrade/customization/archive evidence, UI and frozen source/preservation artifacts.

## R3 — final native-boundary correction and G8 decision

**G8 GO for frozen 19.0.1.2.1 on `baseer_reports_qa_20260907` only.** The bounded seed change meets its purpose without changing salary mathematics, employee selections, existing schedules or accounting. No unresolved blocker was identified in the reviewed delta.

Important correction to the R2 expectation: runtime inspection established that native `hr.version` does **not** automatically invoke its company checker on every raw ORM write. The tested explicit `_check_company(['resource_calendar_id'])` rejects a mismatch, and the native UI selector filters the company; this release does not add or claim an automatic RPC/ORM isolation guard. Preserving that native behavior is acceptable for this optional-template seed scope, and is explicitly recorded in WS-005 and the handoff. No new record rule or privilege expansion was added.

Independently recalculated all **27 source file hashes and 27 ZIP entry hashes** against candidate.json; all match. Archive SHA-256: **`9f97235af9b75ebf697140b082ed3eecfb5f38105afc1ee880678069fbd16479`**. The pinned database backup matches `0923d6a01b6ba679157abfea1c8034c888755a69ea6bd883155233a07d358443`. Prior BP-S4 archive remains `e8138fa1dab9812e81829baae8d542793df72166e5aaddbaf6675f2e077f0519`, and all 210 official Odoo Mates source files remain unchanged. No Git commit is asserted.

Read the executed acceptance script and **43 passing rollback assertions**: existing company pairs, multi-create distinct ownership, exact 84/7/12 and 60/6/10 totals and one-day rows, Friday omission, native defaults retained, repeat seed/initializer without duplicates, renamed/modified/archived records preserved, polluted context cleaned, unauthorized company creation denied, mismatched XML identity rejected, preserved native calendar reading, explicit native company checker and consumption of 12/10 hours by the existing salary split. Two-company creation measured **0.633 seconds** locally; this is not a concurrent-admin or production SLA. The executor performed a second actual module upgrade; repeated initializer customization checks cover the idempotent code path. Unaffected payroll/PDF tests were appropriately not repeated.

Read the preservation implementation: it freezes original IDs and full row hashes for accounting moves/lines/payments, employees, versions, companies and existing calendars/attendance, then compares those same rows after upgrade. `preservation.json` reports both QA and main comparisons true. New optional calendars/attendance are intentional additions; existing defaults and original rows are preserved. Backup was taken with the QA application stopped. This seed delta introduces no filestore data requiring migration; rollback remains coordinated prior source plus database backup, without uninstalling calendars already in use.

Independently viewed desktop and 390px mobile native employee calendar dropdowns. Both show the original Standard 40 hours/week selection plus the two new company options; no employee selection was saved by inspection. The bilingual data names are compact enough to distinguish 84/7 and 60/6 despite native RTL/LTR ordering. Duration mode is daily-duration configuration and should not be represented as a configured lateness/clock-time schedule. Friday remains an editable six-day assumption; neither template is assigned automatically or certified as labor-law compliant.

This candidate uses source-only candidate.json, so the review separately records the consumed evidence SHA-256 identities:

- `baseer_work_schedules_checks.json`: `a40d6692ed848bcbc88daf666e8ccaeded987792095267d4e0170abefedeb4e1`
- `baseer_work_schedules_checks.py`: `728ba0624a235e5a3380e934542f2b09549a6dba8141d2a874a06a8e121450dd`
- Desktop screenshot: `f080d66f08c834bf47f75097fac23160d0b2bb655783b7424edd07e150ccb196`
- Mobile screenshot: `556b4f0bafb9e6b6ba0998fc3582a6da517be3c1daca809b3201d6b7e46bb34c`
- Preservation result: `b85a48a8031bd263fd2b83de9cf837f47bf8da9081013881d567f46e782cb889`
- Handoff: `3fb55763132d1ca0732233a99cba9bf2bc2fd9b57b3203c02b2dc13351670949`

WSR-002: Final G8 QA-only GO. Reviewer changed only this document, did not edit application code/databases and did not repeat runtime tests. Production deployment is outside this decision; previous payroll/EOS limitations remain unchanged.
