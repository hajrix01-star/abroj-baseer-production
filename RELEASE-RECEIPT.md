# Release receipt — Baseer heat-calendar target editor

**Freeze date:** 2026-09-14

**Production source baseline:** `863bd851dc107ba8911b417263f21b83270701f0`

**Immutable release tag:** `heat-calendar-targets-live-candidate-2026-09-14.1`

**Included module update:** `baseer_sales_heat_calendar 19.0.1.0.8`.

This release contains only the heat-calendar target-editor change relative to
the live cashier-release baseline. A manager can select all or selected
months and weekdays, fill up to 84 explicit month × weekday cells, then
adjust each cell independently in one atomic save. The server is the source
of truth for exact decimal validation, company scope, stale-write detection,
and duplicate prevention. The calendar refreshes after a successful save.

It preserves the approved daily POS-sales summary as a read-only source. It
does not add a schema migration, dependency, external integration, target
wildcards, or accounting, invoice, payment, stock, payroll, HR, occasion, or
sales-summary writes. The cashier-procurement change remains the deployed
baseline and is not reintroduced or altered by this release.

The payload hash is SHA-256 over sorted records of
`relative-path + NUL + SHA-256(file-content) + newline`, excluding this
receipt itself. The final value is recorded in the external release manifest
after the frozen commit is created. The archive SHA-256 is also recorded
outside the archive to avoid a self-referential checksum.

This candidate deliberately excludes database dumps, filestores, `.env`,
production `odoo.conf`, local sessions, compiled Python artifacts, Noorix
source material, and every rehearsal-only file.

Images remain pinned in `compose.production.yaml`:

- Odoo: `odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`
- PostgreSQL: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`
