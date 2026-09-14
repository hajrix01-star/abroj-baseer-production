# Release receipt — Abroj/Baseer heat-calendar candidate

**Freeze date:** 2026-09-14  
**Payload source commit:** `9bfb75fc3e62d83c064406ad78a03fd9fe8233ed`  
**Immutable release tag:** `heat-calendar-candidate-2026-09-14.2`  
**Payload hash:** `E5DD600A413C68FF84F69B6270E27C1FE5E3CB7F8208138CFC69EC0CDDF08A4A`

The payload hash is SHA-256 over sorted records of
`relative-path + NUL + SHA-256(file-content) + newline`, excluding this
receipt itself. It covers `871` tracked files (`42,294,958` bytes).

The tag names the commit that contains this receipt. The release archive
SHA-256 is recorded alongside the uploaded archive in the external release
evidence, because placing an archive's own checksum inside that archive would
make the checksum self-referential.

This candidate deliberately excludes all database dumps, filestores, `.env`,
production `odoo.conf`, local sessions, compiled Python artifacts, Noorix
source material, and every rehearsal-only file.

Images are pinned in `compose.production.yaml`:

- Odoo: `odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`
- PostgreSQL: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`
