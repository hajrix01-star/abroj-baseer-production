# Evidence — cashier procurement live release

Collected by read-only checks after cutover; no credentials, configuration
values, or customer data are included.

**UTC:** `2026-09-14T19:10:12Z`  
**Active release:** `863bd85`  
**Immutable tag:** `cashier-procurement-live-candidate-2026-09-14.2`

| Check | Evidence |
|---|---|
| Candidate archive SHA-256 | `a387ccbdc764e1a9e0bae90d8fae53456181fd47af290a7e94bab797182e89fa` |
| Database recovery dump SHA-256 | `33e864fc72cfd8900f3dd2a9706a8c2018691d93c2e5e2830c700732af9a204d` |
| Filestore recovery archive SHA-256 | `206894c9fd6c46e5901bb29bc175fc563a2b863fa2be01ec2eb80715eda09fac` |
| Protected snapshot before upgrade | `10ecaaedc2a8f54f6cae76102b534553c1fc82d611e8c9c11b36c4751431b9a4` |
| Protected snapshot after upgrade | `10ecaaedc2a8f54f6cae76102b534553c1fc82d611e8c9c11b36c4751431b9a4` |
| Snapshot comparison | Identical |
| Public login | `https://baseer.abroj.sa/web/login` → HTTP `200` |
| PostgreSQL service | Running and healthy |
| Odoo service | Running |

## Installed modules

```text
baseer_access_roles|installed|19.0.1.0.3
baseer_procurement_requests|installed|19.0.11.0.2
```

The recovery pair is held on the production host under the release backup ID
`cashier-procurement-20260914T190650Z`. It is not copied into this repository.
