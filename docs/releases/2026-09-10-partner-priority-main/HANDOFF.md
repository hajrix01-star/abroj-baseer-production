# PP1 — deployed to MAIN, 2026-09-10

User explicitly approved transfer after reviewing QA. Installed `baseer_partner_priority19.0.1.0.0` on `baseer_dev`: http://127.0.0.1:18069/odoo/vendors . Frozen composite `a8d533d67ee4ca3e4a7ce06fc44bc5e459fc192c` preserves all1126current BP1 source files and adds exactly9 reviewed PP1 files from9424da9a50ecda8d0462dc44ce2e7f0ab4012427. Browser printing remains installed. Source: `.local-backups/partner-priority-main-20260910/candidate`; pinned image and read-only mounts verified.

Company favorites are independent between companies and shared within each company. Native stars toggle preference. Relevant purchase/sales selectors and purchase-batch supplier fields place favorites first, then posted vendor-bill frequency in the active company's last90calendar days, then name/id. Existing ACLs and record rules apply. Without bill read access: favorites then alphabetical fallback. No QA users, synthetic suppliers or preferences were copied to MAIN.

Validation reused the accepted QA28integration and6independent checks plus native browser/company isolation evidence. Detailed behavior, single-reader benchmark and declared UI/performance limits remain in [QA handoff](../2026-09-09-partner-priority/HANDOFF.md) and [independent acceptance](../2026-09-09-partner-priority/FINAL-REVIEW.md).

- [candidate.json](candidate.json), [integration.json](integration.json):1135frozen files;1126unchanged and9reviewed additions.
- [rehearsal.json](rehearsal.json): exact composite installed on fresh MAIN clone;367business tables unchanged; frequency-sorted native queries across3companies. No HTTP/cron/original filestore mount. Temporary rehearsal database removed after success.
- [main-backup.json](main-backup.json), [post-release-backup.json](post-release-backup.json): coherent database/filestore/config/source snapshots while MAIN stopped; each verifies651attachment references and dump TOC. No new full filestore restore drill claimed.
- [main-preservation.json](main-preservation.json): every original row and column in367protected business tables unchanged. Only additive company-dependent favorite JSONB schema; no business migration or seeds.
- [runtime.json](runtime.json): HTTP200, correct installed version, no pending modules, frozen read-only mounts. Both compose mappings and daily backup source guard updated.
- [browser-evidence.json](browser-evidence.json), [main-suppliers.png](main-suppliers.png): actual Arabic MAIN list shows21native stars; vendor-bill supplier dropdown returns8suggestions and Search More. Unsaved verification form discarded; no preference changed on MAIN. Toggle/isolation proof reused from identical accepted QA addon.

Rollback uses the coherent predeployment database/filestore/config/source boundary and saved compose files; do not uninstall unrelated modules or import QA data. Local deployment only, no PP1 GitHub push requested/performed. Independent decision: [PREDEPLOY-GO.md](PREDEPLOY-GO.md), including final appendix.

## GitHub source publication — subsequent user request, 2026-09-10

User explicitly requested updating GitHub. Published accepted source to `hajrix01-star/Odoo-Baseer`, branch `main`, commit `b3e586558973759422e035741d6a91f24f6f687e`. Exactly9 approved addon files added plus release-source.json updated;1126 prior source files unchanged. All1135 hashes match deployed frozen source `a8d533d67ee4ca3e4a7ce06fc44bc5e459fc192c`. Local Python/XML/inventory verification passed. No databases, attachments, secrets or private operational evidence exported; no running local service or business data changed by publication. Source CI run34473528226; final result recorded in github-ci.json.
