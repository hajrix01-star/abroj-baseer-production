# خطة تصحيح أخطاء الإدخال — بحث فقط

2026-09-10. Requested research and proposed plan; no application, database or GitHub changes authorized by this planning request. Current MAIN remains FL2.

## Findings

- Odoo19 account.move.button_draft/action_post provide the native draft/edit/repost path. _check_draftable and native write/post guards remain authoritative; hash locks, accounting dates, exchange/cash-basis records and electronic invoice constraints cannot be bypassed.
- account.move.reversal.modify_moves implements reversal plus replacement invoice. It is an alternative for records that should remain issued, not a required step for every mistaken supplier-bill entry. Payment allocations can be removed during reversal; the existing payment must be identified and reconciled deliberately, not duplicated.
- account.payment.action_draft/action_post exist. A standalone journal reversal is not sufficient proof that payment state, invoice settlement and bank reconciliation remain correct.
- Original database inspection: baseer_purchase_batch installed; account_edi and l10n_sa_edi currently uninstalled. Future installation must retain native electronic invoice constraints; no production ZATCA submission status was assumed.
- baseer_purchase_batch protects approved rows from editing. Each row links move_id/payment_id and stores entered amounts and source information. A correction must update these links/current values and preserve the before/after audit; simply editing account.move would leave its batch stale. Other rows must remain unchanged.

## Recommended first delivery

One narrow correction flow for supplier bills, including approved purchase-batch rows, and simple manual cash/bank payments. Accountant/owner only, existing company permissions. No core edit, broad sudo, automatic refund or external bank action.

UI: تصحيح العملية → review editable current details → تأكيد التصحيح. Show original/correct supplier, actual bill lines/quantity/price/tax, correct payment journal and recorded amount if a payment exists, short reason. Default preserves payment values. Explicit option to correct the payment record too; never infer actual paid amount from invoice total. For the existing one-line gross-entry batch, expose its existing gross-inclusive amount and VAT choice. For multi-line invoices reuse native invoice lines; never overwrite amount_total or invent a balancing difference line.

Example: actual invoice500 and actual paid500, entered400 or600: invoice corrected to500; payment corrected to500 only if the accountant explicitly confirms its record was also mistaken. If actual paid400, keep400 and residual100; that is a real remaining amount, not an invented result of the input error.

## Execution rules

1. Read latest state, permissions, company and source links; lock affected records and detect changes made after preview. Reject duplicate confirmation. Validate eligibility before any writes.
2. For a simple editable record in an open period, use native reconciliation removal where necessary, native reset-to-draft, correct the selected fields, repost, and reconnect the existing payment to the corrected bill. Correct via account.payment for payment errors. No fictitious reverse cash flow. Native tax and currency calculations remain authoritative.
3. Keep the batch row, its totals/current links, native bill and payment consistent. Preserve original and corrected values, actor, time and reason. Do not reopen/reapprove the entire batch or regenerate other bills.
4. All changes occur in one database transaction. Any failure rolls everything back. No hidden callbacks to external payment services.
5. Initially exclude bank-statement-matched payments, shared payments spanning bills, reconciled credits/write-offs/complex currencies, closed or hash-locked periods, externally issued electronic invoices and documents with other operational links not covered by tests. Show the precise reason and navigate to the native accounting resolution. Never break another invoice's settlement silently. Native reversal/replacement can be added later after its accounting/reporting effects are separately proven.

## Critical acceptance on QA

- Actual500, erroneous400 and600; invoice-only and explicit invoice+payment corrections, unpaid/paid/partial cases.
- Cash↔bank journal error and wrong supplier, preserving actual money movement and correct payable allocation.
- Cash report after a same-period editable correction shows actual outgoing500, not artificial receipts400/outgoing900 from reversal plus repost. Cards and report must still match. Corrections across periods are not backdated automatically; period/accounting constraints govern eligibility.
- Batch displays500, correct supplier/payment method, unchanged neighboring rows and no duplicate invoices/payments. Multi-line and tax-inclusive totals follow native tax engine.
- Owner/accountant permissions and company isolation; cashier denied. Double-click/concurrent edit and induced failure produce no duplicate or partial correction.
- Native locked/statement/shared-payment exclusions fail before mutation. Audit before/after remains available.

After these pass: demonstrate on QA, then use approved frozen-source/backup/preservation publication process when user authorizes implementation and release. This plan does not implement the feature or assert the proposed combined workflow has been tested.

## Sources

- https://www.odoo.com/documentation/19.0/applications/finance/accounting/customer_invoices.html
- https://www.odoo.com/documentation/19.0/applications/finance/accounting/customer_invoices/credit_notes.html
- https://www.odoo.com/documentation/19.0/applications/finance/accounting/payments.html
- Local: odoo/addons/account/models/account_move.py (button_draft, _check_draftable, _reverse_moves); account_payment.py (action_draft/action_post); wizard/account_move_reversal.py (modify_moves).
- Local: custom_addons/baseer_purchase_batch/models/purchase_batch.py and baseer_access_roles/models/purchase_batch.py; odoo/addons/account_edi/models/account_move.py and l10n_sa_edi/models/account_move.py.
- Official search excerpts support the general workflows; full documentation page fetches timed out. Detailed behavior was checked against local Odoo19 code. No legal-compliance opinion or new accounting integration test is claimed.
