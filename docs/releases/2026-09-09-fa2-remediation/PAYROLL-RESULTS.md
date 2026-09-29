# FA2 — PAY-001 through PAY-006 remediation evidence

Owner: `audit_payroll_accounting`. Date: 2026-09-09. Candidate module `baseer_payroll` version `19.0.1.4.0`. Implementation follows approved G0–G3 in FA2-REMEDIATION and the approved G2 delta in [PAYROLL-DESIGN.md](PAYROLL-DESIGN.md). Application ownership excludes `security/security.xml`; that file belongs to the independent security owner. FA1 evidence was not changed.

**Result: all six PAY findings are addressed within the approved scope; ready for integration and independent acceptance.** This is not a whole-system release decision or a claim of absence of defects. All application runtime work used `baseer_fix_payroll_20260909`. Tests rolled back except synthetic concurrency fixtures intentionally committed only to this exclusive clone. QA and main were not written by this work.

## Closure matrix

| Finding | Original severity | Change and source | Independent observed result | Evidence |
|---|---|---|---|---|
| PAY-001 | P1 | Salary expense must be active, in the company, and expense/direct cost. Configuration constraint and approval configuration guard: `models/payroll.py:22`; settings domain updated. | Setting an `asset_current` expense fails before payroll can post. The six-month salary debit remains exactly3100 per month to the configured expense. | `payroll-independent-result.json`: wrong salary classification rejected and monthly expense comparisons. |
| PAY-002 | P1 | Separate native payment evidence, pending amount, liability settled, and payable residual. `models/financial_record.py:47`; `models/payroll.py:228`; payslip/payment reports. Cash is confirmed by native paid **or** matched, not both. Writeoff cash portions use cumulative cents. | Noncash3100 clearance: paid0, residual0, stage settled, no native payments, statement total0. Outstanding3100: native in_process/unmatched, paid0, pending3100, stage processing. Mixed2500cash+500writeoff: paid2500, settled3000, residual0. One cash SAR allocated over three1SAR salaries sums to1.00, without losing a cent. | Independent/boundary results; pending and mixed PDFs. |
| PAY-003 | P1 | Fixed30 full contractual month is a full monthly wage less approved absence/30. Partial coverage is calendar covered days/30 capped at1, then absence/30. `models/payroll.py:331`. Existing posted gross/components are not recalculated. | Full February3000; one unpaid March day2900; half-day2950; partial leap February15days1500. Calendar six-month3100 wages remain correct. | Independent and boundary results. |
| PAY-004 | P2 | Explicit EOSv2 Gregorian anniversaries and visible final-day convention, reviewer Gregorian confirmation before bill. V1 calculation retained for reproducibility; issued sources immutable; V1 draft must explicitly upgrade. `models/end_service.py:19,91,206`. | Wage3000, Gregorian2020-01-01..2024-12-31 inclusive: resignation2500, termination7500. Exact2years resignation1000; exact10years22500; leap-day-start exact5years2500. Legacy draft cannot calculate/issue silently. Native one-year1500 bill, partial444.44+1055.56, replay and reversal all pass. | Independent/EOS results; one-page EOS PDFs. |
| PAY-005 | P2 | Approved Odoo partial leave duration is consumed and clipped to period/contract, with per-date cap. `models/payroll.py:304`. | Native half-day0.5 accepted. A cross-month PM→AM leave is0.5 in each month, salary2950 each. Native2hour leave produces2975. Whole approved March day remains2900. | Independent/boundary/EOS results. |
| PAY-006 | P2 | One contextual native correction wizard: signed wage/deduction entry; latest payroll recovery reversal; latest direct repayment reversal; disbursement reversal after active recoveries are reversed. `models/correction.py:97,185,209,259,277`. Immutable source/allocation links and native entries remain authoritative. | Partial-paid2950 → deduction100 → revised2850/debt1850; fully paid then+125.55 → new debt125.55 → paid2975.55. Original accrual IDs/accounts/partners/debits/credits unchanged. Reversal of150 direct repayment restores loan500; reversal of500 payroll recovery restores loan1000 and increases salary debt500. Advance reversal closes debt0, recovered0, schedule balances0 with original1000 retained. Stale/duplicate/reversed-source and forged links fail. | Independent/security/concurrency/RPC results and correction PDFs. |

## Executed checks

Evidence JSON is under `payroll-runtime/`; [payroll-final-checks.json](payroll-final-checks.json) records counts and SHA-256 of payroll source files, excluding the separately owned security.xml.

| Runtime script | Checks passed | Additional expected denials |
|---|---:|---:|
| `payroll-remediation-test.py` |125/125|5|
| `payroll-eos-test.py` |20/20|5|
| `payroll-boundary-test.py` |13/13|0|
| `payroll-security-test.py` |4/4|9|
| `payroll-concurrency-test.py` |10/10|0|
| `payroll-rpc-test.py` |11/11|0|
| `payroll-view-policy-test.py` |2/2|0|
| `payroll-seed-integration-test.py` |137/137|0|
| `payroll-dialog-translation-test.py` |11/11|0|
| **Total** |**333/333**|**19**|

The primary PAY functional/boundary suites account for183 checks, followed by2 compiled-form policy checks,137 combined company-seed regression checks, and11 scoped Arabic translation checks. Expected denials inside RPC/concurrency/seed checks are already included in333; they are not counted again in19. The independent-result observations also retain actual noncash/pending values and legacy365 outputs for comparison. Both prior payment observations now have the intended separate meanings. Initial trial failures were fixed before these final results: the half-day fixture needed Odoo19's final AM period, and a native full reversal may already reconcile on posting, so the controlled reversal reconciles only remaining open lines.

Final combined seed regression reused `company_accounting_seed_checks.py` through a new FA2 copy, retaining all137 checks and changing only the hard clone guard plus the fixture's explicit Gregorian confirmation/evidence before EOS issue. It passed with full rollback. The loaded seed implementation matches the workspace SHA-256 `5e75319478c40a03805a5a6bc82b01582c0cf64c022e8de9856cd86dd567a796`; no seed/application edits or extra source overlay were needed. Repeating setup for six companies took0.65s; new Saudi company plus native precommit took3.57s; complete shell run16.44s. New-company salary1000, advance100 and seeded EOS bill/payment passed alongside configuration-preservation/security checks. Evidence: `payroll-runtime/company_accounting_seed_checks.json`.

Six-month independent loan schedule: principal1199.99 over6, January recovery200, February direct150.01 and deferred49.99, March recovery249.99, April/May200, June199.99. Loan balances after monthly payroll were999.99,849.98,599.99,399.99,199.99,0. Monthly other deductions7.13,14.13,21.13,28.13,35.13,42.13 gave net2892.87,3085.87,2828.88,2871.87,2864.87,2857.88. Each was paid731.27 by bank and the balance by native cash; debit/credit accounts, cent conservation, native residuals and replay were checked independently.

Concurrency used two real PostgreSQL/Odoo cursors with REPEATABLE READ and nonadministrator payroll+accounting users. Different correction wizards: one succeeds, one gets serialization retry then stale-evidence rejection. Same wizard: both calls return successfully with one correction entry. Settlement payment versus salary reduction: one succeeds and the other is rejected after retry with changed evidence. `models/payroll.py:244` and `models/loan.py:91` create a new MVCC row version without altering write_date's value, so waiting mutations cannot rely only on an old advisory-lock snapshot. A repayment followed by its reversal also invalidates an older wizard even when its balance returns to the same number (ABA), because allocation/reversal history is part of the snapshot.

Public `call_kw` tests verify Officer denial for create/confirm/action_correct, allowed nonadmin accounting-manager create/confirm, and denial in the wrong active company. The native `get_public_method` boundary rejects `_sources`, `_new_move`, `_salary_adjustment`, and `_reverse_recovery`. Boolean `baseer_payroll_internal=True` and forged context defaults do not substitute for the private Python capability.

Static verification:14 Python files parse,14 XML files parse, `git diff --check` passes. Native module upgrades succeeded. Seventy Arabic translation entries/references were added or updated from Odoo's native PO export, then five scoped correction-dialog contexts were added for Slip, Kind, Date, Reason and Cancel following root's actual UI finding. Native import, fields_get, compiled view and export checks confirm the Arabic labels; the existing EOS reason and loan repayment-kind translations remain unchanged. Final presentation follow-ups also add the new payment-report Status translation occurrence and hide the new inclusive-day checkbox on historical V1 records (whose source policy excludes that day). Unknown/historical drafts can explicitly select v2. No source amounts or calculation logic changed in these presentation follow-ups; root approved both confirmed presentation defects before final source freeze.

## PDF evidence

Native QWeb output,22 A4 pages in12 PDFs, rendered through Poppler and visually inspected in Arabic and English. [payroll-pdf-manifest.json](payroll-runtime/payroll-pdf-manifest.json) records every count/size; page PNGs are in `payroll-runtime/visual/`.

- [Six-month Arabic payslips](payroll-runtime/payroll-six-months-ar_001.pdf) and English counterpart:6pages each, one record per month, salary/advance/deduction/net/payment/residual and employee signature.
- [Corrected Arabic payslip](payroll-runtime/payroll-correction-ar_001.pdf): original net2950, posted adjustment25.55, revised net/paid2975.55 and signature, one page.
- [Pending salary](payroll-runtime/payroll-pending-ar_001.pdf) and [pending payment statement](payroll-runtime/payroll-pending-payments-ar_001.pdf): paid0, processing3100; statement row explicitly in process. English counterparts match.
- [Mixed payment statement](payroll-runtime/payroll-mixed-payment-ar_001.pdf): cash paid2500, no false inclusion of500writeoff; Arabic Status/pending labels verified after the final translation update.
- [EOS final Arabic receipt](payroll-runtime/payroll-eos-final-ar_001.pdf) and English counterpart:1500, confirmed native payments, explicit Gregorian inclusive policy, no remaining amount, two signatures, one A4 page. Native bill reversal invalidates final-receipt status.

The synthetic company retains its default placeholder logo and synthetic English names/reference notes. These are fixture identity data, not production branding. `Eligible days` remains the count of eligible **calendar** days; the fixed30 salary fraction is computed separately, so a31-day month with half-day absence displays30.5 eligible days and pays29.5/30 of monthly wage.

## EOS policy and official references

The supported v2 contract is expressly Gregorian with reviewer confirmation, inclusive final service day by default and an explicit alternative. It is **not** an automatic legal classification of every Saudi contract or every departure reason. The HRSD official general provisions, Article10, use Hijri unless the employment contract or work regulations specify otherwise; that is why confirmation is required. [HRSD general provisions](https://www.hrsd.gov.sa/التعريفات/الأحكام-العامة), checked2026-09-09.

HRSD Articles84–85 describe the first-five-year/remaining-year calculation and the resignation2/5/10year bands. This implementation removes leap-day threshold drift under the approved Gregorian convention. Other reviewed reasons still require documentary verification. Wage inclusions/exclusions, exceptional causes, unrecorded service breaks and other final-settlement items require business review; this change does not certify them. [HRSD employment relations](https://www.hrsd.gov.sa/علاقات-العمل), checked2026-09-09. The [official calculator](https://www.hrsd.gov.sa/ministry-services/services/end-service-benefit-calculator) is a contextual reference; no automated calculator-equivalence claim is made for date inclusion or contract policy.

## Deliberate limits and handoff

- No automatic Hijri conversion, retroactive recalculation of issued V1 awards, or silent migration of old drafts. Changing a legacy draft requires its visible policy action and renewed review.
- No reduction of salary beyond unsettled debt, no implied physical cash return and no deletion of historical accrual/payment/allocation records. Overpayment collection remains a real separately evidenced accounting/business event. Correction entries document the reviewed adjustment and do not send external transfers.
- This slice verified SAR/two-decimal fixtures and the stated business scenarios. It did not re-certify all salary contract policies, every leave-calendar edge, every exceptional EOS reason, foreign-currency workflows, external bank delivery, or all historic data combinations.
- Capacity50, integrated source freeze, main-clone migration rehearsal, full application UI and independent delivery acceptance are owned by root/other reviewers. Their outcomes must be attached to the release decision; this report does not substitute for them.

Reproduce on the exclusive clone with the bundled Python: `docs/build-governance/fa2_ops.py stage payroll`, `upgrade payroll`, then `run payroll docs/releases/2026-09-09-fa2-remediation/<script>.py`. All runs use the staged snapshot, not live files under another agent's development. The concurrency script commits synthetic fixtures and must only run on its hard-asserted clone; RPC microtests reuse those fixtures and roll back.
