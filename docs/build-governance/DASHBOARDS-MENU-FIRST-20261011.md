# Dashboards menu first — QA

Owner authorization: publish menu ordering to QA only.
Frozen source: PR #294, 7d6f4e5ba5de5b44e44bcbb271b38f677f536bab.
Scope: baseer_sales_dashboard 19.0.1.5.1; native dashboard root sequence 37 -> 0, before Discuss (5). No action, parent, groups, or financial changes.
Existing evidence: Source 38161069506 PASS; Odoo 38161069623 PASS; XML assertions and diff check PASS. No repeated environment/load tests warranted.
Capacity preflight: 2,540,503,040 bytes available; no backup deletion needed.
Release acceptance: independent review, protected QA request, server result.env and upgrade log, native menu order and preserved metadata. Production excluded.
