# Release receipt — Abroj/Baseer heat-calendar targets candidate

**Freeze date:** 2026-09-14
**Functional source commit:** `bef712075f4fb8fd192d5d2b009364f418f5456a`
**Immutable release tag:** `heat-calendar-targets-candidate-2026-09-14.3`

This delivery replaces the former generic weekday and wildcard target setup
with exact target scopes: one company, Gregorian year, month, and named
weekday. It includes the manager-only setup dialog, Arabic and English labels,
automatic calendar refresh after saving, and server-enforced company scope.

The delivery archive SHA-256 is recorded in the release evidence outside this
file, because embedding an archive's own checksum would be self-referential.
The immutable Git tag is the authoritative link between this receipt, the
source revision, verification output, and the published archive.

This candidate deliberately excludes all database dumps, filestores, `.env`,
production `odoo.conf`, local sessions, compiled Python artifacts, Noorix
source material, and every rehearsal-only file.

Images are pinned in `compose.production.yaml`:

- Odoo: `odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`
- PostgreSQL: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`
