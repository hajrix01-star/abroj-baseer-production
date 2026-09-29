# WS4 native QA evidence

2026-09-09. Test owner: schedule_edit_tests. Database restricted by assertions to `baseer_reports_qa_20260907`, company 10. No MAIN access, service upgrade, service stop, or production fixture writes performed by this test owner. Root upgraded QA before execution. Both scripts compile with the bundled Python runtime.

## Results

- `ws4_checks.py` / `ws4_checks.json`: **61/61 passed**, `rolled_back=true`. Includes public action/default form creation, same-name revision and visibility, effective native versions, unchanged historical version date/calendar/payroll inputs, byte-identical source attendance/actual attendance/approved leave/resource leave rows, native historical payroll hours, global-holiday-only copying, archived and actual private-copy exclusion, unrelated identical-name template exclusion, idempotency, stale forms, dates, metadata/context forgery, edit scope tampering, manager and company isolation, whole-edit rejection on attendance/leave/future-version conflicts, and inclusive salary month-boundary guard.
- Fifty active directly assigned fixture employees: one atomic apply **0.7181 seconds**, all 50 received exactly one new dated version. This is isolated local QA timing, not production throughput certification. A source with **201 inactive candidates** rejected before any partial revision/fanout, confirming the limit counts candidates beyond visible active employees.
- `ws4_concurrency.py` / `ws4_concurrency.json`: **72/72 passed**, `cleaned_up=true`. Eight independent native REPEATABLE READ races: simultaneous template edits; native version membership create, calendar write, unlink, date change, active/archive change, and wage write winning against a stale template form; and template edit winning against an incoming native assignment. Every contender waited on a real PostgreSQL advisory/transaction lock, encountered `SerializationFailure`, retried once, and rejected the stale form or superseded source. Fresh forms after membership commits selected the correct population; fresh wage fanout copied the committed wage.
- Functional fixture writes rolled back. Concurrency holders committed only uniquely tagged fixture records; contenders rolled back; exact-tag native ORM cleanup removed all committed employees, versions, calendars, and wizards. Logs: `ws4-checks.log` and `ws4-concurrency.log` (ignored runtime files).

## Evidence hashes (SHA256)

| Artifact | SHA256 |
|---|---|
| ws4_checks.py | 952457C02710007458AB5ED041C51770561D94897DFFEBB82FB423514735ED1F |
| ws4_checks.json | 979EEFAAE4FF0B2241A321C2636585C82BBE9AC5D848D4F946A88EFC9B2DE203 |
| ws4_concurrency.py | 8EBC8EA3D7E48DBC84B3F15A23D6CE511B3747E13648DCEE36DDFA0212E23437 |
| ws4_concurrency.json | 58849F98B730B53E8FE2401C780FF3DEE9AB0F22E8F06D0AD09D5620FEF8E82A |

Runtime command: pipe each script into `docker compose -f compose.yaml -f compose.reports-qa.yaml run --rm --no-deps -T reports_qa odoo shell --config=/etc/odoo/odoo.local.conf --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 --database=baseer_reports_qa_20260907 --no-http --max-cron-threads=0`. Scripts ran sequentially. Root owns WS1 regressions, browser verification, deployment and independent delivery approval.
