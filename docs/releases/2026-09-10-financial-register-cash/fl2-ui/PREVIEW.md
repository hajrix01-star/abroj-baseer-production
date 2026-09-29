# FL2 — QA cash view

QA-only experiment, 2026-09-10. User requires a small native extension, with no Odoo core, posting-engine or duplicate financial-data changes.

Open http://127.0.0.1:18074/odoo/action-825, select «الحركات النقدية», company «المعلم الشامي», February 2026. Same KPI area becomes receipts 8,000.00 SAR, signed payments -5,000.00 SAR and net 3,000.00 SAR. Native rows show the two contributing entries. Clicking payments narrows both cards and rows to the one 5,000 payment. Native source navigation opens its original balanced entry. Returning to All restores invoice cards and removes cash month. The native header's selected companies are restored through Odoo 19 user.activeCompanies.

The intentional QA demo also contains a draft, cancelled entry and internal transfer; none inflates the reference report totals. These data exist only in baseer_ar1_roles_20260910. Focused accounting fixtures in the separate clean database roll back fully.

Scope: one active authorized SAR company, calendar month, VAT-inclusive movements. Additional native facets narrow both cards and rows. The existing cash report supplies final signed allocations; its security, tracing and transfer rules remain authoritative. No new cash computation engine or stored transaction model.

Evidence: ../fl2-cash-checks.json (63 focused checks, rollback/module preservation), frontend-checks.json (13 UI logic checks), Arabic desktop/filter/return/source snapshots and 480px native kanban. Mobile document width is480 with no page overflow. No large-ledger/concurrent capacity claim.

MAIN remains frozen FL1 at0a6246b7215caddf9e7b14ffe799f84ee03f8cd3; GitHub remains de47b3f1fdc36a628580290c2ac6b9a55796f82d. FL2 working addon19.0.1.1.0 is not published or approved for production.
