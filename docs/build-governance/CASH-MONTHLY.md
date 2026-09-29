# BASEER-CASH-3 — monthly cash categories

2026-09-07. User authorized implementation after choosing one company at a time to keep code simple. QA database only. G0–G3 pending independent gate review before application edits.

## G0: scope and financial workflow

Keep posted cash movements, proportional invoice allocation and evidenced VAT extraction from BASEER-CASH-2. Replace company multiselect with single-selection radio chips. Select 1–12 calendar months, including noncontiguous months. Display each selected month, selected-month total and outgoing percentage of collected sales. Preserve native source navigation and back state. One outer page scroll, compact mint appearance, matching compact PDF and canonical XLSX. No vendor edits, dependencies, posted-ledger edits, production install, or multi-company consolidation.

Percentage = absolute outgoing selected-basis amount / positive evidenced sales collections * 100, Decimal rounded to two places. Denominator includes only positive customer sales collections traced to out_invoice/out_receipt. Customer refunds stay explicit outgoing flows, not deducted again from denominator. Loans, capital, supplier refunds, unmatched cash and untraced POS are excluded from sales denominator; disclose this scope in the report. Zero denominator returns unavailable (not zero percent). VAT option affects both sides equally when tax is evidenced. User accepted collected-sales basis; this remains a QA management report, not a statutory cash-flow declaration.

## G1: bounds and continuity

One tester, single authorized SAR company, 1–12 unique months within a 24-month span, existing leaf 10k read/trace limits plus aggregate bounded budget. Maximum 1000 canonical rows for full DOM rendering; reject excess clearly rather than truncate financial data. No infrastructure load test on shared PostgreSQL. Record real bounded QA render latency and limits, not production capacity certification. Queries are read-only; restart/upgrade only reports_qa service. Existing backup and module rollback remain available.

## G2: data contract

Use validated baseer_months YYYY-MM list. Preserve legacy single-range leaf contract for regression and reuse Decimal allocation engine. Monthly aggregation must use exact numeric values (Decimal/string), never add binary floats. Unique canonical IDs; deterministic order; missing category/month cells zero. Monthly monetary columns have explicit period/company scope; total spans only selected months. Percentage is server-calculated, links to outgoing evidence. Revalidate requested expression and month, never accept caller-supplied source IDs. Balance columns show each month's opening/closing; total balance cells use no sum (null) to avoid adding snapshots. Selected-month movement total remains valid for gaps. No schema migration or new cache. Unknown/unsupported filters retain clear validation.

## G3: direct path and stack

Reuse installed Odoo 19/EH 19.0.1.8.1 native viewer, accessible inputs, folding, source actions and PDF/XLSX pipeline. Extend owned baseer_cash_categories only. Reuse local IBM Plex Arabic and existing mint tokens; no new UI library or animation. Native month input gathers month identifiers only, not financial calculations. Separate narrow report PDF action/paper format if needed, preserving original reports. Explicit PDF column panels for many months must repeat row descriptions and clearly identify the panel rather than shrink unreadably.

## G4 acceptance and ownership

Parent: contract, PDF adaptation, integration and QA tests. cash_handler: financial backend. report_contract: JS/XML/SCSS and translations. gate_review: independent gates and delivery. Existing Odoo buttons/input/selection tokens stay central; monthly selector is report-specific. Mobile stacks labeled month values per row when columns cannot fit; desktop uses table. No horizontal scrolling, keyboard/radio/month controls available; loading disables controls. Arabic/English, RTL/LTR, Western digits, existing report smoke checks. Tests cover disjoint months, denominator exclusions/zero, partial payments, VAT modes, month/total source actions, tampered column scope, company ACL, empty selection, bounds, exact monthly sums, exports and UI back state.
