# HRS1 — Independent delivery review

Reviewer: services_accounting_advice. Date: 2026-09-08.

## Current decision

**GO — QA candidate HRS1 / 19.0.1.0.0, 2026-09-08.** The final decision below supersedes the chronological pending items in this report. G0–G4 design remains accepted under `HR-SERVICES-GATE-REVIEW.md`. This is acceptance of the installed/tested QA candidate only, not authorization to deploy or migrate production/main, and not a load-capacity certification.

Scope: `custom_addons/baseer_hr_services`, architecture `docs/architecture/registry/HR-SERVICES.md`, gate contract, and root-owned runtime/concurrency check scripts. No application or database changes by this reviewer. CSS1 accounting map and seed evidence are reused, not re-audited.

## Code findings so far

- Service belongs to the active company, has matching private provider and employee (including archived employees), uses the approved seeded HR service map and a validated expense account. The accounting bill is native `account.move`; there is no second ledger or payroll deduction.
- Approval requires HR manager and native invoice rights. A row lock and MVCC retry-compatible row touch serialize approval; reciprocal unique links constrain a service to one original bill. Repeated approval returns its existing bill. Posting and service linkage share a savepoint.
- RPC writes cannot supply service control fields or original bill links. The internal capability is an identity-checked Python object, not a caller-supplied Boolean. Bill and line financial editing/deletion/reset are guarded, with native payment/reconciliation and reversal intended to remain usable.
- HR financial projection reads only the linked bill and checks company equality. It exposes bill identity/state, payment state, residual, net/tax and existence of a posted refund. Invoice actions enforce native accounting ACLs; the existing employee financial page retains its payroll-manager parent restriction.
- Native `payment_state`, including `in_payment`, is displayed without replacing it with a residual-zero rule. A posted credit-note indicator makes a partial correction visible. The service workflow state is separate from payment state.
- Native list/form/kanban/chatter and existing date/money widgets are reused. Employee history lists are bounded to ten rows and general searches paginate. No new JavaScript or libraries were introduced.

## Items to resolve or demonstrate before GO

1. The reviewed form hides Cancel whenever a bill exists, although the backend supports cancellation after a native canceled bill or full reversal. Provide a native-visible route after a valid full reversal/cancellation, or explicitly document and accept the resulting approved-service/reversed-bill display. A partial refund must never enable cancellation.
2. Execute actual unpaid, partial, `in_payment`, paid, partial refund and full reversal scenarios. A zero payable residual while the payment is still in payment must retain `in_payment`. Ensure financial guards do not break the native reversal/reconciliation flow.
3. Exercise HR-only form fields (`net_amount`, `tax_amount`, hidden bill/map references) and paid/unpaid filters, not just two scalar summary fields. Confirm no access to invoice contents/attachments or payroll financial fields. Test HR manager without native accounting rights.
4. Exercise forged links/control/default/context values, company boundary, missing/invalid account/tax and locked period with rollback. Confirm protected bill lines cannot be moved into/out of the linked bill or appended by direct RPC.
5. Obtain actual two-connection approval evidence, all-or-nothing failure evidence, preservation proof, native Arabic/English/mobile views, and final matching source/package/deployment hashes.

## Evidence received at this checkpoint

Source inspection: `models/service.py`, `models/bill.py`, `models/employee.py`, ACL/rule XML/CSV, employee/service views, manifest. Root-owned `hr_services_checks.py` already covers basic approval, gross precision, VAT, company/forgery checks, archived employee, draft cancellation/deletion, partial/full payment, HR scalar summary permissions and rollback fingerprinting. `hr_services_concurrency.py` uses two actual database connections against a disposable clone and retries native serialization/deadlock errors. Script presence is not test execution evidence.

Capacity remains an assumption of 100 companies, 1,000 employees and 20,000 services/year; a two-connection correctness test does not certify five-user load or that full dataset. Tax entitlement, amortization and prepaid treatment remain outside this expense-only workflow. No production/main-database changes are approved by this review.

## Executed extended acceptance — 2026-09-08

At the lead's explicit request, this reviewer authored `hr_services_extended_checks.py` and executed it in QA. Consequently, these are reviewer-authored acceptance checks, not a claim that every test was independently authored by another team. Application implementation remained owned by the backend/UI workers. Root-owned main checks, concurrency and preservation evidence remain separate corroboration.

The first actual execution found an HR-only paid-filter AccessError: traversing `bill_id.payment_state` required account.move read rights. The worker replaced this with a bounded SQL subquery derived from the caller's service `_search`, preserving service record rules and company match; only the permitted invoice scalar is queried under elevated read. No general invoice ACL was granted. The final execution passes **35/35 assertions across six cases** with all fixtures rolled back and financial/HR/master fingerprints unchanged, in `hr_services_extended_checks.json`.

Confirmed: HR-only creates and updates a draft, reads full draft/approved form projection including net/tax and Many2one names, reads statement projection, filters paid/unpaid and positive/zero residual, and preserves False semantics for unbilled state searches. Invalid operators are rejected. The same HR user cannot read native invoice lines, open/pay the invoice, or read payroll history. HR manager without invoice rights cannot approve or create a bill. Partial native refund leaves 60 of 100 due, exposes the correction indicator and cannot cancel/delete the service. Full native reversal allows service cancellation but cannot reopen/delete its linked history. Arabic PDF actually renders from synthetic fixture data.

**Native-state limitation clarified:** this installed Community implementation's `account.move._get_invoice_in_payment_state()` returns `paid`. A real outstanding-payment-account fixture produces an unmatched payment but native invoice state `paid`; the service correctly reports that same state. No natural invoice `in_payment` transition was observed or simulated, and this review does not certify one. The source projects that native selection transparently if a future accounting extension supplies `in_payment`.

User steering adds an editable suggested service provider, without automatically changing VAT. This routine native default/onchange behavior requires a focused check after the worker completes it. Release decision still awaits that final delta, actual release evidence and matching package/deployment hashes.

### Provider suggestion amendment verified

The final extended run now passes **56/56 assertions across seven cases**, including the provider amendment. Confirmed all nine configured service/provider suggestions; normal default_get and missing-provider create; explicit provider/context preserved; user can edit the draft provider; onchange proposes the corresponding provider while preserving the VAT choice; unmapped ticket service leaves provider selection manual; company 6/10 isolation; archived providers not suggested. The run loaded current disk code in a fresh QA Odoo registry and rolled back all fixtures. No app-level automatic VAT change is introduced. Existing values and historical records are not rewritten.

The cancel button now allows the native full-reversal/canceled-bill state while excluding a partial correction; initial UI blocker item 1 is resolved in source. Final release still awaits candidate binding and remaining root evidence, rather than another full test run without a subsequent code change.

## Final delivery decision and bound evidence

**GO for QA review/use of HRS1 / 19.0.1.0.0. No outstanding P0/P1 defect identified in this review.**

The reviewer independently recomputed the ZIP SHA-256 and each of the 14 source-file hashes, compared each ZIP member, and read each file's SHA-256 from the running QA container mount. All matched the candidate manifest:

`16d1e1d9036ade36041d26fedbc8f9e4f6f682ef61be3412f20fc4d5ee8c065a`

Release binding: `docs/releases/2026-09-08-hr-services/candidate.json`, archive `baseer_hr_services-19.0.1.0.0.zip`, and `verified-package.json`. The latter confirms installation; hash agreement was not accepted solely from its Boolean but recomputed independently.

Actual evidence inspected:

- Root-owned basic acceptance: **71/71 passed**, native approval measured 0.457113 seconds in this QA run.
- Reviewer-authored extended acceptance: **56/56 passed**, seven cases, all fixtures rolled back. Authorship/independence limitation remains disclosed above.
- Root-owned race: **6/6 passed**, distinct PostgreSQL backend PIDs, one observed `40001` retry, both responses same original posted bill, no automatic payment. Times 0.6437/0.6128 seconds. Reviewer independently checked that the disposable race database no longer exists.
- `preservation.json`: original QA rows unchanged, main unchanged, no reported issues. This reviewer inspected the root's preservation result; did not independently rerun its full original-row comparison.
- Arabic native PDF was generated by the reviewer-authored runtime test. Reviewer visually inspected `hr_services_pdf_preview.png`: Arabic labels and shaping, Western amounts/dates, readable A4 layout and signature areas, with no clipping in the supplied preview. Root confirms the PDF is one A4 page. The logo shown is the QA company's existing placeholder.
- Lead reports actual desktop and 390×844 mobile native UI inspection, default Passports provider changing to HR Ministry for work permits, Arabic display, viewport restored, and the one UI-created synthetic draft deleted through native Odoo. These interactive checks are lead-observed, not a claim that this reviewer drove that browser session.

Financial and permission acceptance is limited to this company-paid expense workflow: one native supplier invoice; native payments/reversal; no new payroll deduction, prepaid asset amortization or second ledger. `in_payment` remains an unobserved transition in the installed Community configuration as documented above, and the UI reflects native `paid` accurately for that configuration. Do not describe that state as independent proof of bank clearance.

Documentation note (P2) closed on 2026-09-09: README now accurately describes draft/canceled deletion, cancellation after native full reversal, protected linked history, and native `paid` not independently proving bank matching. This is a README-only amendment; no runtime implementation changed. The reviewer independently rehashed the replacement ZIP and compared all 14 source/ZIP/container files again. The final hash above supersedes `e10ed445909376313adee78f0c29e34331500f2bc93bbe094604792ef0b52630`. Existing functional evidence remains applicable; a documentation-only correction does not warrant another financial test run. **QA GO remains in effect with no remaining review findings.**

No production/main deployment approval is granted here. The 100-company/20,000-service assumptions were not load-tested; the measured small QA fixture and two-connection race certify the exercised behavior only. Further implementation changes invalidate this exact candidate binding and require proportionate delta review.
