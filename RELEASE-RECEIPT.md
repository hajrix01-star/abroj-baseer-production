# Release receipt — Abroj/Baseer production source

**Date:** 2026-09-14  
**Payload hash:** `E34F1F34297D27AF9D4752B855A13ECAF58CB515CE036D71E9821E5E74D39646`

The payload hash is SHA-256 over sorted records of
`relative-path + NUL + SHA-256(file-content) + newline`, excluding this
receipt itself. It covers `853` files (`42,190,183` bytes): `23` Baseer/Abroj
addons and `5` third-party addon manifests required by the installed database.

It deliberately excludes all database dumps, filestores, `.env`, production
`odoo.conf`, local sessions, compiled Python artifacts, Noorix source material,
and every Noorix rehearsal addon.

Images are pinned in `compose.production.yaml`:

- Odoo: `odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`
- PostgreSQL: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`
