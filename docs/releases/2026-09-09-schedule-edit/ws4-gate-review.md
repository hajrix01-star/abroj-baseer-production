# WS4 independent architecture and gate review

2026-09-09. Reviewer: schedule_edit_review, acting as independent architect, ERP/capacity reviewer and gatekeeper. Implementation owner: root. Scope: `ws4-plan.md` including accepted R3; no application code changed by this reviewer.

## Decision

G0, G1, G2 and G3 are **approved** for implementation. This is design approval, not release approval. G4–G8 remain subject to implementation evidence and independent delivery review.

| Gate | Independent decision and evidence |
|---|---|
| G0 | Approved: user-approved edit/date/history contract is bounded; direct native template assignments are the linked population; private copies remain independent, with no guessed provenance or business-data migration. ERP cycle is schedule configuration → dated native employee version → existing attendance/payroll consumers; no journal/payroll posting is introduced. |
| G1 | Approved: explicit assumptions of 10 managers, 3 concurrent writes, 200 total source-linked candidate employees, 28 periods and 10,000 versions/company; reject over limit without partial application. Isolated 50-employee timing target is a future measurement, not an existing capacity claim. Coherent restore and fresh predeployment backup are identified. |
| G2 | Approved: immutable replacement calendar plus native hr.version keeps historical hours available. Source stays active for native history but is removed from template selection. Source successor and replacement effective date establish explicit revision history. Existing preflight and salary-signature rules remain authoritative, with atomic rollback and server ACLs. R3 supplies employee-first/calendar-second tuple locking and guards against membership phantoms and stale forms. |
| G3 | Approved: reuse pinned Odoo19 ORM/views, integer-minute/Decimal backend, existing time picker and native translated responsive controls; no dependency or stack change. Native float adapter is unchanged. Functional, history, negative, concurrency, XML/translation, UI and release-preservation checks are explicitly planned. |

## Accepted architectural details to verify in code

1. Before calendar locks, discover and deterministically lock every employee with any source-calendar version, including historical and inactive references; cap unique candidates at 200. Revalidate scope and fingerprint after the source tuple touch. Do not acquire newly discovered employee locks after the calendar lock: reject/retry instead.
2. Native hr.version create/write/unlink paths that change calendar membership, employee or effective date participate in employee-first then old/new-calendar tuple touches. Calendar touches, not advisory waits alone, force stale REPEATABLE READ snapshots to abort. The fanout acquires all candidate employee locks before calendar touches; no application bypass token may skip concurrency protection.
3. Preserve old calendar attendance rows, employee past versions and posted financial records. Run existing attendance/leave/payslip preflight for every affected employee and keep first-of-month protection when inclusive-salary splitting changes. Reject conflicting future versions rather than overwrite a future choice.
4. Reject assigning a replacement before its effective date and reject editing it with an earlier effective date. Reject new assignments to a superseded source on or after its successor effective date, while permitting historical references and old assignments before that date.
5. Template identity is exact record identity. Copies made by the existing employee wizard remain private and independent; identical names or identical hours do not establish linkage. Show this scope clearly alongside the affected employee count.
6. Idempotency, manager/company authorization, revision metadata protection, no partial fanout, global-holiday copying and historical calendar access need actual tests. A future revision may become the visible template immediately, but its effective-date guards must prevent premature use.

## Direct-path review

The shortest correct path is extending the existing simplified wizard with an edit mode, creating one immutable calendar replacement and dated native versions. In-place attendance mutation breaks history. A separate template entity or inferred provenance migration adds risk and is unnecessary for the approved scope. A company-wide mutex is unnecessary when bounded candidate employee locks and participating calendar tuple touches close the membership race.

## Review operations

- GR1 intent/result: read alpha-build-team SKILL and governance, architecture, capacity and ERP references; inspect `schedule.py`, `schedule_views.xml` and payroll employee/version locking. Existing editor creates private calendars and uses history-safe preflight; payroll Employee.write already acquires employee profile locks, establishing the compatible employee-first order. Read-only, no business-data effect.
- GR2 intent/result: review root-authored `ws4-plan.md`; request exact linkage, bounded historical/inactive candidates, tuple-touch membership participation and effective-date guards. Root accepted and recorded R3. Decisions above apply to that amended design. No runtime execution or capacity measurement represented by this review.
- GR3 intent/result: write this independent gate decision before implementation; root may now proceed within the approved design. Any contract, capacity, locking or dependency change reopens the affected gate. Rollback: documentation-only addition; append a correcting decision rather than erase this record.

## GR4 partial implementation review

Read current Calendar/Version hooks and G4 XML while backend implementation remains in progress; inspect pinned native Odoo hr.version/hr.employee source in the running container (read-only). No application source edited by reviewer.

- Native hr.version.active is an independent stored flag and `_get_version` filters it. Request participation of active changes in employee/calendar locking; otherwise archive/unarchive races bypass membership protection.
- Native payroll profile locks are advisory only. Request employee tuple touches for every nonempty Version.write, including salary and other copied version fields, so a stale fanout snapshot cannot silently copy pre-change values into its new employee version. Calendar tuple touches remain limited to membership changes. This implements the approved snapshot-conflict design without introducing another lock scope.
- Native contract-start synchronization reenters Version.write with date_version and is covered by the hooks; calendar inverse updates resource.resource rather than recursively writing versions. No recursion defect found in these inspected paths.
- G4 native edit/copy/latest controls and date visibility fit the approved interface contract. Ask for wording covering all separate employee schedules, because an unchanged private copy is also independent. Runtime translated desktop/mobile verification remains outstanding.

These are implementation review requests, not a release decision. Worker/root received both concurrency findings directly; closure requires checking the final code and evidence.
