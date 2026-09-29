# HRS1 — Independent G0–G3 accounting and ERP review

Date: 2026-09-08. Scope: `HR-SERVICES-BUILD.md`, completing the employee-services workflow on QA. Reviewer owns this document only; implementation and tests belong to other agents. No app or database edits were made by this review.

## Decision

**G0 GO / G1 GO / G2 GO / G3 GO** under the confirmed clarifications below. These are design gates authorizing the planned implementation, not release approval or confirmation that the workflow has passed runtime tests.

The direct path is appropriate: a small HR service record references one native supplier bill, and native payment/reconciliation remains the financial authority. No separate ledger, tax engine, supplier entity, payroll deduction engine or payment workflow is justified.

## Evidence reviewed

- `HR-SERVICES-BUILD.md` — user-authorized scope, QA target, capacity and native implementation contract.
- CSS1 approved catalog and its 15 HR service leaves, reused from `baseer_service_seed` (utilities/platform subscriptions are outside employee-service selection).
- `baseer_purchase_batch/models/purchase_batch.py` — SAR ownership boundary, Decimal input validation, native_quote, and validated expense product/category mapping.
- `baseer_payroll/models/financial_record.py` and `views/settlement_views.xml` — current financial-record page and fields restricted to `om_hr_payroll.group_hr_payroll_manager`.
- Native `odoo/addons/account/models/account_move.py` — payment-state computation distinguishes `in_payment`, `paid`, `partial`, and `reversed`; residual alone does not express all of these states.

## Gates

| Gate | Result and rationale |
|---|---|
| G0 | GO. General HR register and employee services show the same records. Draft → approve/post one bill → native payment. Company-borne expense only; no automatically generated employee debt, salary deduction or prepaid amortization. QA only. |
| G1 | GO. Explicit assumptions:100 companies,1000 employees,20000 services/year,5 concurrent users. Indexed and paginated native lists, bounded per-employee access. Measure one approval below3 seconds and an isolated two-caller approval race; do not label this a measured five-user/annual-volume certification. |
| G2 | GO. Immutable company, same-company references, unique invoice link, row lock, native bill/payment authority, private internal guard, scoped HR permissions and narrowly limited financial summary projection. Corrected cancellation and state semantics below are mandatory. |
| G3 | GO. New addon extends the existing HR, CSS1, payroll page and native accounting APIs. Existing native views, date widget and translations; no additional libraries or JS. Financial calculation stays server-side with Decimal validation and native Odoo tax boundaries. |

## Confirmed contract and financial controls

### Ownership and service input

- Company defaults from the active company and cannot be switched on an existing service. Create rejects an explicitly mismatched company rather than silently assigning another company. SAR is the existing seed/map compatibility boundary.
- Employee and private provider belong to the service company. Archived employees are permitted for final/historical administrative services, using `active_test=False` without reactivating them. This does not authorize another company's employee or vendor.
- Selection is limited to the15 seeded HR services with a valid active expense mapping. OTHER requires descriptive notes. Visa is one product with issue/extend exit-and-return detail; no final-exit product.
- Service date, invoice date, optional expiry, notes and attachments are administrative metadata. Expired historical documents may be recorded; an expiry before issuance/service must receive clear validation where the date represents the same service validity period.
- Supplier invoice reference is optional. A service sequence/description supplies traceability when no external reference exists. Do not impose a meaningless required reference field or invent a tax invoice number.
- Money validation rejects booleans, non-finite/negative/zero values, and more than2 decimal places. VAT switch selects only the active company's principal valid15% purchase VAT. Disabled VAT creates an untaxed invoice line; a blank vendor VAT is not a declaration of exemption.

### Approval and exactly one financial document

- Approval requires HR manager rights plus the native accounting rights required to create and post the vendor bill. No sudo financial action.
- Read/check access before locking the service row; re-read bill link after lock. The SQL unique bill link prevents two services sharing the same bill; a repeat approval of one service returns its existing linked bill rather than creating another.
- Bill creation, posting and immutable service link are atomic. Any accounting validation/lock-date error leaves no partial bill/service transition. Use active purchase journal and account/product/tax references from the same company.
- Protect bill_id, approval/control fields and financial computed values against RPC create/write. Internal context authorization is an unforgeable process object, not a Boolean/string that the caller can submit.
- Existing invoice amounts and posting state are authoritative after approval. A reset-to-draft/edit through native accounting must not leave a service presenting stale values as an approved original. Enforce the agreed reversal-only correction path for linked bill financial content/deletion, or explicitly surface a review state and derive amounts from the changed native bill without auto-creating a replacement. Validate this boundary before release.

### States, payment and cancellation

- Project native `payment_state`, including `in_payment`; do not label residual=0 as paid when the native state still says in payment. Residual is a separate amount, not an alternative payment-state engine.
- Native payment register handles partial/full payment and bank/cash methods under native ACLs. No service method marks a record paid, fabricates a bank settlement or sudo-posts a payment.
- Draft cancellation/deletion is allowed only **before any bill link exists**. A service with a bill link does not become editable/deletable merely because its bill is later reset to draft.
- Financial cancellation uses native bill cancellation or a completed full reversal recognized by native state. `reversed_entry_id` existence or a partial credit note alone is insufficient to label the service fully canceled. Preserve the original bill and service history.
- Archiving retains history; renewing later must not overwrite a previous paid service's amount or invoice. This approval does not expand scope into an unrequested renewal engine beyond the agreed service record workflow.

### HR visibility and restricted financial summary

- HR readers may see the cost, status and remaining amount **of services they can already read** within allowed companies, even without general invoice access. This is an intentional business permission for the HR register.
- **G2 GO for a narrow compute_sudo projection** of the linked bill's amount/currency/payment state/residual, after verifying bill.company_id equals service.company_id. It must not search unrelated invoices, expand the recordset, expose invoice lines, supplier invoice attachments, payroll details or execute accounting actions.
- Service bill link/control fields remain immutable. Bill opening and payment actions enforce native account ACLs; a readable HR summary does not grant invoice access. Do not globally broaden account.move or employee payroll record rules.
- Employee Services is a separate HR-visible page. The existing financial-record page remains payroll-manager restricted; adding service information there does not widen access to salaries/loans/EOS.
- Listing/chatter attachments inherit service ACLs. Vendor bill attachments remain governed by their own ACLs. Service record attachments deliberately added by HR are not a reason to expose unrelated bill attachments.

## Required acceptance scenarios

1. HR user creates/edits own-company draft and reads approved service summary without invoice privileges; cannot approve/pay/open restricted invoice. HR manager without accounting rights cannot post. Authorized HR/accounting manager can approve.
2. Reject cross-company employee/provider/category/bill, forged protected fields and forged internal-context flags. Reject access through disallowed companies, including summary projection.
3. Archived same-company employee works without reactivation; non-SAR and invalid/missing service maps fail clearly.
4. Gross-only and VAT15 cases, Decimal precision edges, disabled/misconfigured VAT, native invoice gross/tax equivalence, journal/account company ownership and locked-period failure.
5. Double approval sequentially and via two genuine database connections creates exactly one posted bill. Failed posting rolls back all changes. No duplicate financial entry at service save.
6. Native unpaid/partial/in_payment/paid projection, with payable reconciliation and bank/cash differences; zero residual with in_payment must not appear paid.
7. Partial refund remains distinct from full cancellation; full reversal/canceled bill follows the agreed native state. Reset linked bill to draft does not reopen/delete the service or silently present stale approved values.
8. Draft with no bill can be canceled/deleted. Approved/canceled-with-bill service preserves links/history and may be archived, not erased.
9. HR page and general menu share the same record; payroll financial-page restrictions remain unchanged. Paginated employee/history views avoid loading every company service.
10. Existing financial and HR records preserved, no payroll deductions or prepaid entries introduced, QA-only tests and disposable race clone cleaned up. Match the final candidate hash to deployed/tested files before G8.

## Not certified by this review

No test execution or data change occurred in these gate checks. Receipt of a supplier service is not a legal/tax determination; annual insurance may require a prepaid treatment outside this expense-only workflow. No claim is made that100 companies or20000 annual records were load-tested. A separate independent delivery review must decide G8 from actual implementation and evidence.

## G4 — Native Odoo experience accepted

**G4 GO for the proposed native form/list/kanban/chatter design.** General HR list and employee tab open the same service record. The15 HR service choices, service data and amounts are grouped clearly; visa subtype appears only for Visas and OTHER notes remain required. Native kanban supports small screens, and native form/list controls provide standard keyboard and touch behavior without another UI library or new JavaScript.

Arabic and English strings/errors use Odoo translation. Existing approved date/monetary widgets and Western digits are reused, with RTL/LTR behavior verified at acceptance. The UI displays server-authoritative totals and the approved limited invoice summary; it does not compute a competing financial state or hide native in_payment as paid.

Approve, invoice, payment, cancel, archive and delete actions must reflect their actual server-side rights/state rules; invisible buttons alone do not supply authorization. The HR Services page uses HR rights, while the existing financial page keeps payroll-manager restrictions. Reuse native components and layouts rather than introducing a new design system. Final G8 still requires actual Arabic/English views, mobile/desktop journey evidence and matching tested candidate files.
