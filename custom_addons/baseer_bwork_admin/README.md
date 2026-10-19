# BWork Administration

Optional Odoo19 native console, depending only on `baseer_bchat`. Installation
does not assign roles, seed policies, install financial dependencies or add
cron/hooks. The existing effective room administrator (base.user_admin plus the
existing manager group/permission) is required. Superuser report calls are
rejected. Warning configuration additionally requires `base.group_system`.
Native transient housekeeping has one private exception: its fixed own-console
ID selection preserves Odoo's age floor/clock/batch bound, followed by sudo
unlink of expired derived UI records only. Sudo reads/searches/reports/config
remain denied; policies, rooms, messages and linked files are never deleted.

Select currently enabled, authorized companies (maximum10). Metadata pages
default to80, maximum200. A snapshot has one shared100000 source-row budget,
including distinct attachment references. Exceeding it returns
`status=limit_exceeded`, `complete=false`, `totals=null`, never sampled totals.
Missing attachment metadata similarly returns `integrity_error` without totals.
Responses are capped at1MiB.

Storage uses distinct attachment `file_size` metadata per company, not filestore
or disk scanning. Originals and thumbnails are shown separately; their combined
logical total is deduplicated, so the separate categories need not add to it.
All linked files are preserved. A company warning threshold defaults to0
(disabled); it neither blocks uploads nor deletes data. Existing staged24h
cleanup is unchanged. Cron schedules do not prove successful runs; provider
delivery/readiness is not asserted. No tokens, content, arbitrary errors or
service-account configuration are returned.

Local contract checks (no Odoo evidence):

```text
python -m unittest discover -s custom_addons/baseer_bchat/tests_contract -p test_bwork_admin_contract.py -v
python -m compileall -q custom_addons/baseer_bwork_admin
```

Actual ORM/HTTP tests run only in the disposable pinned-image workflow
`.github/workflows/test-bwork-admin.yml` (exact16tests, zero skipped). Local
compilation/contracts do not establish installed Odoo, QA or real FCM delivery.
