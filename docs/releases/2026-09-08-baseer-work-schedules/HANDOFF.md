# BP-S5 — native work schedules

QA baseer_reports_qa_20260907, baseer_payroll19.0.1.2.1. Frozen source/ZIP hashes in candidate.json; pre-upgrade database backup fingerprint in backup.json. Original main unchanged.

Two optional native duration-based calendars per company:84h/7days (12h/day);60h/6days (10h/day, Friday omitted). Editable from native Working Hours. Existing company/employee defaults are preserved; choose explicitly in Employee→Payroll→Working Hours. New company creation automatically seeds the same two choices. Existing QA companies also receive them. No new dependencies or fixed clock-time policy. Duration-based calendars are for daily hours, not a configured late-arrival schedule.

43 native rollback assertions passed, including new/multi-company create, exact daily/weekly totals, repeat initializer, administrator edits/archive, polluted default context, restricted company creation and salary calculator consumption. Two-company creation measured0.633s in QA; not a concurrency/SLA certification. Actual module upgraded twice without duplicates. Existing financial/employee/version/company/calendar/attendance rows match before hashes; preservation.json reports QA/main true. Native calendar read ACL remains unchanged; native selection filters company. Explicit native company checker validated, but hr.version does not automatically invoke it on every raw ORM write; no new RPC isolation claim.

Native Arabic desktop/mobile selector evidence: docs/build-governance/baseer_work_schedules_desktop.png and baseer_work_schedules_mobile.png. Inspection only, no employee edits. Work contract and independent review: BASEER-WORK-SCHEDULES.md / BASEER-WORK-SCHEDULES-REVIEW.md under docs/build-governance.

Rollback: restore reviewed BP-S4 source19.0.1.2.0 and this QA database backup during maintenance if required. Do not uninstall or delete calendars already selected by employees. No filestore mutations introduced. Main promotion is outside this delivery.
