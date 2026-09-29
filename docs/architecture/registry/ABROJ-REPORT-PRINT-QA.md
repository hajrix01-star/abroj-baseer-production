# ABROJ-REPORT-PRINT-1 — QA print layout (2026-09-29)

Scope: `baseer_document_theme` 19.0.2.0.6 and `abroj_project_costing` 19.0.1.4.8, QA only. No payment, accounting, sequence, or source-data logic changed.

The receipt delegates to Odoo's `account.report_payment_receipt_document`; its project appendix is styled only when `o._name == 'abroj.cost.receipt'`. If the project stores a customer name without a partner record, the receipt prints that name without changing master data. The project report still uses `web.external_layout`, with `o` and `company` explicitly bound to the printed project. Both use the selected company's document layout.

The Baseer Boxed header previously lost styles when wkhtmltopdf extracted it into a separate document. Its font and layout are now self-contained; the shared body no longer adds a second top offset. IBM Plex Sans Arabic Regular/Bold is bundled with its OFL license in `baseer_document_theme`. Both report actions reserve 42 mm for the header. The project KPI and detail groups use fixed-width tables instead of unsupported CSS Grid, with multiple fields per row.

Verification: XML parsing and focused QWeb/company-layout tests passed on an isolated QA database clone. After the QA module upgrade and Odoo restart, the existing receipt and project report each generated a one-page A4 PDF. Visual inspection confirmed the company logo/name, clear header separator, compact body tables, and footer. The QA samples have no study or actual-cost line rows, so dense populated-table pagination remains unverified.

Rollback: the pre-change module archive and QA database dump are in `/srv/abroj-baseer-production/qa/clean-20260928/.backups/report-layout-20260929-01/`. Production/Live was not changed. This QA result is not a production release approval.
