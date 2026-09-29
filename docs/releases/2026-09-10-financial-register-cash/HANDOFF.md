# FL2 — Financial register cash mode

MAIN upgraded successfully to baseer_financial_register19.0.1.1.0 on2026-09-10. Frozen source e84fcfb96800fe8a655a3e40fb6db3d215085238, parent FL1 0a6246b7215caddf9e7b14ffe799f84ee03f8cd3.1167 files:1158 unchanged,8 modified,1 added. Existing pinned Odoo image and three frozen read-only mounts verified. No core/posting engine changes.

Open http://127.0.0.1:18069/odoo/action-825 → الحركات النقدية. One active authorized SAR company and calendar month; VAT inclusive. Same KPI area displays receipts, signed payments and net from the existing cash report's final allocations. Native filters narrow cards and source rows together. Clicking a card filters contributors; native source links open original entries. All mode restores invoice cards and header-selected companies. Cashier access remains denied by the existing financial register gate.

Verified MAIN preservation: all368 protected business tables retain exact original rows and columns, user group/company memberships and preset assignments unchanged, all unrelated installed module versions unchanged. Coherent pre/post database and filestore backups verified661 attachment references each. No new restore drill claimed. No QA database or synthetic transactions copied to MAIN.

Actual MAIN read-only smoke passed for all3companies: report/row parity, native cash field reads, three cards, All mode and English/Arabic native view rendering. QA accounting63checks, frontend13checks and actual Arabic desktop/480px visual evidence reused with exact source hashes; no unnecessary fixture rerun. No large-ledger/concurrent capacity certification.

GitHub main published source-only at3f3808576d2e62b7c7d66a6880b8fc326db51ef9.1167 accepted source files pass checksum and Python/XML validation. GitHub Actions34494233699 succeeded for that exact commit; remote main matches and publication checkout is clean. No database, filestore, operational evidence or credentials exported. Remote server deployment remains outside this local-original update.

Operational evidence: candidate.json, PREDEPLOY-GO.md, main-preservation.json, runtime.json, main-smoke.json, main-backup.json, post-release-backup.json and FINAL-REVIEW.md. Source-only publication: github-publication.json. Existing backup mapping now references this release. Reuse fl2_release.py and fl2_github_sync.py for this release's verification; do not broadly copy working sources or QA data.
