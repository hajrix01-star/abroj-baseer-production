# Owner app ordering

Scope: local menu presentation only, baseer_web_navigation 19.0.1.1.1.
Order: Dashboards, Point of Sale, Sales, Purchase, Invoicing, Inventory, Google Business, Google Ads, Employee Followup, POS Suite. Remaining visible apps keep their native relative order.
Implementation wraps native menu service getApps, sorts a copied list by XML identity, preserves all secured menu objects and prior service filters; no new dependencies, menus, database writes, access grants or company changes.
Native Odoo 19 menu service inspected from current QA; existing project-costing filter composes with ordering regardless of patch order. Missing applications are skipped, not installed or synthesized.
Validation: node custom_addons/baseer_web_navigation/tests/test_app_order.mjs; syntax checks; git diff check. No new environment/load test justified by this presentation-only difference. Deployment not yet claimed.
