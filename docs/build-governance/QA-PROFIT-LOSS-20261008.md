# P&L bounded QA release — 2026-10-08

- Owner authorized completing the report work through QA. Production is excluded.
- Source PR #230 reviewed head: `b23cd693ad1c5682d6dc4cf50da2aaf6a3790fb1`.
- Squash merge source: `e501bd423d05176c9a42bd6b150f4bd0e3ce8783`.
- Independent alpha-delivery reviewer `reports_release_review_oct8`: GO for limited individual QA testing; not production or complete suite acceptance.
- Backend run [37776010733](https://github.com/hajrix01-star/abroj-baseer-production/actions/runs/37776010733): 14 tests, zero failures/errors.
- Desktop/mobile Hoot run [37776010767](https://github.com/hajrix01-star/abroj-baseer-production/actions/runs/37776010767): passed, including stale request regression, Arabic/English and source drilldown.
- Source integrity run [37776010893](https://github.com/hajrix01-star/abroj-baseer-production/actions/runs/37776010893): passed.
- Diagnostic capacity run [37775538896](https://github.com/hajrix01-star/abroj-baseer-production/actions/runs/37775538896): 100k lines/5k accounts, non-superuser; first report 2.6486 seconds, peak RSS 518.5 MiB. Backend unchanged since that run. Concurrent readers skipped due memory guard, not certified.
- QA allowlist: only `baseer_profit_loss_report`; existing `baseer_reports_menu` dependency. Wrapper installs absent module or upgrades installed module, takes its prescribed recovery pair, and verifies installed state. No accounting data migration or production change.
- Remaining acceptance: live QA source/module/menu and visual check; thousands separators are a known P2; A4/PDF, TB/BS bridge and concurrent capacity are not complete. Excel explicitly deferred by owner.
- Publication: use reviewed policy `baseer-2026-10-08-profit-loss` and official QA workflow. Queue success alone is not deployment proof. Runtime confirmation remains pending.
