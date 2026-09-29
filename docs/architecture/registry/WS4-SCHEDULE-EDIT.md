# WS4 schedule-edit architecture delta

Owner root; independent reviewer schedule_edit_review. ARCHITECTURAL extension of WS3, frozen candidate a6401283d15b09abb74b6ebb4ed560097de5242d.

Native resource.calendar remains clock-time authority; native hr.version remains dated employee schedule and salary authority. Existing integer-minute compiler and Decimal payroll calculation unchanged. The edit action creates an immutable same-name replacement, source successor link, and native dated versions for exact active direct assignments. Source remains active historically and leaves template list. Private employee calendars remain independent.

Employee-first locks and calendar tuple touches cover native membership create/write/unlink, active changes and stale salary copying. Atomic preflight rejects existing attendance/leave/approved payslip coverage, same-date history conflict, future employee versions, and midmonth salary-split changes. All candidate employees including archived historical references bounded at200. No cron, queue, new library or journal/payment effect.

Native manual employee-version archival/deletion remains Odoo HR history administration; WS4 protects its concurrency but is not a replacement native history-management policy. Source effective-date guards apply to assignment dates.

Build/review evidence: docs/build-governance/ws4-plan.md and docs/releases/2026-09-09-schedule-edit/REVIEW.md. Deployment state is recorded in release HANDOFF/runtime.json after promotion.

Final lastVerifiedCommit: 2b555de2dc26349098dd1ab741d26e0eb260c334. MAIN19.0.1.1.1 current. WS4A metadata delta defaults native resource action to namedCurrentSchedules filter without changing originalcompanydomain; clearingfilter reveals history. ActualMAINlist/button and250tablepreservation verified.
