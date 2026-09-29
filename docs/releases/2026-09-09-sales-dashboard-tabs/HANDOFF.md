# SD3 — Sales dashboard tabs

Candidate: `60fe49fe3907eaa0985f70fa3ec428ab512a559d`, module `baseer_sales_dashboard 19.0.1.1.1`, parent SD2 `973395f87b62c8d09f1e6fdc301a7d89e2988d56`.

Two equal desktop cards show shift performance and payment-method sales. Each opens on Chart view and switches independently to Details in the same card. The payment table has three columns; category totals appear in a compact footer after Period details. Four permanent explanation paragraphs were removed; conditional incomplete-data warnings and the illustrative-empty label remain.

Category amounts are grouped with Decimal from existing validated method allocations. They sum to covered sales, without a new query, schema, source policy, or accounting posting change. All 1106 files outside the dashboard addon are byte-identical; the candidate contains 1118 files and seven changed addon files.

Validation: 14 backend checks and 11 UI checks passed; fixtures rolled back. Actual Arabic QA browser confirms adjacent cards, both tab directions, recreated chart canvases, shift customer metric, removed category column and explanations, and category totals. August category values 40,960.73 + 74,502.65 + 73,332.12 equal 188,795.50. March–August demo KPIs remain 935,779.00 sales / 15,282 customers / 5,085.76 daily sales / 83.05 daily customers / 61.23 average bill.

Responsive rules have focused source checks. The current browser viewport override did not resize the live tab (973px actual width), so this delta does not claim a new 390px browser verification; qa-mobile.png is not mobile evidence. Desktop cards and tables have no horizontal overflow. Shared native integration files are unchanged.

QA preview: http://localhost:18070/odoo/dashboards?dashboard_id=9 . MAIN: http://127.0.0.1:18069/odoo/dashboards?dashboard_id=8 . Synthetic six-month data stays in QA only. See browser-evidence.json, qa-charts.png, qa-details.png and focused test evidence. Deployment closure is recorded below after protected publication.

Published to MAIN after independent PREDEPLOY-GO. Runtime verifies installed 19.0.1.1.1, immutable candidate mounts, HTTP 200 and zero pending module operations. All 367 protected business tables retain exact prior columns and rows. Coherent pre-release and post-release backups each verified 651 attachment files. Actual MAIN Arabic dashboard ID8 shows both default Chart tabs and honest empty states. Evidence: runtime.json, main-preservation.json, main-backup.json, post-release-backup.json, main-browser.txt, main-dashboard.png. Independent closure: FINAL-REVIEW.md.
