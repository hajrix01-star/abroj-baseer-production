# Evidence — isolated Hostinger rehearsal 52e9ff5

- Candidate tag: `heat-calendar-candidate-2026-09-14.3`
- Candidate commit: `52e9ff5415a3956a478ff369825f689a7fc27711`
- Verified archive SHA-256: `9BE4C6AE1FD7957E29D28BABBFB98AD28D0C9F00AA7E0792720E28574B3E97D7`
- Verified payload SHA-256: `5C56DF0AC57B153197ACFE51AB2F559868E02D27F339AF971071098B3B63041C` across 871 files / 41,984,982 bytes.
- GitHub release: [heat-calendar-candidate-2026-09-14.3](https://github.com/hajrix01-star/abroj-baseer-production/releases/tag/heat-calendar-candidate-2026-09-14.3).
- Isolated project: `baseer-odoo-heat-rehearsal-52e9ff5`; database: `baseer_heat_rehearsal_52e9ff5`; loopback-only port: `127.0.0.1:18189`.
- Fresh source snapshot: `2026-09-14T14:50:48Z`, SHA-256 `1f94eb90d81f0cb3e5cda652d4f63a5998d37690a3379c015d317dbc37eb3535`.
- Filestore verification: 640 files in production source and 640 in the rehearsal destination, both with manifest `46d7ea5715173ee5592f6934af76da91ec06418407b32d63a72cef47db2e222c`.

Production was read only to create the snapshot and filestore copy. No production service, source, database, user membership, or business record was modified.

## Results

- The pre- and post-install protected snapshots are byte-for-byte identical: 8,558 moves, 21,207 move lines, 4,192 payments, 50 employees, 0 payslips, 338 business contacts, and 0 POS daily reports. See [snapshots](evidence-52e9ff5).
- One-off installation and HC-T01–HC-T04: 0 failed / 0 errors of 4 tests; see [module test log](evidence-52e9ff5/module-tests.log).
- All discovered companies passed the dashboard RPC: SHAMI TAX (54), المعلم الشامي (2), دوحة المستهلك (3), and ARZ (1). The dashboard ID (9) was discovered from the rehearsal database, not configured statically.
- A single-company manager and system user were denied cross-company target access; a limited POS user was denied cross-company dashboard access; the manager could create and remove a target inside their own company.
- Warm RPC p95: SHAMI TAX 0.0444s; المعلم الشامي 0.0459s; دوحة المستهلك 0.0393s; ARZ 0.0409s — all below the 2s criterion. Twenty concurrent authenticated readers completed; p95 was 0.3134s.
- Cold evidence contains five fresh-process samples for each company (20 total). End-to-end p95/max: SHAMI TAX 0.7531s; المعلم الشامي 0.9234s; دوحة المستهلك 0.8864s; ARZ 0.9323s — all below the 4s criterion.
- `EXPLAIN (ANALYZE, BUFFERS)` for the real source summary and closure predicates used Index Scan; execution times were 0.043ms and 0.009ms respectively. See [query evidence](evidence-52e9ff5/explain-aggregate.txt).
- The Arabic management forms were visually verified without saving data: see [Arabic UI proof](evidence-52e9ff5/UI-ARABIC-PROOF.md). Candidate `.3` changes only its release receipt from `.2`; the UI payload is identical and is independently byte-verified.
- The corrected runbook was validated with its explicit `POSTGRES_DB` injection inside the Odoo container; it resolved to the isolated DB and returned the same protected snapshot. See [runbook check](evidence-52e9ff5/runbook-db-env-snapshot.json).

Raw non-secret evidence is retained in [evidence-52e9ff5](evidence-52e9ff5). This proves a candidate rehearsal only; it is not a production cutover and does not itself declare GO.
