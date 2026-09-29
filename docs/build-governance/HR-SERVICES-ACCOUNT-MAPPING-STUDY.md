# HR services: current chart and proposed mapping

Date: 2026-09-08. Discussion study only. No configuration or accounting changes.

## Evidence

- Existing account snapshot: `hr_services_current_accounts_review.json`, read directly from QA database `baseer_reports_qa_20260907`.
- Additional read-only query of `account_group`: exactly one group, ID 1, company 9, name `مصاريف تشغيلية تجريبية`, prefix start/end `QA6`, no parent. No native employee-services group exists for the Saudi 400xxx accounts.
- Native source: `odoo/addons/account/models/account_account.py`, account-group selection at lines 437–438 and group model from line 1514. Membership is based on account-code prefix ranges, not arbitrary service labels.
- Reporting implementation is owned by a separate reviewer. This study does not claim the installed P&L automatically displays a dedicated employee-services heading.

## Actual current position

Companies 6, 7, 8, 9 and 10 use the Saudi chart and each has active expense accounts 400006 (employee leave tickets), 400009 (medical insurance), 400014 (visa), 400015 (other personnel), 400024 (air tickets), 400075 (other employee expenses). Each also has active 104021 (prepaid medical insurance, asset_prepayments). Company 1 uses generic_coa, with 600000 Expenses and 141000 Prepayments rather than these specialized Saudi accounts.

No duplicate account codes were found in the prior direct review. Similar-purpose accounts are selection choices, not evidence of erroneous duplication. No existing codes, journal entries or account links should be merged or renumbered to obtain a cleaner report.

## Proposed service mapping

| Service | Current candidate | Proposed report path / decision |
|---|---|---|
| Employee leave flight ticket | 400006 employee tickets | Expenses / employee services / employee tickets. Prefer this over generic 400024 for this specific benefit. |
| Business travel ticket | 400024 air tickets | Expenses / business travel. Keep separate from employee leave ticket where the business distinguishes these purposes. |
| Medical insurance | 400009 medical insurance | Expenses / employee services / medical insurance, for the expense recognized in the reporting period. |
| Insurance covering future periods | 104021 prepaid medical insurance, then 400009 | Balance sheet / prepayments initially; subsequent expense to medical insurance according to the accounting policy. Do not show the unconsumed balance as current-period service expense. |
| Exit/re-entry visa | 400014 visa expenses | Expenses / employee services / visa fees. |
| Iqama issuance/renewal and work permits | No explicitly named iqama account found | One dedicated expense account if separate GL visibility is wanted, chosen within the existing company code scheme after collision check. No new account per renewal or employee. |
| Sponsorship transfer | No specific named candidate verified | Map explicitly to the appropriate personnel/permit expense treatment; do not automatically treat every payment to a government supplier as a visa fee. |
| Health certificate and miscellaneous employee service | 400075 other employee expenses, or an explicitly approved suitable existing account | Expenses / employee services / other services. Avoid alternating between 400015 and 400075 for identical service types. |
| Amount explicitly recoverable from employee | Existing configured employee-advance/receivable account | Balance sheet / employee receivables, with employee subledger. Not an automatic company expense or payroll deduction. |
| Refundable deposit or amount advanced before service | Suitable existing asset account after identifying the transaction | Balance sheet until used/refunded. Do not choose an expense solely because the payment originates from the services screen. |

The supplier is not the sole account selector: a single supplier can issue tickets, insurance and visa-service invoices. The service type/product and transaction nature determine the expense/asset mapping; the supplier identifies the payable counterparty. A supplier default may assist entry but must not override the service classification.

## Proposed reporting arrangement

Use an explicit presentation group `خدمات الموظفين` for the selected service expense accounts if the installed report supports account selections. Keep salary, end-of-service, employee loans and prepaid balances in their proper sections. The service register supplies drill-down by employee and service type without a GL account per employee.

Do not create an account.group spanning 400003–400075: the range includes many unrelated accounts. Since the existing service accounts are not contiguous, native prefix groups alone cannot make one clean services branch without also grouping unwanted accounts or changing existing codes. The report reviewer must decide the smallest safe presentation configuration.

General overview totals should distinguish service document cost, paid/outstanding amounts and recognized expense when prepaid services exist. A yearly insurance service can retain its full document cost in the HR register while P&L recognizes only the applicable period's expense.

## Company 1 exception

Preserve generic_coa. Its generic expense and prepayment accounts can support basic recording, but dedicated service expense accounts would improve financial-statement detail if that company needs it. Add only explicitly mapped missing accounts; never reload the Saudi chart over the existing chart. Keep the service-type register useful even where a generic account remains selected.

## Boundaries

Supplier bills/payment entries remain the financial source of truth. A service record references the original document rather than duplicating its expense. Service-type defaults are per company, created idempotently and preserving existing deliberate mappings. Payroll and end-of-service account settings remain outside this services mapping.
