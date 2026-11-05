# Tobacco PDF period filename — 2026-11-05

Bounded LOCAL regression repair, based on `d58255772` and the existing
REPORTS-UNIFIED-ENGINE-20261024 map. The October 24 unified export replaced the
legacy report action's period filename with the document title. Actual owner
downloads show `رسوم التبغ لـ 10-2026.pdf` before and `تقرير رسوم التبغ.pdf` after.

Only `baseer_pos_tobacco_report` owns this fix (.5.3): after the existing export
engine validates and renders the requested PDF, its inherited transport restores
the legacy monthly or custom-date filename from the validated wizard. XLSX and
other providers retain their current names. PDF bytes, report title, calculations,
filters, permissions, company isolation and operational records are unchanged.

Verification: strengthen the existing real Arabic/English PDF export test with
the exact monthly filename and unchanged XLSX title; add actual PDF custom-range
and custom-full-month assertions. Reuse existing CI; no new test environment or
load test is warranted for the owner's single-report filename change. Independent
scoped delivery review, protected single-module QA/production and actual owner
download-name evidence are required before claiming completion.
