# Production cutover evidence — heat calendar 52e9ff5

- Deployed candidate: `heat-calendar-candidate-2026-09-14.3` at `52e9ff5415a3956a478ff369825f689a7fc27711`.
- Live source: `/srv/abroj-baseer-production/releases/52e9ff5`.
- Verified release archive SHA-256: `9BE4C6AE1FD7957E29D28BABBFB98AD28D0C9F00AA7E0792720E28574B3E97D7`.
- Fresh recovery pair was taken while Odoo was stopped at `2026-09-14T15:12:47Z`:
  - DB dump SHA-256: `c0142e70fcff4818b1e80e489b1403b85361c36d7b12f4a54e55b63e5c082349`
  - Filestore archive SHA-256: `38e58306d2d11f20c8fca52c59fc5329f352120b00abad8a118249eb1a4c3c52`
- The targeted `-i baseer_sales_heat_calendar` completed before the `current` symlink changed.
- Protected snapshots matched before install, after install, and after deployment: 8,558 moves, 21,207 move lines, 4,192 payments, 50 employees, 0 payslips, 338 business contacts, and 0 POS daily reports.
- Post-deploy smoke succeeded: installed module, published dashboard ID 9, and heat-calendar retrieval for SHAMI TAX (54), المعلم الشامي (2), دوحة المستهلك (3), and ARZ (1). The public login endpoint returned HTTP 200; an external client verified TLS successfully.
- No `Traceback`, `CRITICAL`, or `FATAL` entry was found in the service logs since cutover.

The recovery artifacts remain on the host in the release backup directory. Small, non-secret evidence copies are retained in [production-evidence-52e9ff5](production-evidence-52e9ff5).
