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

Source acceptance: PR707 head `08359332b5fa7649a6704da0115342f4dc0266fe`,
frozen merge `444f59b3d963315f4044b3a74ee52262ff4029c8`. Independent scoped
review GO, no P0–P2 findings. All seven CI checks passed. Native ten-provider
export/detail job127289835663 ran 93 tests with zero failures/errors, including
exact Arabic/English PDF monthly names, unchanged XLSX names, and both custom
period cases. Initial tobacco UI job passed 32 backend tests but Chrome failed
to start; only that job was retried, job127292389001 passed. Source unchanged.
QA baseline: ARZ October2026, 68 rows, opening/refunds0.00, net2270.60 SAR.
Both release policies pin the exact merged source and this single module only.

Owner amendment before Live: make the tobacco PDF portrait A4, then publish both
changes together. The first filename-only source was accepted on QA: module
19.0.1.5.3 installed; actual `رسوم التبغ لـ 10-2026 (3).pdf` downloaded at
2026-11-05 14:18:33 UTC,32602bytes,SHA256
1738DCB589F19949971E0C2EF2A0EF1DFCA79405530CF5B0D24C2C77B68E4A03.
Chrome added the duplicate suffix. The first production policy was approved but
never deployed; it is superseded by a new combined candidate/release policy.
The renderer now selects portrait for the fixed validated `tobacco` key only;
all other providers retain their existing column-based orientation. A4 was
already fixed. Real PDF tests assert actual 595.28×841.89 point page dimensions
in AR/EN, custom periods and with/without products. Versions: menu19.0.1.1.1,
tobacco19.0.1.5.4. No new document schema, data, permissions or dependency.

CI orientation candidate531e3a143: all native PDF dimension/name tests passed
(93 tests); tobacco UI, report Hoot and operations suites passed. The unrelated
activity desktop browser twice exceeded Odoo's cold-start10-second Chrome
budget while its mobile/browser and17backend cases passed. Add one bounded
blank-page Chrome warm-up to that existing runner workflow, keeping both real
desktop/mobile success gates. No application source change for this CI repair.
