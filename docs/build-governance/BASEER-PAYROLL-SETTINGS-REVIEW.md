# Payroll Settings delta — independent review

Reviewer: om_review. Scope: BP-S1 on QA only, 2026-09-08. Reviewer owns this document only; no application/database changes. Prior payroll architecture and completed QA acceptance remain the baseline.

## R1 — G0–G4

Read `BASEER-PAYROLL-SETTINGS.md` and the existing configuration-boundary design. **G0–G4 GO for this narrow implementation.** The evidenced failure is an unconfigured active company reaching the required payroll-journal insert. Exposing the same authoritative `res.company` fields through native Payroll Settings and validating before insertion is the shortest appropriate fix. No new accounting policy, salary calculation, company mapping, library or payroll engine is needed.

Preserve the original validation semantics when extracting the pure helper: missing fields, company ownership, account types/reconciliation and general-journal type. The pure check must not create salary structures/rules or write settings. Call it before every managed-run insert path, including defaults/context and the creation wizard; the wizard's selected company must remain explicit so stale-company requests are rejected rather than silently redirected.

Native transient related fields must keep administrator-only configuration writes and the native settings company boundary. View domains assist selection, while server checks remain the final authority. Saving configuration and generating a run must not infer or populate account mappings for companies 6 or other real/previous QA companies. Arabic/English missing-config feedback should name the relevant company and identify Payroll → Settings without exposing a raw SQL error.

G1 capacity evidence is inherited: six settings fields and a preflight check need no additional load benchmark. G4 uses the existing native settings app and components; validate desktop/mobile visibility and an actual synthetic settings-save/create journey. Scope remains version 19.0.1.0.1 with separate patch hashes; preserve the prior frozen ZIP and source identities. Focused regression tests are proportionate unless extraction changes financial behavior.

BPSR-001: Contract reviewed before implementation; scoped gates approved. G5–G8 remain open for exact diff, focused tests, UI, preserved-data and patch-identity evidence. No application or database operation performed by reviewer.

## R2 — delta source inspection

Read `models/settings.py`, the extracted configuration helper and managed-run/wizard call sites in `models/payroll.py`, the inherited native settings view and the focused test script. **No source-level blocker found in the reviewed delta.** The six writable related fields point to the existing company fields, without a second configuration store. The helper retains prior current-company, account ownership/type/reconciliation and journal-type checks and performs no writes. The managed create path invokes it before `super().create`; the wizard now passes its selected company explicitly.

The settings view inherits the existing Odoo Mates app and exposes the company alongside the fields. Choice domains match the native company/journal/account boundaries, while execution still relies on server validation. The first upgrade's unsupported `account.deprecated` domain was removed; that failed upgrade is not counted as a passing test. No calculation, rule or ledger behavior is intentionally changed. Incomplete settings may be saved as native configuration; the necessary guarantee is that generating a managed run rejects incomplete/invalid mappings clearly before insertion. No automatic mapping for an unconfigured company is introduced.

The focused script covers missing configuration through direct/context/wizard paths, no inserted run, stale-company rejection, Arabic feedback, related read/write isolation, pure-check noncreation, configured employee loading and invalid selections. It rolls back in `finally`. Runtime results, an actual native settings UI journey and the final artifact/preservation identities remain required for scoped G8 closure; this reviewer does not repeat database tests.

BPSR-002: Source and test-design inspection completed. Only this review file changed; final outcome remains pending evidence.

## R3 — independent G8 closure

**GO for BP-S1 version 19.0.1.0.1 on QA.** The reviewed narrow delta resolves missing-company configuration before managed-run insertion and exposes the existing authoritative fields in native Payroll Settings. No financial calculation or ledger change is approved or hidden in this scope; the prior payroll limitations remain.

Independently verified **16/16 source hashes**, **16/16 matching archive entries**, archive SHA256 `a92eb444a1722900a3be3d48f3e8a5a865b5714f90bb4f6613c45df4c1edb5cf`, **5/5 evidence hashes** and **4/4 backup hashes**, all with zero mismatches. The previous 19.0.1.0.0 archive still matches its frozen hash. Main snapshots are byte-for-byte equal. QA before/after hashes match for all **83 moves, 198 move lines and 29 payments**.

The focused result has **22 passing checks**, overall passed and rollback true. It covers all three missing-config entry paths, translated/company-aware feedback, no failed-run insert, stale-company rejection, same-company related settings reads/writes, no helper-created rules/structures/entries, configured employee loading and invalid account/journal choices. These are independently reviewed executor tests, not tests rerun by this reviewer. The native Arabic message uses the correct Odoo Python translation marker in the final candidate.

Personally viewed the desktop and 390-pixel mobile settings screenshots: company identity and the six configuration fields render through the native Settings app, with the native Save control. Root reports successful native Settings Save on demo company 10. The created-run screenshot confirms a two-employee January 2027 draft with 5,000 gross, 850 overdue advance deductions and 4,150 net. Root then deleted only that UI test draft (run 85); earlier demonstration runs remain. This is a more complete settings-to-run journey than the no-existing-loan rollback fixture and the differing totals are expected, not a discrepancy.

Final preservation records only company 10's native settings normalization (`hr_presence_control_attendance` NULL to false, remaining disabled) and audit metadata; payroll mappings and other company rows remain unchanged. No mappings were invented for unconfigured companies. Settings may retain incomplete input, while managed payroll creation requires a complete valid configuration. The handoff states this distinction, the native administrator permission boundary, same backing company fields, QA route, dependencies and backup precautions.

No additional capacity or full six-month rerun is necessary for this pure configuration projection/preflight delta. The predecessor's salary/loan protections and accepted limitations remain applicable. Production promotion and actual configuration choices for other companies are not part of this GO.

BPSR-003: Final source/archive/evidence/backup verification, financial snapshot comparison and UI/test/handoff review completed. Only this document changed. Scoped G5–G8 closed; no application edits or database tests performed by reviewer.
