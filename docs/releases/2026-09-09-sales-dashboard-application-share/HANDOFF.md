# SD4 — Applications share in payment details

Adds one row: Applications share of total sales (%), with Arabic translation, under the payment Details totals. The server sums validated allocations across all categories whose kind is platform and divides by total approved sales in the selected company/period. It returns a formatted Decimal percentage; the browser only displays it.

Complete coverage and positive sales with no applications show0.00%. Missing or mismatched allocations, no sales or zero total show an em dash; no misleading partial ratio. No new query, database field, dependency, accounting posting or layout change. Parent is SD3 commit60fe49fe3907eaa0985f70fa3ec428ab512a559d; module version19.0.1.1.2.

Example:600 /4447 ×100 =13.49%. This is a share of recorded sales, not a commission or platform settlement rate. Existing bank/platform accounting policy is unchanged.

QA: http://localhost:18070/odoo/dashboards?dashboard_id=9 . MAIN: http://127.0.0.1:18069/odoo/dashboards?dashboard_id=8 . See focused checks, browser evidence and candidate-bound independent review. Deployment evidence will be appended after publication.
Focused backend9/9 PASS with complete rollback. QA Arabic Details displays13.49% for600/4447, with no card overflow at actual973px viewport. A later observed native Year2026 selection displays38.89% on1,182,614.40 covered sales; the page was concurrently steered, so this is an observed selected-period result, not an automated Last Month test. No further browser filter changes were attempted.
Published candidate1108f2a8fc0edee2f61d728135feee02590a8f46 after independent G8 GO. Installed19.0.1.1.2, frozen1118files with1113unchanged and5dashboard-only changes. All367protected business tables exact before/after. Coherent pre/post backups verified651attachments each. ActualMAIN empty period displays the new ratio as an em dash, without a misleading percent. Evidence: main-preservation.json, runtime.json, main-backup.json, post-release-backup.json, main-browser.txt, FINAL-REVIEW.md.
