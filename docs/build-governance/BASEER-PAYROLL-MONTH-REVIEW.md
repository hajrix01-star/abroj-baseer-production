# BP-S3 — payroll month and Financial Record independent review

Reviewer: om_review. Date: 2026-09-08. Ownership: this review document only. Accepted BP-S2 candidate 19.0.1.1.0 is the unchanged architectural baseline. No source or database mutation was performed by reviewer.

## R1 — G0–G4 scoped design GO

Read `BASEER-PAYROLL-MONTH.md` and the current settlement creation/month field views. **G0–G4 GO** for this narrowly authorized QA delta: payroll-local month/year selection, new settlement date default from the selected run's end date, and moving employee loan summary/history access into Financial Record. Reusing the existing Date field, native field props, source loan relation and existing navigation action avoids a new financial authority or schema.

Binding implementation/acceptance points:

1. Serialize the selected calendar month as the first calendar day with no timezone/UTC conversion. Preserve existing server normalization; reject invalid input and handle empty required input without accidentally selecting another month. Readonly output must show month/year, with Arabic/English labels and Western digits. The widget is payroll-local; do not patch a shared date widget. Verify native month behavior on desktop/mobile and fallback text/validation where the browser does not supply a month picker.
2. For a newly created settlement only, use that approved run's `date_end` when no payment date is explicitly supplied. Honor explicit `payment_date` values and explicit contextual `default_payment_date`; an explicit False is not silently replaced with a date and remains subject to existing required-date validation. Retain all existing role/company/lock-date/source-date validation, and never update an old wizard/payment to apply this default. Test 28/29/30/31-day and year-boundary months plus an explicit following-month payment date.
3. Move only the visual loan balance/count/history group from salary setup to Financial Record, keeping the existing model field groups and employee/company-filtered loan action. Retain the existing smart-button shortcut and salary configuration. No new queries, access relaxation or monetary calculations.
4. Focused tests and actual saved month selection/default date/mobile/loan navigation evidence are sufficient; the unchanged six-month finance/concurrency implementation need not be retested. Preserve BP-S2 source/archive identity and compare original financial data/main before and after QA upgrade. No new capacity claim, dependency or production promotion is covered.

BPM-R001: G0–G4 GO communicated before application edits. G5–G8 remain pending implementation and focused evidence. Version target 19.0.1.1.1, QA only.

## R2 — backend implementation checkpoint

Read the updated settlement `create` and `baseer_payroll_month_checks.py/.json`. The sole date behavior change is `vals.setdefault('payment_date', self.env.context.get('default_payment_date', run.date_end))`, after the existing run identity/company/approval checks. Explicit values take priority over contextual defaults; absent values use the run end; explicit False remains subject to native required-field rejection. No old wizard/payment rewrite or payment-state/amount change was introduced.

All 18 focused rollback checks passed: February 28 and leap-day 29, April 30, December 31/year transition, editable date, explicit/context precedence, empty/invalid input, a native February 4 payment whose January salary entries retain January 31, and existing loan navigation restricted to the employee/company including repaid loan 13. No backend blocker found. UI/widget, final source identity and preservation review remain pending G8.

## R3 — independent final delivery decision, G5–G8

**G8 GO for 19.0.1.1.1 on the QA database only.** The final implementation stays within BP-S3: a payroll-local month field, one new-settlement date default and relocation of the existing employee loan summary. There is no new payroll calculation, journal/payment authority, access change, report-template modification or production promotion. No unresolved release blocker was identified.

Independently recalculated **22 source hashes, all 22 archive entry hashes, 12 frozen evidence hashes and 4 backup hashes**; all match `docs/releases/2026-09-08-baseer-payroll-month/candidate.json`. Archive SHA-256: **`d4c8fdd9d5984e7940414a94d7b00addc6d2cb8421ea41d57db7c73129c58b42`**. The predecessor BP-S2 archive still hashes to `b4fc12814961ddd43e4ef526fa98b4cd7c9fea6434143b3ae8bc30da4928bee3`, and all 210 official Odoo Mates source files remain unchanged. Candidate identity is the frozen source/artifact hashes, not an invented Git commit.

Read the final widget/template and affected view registrations. `useInputField` connects to native record persistence; editable values use ISO calendar year/month, with strict month/year validation and an explicit first day. No UTC conversion is introduced. Readonly values use Gregorian month/year and Western digits. Month registration is local to this addon. Existing manager field restrictions and employee/company loan navigation remain unchanged, the loan balance/count/history group is in Financial Record, and salary setup retains only its configuration fields plus the preexisting top smart-button shortcut.

The previously reviewed **18 focused rollback checks** cover the server date boundaries and override behavior, invalid/empty month, actual later payment versus unchanged salary accounting date, and repaid employee-loan history. Executor UI evidence records selecting 2026-10 and persisting wizard 70 as 2026-10-01; the expected duplicate-run guard prevented a second October run. Independently viewed the native desktop month input, 390px February 2028 month/year input without a day, January payment screen defaulting to month end, mobile Financial Record loan summary and the linked repaid loan list. Loan count 1 / balance 0 and the closed 1,200 loan are consistent with the scoped source history. The existing loan view title received its final Arabic translation after the older screenshot; this is nonfinancial presentation only.

Independently compared the before/after snapshot evidence as well as `preservation.json`: **101 journal entries, 238 entry lines and 37 payments** have identical fingerprints; company/partner/user and user-company/group relation snapshots match. Main snapshots are exact. No financial test fixture remains from the focused tests. The accepted BP-S2 six-month/concurrency/payment evidence remains valid for those unchanged paths; repeating capacity or PDF generation is unnecessary because neither execution scale nor report templates changed.

Known native-control tradeoff: while editing, the month picker's displayed month language follows the browser/OS locale (English in this test); Odoo readonly month display follows the Arabic/English application language. Both show only month/year. This is explicitly documented in the handoff and is not a data or payroll correctness defect. Previous posted-correction restrictions, required company accounting setup and QA-only deployment limits remain in effect. No new capacity/SLA claim is made.

BPM-R002: G8 QA-only GO recorded after independent source, artifact, preservation and UI review. Only this review document was changed by the reviewer; no database mutations or repeat transaction tests were performed.
