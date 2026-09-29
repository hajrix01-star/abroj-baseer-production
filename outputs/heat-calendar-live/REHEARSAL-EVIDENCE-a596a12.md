# Evidence — isolated Hostinger rehearsal a596a12

- Candidate tag: `heat-calendar-candidate-2026-09-14.2`
- Candidate commit: `a596a12eb31021b114ea2833cfde1cd691b06460`
- Isolated project: `baseer-odoo-heat-rehearsal-a596a12`
- Isolated database: `baseer_heat_rehearsal_a596a12`
- Loopback-only port: `127.0.0.1:18188`
- Production was read only. Its fresh rehearsal DB snapshot was created at `2026-09-14T14:29:26Z`, SHA-256 `a3c56ba71c0598f0ce4d6a0defe96a6210ac446383bee60390036a1796b5f5b2`.

## Results

- Module install and HC-T01–HC-T04: 0 failed / 0 errors; see [module test log](evidence-a596a12/module-tests.log).
- Four discovered companies passed the RPC: SHAMI TAX (54), المعلم الشامي (2), دوحة المستهلك (3), ARZ (1); dashboard ID was discovered as 9, not configured statically.
- Cross-company access was denied for a manager, a system user and a limited POS user. The manager could create and delete a target inside their own company.
- Protected business-data snapshot matched before/after: moves 8,558; move lines 21,207; payments 4,192; employees 50; payslips 0; business contacts 338; POS daily reports 0.
- Warm RPC p95 across the four companies: 0.0456s, 0.0455s, 0.0482s, 0.0596s (all below the 2s threshold). Twenty authenticated concurrent readers: p95 0.337s, all 20 completed.

Raw, non-secret evidence is retained in [evidence-a596a12](evidence-a596a12). The rehearsal is separate from the live project and remains available only pending the independent final delivery decision.
