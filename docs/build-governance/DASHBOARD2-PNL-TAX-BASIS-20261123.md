# Dashboard 2 profit and loss tax basis — 2026-11-23

## G0: scope and accounting contract

Provide a tax-inclusive default and tax-exclusive switch for the Dashboard 2 profit and loss table. Apply the selected basis to displayed account groups, subtotals, period comparisons, drilldown and export. Preserve source entries, invoice/EDI data, company isolation and record rules. Totals must reconcile by company, period and ledger scope to the Baseer profit and loss report; existing dashboard account classification remains visible, including the independently established SAR 49 operating-classification difference for Shami. Do not claim payment-channel parity: dashboard allocation is proportional while Baseer retains unallocated amounts.

## G1: capacity and acceptance

Existing owner uses several companies and monthly reports; simultaneous usage is unknown. Start with a single user and Shami November 2026 on the approved isolated QA, compare before/after latency and amounts; do not claim concurrency capacity. No synthetic load is warranted without a demonstrated new risk and usage volume.

## G2: source and controls

The existing Baseer profit and loss engine provides verified posted-line tax allocation, Noorix evidence and ambiguity failures. The dashboard gross helper has different allocation semantics and cannot alone prove equality. Design a request-scoped backend calculation with Decimal and existing access checks; classify verified account amounts by dashboard categories. For all-company selection scope each company separately, fail closed when access or attribution cannot be proved, and never share financial caches across users. Propagate tax basis to comparisons, details and CSV or visibly reject unsupported combinations until implemented. Independently review exact implementation and reconcile mixed/zero tax, refunds, Noorix, POS, multi-company, permissions and period comparisons.

## G3: direct route

Retain Odoo 19, the existing OWL UI and report controls, with no new dependencies or schema migrations. Reuse the existing report calculation rather than creating a parallel tax formula. Arabic/English, RTL/LTR, narrow screen, stable monetary formatting and accessible state are acceptance conditions. Baseline: QA Shami November, tax-exclusive revenue 176792.30, gross profit 174190.49, net profit 159875.15; operating result differs by 49 due to classification, not tax. The QA server has limited disk space, so protected release checks and recovery evidence are mandatory.

G0–G3 were reviewed independently by accounting/source and architecture investigators before implementation. G4–G8 and production release remain pending.
