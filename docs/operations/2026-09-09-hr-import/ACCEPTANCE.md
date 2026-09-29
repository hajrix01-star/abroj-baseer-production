# HR1 independent acceptance — GO

Names-only migration to MAIN `baseer_dev`, reviewed 2026-09-09.

- Authorized names-only scope, current staff active and former staff archived; two explicit historical merges retain all 51 source XML IDs across 49 employees.
- Source-company/name/status/employee-number mapping independently compared offline; salary, allowance, contract and actual shift migration excluded.
- Native required calendar satisfied by three company-isolated pending flexible calendars, zero daily/weekly hours and no attendance/holiday lines; existing calendar rows unchanged and exact new-calendar allowlist asserted.
- Real ORM rollback passed: 49 employees, 51 identities, 34 active / 15 archived, 152 protected tables or baseline calendar rows unchanged; Administrator preserved; second pass creates nothing.
- Native salary_simulation context skips avatars/onboarding and unrelated leave-manager/work-entry/public-holiday timesheet hooks for bare new profiles; normal model validation retained.
- Nine coherent-backup artifact hashes independently verified; 644 attachment references recorded verified. This backup has not undergone a fresh full database restore.
- GO authorizes the exact reviewed names-only commit. Post-commit reconciliation and user-visible verification remain required; no production commit performed by reviewer.

| Company | Active | Archived |
|---|---:|---:|
| ARZ | 13 | 12 |
| المعلم الشامي | 15 | 3 |
| دوحة المستهلك | 6 | 0 |

Exact writer SHA256: `69874545a922c19ff1c1f925d636394ba0c3daa2522b68ddbfee4288af233b3c`

Exact payload SHA256: `7c31b0e1b8d20b6e7a9f5a66828d1682bf0a3d5f94edd9cfe004554d7ed2d9e8`

Review performed through local source/evidence reads and independent file/hash/mapping comparisons; reviewer made no source or target database writes.
