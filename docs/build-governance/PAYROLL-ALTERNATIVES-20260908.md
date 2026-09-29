# Payroll alternatives — research only, 2026-09-08

## Superseding decision — free-only follow-up, 2026-09-08

User excluded paid XFanis. The earlier XFanis-first recommendation below is retained as research history and is no longer the proposed path. Current proposal: evaluate free Odoo Mates payroll plus its accounting addon in isolated QA before deciding whether to extend it or build a focused Baseer addon. This follow-up performed research only; no package installation or database change.

External evidence reviewed:

- The publisher's LinkedIn page lists 2–10 employees. This is self-reported, not independently audited company size: https://www.linkedin.com/company/odoomates
- Reddit users recommend Odoo Mates for learning; this supports educational reputation, not payroll19 acceptance: https://www.reddit.com/r/Odoo/comments/1i7ht75/
- A customer job posting describes actual use of Odoo Mates payroll on Odoo13 and requests accounting setup assistance. Evidence of historical use, not an independent quality audit or version19 review: https://www.fr.freelancer.com/projects/accounting/odoo-accountant
- Reddit accounting17 discussion includes a response suggesting journal configuration for payment issues. Accounting discussions cannot establish payroll19 failure: https://www.reddit.com/r/Odoo/comments/1l8mxz7/
- GitHub issue187, titled installation failure on19, concerns om_account_asset, not payroll, and is closed: https://github.com/odoomates/odooapps/issues/187
- Payroll test-import PR168 targets16.0; payroll accounting PR135 targets17.0. Neither is proof of a19.0 failure: https://github.com/odoomates/odooapps/pull/168 and https://github.com/odoomates/odooapps/pull/135

No sufficient independent long-term payroll19 reviews were located in this search. This does not prove none exist. Current raw19.0 accounting code still creates a move on each action_payslip_done call and cancels/unlinks linked moves in action_payslip_cancel. This remains a source-level concern requiring an explicit replay/correction runtime test; it is not the Cybrosys runtime failure and must not be represented as already reproduced on Odoo Mates. https://raw.githubusercontent.com/odoomates/odooapps/19.0/om_hr_payroll_account/models/hr_payroll_account.py

Custom alternative assessment: a focused reusable payroll addon is moderate work when using native employees, calendars/leaves, accounting/payment reconciliation and PDF reporting. Salary presentation/calculator is comparatively straightforward; partial-period eligibility, installment deferral, split settlement, corrections, duplicate approval prevention and company isolation need meaningful financial acceptance. Reuse requires compatible Odoo19Community, declared dependencies, configurable company/accounts/journals/rules and no hardcoded database IDs. Other major Odoo versions require adaptation/testing; installing source does not migrate payroll records. No claim that all desired Odoo Mates extensions are small until tested.

User requests closest existing Odoo19Community payroll/loans solution with minimal modifications, after failed Cybrosys/OpenHRMS evaluation. No package installed, no purchase, no vendor message, no database changes in this research turn.

## Requirements retained

Employee salary setup; gross salary plus agreed daily/weekly hours and working days split into basic and included overtime using legacy Baseer calculator; allowances/manual deductions; monthly batch; approved leave/new joiner proration and full-period unpaid-leave exclusion; loans, installments and deliberate deferral; accounting-linked salary payout including partial bank/cash settlement; employee PDF payslip and batch printing/signature. Attendance remains native and independent of payroll deduction. Three independent Saudi SAR companies. Formula is a user-requested compensation calculation, not a newly verified Saudi legal rule.

## First candidate to demonstrate: XFanis suite

Publisher offers19.0Community, paidOPL-1. Closest documented functional coverage among inspected options, **not runtime approved and not a claim that all remaining changes are small**.

- `xf_payroll_system`: employee contracts, salary components/structures, fixed/manual/formula inputs, period batches, configurable approval stages including minimal workflow, individualPDF. https://odoo-addons.xfanis.dev/apps/modules/19.0/xf_payroll_system
- `xf_payroll_system_account`: component account/partner mapping, contract/slip journal selection, individual/batch posting. This proves a posting feature, not a native payment-registration or reconciliation flow. https://odoo-addons.xfanis.dev/apps/modules/19.0/xf_payroll_system_account
- `xf_loan`: loan installment schedules, interest-free default, role workflow. https://apps.odoo.com/apps/modules/19.0/xf_loan
- `xf_payroll_loan`: automatic inclusion of unpaid installments as payslip deductions, without accounting alone. https://odoo-addons.xfanis.dev/apps/modules/19.0/xf_payroll_loan
- `xf_payroll_loan_account`: integration of loans/payroll/accounting; dependencies include loan accounting plus above and2shared helpers. Publisher checkout description lists totalUSD48 including dependencies; Odoo Apps showedUSD47.98. Verify actual total/license before purchase. https://odoo-addons.xfanis.dev/apps/modules/19.0/xf_payroll_loan_account and https://apps.odoo.com/apps/modules/19.0/xf_payroll_loan_account

Small-looking prospective adaptations: expose employee salary calculator inputs and agreed rule, hide unused setup, Arabic presentation/signature onPDF. Not estimated as small until model/source examination. No evidence found proving native automatic approved-leave proration, installment deferral/rescheduling, split salary settlement viaaccount.payment, or batchPDFprint behavior. Publisher says release payslip emails PDF automatically: isolate mail in any localQA test. Payroll loan accounting narrative mentionscashaccount; verify actual entries and avoid double-countedcash or fakepaidflags. A dependency namedxf_demo must be inspected for hooks/seeds before localinstallation. Numberofmodules or LOC does not establish reliability.

Paid-source code not acquired or audited. Publisher provides RequestDemo andvideo link; research didnot submitrequest or authorizepurchase. Demo should precedepurchase and anylocalinstallation shoulduseisolatedQAwithnativefinancialacceptance.

## Other candidates

### ERP Heritage EH HR Payroll and EH HR Loan

FreeLGPL-3,19.0Community. Payroll advertises rules/batches/PDF/genericCSV and exposes feeder extension hooks. Its honest-edges section says loan/overtime inputs are empty hooks inbase andwage isentered per slip, not actualcontractread. Loan explicitly has no accounting integration or automaticpayslipdeduction; paidflagmanual. Thus extra payroll/loan/payment integration is substantive for this user. Existing accountingreports bysamevendor donot proveHRreadiness.

https://apps.odoo.com/apps/modules/19.0/eh_hr_payroll
https://apps.odoo.com/apps/modules/19.0/eh_hr_loan

### OCA payroll

Live19.0branchREADME lists onlypayroll19.0.1.0.0; payroll_account absent frommergedbranch reviewed. Searchstillshows19.0accountmigrationPRs. Do not mistakePRtestsuccess forreleaseddependency. Good upstreamcandidate forfutureevaluation, presently requiresadditionalaccounting/loanwork forrequestedfullcycle.

https://github.com/OCA/payroll/tree/19.0
https://raw.githubusercontent.com/OCA/payroll/19.0/README.md

### Odoo Mates

om_hr_payroll19.0.1.1 available LGPL-3 plusom_hr_payroll_account. Reviewed rawaccountcode: action_payslip_cancel cancels/unlinks linkedmoves; action_payslip_done createsnewmove and overwritesmove_id without a visible replayguard inthatmethod. This is source-level concern, not a fresh runtimeproof. Basicengine alone also doesnotmeetloandeferral/settlement scope. Do not recommend merely because freeorpopular.

https://apps.odoo.com/apps/modules/19.0/om_hr_payroll
https://raw.githubusercontent.com/odoomates/odooapps/19.0/om_hr_payroll_account/models/hr_payroll_account.py

### Webkul and Softhealer

Webkulemp_loan_management19.0documentsinterestfree/EMIs/automaticdeductionsandEMIchange;listedCommunitypayrolldependency needsverification and it isnotfullpayrollengine byitself. Softhealersh_hr_payroll19.0documentscontracts/rules/batches andseparateaccountaddon;didnotestablishfullintegratedloandeferral/paymentflow. Not rankedaboveXF onavailableevidence.

https://apps.odoo.com/apps/modules/19.0/emp_loan_management
https://apps.odoo.com/apps/modules/19.0/sh_hr_payroll

## Proposed acceptance demonstration, before claiming adoption

1. Oneemployee gross2000 with12hours/day and30days splitswithoutchangingtotal; agreedlegacyparameters supplied, nolegalconformanceclaim.
2. Monthlybatch correctlyhandlesemployeeactivehalfmonth, fullmonthunpaidleave andpaidleave asdifferentcases; attendanceunconnected.
3. Interestfreeloan600 over3installments:200deduction; deferoneinstallment withoutmarkingpaid or losingremainingbalance.
4. Net salarysettled partlybank/partlycash; payable,residualandrealcashreport agree; no duplicateexpense/bill+entry.
5. Repeat/concurrentapproval cannotduplicateentry; correctionpreserveshistory;3companyisolation; batchPDFArabic/signature.

If anymissingcapability requiresreplacingposting orloancore, rejectminimal-changeclaim ratherthancontinuebuildingalargereplacement. Researchrecommendation isXFfirstdemo, notfullfinancialGO. OriginalandQAservicesuntouched.
