# FA2 SECURITY-001/002/003 — implementation handoff

**Implemented and tested; awaiting independent reviewer acceptance.** Four owned application files only; no schema, financial calculation, dependency or manifest edits by this worker. G0–G3 were independently reviewed before implementation in the appendix of `docs/build-governance/FA2-REMEDIATION.md`.

| Finding | Change | Current evidence |
|---|---|---|
| SECURITY-001 | Three Officer child-read rules reproduce the existing parent employee/department scope, with three Manager allowances. Existing global company rules still intersect all group allowances. | Direct child reads/searches deny unrelated departments; self, no-department and managed-department policies work; Manager sees same-company data while foreign-company reads/searches remain denied/empty. |
| SECURITY-002 | Elevate only the hardcoded `ir.model.data` catalog membership read after normal mapping/category access. | Invoice operator creates with explicit or supplier-derived service defaults and receives Expense from both native category/partner onchange calls. Explicit type remains supported. Unauthorized category/company mutations remain denied. |
| SECURITY-003 | Correct the two `om_om_hr_payroll` namespace references in the native wizard and report handler. | Non-admin Manager invokes native action; registered handler returns real selected rows/239.70 total; English and Arabic HTML and full PDFs render, each one page. |

Validation: **92/92 checks** (57 permission matrix + 26 boundaries + 9 full-render checks). Odoo upgrade on the exclusive clone completed with exit 0 in 11.91 seconds. Each database fixture run rolled back with matching before/after fingerprints. The clone contains the current 142-module baseline and its filestore; its source overlay is frozen FA1 plus these four owned files, isolated from other workers' changes. The full merged FA2 candidate still needs integration testing.

Evidence:

- `security-source.json`: source overlay actually staged for the test database.
- `security-source.patch`: exact change against frozen FA1, including the two-line vendor patch.
- `security-validation.json`: baseline/current file hashes, check totals and PDF identity.
- `security-runtime/security-result.json`: role and payroll parent/child matrix.
- `security-runtime/security-boundaries-result.json`: native onchanges, company/POS/batch guards and actual installed rules.
- `security-runtime/security-report-render-result.json`: report action/data/HTML/PDF assertions.
- `security-runtime/security-contribution-en_US.pdf` and `security-runtime/security-contribution-ar_001.pdf`; read-only visual review images are `security-contribution-en_US.png` and `security-contribution-ar_001.png`.

Limits: RPC uses Odoo's native in-process `call_kw`, not a new authenticated HTTP penetration test. Report fixture uses the private in-process capability to set a synthetic approved state solely to exercise the native report selector/formatter; it does not claim new accounting-posting coverage. Report headers use the installed vendor translations; this slice does not redesign or retranslate its UI. Native SQL selection in the contribution handler is unchanged; its resulting child field reads now obey the repaired ORM rules. No historical payroll row was changed, no message was sent, and no QA/main write was made by these scripts.

Root owns final module version updates, pinned engine identity, combined candidate and independent review. Security rules should be kept aligned with the parent Officer scope if that upstream policy changes in a future Odoo Mates update. This handoff closes implementation work for the three findings; the worker does not grant its own independent G8 approval.
