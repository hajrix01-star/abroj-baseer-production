# Baseer purchase-and-expense dashboard refit — build governance

> Live record. This file is append-only after its first entry. It contains no credentials or customer-level document detail.

## Build contract

- **Goal:** make the published `فواتير الموردين والمصروفات` dashboard visually consistent with Baseer dashboards while retaining its read-only accounting contract.
- **Users:** owner and authorised accounting users of the active company.
- **In scope:** full-width dashboard shell; Baseer-style coloured KPI cards; an accessible, legible monthly movement chart; supplier amounts and each supplier's cost-to-sales percentage; a purchase/expense-category section with amount and cost-to-sales percentage; loading, error, empty, Arabic/English, RTL/LTR, desktop and mobile states.
- **Out of scope:** creation, approval, posting, cancellation, editing or deletion of bills, payments, POS summaries, accounting entries, products, suppliers, categories or dashboard access; changes to taxes, currency policy, or historical source rows; new third-party UI libraries; AI; changes to the standard Odoo dashboard engine outside the existing integration seam.
- **Acceptance:** all displayed money and ratios are calculated in the backend using `Decimal`, are exact-company and selected-period scoped, use only posted source documents, and show Western digits. The user can see a complete visual dashboard at desktop and a two-column/one-column responsive hierarchy on mobile without horizontal scrolling. The source-bills action and access controls remain unchanged.
- **Direct-path decision:** retain the existing `baseer_purchase_expense_dashboard` module, `spreadsheet.dashboard` integration and server RPC. Extend its one read-only payload and replace only its local OWL template/SCSS; do not introduce a dashboard framework, a client calculation layer, or a new dependency.

## ERP cycle and control map (G0)

| Area | Authoritative source | Allowed dashboard behaviour | Control retained |
| --- | --- | --- | --- |
| Purchases and expenses | Posted native `account.move` supplier invoices/refunds, exact active company, selected invoice-date period | Read and aggregate only | No document write, normal accounting access/rules and active-company scope remain enforced |
| Paid and outstanding values | Posted native invoice totals/residuals in company currency | Read and aggregate only | Existing reconciliation/payment process remains the authority |
| Sales denominator | Approved daily POS sales aggregate for the exact active company and selected period | Read one aggregate only | The dashboard does not create or amend sales summaries; absence/zero is surfaced rather than dividing |
| Supplier and category ratios | Backend division of net cost by approved sales; no client recalculation | Display `—` when sales denominator is zero or unavailable | Ratios are analytical indicators, not accounting postings or a profitability assertion |

**Assumption requiring verification before build:** “نسبة من المبيعات” means `net posted supplier-bill/expense amount ÷ approved gross POS sales for the same company and selected period`, not a supplier's share of purchasing. The visible Arabic label will state this definition explicitly.

## G1 — capacity and continuity profile

| Item | Assumption / current bounded design | Target / safeguard |
| --- | --- | --- |
| Critical read | Open/refresh dashboard for a 1–366 day period | One bounded RPC, target under 2 seconds for normal company history; record measured local result before delivery |
| Data growth | Posted vendor invoices/refunds and daily POS reports grow indefinitely | Date/company/state domains; grouped aggregates only; suppliers/categories limited to top 10 with an explicit remainder where applicable |
| Concurrent users | Conservative 10 concurrent accounting/owner dashboard readers per company | Read-only request; no cache/queue needed before evidence |
| Writes/concurrency | None in this feature | Existing source workflows own atomic writes; dashboard is no-write |
| Continuity | Existing production release snapshots and rollback route | Source-only rollback; no schema migration or data transformation planned |
| Observability | Existing Odoo error logs plus measured RPC test | Validate bounded range, empty/zero denominator, and no source writes in focused tests |

## G2 — data and contract proposal

`get_baseer_supplier_bill_metrics(filters)` remains the sole RPC and returns a version-compatible extension of its present payload.

- Money: `Decimal` in server, quantised once to the company currency rounding; payload returns server-formatted display and canonical string value.
- Ratios: `Decimal(net_cost) * 100 / Decimal(approved_sales)`, two decimals, never calculated in OWL. A zero/missing sales denominator returns a null ratio/display `—` and an explanatory status, not `0%`.
- Supplier rows: top ten net supplier totals from posted same-currency vendor invoices/refunds; each row includes `amount`, `sales_ratio`, and a stable partner id/name. Refunds reduce the net amount.
- Category rows: top ten native product categories from the same posted invoice product lines. Their amount is the signed gross line total in the company currency (the same gross basis as the posted bill header and approved gross sales denominator); include the same amount/ratio contract and an explicit unclassified bucket when source category is absent. The batch-category map is not used because it excludes native supplier bills created outside that workflow.
- Sales denominator: one approved daily POS aggregate for `company_id`, inclusive tax and the exact inclusive date range; it must use the existing approved-sales owner API rather than reading browser-side values or duplicating source logic.
- Access: preserve `_baseer_purchase_assert_access()` and never return document identifiers/lines beyond the existing aggregate view.

## G3 — technology and dependencies

| Decision | Alternatives considered | Decision and reason |
| --- | --- | --- |
| UI layer | New chart/UI package; dashboard rewrite; current OWL/SCSS | Keep Odoo OWL + existing dashboard integration and CSS. It is already installed, supports the current Odoo version/RTL, and avoids dependency/license/size risk. |
| Chart | New library; CSS/SVG using existing payload | Use an accessible local semantic/SVG or CSS chart only if it is required by the existing Baseer dashboard design. No new package. |
| Data | Client joins/calculation; new table/cache; existing read RPC | Extend the server RPC with bounded grouped queries. It preserves one numeric authority and needs no migration/cache. |

## G4 — experience system contract

- Reuse Odoo/Baseer dashboard page shell and date filter. The custom content must fill the normal dashboard canvas rather than render as a narrow independent panel.
- Reuse named local design primitives where available: dashboard header, primary/secondary button style, `KPI` card, `Chart` wrapper, `DataTable`/compact list, date filter, alert/empty state and number formatter. Do not copy generic styles into a second private system.
- KPI colours communicate a defined metric state only: total cost = primary purple, paid = success green, outstanding = warning amber, document count = information blue. Do not colour amounts arbitrarily.
- Monthly chart uses a clear axis/labels/tooltip or accessible equivalent, a labelled zero state, and no decorative motion. Actions get only existing Odoo feedback; no added animation is justified for this frequent operational dashboard.
- Desktop: four KPI cards in one row, movement and suppliers/categories in balanced responsive sections. Mobile: two KPI cards per row then one column for chart/tables; buttons wrap without horizontal scroll; numerical cells retain LTR isolation.
- Arabic and English labels are translatable; labels state `نسبة من المبيعات المعتمدة` / `Share of approved sales`.

## Gate register

| Gate | Status | Owner | Independent reviewer | Evidence / next condition |
| --- | --- | --- | --- | --- |
| G0 | Draft | قائد البناء | حارس البوابات | Contract and ERP control map above; await independent review of ratio intent and scope |
| G1 | Draft | مهندس السعة | كبير معماريي البناء | Bounded 366-day profile above; await source/query review |
| G2 | Draft | معماري البناء + خبير ERP | مهندس السعة | Existing RPC/source ownership inspection in progress |
| G3 | Draft | أمين المكتبات | خبير الواجهات | No new dependency proposal; confirm existing OWL route is sufficient |
| G4 | Draft | مصمم التجربة + بنّاء الواجهة | حارس الجودة | Existing dashboard design audit in progress |
| G5–G8 | Not started | — | — | Blocked until G0–G4 approval |

## Decision log

| ID | Decision | Reason | Status |
| --- | --- | --- | --- |
| PED-001 | Refit the existing dashboard module instead of adding a dashboard | Same data owner and route; avoids duplicate access/data logic | Proposed |
| PED-002 | Use approved POS sales as the denominator for requested ratios | Matches the requested “من المبيعات”; must be verified against existing approved-sales API | Proposed |
| PED-003 | Do not add a UI/chart library | Existing Odoo OWL/SCSS path is sufficient and lowest risk | Proposed |
| PED-004 | Use native invoice-line product categories and signed gross line totals | Covers posted supplier bills regardless of entry path and gives a consistent gross cost-to-gross approved-sales ratio; unclassified lines remain visible | Proposed |

## Operations log

| ID | Time (Asia/Riyadh) | Gate | Type | Intent/result | Impact and rollback | Owner / review |
| --- | --- | --- | --- | --- | --- | --- |
| PED-001 | 2026-09-15 | G0–G4 | Read + design contract | User requested a professional refit: coloured cards, clear monthly movement, supplier and category cost-to-sales ratios. Current live dashboard and heat calendar were visually inspected; purchase view is a separate narrow custom panel. This governance record was created before application code. | Documentation only; no app/data change. Remove this new record to revert documentation if needed. | قائد البناء / pending |
| PED-002 | 2026-09-15 | G1–G4 | Independent review | The metrics and design reviewers inspected the current RPC, current sales aggregate, purchase batch category mapping, sales dashboard shell and responsive patterns. They confirmed a bounded exact-company/back-end route, rejected a new library and rejected using batch-only categories. They also identified the existing monthly N+1 aggregation as a replacement target. | Documentation only; no app/data change. | فريق ألفا / pending gatekeeper |

## Contract clarification — PED-005 (append-only)

The independent gate review found that the proposed gross basis and an assumed approved-sales API were not an approved implementation contract. This entry supersedes only those unresolved metric details in the earlier proposal; it does not alter the published accounting sources.

- **Ratio basis:** every supplier and category ratio is `net posted supplier cost before VAT ÷ net approved POS sales before VAT` for the same active company and the same inclusive selected dates. This avoids mixing a VAT-inclusive cost numerator with a net sales denominator. The visible label is `نسبة من صافي المبيعات المعتمدة قبل الضريبة` / `Share of net approved sales before tax`.
- **Existing KPI basis:** the four headline cards and monthly movement remain the existing posted invoice/refund gross, company-currency accounting view. Their labels will explicitly say `شاملة الضريبة` where relevant. They are not used as ratio numerators.
- **Supplier numerator:** `account.move.amount_untaxed_signed`, inverted to the displayed vendor-bill sign, grouped by commercial partner. Posted vendor refunds reduce a supplier’s total; negative net results remain negative.
- **Category numerator:** product lines from posted, same-currency supplier invoices/refunds only, grouped by the native product category. `account.move.line.balance` is the company-currency, pre-tax signed value; a missing product/category is grouped as `غير مصنف`. Tax, payment-term and display-only lines are excluded. The displayed category amount is explicitly labelled pre-tax and may therefore differ from the gross headline total.
- **Sales denominator and access:** there is no reusable approved-sales API for an accounting user. The dashboard will add one narrow, internal aggregate path after `_baseer_purchase_assert_access()` succeeds: it reads only the same-company/date range’s approved `baseer.pos.summary.amount_net` values, returns only the aggregate decimal/status (no sales record ids, customer data or navigation action), and is used only to calculate the already requested ratios. This is intentional, documented analytical access for an authorised owner/accounting dashboard user; it grants neither POS browsing nor write access. A missing or zero denominator returns `—` and a visible explanation.
- **Currency:** the existing same-company currency exclusion is retained for headline, supplier and category aggregates. A source warning remains visible when foreign-currency bills are excluded.
- **Query plan:** one header grouped read for KPIs, one month-grouped header read for the entire period, one supplier grouped header read limited to the top ten plus optional remainder, one category grouped line read limited to the top ten plus optional remainder, and one bounded approved-POS aggregate. No monthly loop, client arithmetic, document reads in the browser or source writes.

## Gate decision update — PED-006 (append-only)

| Gate | Decision | Evidence and mandatory implementation check |
| --- | --- | --- |
| G0 | GO | Exact-company, posted-only accounting sources remain authoritative. The limited POS aggregate is an explicitly authorised analytical read; no workflow/data mutation is introduced. |
| G1 | GO | The selected 1–366 day range and five aggregate reads are bounded. The current monthly per-month loop is removed. Delivery must measure the focused RPC and retain the current partial header index unless evidence calls for a new index. |
| G2 | GO with implementation tests | The corrected net-before-tax ratio contract, `غير مصنف` bucket, refunds, zero denominator and narrow sales access are defined. Tests must prove all of them, including an accountant without general POS access. |
| G3 | GO | Existing Odoo OWL, CSS and installed Baseer chart route are reused; no package, license, migration or cache table is added. |
| G4 | GO with responsive visual acceptance | The refit stays inside `baseer_purchase_expense_dashboard`, reuses the established sales-dashboard shell/KPI/chart/list patterns, carries an HTML table/text fallback for the chart values, maintains RTL/LTR and fits 390/360px without horizontal scrolling. |

## Implementation map — PED-007 (append-only)

| Surface | Planned responsibility |
| --- | --- |
| `custom_addons/baseer_purchase_expense_dashboard/models/dashboard.py` | One read-only payload: headline gross cards, grouped monthly series, net supplier/category ratios, bounded approved POS net-sales aggregate and access/empty/currency statuses. |
| `custom_addons/baseer_purchase_expense_dashboard/static/src/purchase_expense_dashboard.js` | Request/render the extended payload, format accessible chart data, destroy/rebuild the existing local chart safely, never calculate money or ratios. |
| `custom_addons/baseer_purchase_expense_dashboard/static/src/purchase_expense_dashboard.xml` | Use the familiar Baseer dashboard shell, semantic KPI/list/table/chart states, translated labels and clear metric-basis labels. |
| `custom_addons/baseer_purchase_expense_dashboard/static/src/purchase_expense_dashboard.scss` | Reuse the sales-dashboard visual grammar locally: full canvas, balanced grids, coloured semantic KPI cards, responsive 2-up mobile cards, no scroll trap. |
| `custom_addons/baseer_purchase_expense_dashboard/tests/test_dashboard.py` | Prove posted/company/currency bounds, bill/refund and zero sales, supplier/category/unclassified values, accounting-only access to the bounded sales aggregate, no write, and grouped-query behaviour. |

| PED-005 | Use net-before-tax costs and net approved sales for all requested ratios | It is the consistent analytical basis; headline gross totals stay available but are not mixed into ratios | Approved |
| PED-006 | Add a bounded aggregate-only approved POS read behind the existing purchase dashboard authorization | The accounting audience needs the requested ratio without POS browse/write permission | Approved |
| PED-007 | Use native invoice-line product categories with an explicit unclassified bucket | It covers native supplier bills and does not rely on the batch-only mapping | Approved |

| PED-003 | 2026-09-15 | G0–G4 | Gate resolution | The gatekeeper rejected the assumed generic sales API and gross/net ambiguity. The contract was corrected to a documented aggregate-only, authorisation-checked net-sales read, with net supplier/category cost ratios and a no-data state. Gates G0/G1/G3 are approved; G2/G4 are approved subject to focused backend and responsive visual checks. | Documentation only; application code has not yet changed. | قائد البناء / حارس البوابات |

## Capacity and rule-safety correction — PED-008 (append-only)

- The original five-read estimate omitted the existing foreign-currency warning and dashboard document count. The implementation combines the document count into the headline aggregate, leaving **six bounded aggregate reads**: headline/count, foreign-currency warning, approved POS net-sales denominator, secured monthly movement, secured suppliers and secured product categories. All are selected-period, exact-company reads; no calendar-month loop exists.
- The first implementation used direct SQL predicates after an ACL check. Independent review correctly rejected that because an ACL is not a record-rule filter. The monthly and category SQL now consume the `account.move._search()` / `account.move.line._search()` secured ORM subquery as their `id IN (...)` source. That carries Odoo’s caller ACL and record-rule domain into the grouped query. The direct SQL only groups records that the user can already read; it does not substitute a company predicate for record rules.
- Focused tests now include a posted native bill, refund and product-less expense line, prove category and unclassified amounts/ratios, and assert one database query for category grouping and one for month grouping. This is the explicit no-N+1 evidence for those two formerly looping sections.

| PED-008 | Correct the query budget and make grouped SQL inherit Odoo record rules | Independent G5 review caught both the inaccurate read count and raw-SQL rule bypass before release | Approved pending rerun |

| PED-004 | 2026-09-15 | G5–G6 | Independent review and correction | The first G5/G6 review returned NO-GO: direct grouped SQL bypassed record rules, category coverage was not proven, the ratio label omitted its pre-tax basis, and query evidence was missing. The secured-subquery correction, label correction and focused native data/query-count test were applied before re-review. | Candidate code and tests only; no production data or release changed. Roll back by restoring the prior module source. | قائد البناء / مراجعة مستقلة pending |

## Candidate verification — PED-009 (append-only)

- Focused Odoo test run completed with **0 failed / 0 errors** (six dashboard tests; eight test records including inherited setup) after the secured-query correction.
- The full read-only dashboard payload over an inclusive 366-day range completed in **43.4 ms** inside the candidate Odoo server, below the G6 target of one second. This is a candidate measurement, not a production load claim.
- Independent re-review returned **Conditional GO**: access isolation, query bounds and metric implementation are accepted. The remaining release condition is an authenticated visual acceptance at 1280px and 390/360px; the local runner cannot reuse the user’s authenticated application-browser session. No production deployment is authorised by this record.

| PED-009 | 2026-09-15 | G5–G6 | Focused candidate verification | Security/query tests are green and the complete 366-day server payload is within target; visual acceptance remains a release gate. | Test database only; no production deployment or data mutation. | قائد البناء / مراجعة مستقلة Conditional GO |

## Metric-basis revision — PED-010 (append-only)

The user requested a single VAT-inclusive basis for every purchase-dashboard number, including top suppliers, product categories and purchase-to-sales percentages. This supersedes the net-ratio-only part of PED-005 while retaining the same company, date, currency, posted-document and access boundaries.

- Supplier totals now use signed `account.move.amount_total_signed` (vendor-bill display sign preserved), including tax and refunds.
- Product category totals use each secured native product line's signed accounting balance scaled by `price_total / price_subtotal`; this allocates that line's tax to its category while preserving refunds. Product-less lines remain in `Unclassified`; display lines remain excluded.
- The sole denominator is the existing bounded, aggregate-only `baseer.pos.summary.amount_gross` for approved sales in the exact company and period. The dashboard exposes no POS documents or navigation.
- The table header, ratio explanation and unavailable state explicitly state the inclusive-tax basis. The heading continues to state that all displayed amounts include tax.
- Focused Odoo tests were rerun after this revision with **0 failed / 0 errors**, including a posted invoice, a refund and an unclassified expense line (`92.00` gross category value and `46.00%` against `200.00` gross sales).

| PED-010 | 2026-09-15 | G2 | Approved metric revision | User-selected gross/VAT-inclusive basis is applied consistently to cards, movement, suppliers, categories and ratio denominator; no permission or scope expansion. | Candidate code and test database only; revert the candidate commit to restore the prior net-ratio contract. | قائد البناء / focused test green |
