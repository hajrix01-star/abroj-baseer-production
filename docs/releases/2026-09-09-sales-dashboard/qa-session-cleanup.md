# QA session cleanup

2026-09-09: Removed the 24 SD1 reporting fixtures using their exact recorded IDs; see `qa-cleanup.json`. Existing business/ledger rows matched before and after cleanup.

Removed temporary QA user156 (sd1.preview@example.invalid) and its partner1258 through Odoo ORM after checking both IDs and login. Removed `.local-backups/sales-dashboard-20260909/ui-auth.private.json`. Closed the task-owned QA browser tab, reset the preview viewport, and stopped `baseer_odoo_dev-reports_qa-1`. Existing user tabs were preserved. No testing rows or users were created in MAIN.
