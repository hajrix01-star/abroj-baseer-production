# Odoo Mates payroll — independent installation review

Reviewer: om_review. Date: 2026-09-08. Ownership limited to this review document; reviewer does not install or mutate application/database/source files.

## R1 — G0–G3 scoped installation decision

Read alpha-build-team and its governance, accounting/ERP and capacity references; `PAYROLL.md`, `PAYROLL-REVIEW.md`, `PAYROLL-VENDOR-AUDIT.md`, `PAYROLL-ALTERNATIVES-20260908.md`; then the newly written `OM-PAYROLL.md` contract. Historical Cybrosys runtime failures are not evidence of an Odoo Mates failure. Current Odoo Mates replay/cancellation concerns remain source-level test targets until reproduced against the exact installed source.

**G0–G3 GO for the explicitly bounded, unchanged-vendor QA installation/evaluation slice. No financial production approval or custom Baseer implementation approval.** The user has authorized installation and required dependencies, and the established environment is QA `baseer_reports_qa_20260907` on port 18070. Main `baseer_dev` on 18069 is excluded from mutations. Scope and acceptance are proportionate: two free addons, native dependency closure, coherent recovery, native employee/calendar/accounting ownership and guarded synthetic tests. This scope retains the native Odoo monetary boundary without introducing any new arithmetic implementation; it does not certify all vendor rounding or numerical behavior.

### Preconditions before installation

1. Resolve the official 19.0 branch to an immutable commit; inspect the exact manifests, initializers, install hooks, data files and dependency closure from that snapshot. Record source/archive hashes. Copy only `om_hr_payroll` and `om_hr_payroll_account`, keeping them unchanged. If another payroll engine, broad suite or paid dependency appears, return for review.
2. Confirm no Cybrosys/OpenHRMS or other conflicting `hr.payslip` engine is installed on the target QA database and no such engine appears in its executable addon path. Keep main addon path and service untouched.
3. Stop QA for a coherent database/filestore backup; verify the backup identity/hash and record before-state financial/user/company/module fingerprints. Start from the snapshot only while intervening writes cannot be lost; preserve trial state first if that precondition changes.
4. Install without demo data and inspect registry/server logs for actual model, security and view compatibility. Do not infer acceptance from the module store page or successful source download.
5. Before any lifecycle test, suppress actual mail transport, not merely employee email addresses, and retain disabled QA cron. Use synthetic fixtures with guaranteed rollback, including exceptions. No real accounting setup, employee salaries or external messages.

### Required evidence and honest boundaries

Verify draft computation, single balanced approval and native PDF at minimum. Characterize repeated approval, posted-source mutation, cancellation/refund, restricted-company behavior and accounting lock behavior through model methods where practical. Establish whether native payments/reconciliation are actually connected; a `paid` checkbox or `done` state is not proof of cash settlement. A discovered blocking control defect remains a financial NO-GO even when the module installs and its screens open.

The 900-staff, three-operator and seven-year assumptions are recorded for future design, not measured capacity. This slice does not need a load benchmark merely to install a candidate and does not justify a production throughput claim. It also does not deliver the legacy gross/basic/overtime calculator, loan installments/deferrals, custom proration policy, or the complete bank/cash payment journey. Those require a separate, reviewed extension design if the baseline is retained.

The native vendor interface can be inspected without introducing a new design system or library. Record Arabic/English and desktop/mobile limitations that are encountered; do not characterize unchanged upstream UI as a newly completed bilingual Baseer interface. G5–G8 require subsequent installation/test/handoff evidence and independent delivery review.

### Review ledger

OMR-001: Read-only review of the files and skill references named above, then wrote this independent decision. The only mutation is this documentation file. Root remains executor and ledger owner. No database query, package install or financial action was performed by this reviewer.

## R2 — candidate and executed characterization review

Read alpha-delivery-team and its roles/checklist/reserve references. Delivery scope is installation of an unchanged candidate for QA inspection, not operational payroll acceptance. Existing architecture is retained: native employee/version and calendar → vendor rules/payslip/batch → native account.move and QWeb PDF; native payment/reconciliation is a separate boundary with no demonstrated slip-level action. Source authority is server-side; a payslip's state/paid flag is not ledger settlement authority. The source contract and this map identify the changed boundary without reconstructing unrelated Baseer features.

Candidate: official Odoo Mates 19.0 commit `bf4b5867315da40466c2a830a087986427c61b9a`, archive SHA256 `ca5df0581a0ae1cc3654214f392b78c14542e0be73e71d296e23acb6b29f838c`. Independent filesystem checks verified **210/210 listed source hashes** and **4/4 preinstall backup hashes**, with no mismatches. Git lists these local additions as untracked; the upstream commit and explicit hashes identify this candidate, not a claimed local release commit. Installation log shows both selected addons loading, 108-module registry completing successfully, and native shutdown after the installer. No vendor or application fixes are in this candidate.

Inspected `om_payroll_checks.py` and the completed second-run JSON. The fixture uses a fixed SAR 2,000 rule, native employee version/calendar, two synthetic slips, a test journal and two account types. It patches template and mail transport before lifecycle calls and unconditionally rolls back in `finally`. This is source inspection plus independently reviewed executor evidence; reviewer did **not** repeat the financial tests. The first failed fixture attempt remains separately recorded and is not presented as a vendor failure. The corrected second run is `characterization_complete` with rollback true and zero intercepted automatic mail attempts.

| Finding | Severity for real payroll | Executed evidence and boundary |
|---|---|---|
| Basic fixed-rule calculation and first accounting entry work | Positive bounded result | Computed 2,000 and posted equal debit/credit 2,000. This does not validate gross/overtime splitting, allowances, unpaid leave or real salary setup. |
| English, Arabic and two-slip PDF generation work | Positive bounded result | All three outputs have PDF headers and nonzero bytes. Generation is proven; typography, correct translation and signature layout require visual inspection. Batch membership/printing is demonstrated, not mass batch employee generation. |
| Repeated approval duplicates the accrual | P1 | Second direct method call creates a second posted move and replaces the link while the first remains posted. This establishes retry vulnerability, not an ordinary UI single-click failure or a completed simultaneous concurrency test. |
| Finalized source can change | P1 | Approved slip end date changes without protecting the linked posted effect. |
| Cancellation removes accounting history | P1 | The latest linked entry no longer exists after cancellation; the first duplicate still exists. Exact source calls `button_cancel()` and `unlink()`, matching the observation. |
| Foreign-company payslip visibility | P1 | A non-superuser payroll manager assigned only the other company obtains the synthetic slip through `search_read`. Source manager rule allows all slips without a global company rule. Test reads id/company/date, so it proves a source-record access boundary failure, not a full salary-field or ledger-read exploit. |
| Payment journey not demonstrated | Acceptance gap | New payable-account posting succeeds in second run. `action_register_payment` is absent on the slip; this does not prove native accounting settlement is impossible. Bank/cash partial payment, employee partner allocation and reconciliation remain untested. |

Smallest prospective correction is a separate Baseer extension enforcing state/idempotence, posted-source protection, safe accounting corrections and global company boundaries, then explicit native settlement integration. This is a design recommendation only; no implementation or estimate of a trivial fix is approved. Concurrency, closed accounting periods, leave proration, loan/deferral, real employee privacy and end-to-end native payment settlement remain outside the executed proof. No capacity or full bilingual/mobile acceptance claim follows from these fixtures.

Main before/after JSON is byte-for-byte equal. QA before/after financial-table, company, user and company-membership hashes match (76 moves, 180 move lines, 28 payments, five companies, seven users, 14 company memberships). QA partner count stays 22 but its aggregate hash differs; groups relation grows from 36 to 38. Reconcile those deltas and supply final zero-fixture/UI evidence before final installation handoff acceptance. The two group additions appear consistent with the source explicitly granting payroll manager to root/admin, but this needs the exact preserved-data explanation.

**Current financial decision: NO-GO for real payroll.** This does not require uninstalling a user-authorized QA candidate with no real payroll records. Retained access must be described as evaluation only; fixes and the larger Baseer requirements remain pending. Final installation-only decision awaits the remaining preservation/UI handoff evidence.

OMR-002: Independently verified source/backup hashes, reviewed exact accounting/security source, executed-test script/results, compose QA path and installation log, and compared snapshots. Only this review document was changed. Existing vendor financial defects were not repaired or accepted for operational use.

## R3 — installation-only closure

**GO for closure and handoff of the user-authorized QA installation/evaluation slice. NO-GO remains for operational payroll, main deployment, or treating this as the finished Baseer payroll product.** No P1 is waived: those defects prevent the financial journey from being accepted, while the completed deliverable is the installed upstream candidate with reproducible evaluation evidence and explicit limitations.

Reviewed final `preservation.json`, `HANDOFF.md`, appended OM-003–005 ledger and `om_payroll_ui.txt`. Independently viewed desktop and 390-pixel mobile new-form screenshots. They show the native payroll form rendered on both surfaces; mixed English labels, Arabic numerals and a cropped mobile table/tab area remain visible. This accepts the installation's accessibility for inspection, not a polished/responsive Baseer redesign or a completed mobile entry workflow. Executor reports discarding the empty form, resetting the viewport and returning the browser to the payroll list at `/odoo/action-633`.

The remaining preservation differences are explained by precise original-column comparison: partner IDs 2/3 (root/admin) differ only in `write_date` and `write_uid` audit fields, with no added partners or business-field changes. Added group relations are exactly root/admin membership of `om_hr_payroll.group_hr_payroll_manager`, matching the inspected upstream XML; no memberships removed. Evidence reports **zero persisted payslips and zero payroll batches** after rollback. Main remains byte-identical across the recorded snapshots. No new real payroll configuration, salary fixture, loan implementation or bank transfer was committed.

The handoff identifies installed versions, immutable source and backup records, QA route, successful bounded behavior, all material runtime defects, omitted functionality and a recovery route that protects intervening user writes. It accurately distinguishes payable posting success from an untested settlement journey and describes the initial fixture error as a test-fixture error. No financial fixes or extra modules are needed to make the authorized installation reviewable; development of the proposed Baseer controls/calculator/loans requires its own next scope and gates.

OMR-003: Final independent installation review completed from preservation, handoff, ledger and UI artifacts. No tests or database actions rerun; no application/source changes made. R1's installation gates and this bounded G8 handoff are closed. Financial acceptance gates stay open with the P1 findings above.

OMR-004: Independently verified the final `evidence-manifest.json`: all 22 listed evidence files match their SHA256 values. This adds artifact-chain verification to R3 without changing its scoped decision.
