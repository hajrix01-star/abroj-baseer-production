# Procurement Operations Dashboard — Build Record

**Status:** G0–G4 review in progress.  This record is append-only.

## Build contract

### Objective

Provide a read-only **Procurement Operations** dashboard for Odoo Community that
helps a procurement manager act on `baseer.procurement.request` workflow work.
It is a separate operational view, not an accounting, vendor-bill, payment, or
ZATCA dashboard.

### Users and boundary

| User | May use the dashboard | Scope |
| --- | --- | --- |
| Procurement manager | Yes | Requests readable under existing company record rules. |
| Procurement cashier | Yes | Requests readable under existing company record rules. |
| Procurement requester | No in v1 | Continue using the request workflow; no management aggregate is exposed. |
| Procurement accountant / finance | No new access | Uses the existing separate **Supplier bills and expenses** dashboard. |

The endpoint must use the caller's normal ORM access and record rules.  It must
not use `sudo()` or a broader company context.  All source-record navigation
continues through the existing request action and its access rules.

### In scope (v1)

* Counts of non-cancelled requests by their authoritative workflow state.
* A bounded, actionable queue of the most recent **pending** requests only
  (`draft`, `sent`, and `received`).
* A request-cohort trend by `request_date`, plus a distinct completion trend
  by `actual_confirmed_at`, and dimensions by warehouse and purchase route.
* Date filtering and active-company filtering supplied by the dashboard shell.
* Arabic and English labels through Odoo translations; server-provided western
  numeric strings.

### Explicitly out of scope

* Creating, editing, approving, receiving, or cancelling procurement requests.
* Vendor bills, refunds, payments, petty cash, custody, settlement, journal
  entries, stock valuation, or supplier balances.
* Any data write to accounting records or any ZATCA integration/configuration.
* A combined amount that could double-count requests, bills, or payments.
* A derived “late” measure until the source model provides an authoritative due
  or promised date.

### Acceptance criteria

1. A manager or cashier sees only records allowed by the existing
   `company_id in company_ids` rules; a requester receives no new dashboard.
2. The dashboard shows the four non-cancelled workflow meanings exactly: **Draft**,
   **Sent for purchase**, **Cashier receipt confirmed**, and **Quantity receipt
   completed**.  The completed state is an outcome, never a pending-action
   count or queue entry.  Cancelled requests are excluded from all measures.
3. Every card and queue uses `baseer.procurement.request` only and identifies
   a request-cohort date dimension as `request_date` and a completion date
   dimension as `actual_confirmed_at`; no financial metric is labelled as
   payment, expense, supplier liability, or proof of invoice posting.
4. The data API is read-only, verifies the published dashboard and a manager or
   cashier role server-side, rejects unsupported filters, returns a bounded
   payload, and is exercised by role, company-isolation, and zero-data tests.
5. No changes are made to `account.move`, ZATCA modules, fiscal data,
   procurement transitions, or request line values.  Existing supplier-bill
   dashboard access remains unchanged.

## ERP truth map

```
Draft request
  -> Sent for purchase
  -> Cashier receipt confirmed
  -> Quantity receipt completed
  -> optional stock picking

Separate financial path (not read by this dashboard):
vendor bill / refund -> payment / settlement -> accounting and ZATCA controls
```

The authoritative source definitions are the `state`, `request_date`,
`manager_received_at`, `actual_confirmed_at`, `company_id`, `warehouse_id`, and
`purchase_route` fields on `baseer.procurement.request`.  `picking_id` is
context only and is not an accounting source.

## Proposed implementation

Create a small module named `baseer_procurement_operations_dashboard` that
depends on `baseer_procurement_requests`, `spreadsheet_dashboard`, and
`baseer_sales_dashboard`.  The explicit final dependency is deliberate:
`baseer_sales_dashboard` owns the existing `baseer_dashboard_kind` dashboard
contract, native date-filter integration, and DashboardLoader field extension.
The new module will add only its own `procurement_operations` kind and local
component, without changing the sales, heat-calendar, or financial kinds.  It
owns:

* a published dashboard record in the native **Logistics** dashboard group,
  visible only to Procurement manager and Procurement cashier;
* a narrowly-scoped `spreadsheet.dashboard` read-only metric method;
* dashboard presentation assets which reuse the native dashboard shell; and
* tests for authorization, company isolation, payload contract, and zero data.

Keeping it separate from the transaction module avoids coupling procurement
workflow changes to dashboard presentation and keeps the financial dashboard
independent.  No new database model or third-party frontend library is planned.

## Data and capacity contract

The API will accept only a strict native date filter of at most 366 days,
constrain every aggregate, detail row, and navigation action to the active
company and accessible records, and cap the pending action queue at 20 requests.
The request-cohort and completion timelines are capped at one point per day
(366 points); warehouse and route breakdowns are capped at six named rows plus
an `Other` row.  It will use grouped ORM aggregates rather than fetching all
request lines.  Initial design target: 50 concurrent dashboard readers, 10,000
requests per year, and 100,000 request lines; the dashboard does not aggregate
lines in v1.  We will inspect the generated query plan against a QA-like volume
before release if the QA data volume makes that meaningful.

## Gate log

| Gate | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| G0 | Objective, users, source of truth, exclusion of financial/ZATCA scope | Approved | Accounting review and lifecycle clarifications below. |
| G1 | Secure module boundary and data contract | Approved | Separate add-on; explicit owner dependency; no `sudo`; server role/dashboard/company checks. |
| G2 | Multi-company, authorization, payload and numeric correctness | Approved | 366-day/point, 20 queue, 6+Other dimension limits; test plan below. |
| G3 | Dependency/capacity and upgrade impact | Approved | Reuses native dashboard integration; no new third-party library or schema model. |
| G4 | Native, accessible, bilingual UI design | Approved | Native shell; no animation; loading/error/empty states and 390px AR/EN verification. |
| G5 | Implementation and targeted automated tests | Passed locally | Isolated Odoo 19 test run: 4 tests, 0 failed, 0 errors. |
| G6 | QA deploy and release evidence | Not started | — |

## 2026-11-06 — Discovery evidence

* `baseer.procurement.request.state` is indexed and its states are `draft`,
  `sent`, `received`, `purchased`, and `cancel`.
* `action_send_purchase()` advances a request to `sent`; manager receipt moves
  it to `received`; actual quantity confirmation creates the optional picking
  and moves it to `purchased`.
* `purchased` confirms quantity receipt, not vendor-bill posting or payment;
  it is therefore an operational outcome only.

## 2026-11-06 — Accounting review

Accounting review: **G0 GO; G2 conditional GO after the clarifications above.**
The dashboard must keep completed requests out of the action queue, use
`actual_confirmed_at` for completion timing, and never infer invoice posting or
payment from a completed request.  The clarifications were incorporated before
implementation.

## 2026-11-06 — Architecture review and gate closure

Architecture review required bounded timelines/dimensions and an explicit
dependency on the owner of the current dashboard-kind and loader contract.
The limits and dependency are incorporated above.  The reviewer approved the
native UI direction provided that it retains loading, error, and empty states,
uses native detail navigation, and is verified at 390px in Arabic and English.
With those controls, G1–G4 are approved for implementation.

## 2026-11-06 — G5 implementation evidence

Implemented `baseer_procurement_operations_dashboard` as a separate read-only
add-on with no accounting, payment, invoice, custody, stock valuation, or ZATCA
writes.  Its secure endpoint checks the published dashboard, role, active
company, ORM ACLs, and existing request record rules before producing bounded
aggregates.

An isolated Odoo 19.0 test database ran
`ProcurementOperationsDashboardCase`: **4 tests, 0 failed, 0 errors**.  The
tests cover state semantics and pending queue exclusion, active-company
isolation, no-write behavior, requester denial, invalid/oversized filters, and
payload bounds.  The JavaScript files also passed `node --check`, and
`git diff --check` passed.  The Arabic PO was parsed by Odoo's `PoFileReader`
with 37 importable entries.
* Existing request record rules restrict source records to allowed companies.
* The existing **Supplier bills and expenses** dashboard is separately located
  in the Finance dashboard group and is restricted to accounting/owner roles.
