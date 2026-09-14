# Release receipt — Baseer cashier procurement operations

**Freeze date:** 2026-09-14

**Production source baseline:** `4cd12588a2b447cb14f924f09c913b4fb7b24f43`

**Immutable release tag:** `cashier-procurement-live-candidate-2026-09-14.2`

**Included modules:** `baseer_access_roles 19.0.1.0.3` and
`baseer_procurement_requests 19.0.11.0.2`.

This payload contains only the cashier-procurement permission change on the
actual deployed source. A cashier can create, send, and operationally receive
raw-material requests in the active company. Server-side guards reject
cross-active-company request mutation, including direct ORM attempts to
reassign a draft request to another allowed company.

It does not include later heat-calendar target-editor changes, a database
schema migration, a data migration, vendor-bill authority, payment authority,
custody access, settlement access, or accounting-entry authority.

The payload hash is SHA-256 over sorted records of
`relative-path + NUL + SHA-256(file-content) + newline`, excluding this
receipt itself. It is
`3fae2bb1d54d5695dbb5be2d84036d173996eb735c02507e12b68cb5a857132f` over
875 tracked files. The release archive SHA-256 is recorded alongside the
immutable tag in the external release manifest, because placing an archive's
own checksum inside that archive would be self-referential.

This candidate deliberately excludes database dumps, filestores, `.env`,
production `odoo.conf`, local sessions, compiled Python artifacts, Noorix
source material, and every rehearsal-only file.

Images remain pinned in `compose.production.yaml`:

- Odoo: `odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`
- PostgreSQL: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`
